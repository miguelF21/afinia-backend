# AFINIA — Guía Oficial de Integración Frontend (Ionic / Angular)

**Versión del Contrato:** `OpenAPI v1` (`docs/api/afinia-openapi-v1.yaml`)  
**Revisión Alembic de Base de Datos:** `a7b3c9d1e5f2 (head)`  
**Destinatario:** Desarrollador Frontend (Ionic / Angular / Capacitor)  
**Fecha de Certificación:** Noviembre 2026  
**Estado:** Backend Verificado y Certificado con Paridad OpenAPI v1 / Flask (41/41 Operaciones Activas)  

---

## 1. Conectividad y Configuración del Entorno

### 1.1. Base URL según la Plataforma de Ejecución

El backend de Flask expone sus rutas canónicas bajo `/api/v1` (excepto `/health` que responde en la raíz).  
La URL base debe ser configurable mediante `src/environments/environment.ts` y `environment.prod.ts`:

```typescript
// frontend/src/environments/environment.ts
export const environment = {
  production: false,
  // 1. Navegador Web local (Ionic serve en el mismo equipo):
  apiUrl: 'http://127.0.0.1:5000/api/v1',
  
  // 2. Emulador Oficial de Android (Android Studio / AVD):
  // 10.0.2.2 es el alias que el emulador asigna al host loopback del PC:
  // apiUrl: 'http://10.0.2.2:5000/api/v1',

  // 3. Simulador de iOS (Xcode):
  // apiUrl: 'http://127.0.0.1:5000/api/v1',

  // 4. Dispositivo Físico (Android / iOS en red Wi-Fi compartida):
  // Requiere ejecutar Flask escuchando en todas las interfaces (--host 0.0.0.0)
  // apiUrl: 'http://192.168.1.XX:5000/api/v1',

  legalTermsVersion: 'v1-draft',
  legalPrivacyVersion: 'v1-draft'
};
```

> [!WARNING]
> En emuladores Android y dispositivos móviles físicos, `localhost` y `127.0.0.1` apuntan al propio dispositivo móvil. Para Android Studio, usa `http://10.0.2.2:5000/api/v1`. Para dispositivos físicos en la misma red Wi-Fi, usa la IP local de tu computador (ej. `192.168.1.45:5000/api/v1`).

### 1.2. Configuración CORS y Credenciales

El backend tiene configurado CORS estricto con orígenes autorizados:
- `http://localhost:8100` y `http://127.0.0.1:8100` (Ionic serve)
- `http://localhost:4200` y `http://127.0.0.1:4200` (Angular CLI)
- `capacitor://localhost` (Capacitor nativo iOS/Android)
- `ionic://localhost` (Ionic WebView)

Cabeceras permitidas por el servidor:  
`Content-Type`, `Authorization`, `X-Client-Platform`, `X-Requested-With`.  
Soporte de credenciales activado: `supports_credentials=True`.

---

## 2. Autenticación y Gestión de Tokens

### 2.1. Tokens de Acceso (JWT) y Cabecera de Autorización

Todas las peticiones a rutas protegidas requieren la cabecera:
```http
Authorization: Bearer <access_token>
```
- **Duración del Access Token:** 15 minutos (900 segundos).
- **Algoritmo:** HMAC SHA-256 emitido por el backend.
- Si la cabecera falta o el token expira, el backend responde HTTP `401 Unauthorized`.

### 2.2. Modalidad Móvil vs. Web para Refresh Tokens

El backend implementa un mecanismo híbrido de transporte del `refresh_token`:
- **Web (navegador):** Si no se envía cabecera móvil, el `refresh_token` se transporta en una cookie `HttpOnly; SameSite=Lax`.
- **Móvil (Ionic / Capacitor):** Enviar la cabecera `X-Client-Platform: mobile` en `/api/v1/auth/login` y `/api/v1/auth/refresh`. Con esta cabecera, el backend devuelve el `refresh_token` directamente en el cuerpo JSON de la respuesta.

#### Ejemplo de Login Móvil:
```http
POST /api/v1/auth/login HTTP/1.1
Content-Type: application/json
X-Client-Platform: mobile

{
  "email": "usuario@example.com",
  "password": "Password123*Secure!"
}
```

#### Respuesta de Login Móvil (HTTP 200 OK):
```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
    "expires_in": 900,
    "refresh_token": "JEBN7rAFXcbGrF0KP8O17G_z07olVs9OQBhdCQtQ...",
    "token_type": "Bearer",
    "user": {
      "email": "usuario@example.com",
      "email_verified": true,
      "id": "9ae4bba3-7312-4bd9-9b08-608856b8203d",
      "onboarding_complete": true,
      "status": "active"
    }
  }
}
```

#### Renovación de Sesión Móvil:
```http
POST /api/v1/auth/refresh HTTP/1.1
Content-Type: application/json
X-Client-Platform: mobile

{
  "refresh_token": "JEBN7rAFXcbGrF0KP8O17G_z07olVs9OQBhdCQtQ..."
}
```

---

## 3. Formato Canónico de Envoltorios de Respuesta y Errores

### 3.1. Envoltorio de Éxito (`data`)
Todas las respuestas exitosas devuelven los datos dentro de una clave raíz `"data"`:
```json
{
  "data": { ... }
}
```
Las operaciones de eliminación exitosa (`DELETE`) retornan **HTTP 204 No Content** con cuerpo vacío.

### 3.2. Envoltorio de Paginación (`data.items` y `meta`)
Los endpoints con listados paginados (candidatos y mensajes) devuelven:
```json
{
  "data": {
    "items": [ ... ]
  },
  "meta": {
    "has_more": false,
    "next_cursor": null
  }
}
```
Si `meta.has_more` es `true`, enviar `?cursor=<meta.next_cursor>` en la siguiente petición.

### 3.3. Formato Real de Error

> [!IMPORTANT]
> **Campos de error:** Todas las respuestas de error generadas por la factoría `api_error` contienen exactamente:
> - `code`: Código alfanumérico en mayúsculas (ej. `UNAUTHORIZED`, `VALIDATION_ERROR`, `NOT_FOUND`, `FORBIDDEN`).
> - `message`: Explicación textual legible del error.
> - `request_id`: Identificador único de trazabilidad (ej. `"req_0fb524631d68"`).
> - `details` *(opcional)*: Objeto o lista con detalles de campos inválidos.
> 
> El campo `status` **NO** forma parte del cuerpo JSON; el código de estado HTTP se encuentra en la cabecera HTTP de la respuesta.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "El campo accept_terms_version es obligatorio.",
    "request_id": "req_e00e90accc08"
  }
}
```

#### Catálogo de Códigos de Error Reales del Backend

| Código HTTP | `error.code` | Caso de Uso Real |
| :---: | :--- | :--- |
| **400** | `BAD_REQUEST` | JSON malformado, o presencia de campos no permitidos en el payload (rechazo estricto de mass assignment). |
| **401** | `UNAUTHORIZED` | Cabecera `Authorization` ausente, token expirado, firma inválida o refresh token revocado. |
| **403** | `FORBIDDEN` | Usuario con onboarding incompleto intentando acceder a discovery o chat; usuario sin foto principal aprobada; intento de ver foto privada sin match mutuo. |
| **404** | `NOT_FOUND` | Recurso no encontrado. **Nota:** Para un match cerrado tras unmatch o usuarios con bloqueo mutuo, el backend retorna `404 NOT_FOUND` con mensaje `"Match no encontrado."`. |
| **409** | `CONFLICT` | Email ya registrado en `/register`; perfil ya existente al llamar `POST /profile`; match ya existente. |
| **422** | `VALIDATION_ERROR` | Error de reglas de negocio en campos (edad < 18, formato email inválido, lista de géneros vacía, etc.). |
| **429** | `RATE_LIMIT_EXCEEDED`| Demasiadas peticiones en la ventana de tiempo (ej. reenvío de correo o login reiterado). |
| **500** | `INTERNAL_ERROR` | Excepción no controlada en el servidor. |

---

## 4. Inventario Canónico de Endpoints para el Desarrollador Frontend

Confrontación directa 1:1 entre `docs/api/afinia-openapi-v1.yaml` y `app.url_map` de Flask.

### 4.1. Sistema y Salud
| Método | Ruta Canónica | Auth | Descripción |
| :--- | :--- | :---: | :--- |
| `GET` | `/health` | No | Comprueba que el proceso Flask responda (`{"status": "ok"}`). |

---

### 4.2. Autenticación y Cuenta
| Método | Ruta Canónica | Auth | Descripción |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/v1/auth/register` | No | Registro de cuenta pendiente de onboarding. |
| `POST` | `/api/v1/auth/verify-email` | No | Verificación de correo mediante token (`204 No Content`). |
| `POST` | `/api/v1/auth/resend-verification` | No | Reenvío de token de verificación (`{"email": "..."}`). |
| `POST` | `/api/v1/auth/login` | No | Login emitiendo access token y refresh token. |
| `POST` | `/api/v1/auth/refresh` | No | Renovación rotativa de access token. |
| `POST` | `/api/v1/auth/logout` | Sí | Cierre de sesión y revocación del refresh token (`204 No Content`). |
| `GET` | `/api/v1/auth/me` | Sí | Consulta datos básicos y estado del usuario autenticado. |
| `POST` | `/api/v1/auth/forgot-password` | No | Solicitud anti-enumeración de restablecimiento de contraseña (`202 Accepted`). |
| `POST` | `/api/v1/auth/reset-password` | No | Restablecimiento de contraseña con token de un solo uso y revocación de sesiones (`204 No Content`). |
| `POST` | `/api/v1/account/deletion` | Sí | Eliminación segura de cuenta con reautenticación (`202 Accepted`). |

#### Payload de Registro (`POST /api/v1/auth/register`):
```json
{
  "email": "nuevo_usuario@example.com",
  "password": "Password123*Secure!",
  "accept_terms_version": "v1-draft",
  "accept_privacy_version": "v1-draft"
}
```

#### Política de Eliminación, Anonimización y Conservación (`POST /api/v1/account/deletion`)

El endpoint `POST /api/v1/account/deletion` exige sesión autenticada (`Bearer <access_token>`) y cuerpo JSON con `{"password": "<actual>", "confirm": true}`. Para respetar tanto la privacidad del usuario como las restricciones de integridad referencial (`ON DELETE RESTRICT`) de PostgreSQL, el sistema distingue cuatro categorías de tratamiento de datos:

| Categoría | Entidades / Recursos Afectados | Tratamiento Aplicado |
| :--- | :--- | :--- |
| **1. Datos eliminados físicamente de inmediato en BD** | `profiles`, `profile_photos`, `discovery_preferences`, `analytic_questionnaire_answers`, `profile_interactions`, `email_verification_tokens`, `password_reset_tokens` | Borrado físico (`DELETE`) dentro de la transacción SQL. No quedan datos biográficos, preferencias, respuestas del cuestionario ni interacciones de descubrimiento. |
| **2. Archivos multimedia físicos (`uploads/profile_photos`)** | Archivos de imagen asociados a `profile_photos.storage_key` | Tras confirmar el commit en PostgreSQL, cada `storage_key` se registra de forma durable en `.pending_deletions.json` antes de ejecutar `storage_adapter.delete_file(key)`. Si ocurre un fallo de E/S en el sistema de archivos, la fotografía **permanece inmediatamente inaccesible por API** (`404 NOT_FOUND` tanto por eliminación de `ProfilePhoto` como por bloqueo en `get_file_path`) y queda en cola para reintento idempotente mediante `storage_adapter.retry_pending_deletions()`. **No se afirma eliminación física completa mientras existan archivos pendientes en dicha cola.** |
| **3. Datos anonimizados irreversiblemente** | `users`, `refresh_tokens`, `legal_consents.ip_address` | En `users`: `email` se reemplaza por `deleted+<uuid>@deleted.afinia.invalid` (liberando el correo original), `password_hash` se rota con entropía criptográfica (invalidando todo JWT anterior vía `pwd_fp`), `is_active=false`, `email_verified=false`, `lifecycle_status='deactivated'` y se sella `deleted_at` (UTC). En `refresh_tokens`: se revocan todos los tokens (`revoked_at=now`) y se limpian `ip_address=NULL` y `user_agent=NULL`. |
| **4. Datos conservados en mensajes, denuncias y consentimientos** | `matches`, `messages`, `user_reports`, `user_blocks`, `legal_consents` | **Mensajes y matches:** Los `matches` abiertos se cierran lógicamente (`closed_at=now`, `closed_by_user_id=user.id`) y los registros de `messages` se conservan en BD por integridad referencial (`ON DELETE RESTRICT`), quedando inaccesibles por API (`404 NOT_FOUND`) para todos los participantes. **Denuncias y bloqueos (`user_reports` / `user_blocks`):** En PostgreSQL, `user_reports.reporter_user_id` y `user_reports.reported_user_id` son `NOT NULL` con regla `ON DELETE RESTRICT` (mientras que `resolved_by_user_id` es `NULLABLE` con `ON DELETE SET NULL`). Por ello, `POST /api/v1/account/deletion` **no** ejecuta `DELETE` sobre `users`, sino que anonimiza el registro in-place (`deleted+<uuid>@deleted.afinia.invalid`, `is_active=false`, `lifecycle_status='deactivated'`, `deleted_at=now`), conservando los UUIDs referenciales en `user_reports` para auditoría y moderación administrativa (BE-10) sin exponer PII. **Consentimientos legales:** Las filas de `legal_consents` se conservan por `ON DELETE RESTRICT` con `ip_address=NULL` como evidencia regulatoria vinculada al UUID anonimizado. |

---

### 4.3. Perfiles y Preferencias
| Método | Ruta Canónica | Auth | Descripción |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/v1/profile` | Sí | Obtiene el perfil propio (`OwnProfile`). Admite `/api/v1/profile/`. |
| `POST` | `/api/v1/profile` | Sí | Crea el perfil en onboarding (`201 Created`). Admite `/api/v1/profile/`. |
| `PUT` | `/api/v1/profile` | Sí | Reemplaza los datos del perfil propio. Admite `/api/v1/profile/`. |
| `GET` | `/api/v1/profile/discovery-preferences` | Sí | Consulta preferencias de búsqueda actuales. |
| `PUT` | `/api/v1/profile/discovery-preferences` | Sí | Actualiza preferencias de búsqueda (`200 OK`). |

#### Payload de Creación de Perfil (`POST /api/v1/profile`):
> [!CAUTION]
> Enviar únicamente los campos permitidos. Campos no reconocidos (como `display_name` o `location_city`) causan `422 VALIDATION_ERROR`.

```json
{
  "first_name": "Ana",
  "birth_date": "1998-05-15",
  "gender": "femenino",
  "city": "Bogotá",
  "bio": "Estudiante de ingeniería interesada en tecnología y música."
}
```
*Valores permitidos para `gender`:* `"masculino"`, `"femenino"`, `"no_binario"`, `"otro"`, `"prefiero_no_indicar"`.

#### Payload de Preferencias (`PUT /api/v1/profile/discovery-preferences`):
```json
{
  "interested_in_genders": ["masculino", "femenino"],
  "min_age": 18,
  "max_age": 35,
  "target_relationship_type": "amistad"
}
```
*Valores permitidos para `target_relationship_type`:* `"seria"`, `"casual"`, `"amistad"`, `"sin_definir"`.

---

### 4.4. Fotografías de Perfil
| Método | Ruta Canónica | Auth | Descripción |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/v1/profile/photos` | Sí | Carga imagen multipart (`201 Created`). Campo de formulario: `"file"`. |
| `DELETE` | `/api/v1/profile/photos/{photoId}` | Sí | Elimina una fotografía propia (`204 No Content`). |
| `PUT` | `/api/v1/profile/photos/{photoId}/primary`| Sí | Establece la foto como principal (`200 OK`). |
| `GET` | `/api/v1/profile/photos/media/{photoId}` | Sí | **Ruta de Streaming:** Descarga binaria autenticada con `Cache-Control: private`. |

#### Carga de Fotografía en Angular:
```typescript
const formData = new FormData();
formData.append('file', fileBlob, 'avatar.jpg');

this.http.post(`${environment.apiUrl}/profile/photos`, formData, {
  headers: { Authorization: `Bearer ${token}` }
});
```

---

### 4.5. Descubrimiento, Swipes y Matches
| Método | Ruta Canónica | Auth | Descripción |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/v1/match/potential` | Sí | Obtiene candidatos potenciales (feed de descubrimiento paginado). |
| `POST` | `/api/v1/match/swipe` | Sí | Envía interacción `LIKE` o `PASS`. Detecta match atómico. |
| `GET` | `/api/v1/match/my-matches` | Sí | Listado de matches activos con `unread_count` y `last_message`. |
| `GET` | `/api/v1/match/{matchId}` | Sí | Detalle del match y perfil del par coincidente. |
| `DELETE` | `/api/v1/match/{matchId}` | Sí | Cierre lógico del match (`unmatch`). Retiene mensajes en DB (`204 No Content`). |

#### Payload de Swipe (`POST /api/v1/match/swipe`):
```json
{
  "target_user_id": "3f122628-633d-4e9b-8355-b0e8bc5b70e3",
  "action": "LIKE"
}
```
*Valores permitidos para `action`:* `"LIKE"` o `"PASS"` (en mayúsculas).

#### Respuesta de Swipe con Match (HTTP 200 OK):
```json
{
  "data": {
    "action": "LIKE",
    "interaction_id": "c3be60b5-cc63-4cce-96e0-f05d4c528056",
    "is_match": true,
    "match_id": "5a189045-a137-4f72-9d2e-70f52942f956"
  }
}
```

---

### 4.6. Mensajería y Lectura
| Método | Ruta Canónica | Auth | Descripción |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/v1/match/{matchId}/messages` | Sí | Historial de mensajes paginado por cursor (`200 OK`). |
| `POST` | `/api/v1/match/{matchId}/messages` | Sí | Envía mensaje de texto (`201 Created`). |
| `POST` | `/api/v1/match/{matchId}/read` | Sí | Marca mensajes recibidos como leídos (`200 OK`). |

#### Envío de Mensaje (`POST /api/v1/match/{matchId}/messages`):
```json
{
  "text": "Hola, ¿cómo estás?"
}
```

#### Respuesta de Envío (HTTP 201 Created):
```json
{
  "data": {
    "id": "d0fbd223-4de2-4ba1-ac28-69fa333e2330",
    "match_id": "5a189045-a137-4f72-9d2e-70f52942f956",
    "sender_user_id": "22242378-318f-4b36-8405-918644d6744a",
    "text": "Hola, ¿cómo estás?",
    "sent_at": "2026-11-02T17:35:54.538049+00:00",
    "read_at": null
  }
}
```

#### Comportamiento de Chat Cerrado (Post-Unmatch o Bloqueo):
Cualquier intento de enviar o consultar mensajes en un match deshecho o bloqueado retornará:
- **Status:** `404 Not Found`
- **JSON:** `{"error": {"code": "NOT_FOUND", "message": "Match no encontrado.", "request_id": "req_..."}}`

---

### 4.7. Seguridad, Bloqueos y Reportes
| Método | Ruta Canónica | Auth | Descripción |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/v1/users/{userId}` | Sí | Perfil público de otro usuario con filtros de privacidad (`200 OK`). |
| `PUT` | `/api/v1/users/{userId}/block` | Sí | Bloquea al usuario objetivo de forma bidireccional (`200 OK`). |
| `DELETE` | `/api/v1/users/{userId}/block` | Sí | Desbloquea al usuario objetivo (`204 No Content`). |
| `GET` | `/api/v1/users/me/blocks` | Sí | Listado de usuarios bloqueados por el usuario autenticado (`200 OK`). |
| `POST` | `/api/v1/users/{userId}/reports` | Sí | Registra una denuncia tipificada (`201 Created`). |

#### Reportar Usuario (`POST /api/v1/users/{userId}/reports`):
```json
{
  "reason": "spam",
  "description": "El usuario envía mensajes publicitarios reiteradamente."
}
```
*Valores permitidos para `reason`:* `"acoso"`, `"contenido_inapropiado"`, `"suplantacion"`, `"spam"`, `"otro"`.

#### Respuesta de Reporte (HTTP 201 Created):
```json
{
  "data": {
    "report_id": "143400dd-c803-412d-8227-e0e1d5469db1",
    "status": "received"
  }
}
```

---

### 4.8. Legal, Notificaciones, Moderación Administrativa y Cuestionario Analítico
| Método | Ruta Canónica | Auth | Descripción |
| :--- | :--- | :---: | :--- |
| `GET` | `/api/v1/legal/current` | No | Retorna versiones y enlaces vigentes de Términos y Privacidad (`200 OK`). |
| `POST` | `/api/v1/legal/acceptances` | Sí | Registra la aceptación explícita e idempotente de las versiones legales vigentes (`200 OK`). |
| `GET` | `/api/v1/notifications` | Sí | Consulta paginada por cursor de notificaciones propias (`new_match`, `new_message`) (`200 OK`). |
| `POST` | `/api/v1/notifications/{notificationId}/read` | Sí | Marca como leída una notificación propia de forma idempotente (`204 No Content`). |
| `GET` | `/api/v1/admin/reports` | Sí (`admin`) | Lista denuncias para moderación administrativa con paginación por cursor y sin exponer PII (`200 OK`). |
| `POST` | `/api/v1/admin/reports/{reportId}/resolve` | Sí (`admin`) | Resuelve una denuncia (`dismiss` $\rightarrow$ `dismissed`, `warn`/`suspend` $\rightarrow$ `resolved`) bajo bloqueo `SELECT FOR UPDATE` (`200 OK`). **Nota de alcance MVP:** `action=warn` y `action=suspend` se registran como decisiones administrativas auditadas en `user_reports`; no ejecutan suspensión, bloqueo ni eliminación automática sobre la cuenta denunciada en `users`. |
| `GET` | `/api/v1/questionnaire` | Sí | Retorna la definición canónica del cuestionario analítico de 16 preguntas (`draft-1`). |
| `PUT` | `/api/v1/questionnaire/answers` | Sí | Guarda o actualiza atómicamente (UPSERT) las respuestas del cuestionario (`200 OK`). |
| `GET` | `/api/v1/questionnaire/answers` | Sí | Consulta las respuestas persistidas del usuario autenticado (`200 OK`). |

---

## 5. Estado de Paridad del Contrato OpenAPI v1 (41/41 Operaciones)

Las **41 operaciones** especificadas en `docs/api/afinia-openapi-v1.yaml` están completamente registradas, implementadas y certificadas en PostgreSQL QA bajo la revisión Alembic **`a7b3c9d1e5f2`** (`0` pendientes en `verify_api_contract.py`):

- **41/41 operaciones** verificadas con persistencia real en PostgreSQL QA (`127.0.0.1:55433/afinia_qa_db`).
- La tabla física `notifications` fue promovida formalmente a producción/QA mediante la migración autorizada `backend/migrations/versions/a7b3c9d1e5f2_user_notifications.py` y certificada end-to-end con emisión de eventos `new_match` y `new_message`, paginación por cursor HMAC SHA-256, lectura idempotente (`read_at`), aislamiento multi-inquilino y limpieza atómica en `POST /api/v1/account/deletion`.
- En moderación administrativa (`/api/v1/admin/reports`), las acciones `action=warn` y `action=suspend` se registran formalmente como decisiones administrativas auditadas en `user_reports` sin ejecutar sanciones destructivas automáticas sobre la cuenta en `users`, preservando el principio de intervención supervisada del MVP.

---

## 6. Endpoints Adicionales Implementados en Backend (Fuera de OpenAPI)

El backend cuenta con 3 rutas implementadas en Flask que no forman parte de la especificación pública de OpenAPI v1:
1. `GET /api/v1/profile/photos/media/<photo_id>`: Distribución binaria controlada de fotografías con cabecera `Cache-Control: private, no-store`.
2. `POST /api/v1/analytics/answers`: Ingesta directa de respuestas hacia la tabla `analytic_questionnaire_answers` para el entrenamiento del modelo.
3. `POST /api/v1/analytics/predict`: Inferencia del modelo de Machine Learning (`AfiniaDecisionTree`).

---

## 7. Herramientas de Verificación y Reproducibilidad en el Repositorio

Para validar la conformidad de la API o ejecutar pruebas locales sin credenciales expuestas:

1. **Auditoría Automatizada de Paridad OpenAPI vs Flask:**
   ```bash
   python backend/scripts/verify_api_contract.py
   ```
   Compara todas las operaciones de `docs/api/afinia-openapi-v1.yaml` contra las reglas de rutas activas en Flask.

2. **Prueba Smoke HTTP de 15 Pasos Canónicos:**
   ```bash
   python backend/scripts/smoke_test_e2e.py
   ```
   Ejecuta el ciclo de vida completo de 2 usuarios sintéticos (registro, verificación, login móvil, perfil, preferencias, fotos, descubrimiento, swipe recíproco, match, mensajes, lectura, bloqueo, reporte, unmatch y verificación de chat cerrado) con limpieza selectiva estricta en PostgreSQL QA.
