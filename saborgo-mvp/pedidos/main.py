import os
import json
import datetime
import asyncio
import redis
from fastapi import FastAPI, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from aiokafka import AIOKafkaProducer
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter

app = FastAPI(title="SaborGo - Pedidos Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
Instrumentator().instrument(app).expose(app)

MONTO_TOTAL_SOLES = Counter('saborgo_monto_total_soles', 'Acumulado total de dinero transaccionado')
PEDIDOS_TOTAL     = Counter('saborgo_pedidos_total', 'Conteo total de pedidos', ['metodo_pago'])

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://saborgo_user:saborgo_password@db:5432/saborgo_db")
engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()
KAFKA_SERVER = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
cache = redis.from_url(REDIS_URL, decode_responses=True)
CACHE_KEY_RECIENTES = "pedidos:recientes"
CACHE_TTL = 10

def invalidar_cache():
    try:
        cache.delete(CACHE_KEY_RECIENTES)
    except Exception as e:
        print(f"⚠️  Redis cache invalidation error: {e}")

class OrdenDB(Base):
    __tablename__ = "ordenes"
    id           = Column(Integer, primary_key=True, index=True)
    cliente      = Column(String, nullable=False)
    direccion    = Column(String, nullable=False)
    metodo_pago  = Column(String, nullable=False)
    total        = Column(Float, nullable=False)
    estado       = Column(String, default="Pendiente")
    fecha        = Column(DateTime, default=datetime.datetime.utcnow)
    calificacion = Column(Integer, nullable=True)
    lat_cliente  = Column(Float, nullable=True)
    lng_cliente  = Column(Float, nullable=True)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PedidoCreate(BaseModel):
    cliente: str
    direccion: str
    metodo_pago: str
    total: float
    lat_cliente: Optional[float] = None
    lng_cliente: Optional[float] = None

class CalificacionSchema(BaseModel):
    estrellas: int

class OrdenResponse(BaseModel):
    id: int
    cliente: str
    direccion: str
    metodo_pago: str
    total: float
    estado: str
    fecha: datetime.datetime
    calificacion: Optional[int] = None
    lat_cliente: Optional[float] = None
    lng_cliente: Optional[float] = None
    class Config:
        from_attributes = True


class WSManager:
    def __init__(self):
        self.activas: List[WebSocket] = []

    async def conectar(self, ws: WebSocket):
        await ws.accept()
        self.activas.append(ws)

    def desconectar(self, ws: WebSocket):
        if ws in self.activas:
            self.activas.remove(ws)

    async def broadcast(self, datos: list):
        mensaje = json.dumps(datos, default=str)
        cerradas = []
        for ws in self.activas:
            try:
                await ws.send_text(mensaje)
            except Exception:
                cerradas.append(ws)
        for ws in cerradas:
            self.desconectar(ws)

manager = WSManager()


async def enviar_evento_kafka(orden_id: int, cliente: str, total: float):
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_SERVER)
    for i in range(5):
        try:
            await producer.start()
            break
        except Exception:
            if i == 4: return
            await asyncio.sleep(3)
    try:
        evento = {"orden_id": orden_id, "cliente": cliente, "total": total,
                  "timestamp": str(datetime.datetime.utcnow())}
        await producer.send_and_wait("ordenes_topic", json.dumps(evento).encode('utf-8'))
    except Exception as e:
        print(f"❌ Error Kafka: {e}")
    finally:
        await producer.stop()


def _serializar_pedidos(pedidos) -> list:
    return [
        {
            "id": p.id, "cliente": p.cliente, "direccion": p.direccion,
            "metodo_pago": p.metodo_pago, "total": p.total,
            "estado": p.estado, "fecha": str(p.fecha),
            "calificacion": p.calificacion,
            "lat_cliente": p.lat_cliente,
            "lng_cliente": p.lng_cliente,
        }
        for p in pedidos
    ]


async def broadcast_pedidos_recientes():
    db = SessionLocal()
    try:
        cached = None
        try:
            cached = cache.get(CACHE_KEY_RECIENTES)
        except Exception as e:
            print(f"⚠️  Redis read error: {e}")

        if cached:
            datos = json.loads(cached)
            print("⚡ [PEDIDOS] Sirviendo pedidos desde caché Redis.")
        else:
            pedidos = db.query(OrdenDB).order_by(OrdenDB.id.desc()).limit(15).all()
            datos   = _serializar_pedidos(pedidos)
            try:
                cache.setex(CACHE_KEY_RECIENTES, CACHE_TTL, json.dumps(datos))
                print("💾 [PEDIDOS] Caché Redis actualizado.")
            except Exception as e:
                print(f"⚠️  Redis write error: {e}")

        await manager.broadcast(datos)
    finally:
        db.close()


@app.post("/pedidos/crear")
async def crear_pedido(pedido: PedidoCreate, background_tasks: BackgroundTasks,
                       db: Session = Depends(get_db)):
    nueva_orden = OrdenDB(
        cliente=pedido.cliente,
        direccion=pedido.direccion,
        metodo_pago=pedido.metodo_pago,
        total=pedido.total,
        lat_cliente=pedido.lat_cliente,
        lng_cliente=pedido.lng_cliente,
    )
    db.add(nueva_orden)
    db.commit()
    db.refresh(nueva_orden)
    MONTO_TOTAL_SOLES.inc(pedido.total)
    PEDIDOS_TOTAL.labels(metodo_pago=pedido.metodo_pago).inc()
    background_tasks.add_task(enviar_evento_kafka, nueva_orden.id, nueva_orden.cliente, nueva_orden.total)
    invalidar_cache()
    await broadcast_pedidos_recientes()
    return {"msg": "Pedido creado con éxito", "orden_id": nueva_orden.id, "estado": nueva_orden.estado}


@app.get("/pedidos/recientes", response_model=List[OrdenResponse])
def obtener_pedidos_recientes(db: Session = Depends(get_db)):
    try:
        cached = cache.get(CACHE_KEY_RECIENTES)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return db.query(OrdenDB).order_by(OrdenDB.id.desc()).limit(15).all()


@app.post("/pedidos/{orden_id}/calificar")
async def calificar_pedido(orden_id: int, calificacion: CalificacionSchema,
                           db: Session = Depends(get_db)):
    if not (1 <= calificacion.estrellas <= 5):
        raise HTTPException(status_code=400, detail="La calificación debe ser entre 1 y 5 estrellas.")
    orden = db.query(OrdenDB).filter(OrdenDB.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada.")
    if orden.estado.lower() != "aprobado":
        raise HTTPException(status_code=400, detail="Solo se pueden calificar pedidos aprobados.")
    if orden.calificacion is not None:
        raise HTTPException(status_code=400, detail="Este pedido ya fue calificado.")
    orden.calificacion = calificacion.estrellas
    db.commit()
    db.refresh(orden)
    invalidar_cache()
    await broadcast_pedidos_recientes()
    print(f"⭐ [PEDIDOS] Orden #{orden_id} calificada con {calificacion.estrellas} estrellas.")
    return {"msg": "Calificación registrada", "orden_id": orden_id, "estrellas": calificacion.estrellas}


@app.websocket("/ws/pedidos")
async def websocket_pedidos(websocket: WebSocket):
    await manager.conectar(websocket)
    print(f"🔌 WebSocket conectado. Clientes activos: {len(manager.activas)}")
    await broadcast_pedidos_recientes()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.desconectar(websocket)
        print(f"🔌 WebSocket desconectado. Clientes activos: {len(manager.activas)}")