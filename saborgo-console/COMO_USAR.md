# SaborGo · Consola de Clúster

Dashboard web profesional que muestra el estado de tu clúster Kubernetes en
vivo: pods, servicios, deployments, métricas y auto-recuperación (self-healing),
todo con la identidad visual de SaborGo. Reemplaza los comandos de terminal por
una sola interfaz que el profesor puede ver mientras compartes pantalla.

---

## 1. Requisitos previos

- Kubernetes corriendo (Docker Desktop con Kubeadm) y tus pods desplegados en el
  namespace `saborgo`.
- `kubectl` accesible desde tu terminal (ya lo tienes).
- Python 3.

Verifica que tus pods estén arriba:

    kubectl get pods -n saborgo

---

## 2. Instalación (una sola vez)

Copia la carpeta `saborgo-console` a tu Mac, por ejemplo a tu escritorio.
Abre una terminal dentro de esa carpeta y ejecuta:

    cd ~/Desktop/saborgo-console
    pip3 install -r requirements.txt --break-system-packages

---

## 3. Encender la consola

    cd ~/Desktop/saborgo-console
    python3 server.py

Verás:

    SaborGo Cluster Console
    → http://localhost:8000

Abre ese enlace en el navegador. ✅ Listo.

---

## 4. Cómo se usa en la demo

El dashboard se refresca solo cada 2 segundos. No tienes que hacer nada en la
terminal durante la presentación.

**Terminal en vivo (nuevo):** debajo del grid de pods hay una terminal con
estética macOS que muestra los comandos `kubectl` reales que el backend va
ejecutando, más los cambios de estado reales del clúster (pods creados,
eliminados, reinicios) — todo en cian/verde/ámbar según el tipo de evento,
con cursor parpadeante. No es una animación falsa: es el log real de lo que
está pasando en tu Kubernetes, formateado como terminal.

**Para demostrar el self-healing (lo más impactante):**

1. Pasa el cursor sobre cualquier pod — aparece una ✕ en la esquina.
2. Haz clic en la ✕.
3. El pod se marca en rojo ("muriendo"), y una notificación dice que Kubernetes
   lo recreará.
4. En la terminal en vivo verás aparecer al instante la línea
   `$ kubectl delete pod ... --force`, y 2-3 segundos después la línea de
   confirmación `pod "..." Running — réplica restaurada`.
5. En el grid, el pod reaparece automáticamente con un nuevo identificador y
   el contador de "Reinicios" sube.

Esto demuestra visualmente que Kubernetes mantiene el estado deseado: si algo
se cae, lo reemplaza solo — y la terminal lo prueba con comandos reales, no
solo con un ícono cambiando de color.

---

## 5. ¿Dónde correrlo? (recomendación)

**Local en tu Mac (localhost) — recomendado.** Para una demo presencial donde
compartes o proyectas tu pantalla, `localhost:8000` es lo más simple y robusto:
sin dependencias de red, sin latencia, sin túneles que se caigan.

Solo necesitarías ngrok si el profesor quisiera abrir el dashboard desde **su
propia** laptop, lo cual es raro en una sustentación presencial. Si llega a
pedirlo, se resuelve en 1 minuto con:

    ngrok http 8000

---

## 6. Notas

- El botón ✕ ejecuta `kubectl delete pod` real sobre un pod del servicio elegido.
  Es seguro: Kubernetes lo recrea de inmediato. En `pedidos` (2 réplicas) ni
  siquiera hay interrupción de servicio.
- El panel "Actividad del clúster" lee los eventos reales del namespace
  (`kubectl get events`), así que verás reflejada cada acción.
- Si algún pod aparece en amarillo ("ContainerCreating"), es normal durante los
  segundos en que Kubernetes lo está recreando.
