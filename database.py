from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
import os
import datetime

# Conectarse a la URL de la base de datos de Docker
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin_dicom:superpassword123@db_postgres/dicom_database")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- TABLA DE USUARIOS ---
class Usuario(Base):
    __tablename__ = "usuarios"
    
    id = Column(Integer, primary_key=True, index=True)
    nombres = Column(String, index=True)
    apellidos = Column(String)
    correo = Column(String, unique=True, index=True)
    telefono = Column(String)
    rol = Column(String, default="usuario")
    password_hash = Column(String)
    activo = Column(Boolean, default=True)

# --- TABLA DE ARCHIVOS ---
class Archivo(Base):
    __tablename__ = "archivos"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre_original = Column(String)
    nombre_dicom = Column(String, unique=True)
    ruta_fisica = Column(String)
    fecha_subida = Column(DateTime, default=datetime.datetime.utcnow)
    subido_por = Column(Integer, ForeignKey("usuarios.id"))
    estado = Column(String, default="convertido")

# --- TABLA DE AUDITORÍA ---
class Auditoria(Base):
    __tablename__ = "auditoria"
    
    id = Column(Integer, primary_key=True, index=True)
    fecha_accion = Column(DateTime, default=datetime.datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    accion = Column(String)
    detalles = Column(String)
