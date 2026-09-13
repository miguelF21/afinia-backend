# REQUISITOS FUNCIONALES - AFINIA

## MÓDULO 1 — AUTENTICACIÓN
- **RF1.1 Registro:** El sistema debe permitir a los usuarios registrarse utilizando correo electrónico y contraseña.
- **RF1.2 Inicio de sesión:** El sistema debe permitir a los usuarios iniciar sesión y recibir un token JWT válido.
- **RF1.3 Cierre de sesión:** El sistema debe permitir invalidar la sesión actual (borrado local del token).
- **RF1.4 Tratamiento de datos:** El usuario debe aceptar los términos de uso y el tratamiento de datos para fines académicos antes de registrarse.

## MÓDULO 2 — ONBOARDING
- **RF2.1 Información básica:** Recopilar género, edad y ubicación (ciudad).
- **RF2.2 Experiencias:** Recopilar datos sobre experiencias sentimentales pasadas e intenciones relacionales actuales.

## MÓDULO 3 — CUESTIONARIO DE PREFERENCIAS
- **RF3.1 Cuestionario Estructurado:** El sistema debe presentar preguntas sobre personalidad, físico, humor y valores.
- **RF3.2 Almacenamiento Analítico:** Cada respuesta debe mapearse de manera unívoca a una variable analítica y almacenarse en la base de datos de manera normalizada.

## MÓDULO 4 — PERFIL
- **RF4.1 Datos Públicos:** Permitir configurar fotos, descripción corta y tags de intereses visibles para otros usuarios.
- **RF4.2 Privacidad Analítica:** Los datos de cuestionarios analíticos no deben ser públicos en el perfil de descubrimiento.

## MÓDULO 5 — DESCUBRIMIENTO
- **RF5.1 Filtros:** Mostrar perfiles basados en el género de interés, rango de edad y ciudad.
- **RF5.2 Interacción LIKE/PASS:** El sistema debe permitir al usuario deslizar o interactuar indicando LIKE (Me gusta) o PASS (Pasar).
- **RF5.3 Registro de Evento:** Toda acción LIKE/PASS debe generar un registro auditable (`viewer_user_id`, `shown_profile_id`, `action`, `timestamp`).

## MÓDULO 6 — MATCH
- **RF6.1 Generación de Match:** Si dos usuarios se dan LIKE mutuamente, el sistema debe crear un registro de MATCH de manera transaccional e idempotente (evitar duplicados).
- **RF6.2 Visualización de Matches:** Mostrar al usuario la lista de personas con las que tiene Match.

## MÓDULO 7 — PREFERENCIAS DE DESCUBRIMIENTO
- **RF7.1 Ajustes:** Permitir al usuario cambiar su rango de edad buscado, género de interés y distancia/ubicación.

## MÓDULO 8 — ANALÍTICA (Módulo Académico)
- **RF8.1 Generación de Dataset:** El sistema debe permitir exportar las respuestas del cuestionario y los registros de iteración.
- **RF8.2 Dashboard:** Interfaz para visualizar estadísticas descriptivas (frecuencias, porcentajes de intereses) a nivel agregado.
