# BACKLOG DE TAREAS - AFINIA

Este backlog desglosa el Plan Maestro en Microtareas, enfocado en el corto plazo (Fases 0 a 2).

## FASE 0: AUDITORÍA Y CONFIGURACIÓN

### Tarea 0.1: Configuración de la estructura base
- [ ] **MT 0.1.1:** Crear la estructura de directorios (`backend`, `frontend`, `analytics`, `data/raw`, `data/processed`).
- [ ] **MT 0.1.2:** Inicializar el repositorio Git en la raíz `afinia`.
- [ ] **MT 0.1.3:** Crear el archivo `.gitignore` general.

### Tarea 0.2: Instalación y confirmación de herramientas
- [ ] **MT 0.2.1:** Instalar Angular CLI globalmente.
- [ ] **MT 0.2.2:** Solicitar al usuario la ubicación del Dataset CSV exportado y guardarlo en `data/raw/dataset_encuesta.csv`.
- [ ] **MT 0.2.3:** Configurar el entorno virtual de Python (`venv`) en la carpeta `backend` y crear un `requirements.txt` inicial (Flask, SQLAlchemy).

## FASE 1: REQUISITOS Y ARQUITECTURA

### Tarea 1.1: Documentación funcional y técnica
- [ ] **MT 1.1.1:** Redactar `03_REQUISITOS_FUNCIONALES.md` y `04_REQUISITOS_NO_FUNCIONALES.md`.
- [ ] **MT 1.1.2:** Escribir el `08_MODELO_DATOS.md` detallando las entidades principales.
- [ ] **MT 1.1.3:** Redactar el diseño del `UI_DESIGN_SYSTEM.md` con los lineamientos de colores e interacciones.
- [ ] **MT 1.1.4:** Crear la documentación `21_DICCIONARIO_DATASET_ENCUESTA.md` a partir del análisis del CSV crudo.

## FASE 2: BASE DE DATOS

### Tarea 2.1: Despliegue y configuración PostgreSQL
- [ ] **MT 2.1.1:** Crear archivo `docker-compose.yml` en la raíz (o en `backend/`) para levantar un contenedor con PostgreSQL.
- [ ] **MT 2.1.2:** Ejecutar el contenedor y validar la conexión (`psql` o cliente gráfico).

### Tarea 2.2: Backend Base y Modelos
- [ ] **MT 2.2.1:** Inicializar la estructura Flask (`app/`, `api/`, `models/`, `config.py`).
- [ ] **MT 2.2.2:** Configurar `Flask-SQLAlchemy` y `Flask-Migrate`.
- [ ] **MT 2.2.3:** Escribir los modelos de la base de datos (User, Profile, Questionnaire, Interaction, Match) en el código.
- [ ] **MT 2.2.4:** Generar y aplicar la primera migración de la base de datos.

*(El backlog será refinado y expandido a medida que se completen las fases iniciales).*
