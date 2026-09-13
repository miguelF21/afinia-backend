# ESTADO INICIAL DEL PROYECTO AFINIA

## 1. Qué existe
- **Directorio base:** `C:\Users\migue\Documents\SEMESTRE 10\ANALISIS DE DATOS\`
- **Documentación académica:** 
  - `Análisis_de_Patrones_de_Comportamiento_y_Preferencias_en_la_Elección_de_Pareja (1).pdf`
  - `Afinia Form.docx`
  - `Presentacion_Final_Afinia_UCC.pptx`
- **Herramientas base instaladas:** Node.js, npm, Python, Ionic CLI, Git, Docker.

## 2. Qué falta
- **Código y Repositorio:** No existe aún la carpeta raíz del repositorio inicializado, ni la estructura de código (`frontend`, `backend`, `analytics`).
- **Herramientas no detectadas:** Angular CLI (`ng`) y PostgreSQL CLI (`psql`) no están en el PATH del sistema o no están instalados.
- **Datos (Dataset):** El dataset RAW (103 observaciones, 49 columnas) exportado desde Google Forms no se encuentra en formato `.csv` o `.xlsx` en el directorio de trabajo actual. Debe exportarse y ubicarse en `data/raw/`.

## 3. Tecnologías encontradas (Auditoría del Entorno)
- **Sistema Operativo:** Windows
- **Node.js:** v22.23.2
- **npm:** 10.9.8
- **Ionic CLI:** 7.2.1
- **Python:** 3.10.11
- **pip:** 23.0.1
- **Git:** 2.55.0.windows.3
- **Docker:** 29.6.2 (build dfc4efb)

## 4. Documentación existente
- Documento académico que contextualiza el proyecto y su enfoque en el análisis de preferencias de elección de pareja.
- Formulario de la encuesta de recolección de datos (Word).
- Presentaciones del proyecto.

## 5. Inconsistencias
- **Angular CLI faltante:** A pesar de tener Ionic, el comando `ng` no fue encontrado. Será necesario instalarlo globalmente o ejecutarlo vía `npx`/`npm`.
- **PostgreSQL faltante:** `psql` no responde. Es necesario determinar si se instalará localmente en Windows o si se aprovechará Docker (que está instalado) para levantar la base de datos, lo cual es altamente recomendado.
- **Dataset no ubicado:** Las instrucciones mencionan un dataset comprobado de 103 respuestas, pero no está el archivo en el sistema de archivos actual.

## 6. Riesgos
- **Riesgo de Data Leakage:** Al tener una muestra pequeña (103), cualquier filtración entre Train y Test puede comprometer los resultados.
- **Desbalance de clases:** El target inicial propuesto ("Tipo de relación buscada") tiene un alto desbalance hacia "relación seria y estable", lo que dificulta el modelo predictivo inicial.
- **Sobreingeniería:** Dado que se tienen 2 meses para el MVP, existe el riesgo de dedicar mucho tiempo a la UI o chat, relegando la analítica.
- **Sesgo de la muestra:** Fuerte concentración en población de 18 a 22 años.

## 7. Dependencias
- Aprobación de la arquitectura y el roadmap.
- Provisión del archivo CSV con los datos crudos del Google Forms.
- Instalación/Configuración de la Base de Datos (PostgreSQL).

## 8. Decisiones pendientes
1. **Infraestructura DB:** ¿Utilizar Docker para levantar el contenedor de PostgreSQL o instalarlo nativamente en el entorno Windows?
2. **Angular CLI:** ¿Instalar de forma global (`npm install -g @angular/cli`)?
3. **Manejo del Dataset:** Confirmar la ruta y el nombre del CSV de las respuestas de Google Forms para incorporarlo en `data/raw/` de forma inmutable.
4. **Target Predictivo Inicial:** Confirmar el enfoque de agrupación binaria (RELACION_SERIA vs OTRA_ORIENTACION) para evitar problemas de desbalance severo en la iteración inicial.
