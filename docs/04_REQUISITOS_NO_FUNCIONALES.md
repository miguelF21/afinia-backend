# REQUISITOS NO FUNCIONALES - AFINIA

## RNF1 - SEGURIDAD Y PRIVACIDAD
- **RNF1.1 Hashing de contraseñas:** Todas las contraseñas deben ser almacenadas utilizando un algoritmo de hash seguro (ej. bcrypt).
- **RNF1.2 Autenticación:** Se utilizará JWT (JSON Web Tokens) para las sesiones de API. El token debe expirar.
- **RNF1.3 Minimización de Datos:** Los datos analíticos y el comportamiento del usuario deben ser pseudonimizados al exportarse para el modelo de ML.
- **RNF1.4 Variables de Entorno:** Credenciales, Secret Keys de JWT y cadenas de conexión a base de datos deben gestionarse mediante `.env`.

## RNF2 - ARQUITECTURA E INFRAESTRUCTURA
- **RNF2.1 Monolito Modular:** El backend se estructurará como un monolito modular con Flask. No se implementarán microservicios.
- **RNF2.2 Base de datos:** Se utilizará PostgreSQL como único motor de persistencia relacional.
- **RNF2.3 Migraciones:** Toda modificación al esquema de base de datos debe estar versionada a través de Alembic (Flask-Migrate).
- **RNF2.4 Pipeline Analítico:** Los scripts analíticos deben correr independientemente de los hilos de la API, usando scripts dedicados.

## RNF3 - CALIDAD Y ESTÁNDARES DE CÓDIGO
- **RNF3.1 Control de Versiones:** Uso estricto de Git con commits atómicos.
- **RNF3.2 Patrones de Diseño:** En backend, separación en Capas (Controlador/Ruta, Servicio, Repositorio de ser necesario). En frontend, uso de core, shared y features (patrones Angular).
- **RNF3.3 Trazabilidad Analítica:** Cada variable utilizada para Machine Learning debe poder trazarse hasta su respuesta de origen en la base de datos relacional.

## RNF4 - DESEMPEÑO
- **RNF4.1 Idempotencia:** Los endpoints críticos (como realizar un MATCH) deben ser idempotentes para manejar posibles reintentos de red desde móviles.
- **RNF4.2 Paginación:** El endpoint de descubrimiento debe enviar perfiles paginados para no saturar la memoria del cliente.

## RNF5 - USABILIDAD
- **RNF5.1 Mobile-First:** El diseño UI debe ser responsivo priorizando la visualización en teléfonos móviles.
- **RNF5.2 Consistencia Visual:** La app usará un Design System documentado evitando ser una copia visual directa de otras aplicaciones comerciales.
