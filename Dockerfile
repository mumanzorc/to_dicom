# Usar una imagen oficial de Python ligera
FROM python:3.11-slim

WORKDIR /app

# Copiar dependencias e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del servidor y la interfaz
COPY main.py .
COPY index.html .

# Crear la carpeta de almacenamiento interno
RUN mkdir -p archivos_recibidos

EXPOSE 8866

# Iniciar servidor en el puerto 8866
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8866"]
