# Proyecto Afinia - Analítica de Datos

## Requisitos Previos
1. **Node.js y npm** (Recomendado v20+)
2. **Angular CLI e Ionic CLI** instalados globalmente.
3. **Python 3.10+**
4. **Docker Desktop** activo y corriendo.

## Configuración del Backend
1. Iniciar Docker Desktop.
2. Levantar la base de datos:
   ```bash
   docker compose up -d
   ```
3. Activar el entorno virtual:
   - Windows: `.\backend\venv\Scripts\Activate.ps1`
4. Instalar dependencias:
   ```bash
   pip install -r backend/requirements.txt
   ```
5. Ejecutar migraciones (una vez la BD esté corriendo):
   ```bash
   cd backend
   flask db init
   flask db migrate -m "Initial migration"
   flask db upgrade
   ```
6. Iniciar el servidor:
   ```bash
   python run.py
   ```

## Configuración del Frontend
1. Ingresar al directorio: `cd frontend`
2. Instalar dependencias: `npm install`
3. Correr el servidor de desarrollo: `ionic serve`

## Analítica de Datos
El directorio `analytics` contiene los scripts modulares para procesar los datos provenientes de la carpeta `data/raw`. 
- Se requiere que el archivo CSV exportado desde Google Forms se coloque en `data/raw/` antes de ejecutar el pipeline.
