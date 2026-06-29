import os
import asyncio
import random
import datetime
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://saborgo_user:saborgo_password@db:5432/saborgo_db")
engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()

class Repartidor(Base):
    __tablename__ = "repartidores"
    id         = Column(Integer, primary_key=True, index=True)
    nombre     = Column(String, nullable=False)
    telefono   = Column(String, nullable=False)
    disponible = Column(Boolean, default=True)

class Asignacion(Base):
    __tablename__ = "asignaciones"
    id               = Column(Integer, primary_key=True, index=True)
    orden_id         = Column(Integer, nullable=False)
    repartidor_id    = Column(Integer, ForeignKey("repartidores.id"), nullable=False)
    estado           = Column(String, default="En camino")
    lat_actual       = Column(Float, default=-12.0179)
    lng_actual       = Column(Float, default=-77.0508)
    lat_destino      = Column(Float, default=-12.0179)
    lng_destino      = Column(Float, default=-77.0508)
    ruta_coords      = Column(String, nullable=True)
    eta_minutos      = Column(Integer, default=20)
    fecha_asignacion = Column(DateTime, default=datetime.datetime.utcnow)
    repartidor       = relationship("Repartidor")

Base.metadata.create_all(bind=engine)

# ── Puerta 5 UNI — origen de todos los repartidores ───────────────────────────
UNI_PUERTA_5 = (-12.017901488133642, -77.05080726290063)

def coordenadas_origen():
    """Pequeña variación para que no salgan todos del mismo pixel."""
    lat = UNI_PUERTA_5[0] + random.uniform(-0.0003, 0.0003)
    lng = UNI_PUERTA_5[1] + random.uniform(-0.0003, 0.0003)
    return round(lat, 6), round(lng, 6)

def haversine_km(lat1, lng1, lat2, lng2):
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# ── OSRM — Ruta real por calles ───────────────────────────────────────────────
async def obtener_ruta_osrm(lat_ini, lng_ini, lat_fin, lng_fin):
    try:
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{lng_ini},{lat_ini};{lng_fin},{lat_fin}"
            f"?overview=full&geometries=geojson&steps=false"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url)
            data = res.json()

        if data.get("code") != "Ok":
            return None, 20

        coords = data["routes"][0]["geometry"]["coordinates"]
        duracion_seg = data["routes"][0]["duration"]
        eta_minutos  = max(1, int(duracion_seg / 60))
        ruta = [[c[1], c[0]] for c in coords]
        return ruta, eta_minutos

    except Exception as e:
        print(f"⚠️  [RUTEO] OSRM no disponible: {e}. Usando ruta recta.")
        return None, 20

# ── Gestor WebSocket de tracking ──────────────────────────────────────────────
class TrackingManager:
    def __init__(self):
        self.conexiones: dict = {}

    async def conectar(self, orden_id: int, ws: WebSocket):
        await ws.accept()
        if orden_id not in self.conexiones:
            self.conexiones[orden_id] = []
        self.conexiones[orden_id].append(ws)
        print(f"📍 [TRACKING] Cliente conectado a orden #{orden_id}")

    def desconectar(self, orden_id: int, ws: WebSocket):
        if orden_id in self.conexiones:
            self.conexiones[orden_id] = [w for w in self.conexiones[orden_id] if w != ws]
            if not self.conexiones[orden_id]:
                del self.conexiones[orden_id]

    async def broadcast_orden(self, orden_id: int, datos: dict):
        import json
        if orden_id not in self.conexiones:
            return
        cerradas = []
        for ws in self.conexiones[orden_id]:
            try:
                await ws.send_text(json.dumps(datos, default=str))
            except Exception:
                cerradas.append(ws)
        for ws in cerradas:
            self.desconectar(orden_id, ws)

tracking_manager = TrackingManager()

# ── Loop de asignación ────────────────────────────────────────────────────────
async def loop_asignacion():
    print("🛵 [RUTEO] Loop de asignación iniciado.")
    await asyncio.sleep(6)
    while True:
        db = SessionLocal()
        try:
            resultado = db.execute(text("""
                SELECT o.id, o.direccion, o.lat_cliente, o.lng_cliente
                FROM ordenes o
                LEFT JOIN asignaciones a ON o.id = a.orden_id
                WHERE o.estado = 'Aprobado' AND a.id IS NULL
            """)).fetchall()

            for row in resultado:
                orden_id  = row[0]
                lat_cliente = row[2]
                lng_cliente = row[3]

                repartidor = db.query(Repartidor).filter(
                    Repartidor.disponible == True
                ).order_by(Repartidor.id).first()

                if not repartidor:
                    print(f"⚠️  [RUTEO] Sin repartidores para Orden #{orden_id}")
                    continue

                # Origen: Puerta 5 UNI
                lat_ini, lng_ini = coordenadas_origen()

                # Destino: coordenadas reales del cliente o fallback a UNI
                if lat_cliente and lng_cliente:
                    lat_fin, lng_fin = lat_cliente, lng_cliente
                    print(f"📍 [RUTEO] Destino real del cliente: ({lat_fin}, {lng_fin})")
                else:
                    lat_fin, lng_fin = UNI_PUERTA_5
                    print(f"📍 [RUTEO] Sin coordenadas cliente, usando UNI como destino")

                # Ruta real con OSRM
                ruta, eta = await obtener_ruta_osrm(lat_ini, lng_ini, lat_fin, lng_fin)

                import json
                nueva = Asignacion(
                    orden_id=orden_id,
                    repartidor_id=repartidor.id,
                    estado="En camino",
                    lat_actual=lat_ini,
                    lng_actual=lng_ini,
                    lat_destino=lat_fin,
                    lng_destino=lng_fin,
                    ruta_coords=json.dumps(ruta) if ruta else None,
                    eta_minutos=eta
                )
                db.add(nueva)
                repartidor.disponible = False
                db.commit()
                print(f"✅ [RUTEO] Orden #{orden_id} → {repartidor.nombre} | ETA: {eta} min | Ruta OSRM: {'Sí' if ruta else 'No'}")

        except Exception as e:
            print(f"❌ [RUTEO] Error asignación: {e}")
        finally:
            db.close()
        await asyncio.sleep(5)

# ── Loop GPS ──────────────────────────────────────────────────────────────────
async def loop_gps():
    print("📍 [RUTEO] Loop GPS iniciado.")
    await asyncio.sleep(2)
    import json

    while True:
        db = SessionLocal()
        try:
            activas = db.query(Asignacion).filter(
                Asignacion.estado == "En camino"
            ).all()

            for asig in activas:
                llego = False
                if asig.ruta_coords:
                    ruta = json.loads(asig.ruta_coords)
                    if len(ruta) > 1:
                        # Avanza 4 puntos por tick para ir más rápido
                        salto = min(4, len(ruta) - 1)
                        siguiente = ruta[salto]
                        asig.lat_actual = siguiente[0]
                        asig.lng_actual = siguiente[1]
                        ruta = ruta[salto:]
                        asig.ruta_coords = json.dumps(ruta)
                        dist = haversine_km(
                            asig.lat_actual, asig.lng_actual,
                            asig.lat_destino, asig.lng_destino
                        )
                        asig.eta_minutos = max(1, int(dist / 25 * 60))
                    else:
                        llego = True
                else:
                    paso = 0.015
                    dlat = asig.lat_destino - asig.lat_actual
                    dlng = asig.lng_destino - asig.lng_actual
                    dist = (dlat**2 + dlng**2) ** 0.5
                    if dist < paso:
                        llego = True
                    else:
                        f = paso / dist
                        asig.lat_actual = round(asig.lat_actual + dlat * f + random.uniform(-0.0003, 0.0003), 6)
                        asig.lng_actual = round(asig.lng_actual + dlng * f + random.uniform(-0.0003, 0.0003), 6)
                        asig.eta_minutos = max(1, int(haversine_km(
                            asig.lat_actual, asig.lng_actual,
                            asig.lat_destino, asig.lng_destino
                        ) / 25 * 60))

                if llego:
                    asig.estado = "Entregado"
                    asig.eta_minutos = 0
                    rep = db.query(Repartidor).filter(Repartidor.id == asig.repartidor_id).first()
                    if rep:
                        rep.disponible = True
                    print(f"🏁 [RUTEO] Orden #{asig.orden_id} entregada.")

                db.commit()

                rep = db.query(Repartidor).filter(Repartidor.id == asig.repartidor_id).first()
                await tracking_manager.broadcast_orden(asig.orden_id, {
                    "orden_id": asig.orden_id,
                    "estado": asig.estado,
                    "lat_actual": asig.lat_actual,
                    "lng_actual": asig.lng_actual,
                    "lat_destino": asig.lat_destino,
                    "lng_destino": asig.lng_destino,
                    "ruta_restante": json.loads(asig.ruta_coords) if asig.ruta_coords else [],
                    "eta_minutos": asig.eta_minutos,
                    "repartidor_nombre": rep.nombre if rep else "—",
                    "repartidor_telefono": rep.telefono if rep else "—",
                })

        except Exception as e:
            print(f"❌ [RUTEO] Error GPS: {e}")
        finally:
            db.close()
        await asyncio.sleep(8)

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    t1 = asyncio.create_task(loop_asignacion())
    t2 = asyncio.create_task(loop_gps())
    yield
    t1.cancel(); t2.cancel()

app = FastAPI(title="SaborGo - Ruteo Service", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/ruteo/asignacion/{orden_id}")
def obtener_asignacion(orden_id: int):
    import json
    db = SessionLocal()
    try:
        asig = db.query(Asignacion).filter(Asignacion.orden_id == orden_id).first()
        if not asig:
            raise HTTPException(status_code=404, detail="Sin repartidor asignado aún.")
        rep = db.query(Repartidor).filter(Repartidor.id == asig.repartidor_id).first()
        return {
            "orden_id": orden_id,
            "repartidor_nombre": rep.nombre if rep else "—",
            "repartidor_telefono": rep.telefono if rep else "—",
            "estado": asig.estado,
            "lat_actual": asig.lat_actual,
            "lng_actual": asig.lng_actual,
            "lat_destino": asig.lat_destino,
            "lng_destino": asig.lng_destino,
            "ruta_restante": json.loads(asig.ruta_coords) if asig.ruta_coords else [],
            "eta_minutos": asig.eta_minutos,
            "fecha_asignacion": str(asig.fecha_asignacion)
        }
    finally:
        db.close()

@app.get("/ruteo/repartidores")
def listar_repartidores():
    db = SessionLocal()
    try:
        return [{"id": r.id, "nombre": r.nombre, "telefono": r.telefono, "disponible": r.disponible}
                for r in db.query(Repartidor).all()]
    finally:
        db.close()

@app.get("/ruteo/asignaciones")
def listar_asignaciones():
    import json
    db = SessionLocal()
    try:
        asigs = db.query(Asignacion).order_by(Asignacion.id.desc()).limit(20).all()
        resultado = []
        for asig in asigs:
            rep = db.query(Repartidor).filter(Repartidor.id == asig.repartidor_id).first()
            resultado.append({
                "orden_id": asig.orden_id,
                "repartidor_nombre": rep.nombre if rep else "—",
                "repartidor_telefono": rep.telefono if rep else "—",
                "estado": asig.estado,
                "lat_actual": asig.lat_actual,
                "lng_actual": asig.lng_actual,
                "lat_destino": asig.lat_destino,
                "lng_destino": asig.lng_destino,
                "eta_minutos": asig.eta_minutos,
                "fecha_asignacion": str(asig.fecha_asignacion)
            })
        return resultado
    finally:
        db.close()

@app.websocket("/ws/tracking/{orden_id}")
async def websocket_tracking(websocket: WebSocket, orden_id: int):
    await tracking_manager.conectar(orden_id, websocket)
    try:
        asig_data = obtener_asignacion(orden_id)
        import json
        await websocket.send_text(json.dumps(asig_data, default=str))
    except HTTPException:
        pass
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        tracking_manager.desconectar(orden_id, websocket)
        print(f"📍 [TRACKING] Cliente desconectado de orden #{orden_id}")