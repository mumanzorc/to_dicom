# DICOM Convert

Aplicación web segura para convertir uno o varios archivos a DICOM y administrar los resultados.

## Formatos

Imágenes: JPG/JPEG, PNG y BMP. Documentos: PDF. Texto renderizado como Secondary Capture: TXT, CSV, JSON, LOG, MD, XML y HTML.

## Funciones

- Inicio de sesión con JWT y contraseñas bcrypt.
- Roles `admin` y `usuario`; CRUD de usuarios reservado al administrador.
- Recuperación de contraseña con token de un solo uso y vencimiento de 30 minutos.
- Conversión por lotes, listado, detalle, cambio de nombre, borrado y descarga DICOM.
- Selección múltiple para descarga ZIP o eliminación.
- Registro de auditoría.
- PostgreSQL en Docker y SQLite por defecto para desarrollo local.

## Inicio rápido con Docker

1. Copie `.env.example` a `.env` y cambie todos los secretos.
2. Ejecute `docker compose up --build`.
3. Abra `http://localhost:8866`.

En desarrollo, si no se configura SMTP, la interfaz muestra el token de recuperación. En producción nunca lo devuelve. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` y `SMTP_FROM` para enviar el correo.

## Desarrollo local

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8866
```

La primera ejecución crea un administrador con `ADMIN_EMAIL` y `ADMIN_PASSWORD`. Los valores de demostración son `admin@dicom.local` / `Cambiar123!` y deben reemplazarse.

## API

La documentación interactiva queda disponible en `/docs`. El tamaño máximo por archivo se controla con `MAX_FILE_MB` (50 por defecto).
