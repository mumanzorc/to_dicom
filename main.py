from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from passlib.context import CryptContext
from typing import List
import os
import datetime
import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from PIL import Image, ImageDraw

# Importar nuestra base de datos
#from database import Base, engine, SessionLocal, Usuario
from database import Base, engine, SessionLocal, Usuario, Archivo
# Crear las tablas en la base de datos si no existen
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Gestor Documental DICOM")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- DEPENDENCIA DE BASE DE DATOS ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- SCHEMAS DE PYDANTIC (Validación de datos de entrada/salida) ---
class UsuarioCreate(BaseModel):
    nombres: str
    apellidos: str
    correo: str
    telefono: str
    password: str
    rol: str = "usuario"

class UsuarioResponse(BaseModel):
    id: int
    nombres: str
    apellidos: str
    correo: str
    telefono: str
    rol: str
    activo: bool

    class Config:
        from_attributes = True

# --- FUNCIONES DEL MOTOR DICOM (Mantén tus funciones aquí) ---
# def crear_dataset_base(ruta_salida, sop_class_uid):
# ... (MANTÉN TU CÓDIGO DICOM INTACTO AQUÍ) ...


# --- FUNCIONES DEL MOTOR DICOM ---
def crear_dataset_base(ruta_salida, sop_class_uid):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(ruta_salida, {}, file_meta=file_meta, preamble=b"\0" * 128)
    
    ds.PatientName = "Paciente^Anonimo"
    ds.PatientID = "000000"
    ds.StudyDate = datetime.datetime.now().strftime('%Y%m%d')
    ds.StudyTime = datetime.datetime.now().strftime('%H%M%S')
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = sop_class_uid
    
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds

def jpg_a_dicom(ruta_jpg, ruta_salida):
    ds = crear_dataset_base(ruta_salida, '1.2.840.10008.5.1.4.1.1.7')
    ds.Modality = "OT"
    
    img = Image.open(ruta_jpg).convert('L')
    np_frame = np.array(img.getdata(), dtype=np.uint8)
    
    ds.Rows = img.height
    ds.Columns = img.width
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.SamplesPerPixel = 1
    ds.BitsStored = 8
    ds.BitsAllocated = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    
    ds.PixelData = np_frame.tobytes()
    ds.save_as(ruta_salida)

def pdf_a_dicom(ruta_pdf, ruta_salida):
    ds = crear_dataset_base(ruta_salida, '1.2.840.10008.5.1.4.1.1.104.1')
    ds.Modality = "DOC"
    ds.ConversionType = "WSD"
    
    with open(ruta_pdf, 'rb') as f:
        ds.EncapsulatedDocument = f.read()
    
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    ds.save_as(ruta_salida)

def txt_a_dicom(ruta_txt, ruta_salida):
    with open(ruta_txt, 'r', encoding='utf-8') as f:
        texto = f.read()
        
    img = Image.new('L', (800, 1000), color=255)
    d = ImageDraw.Draw(img)
    d.text((20, 20), texto, fill=0)
    
    imagen_temporal = ruta_txt + "_temp.jpg"
    img.save(imagen_temporal)
    
    jpg_a_dicom(imagen_temporal, ruta_salida)
    os.remove(imagen_temporal)

# --- RUTAS DE LA APLICACIÓN WEB (ENDPOINTS) ---

@app.get("/")
async def servir_interfaz():
    """Sirve el archivo HTML principal."""
    if not os.path.exists("index.html"):
        raise HTTPException(status_code=404, detail="Archivo de interfaz no encontrado.")
    return FileResponse("index.html")

# --- RUTAS DE USUARIOS Y AUTENTICACIÓN ---

@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Login conectado a la base de datos PostgreSQL"""
    # Buscamos al usuario por su correo (que usamos como username en el formulario)
    usuario = db.query(Usuario).filter(Usuario.correo == form_data.username).first()
    
    if not usuario or not pwd_context.verify(form_data.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
        )
    
    if not usuario.activo:
        raise HTTPException(status_code=400, detail="Usuario inactivo")

    # Devolvemos el ID del usuario en el token para saber quién sube archivos
    return {"access_token": str(usuario.id), "token_type": "bearer"}

@app.post("/usuarios", response_model=UsuarioResponse)
async def crear_usuario(user: UsuarioCreate, db: Session = Depends(get_db)):
    """Crea un nuevo usuario en la base de datos"""
    # Verificar si el correo ya existe
    db_user = db.query(Usuario).filter(Usuario.correo == user.correo).first()
    if db_user:
        raise HTTPException(status_code=400, detail="El correo ya está registrado")
    
    # Encriptar contraseña
    hashed_password = pwd_context.hash(user.password)
    
    nuevo_usuario = Usuario(
        nombres=user.nombres,
        apellidos=user.apellidos,
        correo=user.correo,
        telefono=user.telefono,
        rol=user.rol,
        password_hash=hashed_password
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return nuevo_usuario

@app.get("/usuarios", response_model=List[UsuarioResponse])
async def listar_usuarios(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    """Devuelve la lista de todos los usuarios registrados"""
    usuarios = db.query(Usuario).all()
    return usuarios

@app.put("/usuarios/{user_id}", response_model=UsuarioResponse)
async def actualizar_usuario(user_id: int, user_data: UsuarioCreate, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    """Permite editar los datos de un usuario existente"""
    usuario = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    usuario.nombres = user_data.nombres
    usuario.apellidos = user_data.apellidos
    usuario.correo = user_data.correo
    usuario.telefono = user_data.telefono
    usuario.rol = user_data.rol
    
    # Solo actualizar contraseña si se envía una nueva
    if user_data.password:
        usuario.password_hash = pwd_context.hash(user_data.password)
        
    db.commit()
    db.refresh(usuario)
    return usuario


@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...), token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Convierte archivos y los registra en la Base de Datos PostgreSQL."""
    if not os.path.exists("archivos_recibidos"):
        os.makedirs("archivos_recibidos")
        
    usuario_id = int(token) # El token actual guarda el ID del usuario
    archivos_exitosos = 0
    
    for file in files:
        nombre_original = file.filename
        extension = nombre_original.split('.')[-1].lower()
        nombre_base = nombre_original.rsplit('.', 1)[0]
        
        ruta_original = f"archivos_recibidos/{nombre_original}"
        ruta_dicom = f"archivos_recibidos/{nombre_base}.dcm"
        
        with open(ruta_original, "wb+") as file_object:
            file_object.write(await file.read())
            
        estado = "Éxito"
        try:
            if extension in ['jpg', 'jpeg']:
                jpg_a_dicom(ruta_original, ruta_dicom)
            elif extension == 'pdf':
                pdf_a_dicom(ruta_original, ruta_dicom)
            elif extension == 'txt':
                txt_a_dicom(ruta_original, ruta_dicom)
            else:
                os.remove(ruta_original)
                estado = "Error: Formato no soportado"
        except Exception as e:
            estado = f"Error interno: {str(e)}"
            
        # Guardar en Base de Datos si la conversión fue exitosa
        if estado == "Éxito":
            nuevo_archivo = Archivo(
                nombre_original=nombre_original,
                nombre_dicom=f"{nombre_base}.dcm",
                ruta_fisica=ruta_dicom,
                subido_por=usuario_id
            )
            db.add(nuevo_archivo)
            db.commit()
            archivos_exitosos += 1
        
    return {"mensaje": f"Proceso finalizado. {archivos_exitosos} archivo(s) guardado(s) en la base de datos."}

@app.get("/archivos")
async def listar_archivos(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    """Devuelve el listado completo de archivos registrados."""
    archivos = db.query(Archivo).order_by(Archivo.fecha_subida.desc()).all()
    return archivos

@app.delete("/archivos/{archivo_id}")
async def eliminar_archivo(archivo_id: int, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    """Elimina un archivo de la base de datos y del disco duro."""
    archivo = db.query(Archivo).filter(Archivo.id == archivo_id).first()
    if not archivo:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    # Eliminar del disco físico
    if os.path.exists(archivo.ruta_fisica):
        os.remove(archivo.ruta_fisica)
        
    # Eliminar de la base de datos
    db.delete(archivo)
    db.commit()
    return {"mensaje": "Archivo eliminado correctamente"}

@app.get("/download/{filename}")
async def download_file(filename: str, token: str = Depends(oauth2_scheme)):
    ruta_archivo = f"archivos_recibidos/{filename}"
    if not os.path.exists(ruta_archivo):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
        
    return FileResponse(path=ruta_archivo, filename=filename, media_type='application/dicom')

@app.get("/download/{filename}")
async def download_file(filename: str, token: str = Depends(oauth2_scheme)):
    """Permite la descarga segura del archivo generado."""
    ruta_archivo = f"archivos_recibidos/{filename}"
    if not os.path.exists(ruta_archivo):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
        
    return FileResponse(
        path=ruta_archivo, 
        filename=filename, 
        media_type='application/dicom'
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8866)
    
