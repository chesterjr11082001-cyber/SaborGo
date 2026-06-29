import os
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="SaborGo - Catálogo Service")
Instrumentator().instrument(app).expose(app)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://saborgo_user:saborgo_password@db:5432/saborgo_db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# FIX #1: Nombre de tabla corregido de "platillos" a "platos" para coincidir con init-db.sql
# FIX #2: Modelo actualizado con los campos reales de la tabla (categoria, imagen)
class PlatilloDB(Base):
    __tablename__ = "platos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    precio = Column(Float, nullable=False)
    categoria = Column(String, nullable=False)
    imagen = Column(String, nullable=False)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# FIX #3: Response model actualizado con todos los campos del modelo
class PlatilloResponse(BaseModel):
    id: int
    nombre: str
    precio: float
    categoria: str
    imagen: str

    class Config:
        from_attributes = True

@app.get("/menu", response_model=List[PlatilloResponse])
def obtener_menu(db: Session = Depends(get_db)):
    try:
        platillos = db.query(PlatilloDB).all()
        return platillos
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")