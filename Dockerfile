# Usar una imagen oficial de Python ligera
FROM python:3.11-slim

WORKDIR /app

# Copiar dependencias e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del servidor, la base de datos y la interfaz
COPY database.py main.py index.html ./

# Crear la carpeta de almacenamiento interno
RUN mkdir -p archivos_dicom && useradd --create-home appuser && chown -R appuser:appuser /app

USER appuser

EXPOSE 8866

# Iniciar servidor
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8866"]
