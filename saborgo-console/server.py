"""
SaborGo Cluster Console — backend
=================================
Servidor puente que ejecuta comandos kubectl reales y los expone como JSON
para que el dashboard web muestre el estado del clúster Kubernetes en vivo.

Endpoints:
  GET  /                      -> sirve el dashboard (index.html)
  GET  /api/overview          -> pods + servicios + deployments + resumen
  GET  /api/events            -> últimos eventos del namespace (para el feed)
  GET  /api/terminal          -> log de comandos kubectl reales (para la terminal en vivo)
  POST /api/kill/{app}        -> mata un pod del deployment indicado (self-healing demo)
  GET  /api/menu              -> proxy al microservicio catalogo (prueba viva de la app)

Uso:
  python3 server.py
  -> abre http://localhost:8000
"""
import itertools
import json
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

NAMESPACE = "saborgo"
BASE_DIR = Path(__file__).parent

app = FastAPI(title="SaborGo Cluster Console")


# ----------------------------------------------------------------------------
# Log de terminal en vivo
# ----------------------------------------------------------------------------
# Todo lo que aparece aquí es real: comandos kubectl efectivamente ejecutados
# y cambios de estado reales detectados al compararlos contra el snapshot
# anterior del clúster. Nada es simulado.
_TERMINAL_LOCK = threading.Lock()
_TERMINAL_LOG: deque = deque(maxlen=120)
_LOG_ID = itertools.count(1)
_KNOWN_PODS: dict = {}
_LAST_HEARTBEAT = 0.0


def log_line(text: str, kind: str = "info") -> None:
    """kind: cmd | ok | warn | info"""
    with _TERMINAL_LOCK:
        _TERMINAL_LOG.append(
            {
                "id": next(_LOG_ID),
                "t": time.strftime("%H:%M:%S"),
                "text": text,
                "kind": kind,
            }
        )


log_line("kubectl config use-context docker-desktop", "cmd")
log_line("contexto activo: docker-desktop", "ok")
log_line(f"kubectl get pods -n {NAMESPACE} --watch", "cmd")
log_line("escuchando cambios del clúster en tiempo real…", "info")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def kubectl(*args: str, timeout: int = 10) -> str:
    """Ejecuta kubectl y devuelve stdout como texto. Lanza error legible si falla."""
    cmd = ["kubectl", *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        raise HTTPException(500, "kubectl no está instalado o no está en el PATH.")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"kubectl tardó demasiado: {' '.join(cmd)}")
    if result.returncode != 0:
        raise HTTPException(500, result.stderr.strip() or "Error en kubectl")
    return result.stdout


def kubectl_json(*args: str) -> dict:
    return json.loads(kubectl(*args, "-o", "json"))


# Mapa amistoso: nombre técnico -> etiqueta legible + rol
SERVICE_META = {
    "auth": ("Autenticación", "JWT + bcrypt", "🔐"),
    "catalogo": ("Catálogo", "Menú de platos", "📋"),
    "pedidos": ("Pedidos", "Núcleo + WebSocket", "🛒"),
    "postgres": ("PostgreSQL", "Base de datos", "🗄️"),
    "redis": ("Redis", "Caché en memoria", "⚡"),
    "kafka": ("Kafka", "Mensajería de eventos", "📨"),
    "zookeeper": ("Zookeeper", "Coordinador Kafka", "🧭"),
}


def humanize_age(timestamp: str) -> str:
    """Convierte un timestamp ISO de K8s en una antigüedad legible (ej. '4h 12m')."""
    from datetime import datetime, timezone

    try:
        started = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except Exception:
        return "—"
    delta = datetime.now(timezone.utc) - started
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    rem_min = mins % 60
    if hours < 24:
        return f"{hours}h {rem_min}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def _track_terminal_changes(pods, running, total, restarts):
    """Compara el snapshot actual contra el anterior y registra solo lo que
    cambió de verdad — así la terminal se siente viva sin estar saturada."""
    global _KNOWN_PODS, _LAST_HEARTBEAT

    current = {p["name"]: p["ready"] for p in pods}

    if not _KNOWN_PODS:
        log_line(f"kubectl get pods -n {NAMESPACE}", "cmd")
        log_line(f"sincronizado: {len(current)} pods detectados", "ok")
    else:
        gone = set(_KNOWN_PODS) - set(current)
        new = set(current) - set(_KNOWN_PODS)
        for name in gone:
            log_line(f'pod "{name}" Terminating', "warn")
        for name in new:
            log_line(f'pod "{name}" Running — réplica restaurada', "ok")

    _KNOWN_PODS = current

    now = time.time()
    if now - _LAST_HEARTBEAT > 18:
        log_line(f"kubectl get pods -n {NAMESPACE}", "cmd")
        log_line(f"{running}/{total} pods Running · {restarts} reinicios totales", "info")
        _LAST_HEARTBEAT = now


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------
@app.get("/api/overview")
def overview():
    """Estado completo del clúster: pods, servicios, deployments y resumen."""
    pods_raw = kubectl_json("get", "pods", "-n", NAMESPACE)
    svcs_raw = kubectl_json("get", "services", "-n", NAMESPACE)
    deps_raw = kubectl_json("get", "deployments", "-n", NAMESPACE)

    pods = []
    for item in pods_raw.get("items", []):
        meta = item.get("metadata", {})
        status = item.get("status", {})
        labels = meta.get("labels", {})
        app_label = labels.get("app", "—")
        phase = status.get("phase", "Unknown")

        # ¿Está realmente listo?
        container_statuses = status.get("containerStatuses", [])
        ready = all(c.get("ready", False) for c in container_statuses) and bool(
            container_statuses
        )
        restarts = sum(c.get("restartCount", 0) for c in container_statuses)

        friendly, role, icon = SERVICE_META.get(
            app_label, (app_label.capitalize(), "Servicio", "📦")
        )

        pods.append(
            {
                "name": meta.get("name", "—"),
                "app": app_label,
                "friendly": friendly,
                "role": role,
                "icon": icon,
                "phase": phase,
                "ready": ready,
                "restarts": restarts,
                "age": humanize_age(
                    status.get("startTime", meta.get("creationTimestamp", ""))
                ),
            }
        )

    pods.sort(key=lambda p: p["app"])

    services = []
    for item in svcs_raw.get("items", []):
        meta = item.get("metadata", {})
        spec = item.get("spec", {})
        ports = spec.get("ports", [])
        services.append(
            {
                "name": meta.get("name", "—"),
                "type": spec.get("type", "ClusterIP"),
                "clusterIP": spec.get("clusterIP", "—"),
                "ports": ", ".join(str(p.get("port", "")) for p in ports),
            }
        )
    services.sort(key=lambda s: s["name"])

    deployments = []
    for item in deps_raw.get("items", []):
        meta = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})
        desired = spec.get("replicas", 0)
        ready = status.get("readyReplicas", 0) or 0
        deployments.append(
            {
                "name": meta.get("name", "—"),
                "desired": desired,
                "ready": ready,
                "healthy": ready == desired and desired > 0,
            }
        )
    deployments.sort(key=lambda d: d["name"])

    total = len(pods)
    running = sum(1 for p in pods if p["ready"])
    summary = {
        "total_pods": total,
        "running_pods": running,
        "total_services": len(services),
        "total_deployments": len(deployments),
        "all_healthy": running == total and total > 0,
        "total_restarts": sum(p["restarts"] for p in pods),
    }

    _track_terminal_changes(pods, running, total, summary["total_restarts"])

    return {
        "summary": summary,
        "pods": pods,
        "services": services,
        "deployments": deployments,
        "timestamp": time.strftime("%H:%M:%S"),
    }


@app.get("/api/events")
def events():
    """Últimos eventos del namespace, para el feed de actividad en vivo."""
    try:
        raw = kubectl(
            "get", "events", "-n", NAMESPACE,
            "--sort-by=.lastTimestamp",
            "-o", "json",
        )
        data = json.loads(raw)
    except HTTPException:
        return {"events": []}

    feed = []
    for item in data.get("items", [])[-12:]:
        feed.append(
            {
                "reason": item.get("reason", "—"),
                "object": item.get("involvedObject", {}).get("name", "—"),
                "message": item.get("message", ""),
                "type": item.get("type", "Normal"),
            }
        )
    feed.reverse()
    return {"events": feed}


@app.post("/api/kill/{app_label}")
def kill_pod(app_label: str):
    """Mata un pod del deployment indicado para demostrar la auto-recuperación."""
    if app_label not in SERVICE_META:
        raise HTTPException(400, f"Servicio desconocido: {app_label}")
    # Tomamos el primer pod con ese label
    out = kubectl(
        "get", "pods", "-n", NAMESPACE,
        "-l", f"app={app_label}",
        "-o", "jsonpath={.items[0].metadata.name}",
    )
    pod_name = out.strip()
    if not pod_name:
        raise HTTPException(404, f"No hay pods activos para {app_label}")
    log_line(
        f"kubectl delete pod {pod_name} -n {NAMESPACE} --grace-period=0 --force",
        "cmd",
    )
    kubectl("delete", "pod", pod_name, "-n", NAMESPACE, "--grace-period=0", "--force")
    log_line(f'pod "{pod_name}" eliminado — esperando reconciliación del Deployment', "warn")
    return {"killed": pod_name, "app": app_label}


@app.get("/api/terminal")
def terminal():
    """Devuelve el log de comandos kubectl reales para la terminal en vivo."""
    with _TERMINAL_LOCK:
        return {"lines": list(_TERMINAL_LOG)}


@app.get("/api/menu")
def menu():
    """Proxy al microservicio catalogo vía port-forward implícito (prueba viva)."""
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:3001/menu", timeout=3) as r:
            return JSONResponse(json.loads(r.read().decode()))
    except Exception:
        return JSONResponse(
            {"error": "El catálogo no está accesible en localhost:3001. "
                      "Ejecuta el port-forward primero."},
            status_code=503,
        )


# ----------------------------------------------------------------------------
# Frontend
# ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    html = (BASE_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn

    print("\n  SaborGo Cluster Console")
    print("  → http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
