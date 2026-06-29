import os
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from jose import jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi.middleware.cors import CORSMiddleware

# Imports de SQLAlchemy para la Base de Datos
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

app = FastAPI(title="SaborGo - Auth Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = "SaborGo_Secret_Key_2026"
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 1. CONFIGURACIÓN DE POSTGRESQL (Vía variables de entorno de Docker)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://saborgo_user:saborgo_password@db:5432/saborgo_auth_db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. MODELO DE LA TABLA DE USUARIOS
class UserDB(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)

# Crear las tablas en Postgres al iniciar el microservicio si no existen
Base.metadata.create_all(bind=engine)

# Dependencia para abrir/cerrar conexiones limpiamente por cada request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class UserSchema(BaseModel):
    username: str
    password: str

# 3. RUTA DE REGISTRO CON PERSISTENCIA
@app.post("/registro")
def registro(user: UserSchema, db: Session = Depends(get_db)):
    # Buscamos si el usuario ya existe en la tabla de la BD
    db_user = db.query(UserDB).filter(UserDB.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="El usuario ya existe")
    
    # Encriptamos la contraseña con Bcrypt
    hashed_password = pwd_context.hash(user.password)
    
    # Guardamos el nuevo registro
    nuevo_usuario = UserDB(username=user.username, password=hashed_password)
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    
    return {"msg": "Usuario registrado con éxito en la Base de Datos"}

# 4. RUTA DE LOGIN VALIDANDO CONTRA LA BD
@app.post("/login")
def login(user: UserSchema, db: Session = Depends(get_db)):
    # Buscamos al usuario en la BD
    db_user = db.query(UserDB).filter(UserDB.username == user.username).first()
    
    # Validamos existencia y hash de contraseña
    if not db_user or not pwd_context.verify(user.password, db_user.password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    
    # Crear Token JWT
    expire = datetime.utcnow() + timedelta(hours=2)
    token_data = {"sub": user.username, "exp": expire}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"access_token": token, "token_type": "bearer"}