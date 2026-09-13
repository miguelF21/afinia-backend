# PLAN MAESTRO - PROYECTO AFINIA

## FASE 0: Auditoría y configuración (Semana 1)
- [ ] Inicializar el repositorio Git.
- [ ] Configurar la estructura de carpetas (`frontend`, `backend`, `analytics`, `docs`, `data`).
- [ ] Definir e instalar herramientas faltantes (Angular CLI, contenedor PostgreSQL en Docker).
- [ ] Ubicar el dataset inicial de respuestas de Google Forms en la carpeta `data/raw`.
- [ ] Crear los documentos iniciales de arquitectura, requisitos y backlog.

## FASE 1: Requisitos y arquitectura (Semana 1)
- [ ] Redactar Requisitos Funcionales y No Funcionales.
- [ ] Establecer el Modelo de Datos Conceptual, Lógico y Físico.
- [ ] Redactar el documento del Design System y lineamientos UI.
- [ ] Diseñar el mapeo de variables entre Google Forms y el futuro modelo relacional (continuidad de datos).

## FASE 2: Base de datos (Semana 2)
- [ ] Crear la infraestructura local de PostgreSQL (Docker).
- [ ] Configurar el backend en Flask y SQLAlchemy.
- [ ] Diseñar las entidades base (Usuarios, Perfiles, Cuestionario, Interacciones, Matches).
- [ ] Crear y ejecutar las primeras migraciones (Alembic/Flask-Migrate).

## FASE 3: Backend base, autenticación y usuarios (Semana 2-3)
- [ ] Implementar registro e inicio de sesión.
- [ ] Implementar middleware JWT para protección de rutas.
- [ ] Endpoint de perfil de usuario.
- [ ] Pruebas unitarias de API para endpoints de autenticación (Postman / Pytest).

## FASE 4: Frontend base, onboarding y perfiles (Semana 3-4)
- [ ] Iniciar el proyecto en Ionic/Angular con la estructura core/shared/features.
- [ ] Implementar interfaz del Design System (Colores, Tipografía, Botones, Cards).
- [ ] Flujo de Onboarding (Información básica, preferencias iniciales).
- [ ] Vista del perfil propio.

## FASE 5: Cuestionario y recopilación de datos (Semana 4-5)
- [ ] Diseñar UI y endpoints para el cuestionario de preferencias.
- [ ] Asegurar compatibilidad de las respuestas del cuestionario con las variables de la encuesta de Google Forms.
- [ ] Guardar las respuestas transaccionalmente.
- [ ] Emisión de eventos analíticos (`QUESTIONNAIRE_COMPLETED`).

## FASE 6: Discovery, likes y matches (Semana 5-6)
- [ ] Algoritmo base de descubrimiento (filtrar por edad, género de interés y ubicación).
- [ ] Tarjetas tipo swipe (LIKE/PASS).
- [ ] Lógica backend para registrar la interacción y emitir eventos analíticos.
- [ ] Lógica de Match transaccional (Idempotente).
- [ ] Pantalla para ver matches.

## FASE 7: Analítica descriptiva y diagnóstica (Semana 6-7)
- [ ] Desarrollar pipeline reproducible (`src/load_data.py`, `src/clean_data.py`).
- [ ] Analizar el dataset original exportado.
- [ ] Generar estadística descriptiva (distribuciones, demografía de la muestra).
- [ ] Analítica diagnóstica (Correlaciones, tablas cruzadas, test de Chi-cuadrado).
- [ ] Documentar hallazgos en reportes.

## FASE 8: Modelo predictivo (Semana 7)
- [ ] Seleccionar el target predictivo (ej. agrupado binario: RELACION_SERIA vs OTRA_ORIENTACION).
- [ ] Implementar Baselines (DummyClassifier, Regresión Logística).
- [ ] Entrenar y comparar Decision Tree vs Baseline usando Validacion Cruzada Estratificada.
- [ ] Extraer e interpretar los coeficientes / reglas del árbol.
- [ ] Evitar y documentar cualquier leakage.

## FASE 9: Integración, testing y hardening (Semana 8)
- [ ] Pruebas E2E del flujo del MVP (Registro -> Onboarding -> Discovery -> Match -> Analytics).
- [ ] Pruebas de concurrencia y validación de seguridad.
- [ ] Corrección de bugs y refactorización.

## FASE 10: Documentación académica y presentación (Semana 8)
- [ ] Finalizar documentación CRISP-DM y resultados estadísticos.
- [ ] Documentar modelo relacional final y manual de despliegue.
- [ ] Empaquetar proyecto para la sustentación universitaria.
