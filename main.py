from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
import os
import datetime
import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from PIL import Image, ImageDraw

app = FastAPI(title="Gestor Documental DICOM")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Base de datos temporal
USUARIOS = {
    "admin": "admin123",
    "medico1": "secreta1"
}

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

@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Autenticación de usuarios."""
    username = form_data.username
    password = form_data.password
    
    if USUARIOS.get(username) != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
        )
    return {"access_token": username, "token_type": "bearer"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), token: str = Depends(oauth2_scheme)):
    """Recibe un archivo, evalúa su formato y lo convierte a DICOM."""
    if not os.path.exists("archivos_recibidos"):
        os.makedirs("archivos_recibidos")
        
    nombre_original = file.filename
    extension = nombre_original.split('.')[-1].lower()
    nombre_base = nombre_original.rsplit('.', 1)[0]
    
    ruta_original = f"archivos_recibidos/{nombre_original}"
    ruta_dicom = f"archivos_recibidos/{nombre_base}.dcm"
    
    # 1. Guardar el archivo temporalmente
    with open(ruta_original, "wb+") as file_object:
        file_object.write(await file.read())
        
    # 2. Aplicar lógica DICOM según extensión
    try:
        if extension in ['jpg', 'jpeg']:
            jpg_a_dicom(ruta_original, ruta_dicom)
        elif extension == 'pdf':
            pdf_a_dicom(ruta_original, ruta_dicom)
        elif extension == 'txt':
            txt_a_dicom(ruta_original, ruta_dicom)
        else:
            os.remove(ruta_original)
            raise HTTPException(status_code=400, detail="Formato no soportado. Use JPG, PDF o TXT.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en conversión: {str(e)}")
        
    return {
        "mensaje": "Archivo convertido a DICOM exitosamente", 
        "archivo_original": nombre_original,
        "archivo_dicom": f"{nombre_base}.dcm",
        "usuario_responsable": token
    }

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
    
