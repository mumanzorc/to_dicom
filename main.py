import datetime as dt
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import smtplib
import uuid
import zipfile
from email.message import EmailMessage
from pathlib import Path
from typing import Annotated, Literal

import jwt
import numpy as np
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, EmailStr, Field
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import EncapsulatedPDFStorage, ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
from sqlalchemy.orm import Session

from database import Archivo, Auditoria, Base, PasswordReset, SessionLocal, Usuario, engine

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR / "archivos_dicom")).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY = os.getenv("SECRET_KEY", "cambie-esta-clave-en-produccion")
ALGORITHM = "HS256"
TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "50"))
ALLOWED = {"jpg", "jpeg", "png", "bmp", "pdf", "txt", "csv", "json", "log", "md", "xml", "html"}
TEXT_FORMATS = {"txt", "csv", "json", "log", "md", "xml", "html"}

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Conversor seguro a DICOM", version="2.0.0")
oauth2 = OAuth2PasswordBearer(tokenUrl="api/auth/login")
passwords = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserCreate(BaseModel):
    nombres: str = Field(min_length=1, max_length=120)
    apellidos: str = Field(default="", max_length=120)
    correo: EmailStr
    telefono: str = Field(default="", max_length=40)
    password: str = Field(min_length=8, max_length=128)
    rol: Literal["admin", "usuario"] = "usuario"
    activo: bool = True

class UserUpdate(BaseModel):
    nombres: str | None = None
    apellidos: str | None = None
    correo: EmailStr | None = None
    telefono: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    rol: Literal["admin", "usuario"] | None = None
    activo: bool | None = None

class UserOut(BaseModel):
    id: int; nombres: str; apellidos: str; correo: str; telefono: str; rol: str; activo: bool
    model_config = {"from_attributes": True}

class ResetRequest(BaseModel): correo: EmailStr
class ResetConfirm(BaseModel): token: str; nueva_password: str = Field(min_length=8, max_length=128)
class FileUpdate(BaseModel): nombre_dicom: str = Field(min_length=1, max_length=200)
class Ids(BaseModel): ids: list[int] = Field(min_length=1)

def db_session():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def audit(db: Session, user_id: int | None, action: str, detail: str = ""):
    db.add(Auditoria(usuario_id=user_id, accion=action, detalles=detail[:2000]))

def user_dict(u: Usuario):
    return {k: getattr(u, k) for k in ("id", "nombres", "apellidos", "correo", "telefono", "rol", "activo")}

def make_token(user: Usuario):
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"sub": str(user.id), "role": user.rol, "iat": now, "exp": now + dt.timedelta(minutes=TOKEN_MINUTES)}, SECRET_KEY, algorithm=ALGORITHM)

def current_user(token: Annotated[str, Depends(oauth2)], db: Session = Depends(db_session)):
    try: uid = int(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sub"])
    except Exception: raise HTTPException(status_code=401, detail="Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(Usuario, uid)
    if not user or not user.activo: raise HTTPException(status_code=401, detail="Usuario inactivo o inexistente")
    return user

def admin(user: Usuario = Depends(current_user)):
    if user.rol != "admin": raise HTTPException(status_code=403, detail="Se requiere rol administrador")
    return user

def base_dataset(path: Path, sop_uid: str):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_uid; meta.MediaStorageSOPInstanceUID = generate_uid(); meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    now = dt.datetime.now(); ds.PatientName = "Documento^Anonimo"; ds.PatientID = "DOC"
    ds.StudyDate = now.strftime("%Y%m%d"); ds.StudyTime = now.strftime("%H%M%S")
    ds.StudyInstanceUID = generate_uid(); ds.SeriesInstanceUID = generate_uid(); ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID; ds.SOPClassUID = sop_uid
    ds.Modality = "DOC"; ds.ContentDate = ds.StudyDate; ds.ContentTime = ds.StudyTime
    return ds

def image_to_dicom(source: Path, target: Path):
    img = Image.open(source).convert("RGB"); arr = np.asarray(img, dtype=np.uint8)
    ds = base_dataset(target, SecondaryCaptureImageStorage); ds.Modality = "OT"
    ds.Rows, ds.Columns = img.height, img.width; ds.SamplesPerPixel = 3; ds.PhotometricInterpretation = "RGB"; ds.PlanarConfiguration = 0
    ds.BitsStored = ds.BitsAllocated = 8; ds.HighBit = 7; ds.PixelRepresentation = 0; ds.PixelData = arr.tobytes(); ds.save_as(target, enforce_file_format=True)

def text_to_dicom(source: Path, target: Path, extension: str):
    raw = source.read_text(encoding="utf-8", errors="replace")
    if extension == "html": raw = re.sub(r"<[^>]+>", " ", raw)
    if extension == "json":
        try: raw = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except ValueError: pass
    lines = []
    for logical in raw.expandtabs(4).splitlines() or [""]:
        lines.extend(logical[i:i+105] for i in range(0, max(1, len(logical)), 105))
    lines = lines[:180]
    canvas = Image.new("RGB", (1240, max(400, 60 + len(lines) * 20)), "white"); draw = ImageDraw.Draw(canvas); font = ImageFont.load_default()
    for i, line in enumerate(lines): draw.text((30, 30 + i * 20), line, fill="black", font=font)
    temp = target.with_suffix(".png"); canvas.save(temp)
    try: image_to_dicom(temp, target)
    finally: temp.unlink(missing_ok=True)

def pdf_to_dicom(source: Path, target: Path):
    ds = base_dataset(target, EncapsulatedPDFStorage); ds.MIMETypeOfEncapsulatedDocument = "application/pdf"; ds.EncapsulatedDocument = source.read_bytes(); ds.save_as(target, enforce_file_format=True)

def convert(source: Path, target: Path, ext: str):
    if ext in {"jpg", "jpeg", "png", "bmp"}: image_to_dicom(source, target)
    elif ext == "pdf": pdf_to_dicom(source, target)
    elif ext in TEXT_FORMATS: text_to_dicom(source, target, ext)
    else: raise ValueError("Formato no soportado")

def safe_name(name: str): return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)

def send_reset(email: str, token: str):
    host = os.getenv("SMTP_HOST")
    if not host: return False
    message = EmailMessage(); message["Subject"] = "Recuperación de contraseña DICOM"; message["From"] = os.getenv("SMTP_FROM", "no-reply@dicom.local"); message["To"] = email
    message.set_content(f"Token de recuperación (válido 30 minutos): {token}")
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as smtp:
        smtp.starttls(); username = os.getenv("SMTP_USER")
        if username: smtp.login(username, os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)
    return True

@app.on_event("startup")
def bootstrap_admin():
    db = SessionLocal()
    try:
        if not db.query(Usuario).first():
            email = os.getenv("ADMIN_EMAIL", "admin@dicom.local").lower(); password = os.getenv("ADMIN_PASSWORD", "Cambiar123!")
            db.add(Usuario(nombres="Administrador", correo=email, password_hash=passwords.hash(password), rol="admin")); db.commit()
    finally: db.close()

@app.get("/")
def home(): return FileResponse(BASE_DIR / "index.html")

@app.post("/api/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(db_session)):
    u = db.query(Usuario).filter(Usuario.correo == form.username.lower()).first()
    if not u or not passwords.verify(form.password, u.password_hash) or not u.activo: raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    audit(db, u.id, "login"); db.commit(); return {"access_token": make_token(u), "token_type": "bearer", "usuario": user_dict(u)}

@app.get("/api/auth/me", response_model=UserOut)
def me(u: Usuario = Depends(current_user)): return u

@app.post("/api/auth/forgot-password")
def forgot(data: ResetRequest, db: Session = Depends(db_session)):
    u = db.query(Usuario).filter(Usuario.correo == data.correo.lower()).first()
    response = {"mensaje": "Si el correo existe, se enviaron instrucciones de recuperación."}
    if u:
        token = secrets.token_urlsafe(32); db.add(PasswordReset(usuario_id=u.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), vence_en=dt.datetime.utcnow()+dt.timedelta(minutes=30))); audit(db, u.id, "password_reset_request"); db.commit()
        sent = send_reset(u.correo, token)
        if not sent and os.getenv("ENVIRONMENT", "development") != "production": response["token_desarrollo"] = token
    return response

@app.post("/api/auth/reset-password")
def reset(data: ResetConfirm, db: Session = Depends(db_session)):
    token_hash = hashlib.sha256(data.token.encode()).hexdigest(); row = db.query(PasswordReset).filter_by(token_hash=token_hash, usado=False).first()
    if not row or row.vence_en < dt.datetime.utcnow(): raise HTTPException(status_code=400, detail="Token inválido o vencido")
    u = db.get(Usuario, row.usuario_id); u.password_hash = passwords.hash(data.nueva_password); row.usado = True; audit(db, u.id, "password_reset"); db.commit(); return {"mensaje": "Contraseña actualizada"}

@app.get("/api/usuarios", response_model=list[UserOut])
def users(db: Session = Depends(db_session), _: Usuario = Depends(admin)): return db.query(Usuario).order_by(Usuario.id).all()

@app.post("/api/usuarios", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(db_session), actor: Usuario = Depends(admin)):
    if db.query(Usuario).filter(Usuario.correo == data.correo.lower()).first(): raise HTTPException(status_code=409, detail="El correo ya existe")
    values = data.model_dump(); values["correo"] = str(values["correo"]).lower(); values["password_hash"] = passwords.hash(values.pop("password")); u = Usuario(**values); db.add(u); audit(db, actor.id, "user_create", values["correo"]); db.commit(); db.refresh(u); return u

@app.get("/api/usuarios/{uid}", response_model=UserOut)
def get_user(uid: int, db: Session = Depends(db_session), _: Usuario = Depends(admin)):
    u = db.get(Usuario, uid)
    if not u: raise HTTPException(404, "Usuario no encontrado")
    return u

@app.put("/api/usuarios/{uid}", response_model=UserOut)
def update_user(uid: int, data: UserUpdate, db: Session = Depends(db_session), actor: Usuario = Depends(admin)):
    u = db.get(Usuario, uid)
    if not u: raise HTTPException(404, "Usuario no encontrado")
    values = data.model_dump(exclude_unset=True)
    if "correo" in values: values["correo"] = str(values["correo"]).lower()
    if "password" in values: values["password_hash"] = passwords.hash(values.pop("password"))
    for k, v in values.items(): setattr(u, k, v)
    audit(db, actor.id, "user_update", str(uid)); db.commit(); db.refresh(u); return u

@app.delete("/api/usuarios/{uid}")
def delete_user(uid: int, db: Session = Depends(db_session), actor: Usuario = Depends(admin)):
    if actor.id == uid: raise HTTPException(400, "No puede eliminar su propia cuenta")
    u = db.get(Usuario, uid)
    if not u: raise HTTPException(404, "Usuario no encontrado")
    if db.query(Archivo).filter_by(subido_por=uid).first(): u.activo = False
    else: db.delete(u)
    audit(db, actor.id, "user_delete", str(uid)); db.commit(); return {"mensaje": "Usuario eliminado o desactivado"}

@app.post("/api/archivos", status_code=201)
async def upload(files: list[UploadFile] = File(...), db: Session = Depends(db_session), u: Usuario = Depends(current_user)):
    results = []
    for item in files:
        original = safe_name(item.filename or "archivo"); ext = Path(original).suffix.lower().lstrip(".")
        if ext not in ALLOWED: results.append({"archivo": original, "ok": False, "error": "Formato no soportado"}); continue
        raw = await item.read((MAX_FILE_MB * 1024 * 1024) + 1)
        if len(raw) > MAX_FILE_MB * 1024 * 1024: results.append({"archivo": original, "ok": False, "error": "Archivo demasiado grande"}); continue
        key = uuid.uuid4().hex; source = STORAGE_DIR / f"{key}.{ext}"; target = STORAGE_DIR / f"{key}.dcm"
        source.write_bytes(raw)
        try:
            convert(source, target, ext); row = Archivo(nombre_original=original, nombre_dicom=f"{Path(original).stem}-{key[:8]}.dcm", ruta_fisica=str(target), formato_origen=ext, tamano_bytes=target.stat().st_size, subido_por=u.id); db.add(row); db.flush(); results.append({"archivo": original, "ok": True, "id": row.id, "dicom": row.nombre_dicom})
        except Exception as exc: target.unlink(missing_ok=True); results.append({"archivo": original, "ok": False, "error": str(exc)})
        finally: source.unlink(missing_ok=True)
    audit(db, u.id, "files_convert", json.dumps(results, ensure_ascii=False)); db.commit(); return {"resultados": results}

@app.get("/api/archivos")
def files(db: Session = Depends(db_session), _: Usuario = Depends(current_user)): return db.query(Archivo).order_by(Archivo.fecha_subida.desc()).all()

@app.get("/api/archivos/{fid}")
def file_detail(fid: int, db: Session = Depends(db_session), _: Usuario = Depends(current_user)):
    row = db.get(Archivo, fid)
    if not row: raise HTTPException(404, "Archivo no encontrado")
    return row

@app.put("/api/archivos/{fid}")
def update_file(fid: int, data: FileUpdate, db: Session = Depends(db_session), u: Usuario = Depends(current_user)):
    row = db.get(Archivo, fid)
    if not row: raise HTTPException(404, "Archivo no encontrado")
    name = safe_name(data.nombre_dicom); row.nombre_dicom = name if name.lower().endswith(".dcm") else name + ".dcm"; audit(db, u.id, "file_update", str(fid)); db.commit(); db.refresh(row); return row

def remove_file(row: Archivo): Path(row.ruta_fisica).unlink(missing_ok=True)

@app.delete("/api/archivos/{fid}")
def delete_file(fid: int, db: Session = Depends(db_session), u: Usuario = Depends(current_user)):
    row = db.get(Archivo, fid)
    if not row: raise HTTPException(404, "Archivo no encontrado")
    remove_file(row); db.delete(row); audit(db, u.id, "file_delete", str(fid)); db.commit(); return {"mensaje": "Archivo eliminado"}

@app.post("/api/archivos-multiples/eliminar")
def bulk_delete(data: Ids, db: Session = Depends(db_session), u: Usuario = Depends(current_user)):
    rows = db.query(Archivo).filter(Archivo.id.in_(data.ids)).all()
    for row in rows: remove_file(row); db.delete(row)
    audit(db, u.id, "files_bulk_delete", str(data.ids)); db.commit(); return {"eliminados": len(rows)}

@app.get("/api/archivos/{fid}/descargar")
def download(fid: int, db: Session = Depends(db_session), _: Usuario = Depends(current_user)):
    row = db.get(Archivo, fid)
    if not row or not Path(row.ruta_fisica).is_file(): raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(row.ruta_fisica, filename=row.nombre_dicom, media_type="application/dicom")

@app.post("/api/archivos-multiples/descargar")
def bulk_download(data: Ids, db: Session = Depends(db_session), _: Usuario = Depends(current_user)):
    rows = db.query(Archivo).filter(Archivo.id.in_(data.ids)).all(); memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            path = Path(row.ruta_fisica)
            if path.is_file(): archive.write(path, arcname=row.nombre_dicom)
    memory.seek(0); return StreamingResponse(memory, media_type="application/zip", headers={"Content-Disposition": "attachment; filename=dicom_seleccionados.zip"})
