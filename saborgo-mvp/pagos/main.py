import os
import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from aiokafka import AIOKafkaConsumer

# FIX #7: Reemplazado @app.on_event("startup") deprecado por lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Arranca el consumer de Kafka en segundo plano al iniciar
    task = asyncio.create_task(procesar_pagos_loop())
    yield
    # Al apagar, cancelamos la tarea limpiamente
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="SaborGo - Pagos Service", lifespan=lifespan)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://saborgo_user:saborgo_password@db:5432/saborgo_db")
KAFKA_SERVER = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
engine = create_engine(DATABASE_URL)

async def procesar_pagos_loop():
    consumer = AIOKafkaConsumer(
        "ordenes_topic",
        bootstrap_servers=KAFKA_SERVER,
        group_id="pagos_group"
    )

    intentos = 15
    for i in range(intentos):
        try:
            await consumer.start()
            print("🚀 [PAGOS] Conectado exitosamente a Kafka. Escuchando eventos...")
            break
        except Exception as e:
            if i == intentos - 1:
                print(f"❌ [PAGOS ERROR] No se pudo conectar a Kafka tras {intentos} intentos. Abortando.")
                return
            print(f"⏳ [PAGOS] Kafka no está listo aún. Reintentando en 4 segundos... ({i+1}/{intentos})")
            await asyncio.sleep(4)

    try:
        async for msg in consumer:
            try:
                datos = json.loads(msg.value.decode('utf-8'))
                orden_id = datos['orden_id']
                print(f"💳 [PAGOS] Evento recibido. Procesando cobro de la Orden #{orden_id}...")

                # Simulación de pasarela bancaria
                await asyncio.sleep(2)

                # Actualización de estado en PostgreSQL
                with engine.connect() as conn:
                    query = text("UPDATE ordenes SET estado = 'Aprobado' WHERE id = :id")
                    conn.execute(query, {"id": orden_id})
                    conn.commit()
                print(f"✅ [PAGOS] Pago aprobado y estado actualizado para la Orden #{orden_id}.")

            except Exception as inner_error:
                print(f"❌ [PAGOS ERROR] Error en procesamiento de mensaje: {inner_error}")
    finally:
        await consumer.stop()