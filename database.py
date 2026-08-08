import datetime as dt
import os

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dicom.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombres = Column(String(120), nullable=False)
    apellidos = Column(String(120), default="", nullable=False)
    correo = Column(String(254), unique=True, index=True, nullable=False)
    telefono = Column(String(40), default="", nullable=False)
    rol = Column(String(20), default="usuario", nullable=False)
    password_hash = Column(String(255), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    creado_en = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    archivos = relationship("Archivo", back_populates="usuario")

class Archivo(Base):
    __tablename__ = "archivos"
    id = Column(Integer, primary_key=True, index=True)
    nombre_original = Column(String(255), nullable=False)
    nombre_dicom = Column(String(255), unique=True, index=True, nullable=False)
    ruta_fisica = Column(String(1024), nullable=False)
    formato_origen = Column(String(20), nullable=False)
    tamano_bytes = Column(Integer, default=0, nullable=False)
    fecha_subida = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    subido_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    estado = Column(String(30), default="convertido", nullable=False)
    usuario = relationship("Usuario", back_populates="archivos")

class PasswordReset(Base):
    __tablename__ = "password_resets"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    vence_en = Column(DateTime, nullable=False)
    usado = Column(Boolean, default=False, nullable=False)

class Auditoria(Base):
    __tablename__ = "auditoria"
    id = Column(Integer, primary_key=True)
    fecha_accion = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    accion = Column(String(80), nullable=False)
    detalles = Column(Text, default="", nullable=False)
