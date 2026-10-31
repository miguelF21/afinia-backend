# AFINIA — Entrega de integración Frontend/Backend

**Contrato:** `1.0.0-draft` · **Fecha:** 2026-10-27 · **Estado:** PROPUESTO PARA MOCKS, no API implementada.

## Archivos
- `afinia-openapi-v1.yaml`: fuente técnica de verdad objetivo para rutas, cuerpos, validaciones y respuestas.
- `afinia-mock-scenarios.json`: muestras ficticias de estados para pantallas y pruebas de UI.
- `README-INTEGRACION.md`: manual de consumo, alcance y decisiones.

## Iniciar un servidor mock HTTP

1. Tener Node.js disponible e instalar Prism como dependencia de desarrollo:

```bash
npm install --save-dev @stoplight/prism-cli
```

2. Desde el directorio del frontend (ajustar ruta relativa del YAML), ejecutar:

```bash
npx prism mock ../docs/api/afinia-openapi-v1.yaml -p 4010
```

Antes, copia los tres archivos del paquete en `<repo>/docs/api/`. Si eliges otro directorio, reemplaza la ruta del comando. No copies a ciegas el comando sin colocar primero el archivo.

3. Consumir la API simulada con base URL **`http://127.0.0.1:4010`**. Los `paths` ya incluyen `/api/v1`, por lo que **no** debes duplicar este prefijo.

4. Ejemplo:

```bash
curl http://127.0.0.1:4010/api/v1/match/potential -H "Authorization: Bearer mock-access-token"
```

5. Para un escenario de lista vacía usando ejemplos nombrados de Prism:

```bash
curl http://127.0.0.1:4010/api/v1/match/potential -H "Authorization: Bearer mock-access-token" -H "Prefer: example=sin_candidatos"
```

Prism devuelve **ejemplos estáticos**; **NO** persiste registros, autenticación, likes, sesiones ni mensajes. Para probar flujos con estado, el frontend debe usar handlers de mock stateful específicos o pruebas de componentes. Los ejemplos `example.test` son ficticios.

### Advertencia de desarrollo en dispositivos reales

`127.0.0.1` dentro de un Android/iOS físico **no apunta al PC** que ejecuta Prism. El desarrollador deberá establecer una base URL de red accesible solo en QA y configurar CORS/orígenes según plataforma. Nunca exponer el servidor mock a Internet sin control.

## Contrato de respuestas

- Respuesta correcta: `{"data": {...}}`; listas incluyen `meta.next_cursor` y `meta.has_more`.
- Error: `{"error": {"code":"VALIDATION_ERROR", "message":"...", "details": {...} } }`.
- `204`: sin body.
- JWT en cabecera `Authorization: Bearer <access_token>`; exceptuando registro/login/refresh y recursos públicos.
- Perfil público **nunca** devuelve email, `birth_date`, respuestas de encuesta, contraseña ni credenciales.
- Edad calculada en servidor; solo adultos y perfiles completos pueden aparecer en descubrir.
- Los valores enum son identificadores técnicos estables; el frontend pone etiquetas en español.

## Inventario de rutas

| Método | Ruta | Etapa | Estado frente al backend auditado | Propósito |
|---|---|---|---|---|
| `GET` | `/health` | infraestructura | existente_no_verificado | Comprobar que el proceso HTTP responde |
| `POST` | `/api/v1/auth/register` | MVP | existente_requiere_alineacion | Registrar cuenta pendiente de onboarding |
| `POST` | `/api/v1/auth/login` | MVP | existente_requiere_alineacion | Iniciar sesión |
| `POST` | `/api/v1/auth/refresh` | MVP | nuevo | Renovar sesión |
| `POST` | `/api/v1/auth/logout` | MVP | nuevo | Cerrar sesión y revocar refresh |
| `GET` | `/api/v1/profile/` | MVP | existente_requiere_alineacion | Obtener mi perfil |
| `POST` | `/api/v1/profile/` | MVP | existente_requiere_alineacion | Crear perfil durante onboarding |
| `PUT` | `/api/v1/profile/` | MVP | existente_requiere_alineacion | Actualizar mi perfil |
| `GET` | `/api/v1/users/{userId}` | MVP | nuevo | Obtener perfil público visible |
| `POST` | `/api/v1/profile/photos` | MVP | nuevo | Subir fotografía de perfil |
| `DELETE` | `/api/v1/profile/photos/{photoId}` | MVP | nuevo | Eliminar una foto propia |
| `GET` | `/api/v1/profile/discovery-preferences` | MVP | nuevo | Consultar preferencias de búsqueda |
| `PUT` | `/api/v1/profile/discovery-preferences` | MVP | nuevo | Guardar preferencias de búsqueda |
| `GET` | `/api/v1/match/potential` | MVP | existente_roto | Obtener candidatos filtrados y paginados |
| `POST` | `/api/v1/match/swipe` | MVP | existente_inseguro | Registrar LIKE o PASS de otro perfil |
| `GET` | `/api/v1/match/my-matches` | MVP | existente_requiere_alineacion | Listar mis matches activos |
| `GET` | `/api/v1/match/{matchId}` | MVP | nuevo | Consultar un match activo |
| `DELETE` | `/api/v1/match/{matchId}` | MVP | nuevo | Deshacer una coincidencia |
| `GET` | `/api/v1/match/{matchId}/messages` | MVP | nuevo | Listar mensajes de un match |
| `POST` | `/api/v1/match/{matchId}/messages` | MVP | nuevo | Enviar mensaje de texto |
| `POST` | `/api/v1/match/{matchId}/read` | MVP | nuevo | Marcar conversación como leída |
| `GET` | `/api/v1/questionnaire` | MVP | nuevo | Consultar preguntas de preferencias |
| `PUT` | `/api/v1/questionnaire/answers` | MVP | nuevo | Guardar respuestas de preferencias |
| `GET` | `/api/v1/questionnaire/answers` | MVP | nuevo | Consultar mis respuestas |
| `PUT` | `/api/v1/users/{userId}/block` | Producción | nuevo | Bloquear a otro usuario |
| `DELETE` | `/api/v1/users/{userId}/block` | Producción | nuevo | Desbloquear usuario |
| `GET` | `/api/v1/users/me/blocks` | Producción | nuevo | Consultar mis usuarios bloqueados |
| `POST` | `/api/v1/users/{userId}/reports` | Producción | nuevo | Denunciar un perfil |
| `GET` | `/api/v1/legal/current` | Producción | nuevo | Consultar versiones legales publicadas |
| `POST` | `/api/v1/legal/acceptances` | Producción | nuevo | Registrar aceptación explícita de versiones |
| `POST` | `/api/v1/account/deletion` | Producción | nuevo | Solicitar eliminación de cuenta |
| `GET` | `/api/v1/notifications` | Posterior | nuevo | Consultar notificaciones |
| `POST` | `/api/v1/notifications/{notificationId}/read` | Posterior | nuevo | Marcar una notificación como leída |
| `GET` | `/api/v1/auth/me` | MVP | nuevo | Consultar cuenta autenticada |
| `POST` | `/api/v1/auth/forgot-password` | Producción | nuevo | Solicitar recuperación de contraseña |
| `POST` | `/api/v1/auth/reset-password` | Producción | nuevo | Restablecer contraseña con token |
| `POST` | `/api/v1/auth/verify-email` | Producción | nuevo | Verificar correo electrónico |
| `POST` | `/api/v1/auth/resend-verification` | Producción | nuevo | Reenviar verificación de correo |
| `PUT` | `/api/v1/profile/photos/{photoId}/primary` | MVP | nuevo | Elegir foto principal |
| `GET` | `/api/v1/admin/reports` | Producción | nuevo | Listar reportes para moderación |
| `POST` | `/api/v1/admin/reports/{reportId}/resolve` | Producción | nuevo | Resolver reporte administrativo |

**Estados:** `existente_*` quiere decir que se observó código previo pero **NO** que cumpla este contrato ni que funcione en ejecución. `nuevo` requiere implementación. El endpoint histórico `/api/v1/analytics/predict` **no** forma parte del contrato consumible: su esquema está desacoplado del dataset original y no deben mostrarse porcentajes aleatorios. El antiguo `/api/v1/analytics/answers` tampoco es el contrato final: la interfaz consumirá `/api/v1/questionnaire/answers` al implementarse.

## Decisiones de producto y compatibilidad de base de datos

1. El CRUD de perfiles actuales `/api/v1/profile/` conserva el slash final, porque así está reportado en Flask. **No cambiar sin acordar modificación formal del contrato**.
2. El contrato normaliza género y `interested_in_genders` como **lista** (varios valores) para dar cabida a preferencias más flexibles. El ORM actual usa `interested_in_gender` escalar. **Debe abrirse tarea de migración y mapeo** antes de implementarlo; no prometer que funciona hoy.
3. Las fotografías, mensajes, bloqueo, denuncias, consentimientos, verificación de correo y sesiones renovables requieren tablas/infra adicionales, fuera del DB-02 de seis tablas; planificar migraciones futuras.
4. El cuestionario y preguntas del mock son **ilustrativos**, no se ha establecido correspondencia con encuesta real. Resolver antes de congelar identificadores de preguntas.
5. `target_relationship_type` propuesto acepta `seria`, `casual`, `amistad`, `sin_definir`. Confirmar con el negocio y normalizar desde valores históricos si difieren.
6. Los tokens tienen duración de ejemplo 900 segundos: política propuesta, no duración actualmente implementada. Web con refresh cookie segura, móvil en almacenamiento protegido; falta diseño detallado de revocación/CSRF.
7. Datos de ubicación solo incluyen `city`. No se define geolocalización exacta ni filtros de distancia en v1.
8. La mensajería v1 usa consulta HTTP, sin WebSockets; no afirmar chat en tiempo real. La entrega de mensajes y almacenamiento deben aprobarse antes de lanzar.
9. Las URLs de ejemplo `media.example.test` y `legal.example.test` son placeholders, no hosting real.
10. No implementar recomendaciones ML visibles hasta contar con variables reales, evaluación y explicación comprobables.

## Flujos que el desarrollador frontend puede mockear ya

- **Nuevo usuario:** registro → login → perfil → preferencias → descubrir.
- **Match:** mostrar candidato → LIKE/PASS → respuesta `is_match` → bandeja de matches.
- **Mensajería:** abrir match → mensajes vacíos o poblados → enviar mensaje → marcar como leído (solo simulado).
- **Seguridad:** bloquear o denunciar → perfiles omitidos en listas simuladas → confirmación.
- **Errores:** 401 (sesión), 403 (bloqueado), 409 (conflicto), 422 (formulario), 429 (limitar interacción), 500 (error de red general).
- **Estados de UI:** carga, vacío, error, sin conectividad, contenido, paginación y sesión vencida.

## Criterios de integración reales (pendientes)

- Backend devuelve exactamente los nombres, tipos, códigos HTTP y formatos descritos en OpenAPI.
- Pruebas de contrato para respuestas de registro, perfiles, preferencias, discovery, match mutuo, autorización y paginación.
- No comparar cadenas libres de errores para lógica de frontend; comparar `error.code`.
- Seguridad, configuración CORS, rate limits, almacenamiento de fotos y borrado de cuenta requieren validaciones propias.
- Si un contrato cambia, registrar cambio compatible/incompatible y actualizar versión antes de informar a frontend.

**Pendiente de acuerdo con equipo:** confirmar alcance de chat/fotos, opciones de género y preferencias, identificadores de cuestionario, política de sesión y correo transaccional antes del cierre de v1 estable. La moderación tiene rutas internas separadas y requiere roles administrativos.
