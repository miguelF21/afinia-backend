# MODELO DE DATOS - AFINIA

Este es el diseño relacional inicial (Modelo Lógico) para PostgreSQL.

## 1. users
Maneja la autenticación y datos de cuenta.
- `id` (UUID, PK)
- `email` (VARCHAR, UNIQUE, NOT NULL)
- `password_hash` (VARCHAR, NOT NULL)
- `is_active` (BOOLEAN, DEFAULT true)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

## 2. profiles
Contiene la información pública y básica del usuario.
- `id` (UUID, PK)
- `user_id` (UUID, FK a users.id, UNIQUE)
- `first_name` (VARCHAR, NOT NULL)
- `birth_date` (DATE, NOT NULL) - *Calculado a edad en la app*
- `gender` (VARCHAR, NOT NULL)
- `city` (VARCHAR)
- `bio` (TEXT)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

## 3. discovery_preferences
Filtros con los que el usuario busca a otras personas.
- `id` (UUID, PK)
- `user_id` (UUID, FK a users.id, UNIQUE)
- `interested_in_gender` (VARCHAR, NOT NULL)
- `min_age` (INTEGER, DEFAULT 18)
- `max_age` (INTEGER, DEFAULT 99)
- `target_relationship_type` (VARCHAR)

## 4. analytic_questionnaire_answers
Almacena de forma normalizada o en formato EAV (Entity-Attribute-Value) las respuestas al cuestionario. Se sugiere formato normalizado por variables analíticas si son estáticas.
- `id` (UUID, PK)
- `user_id` (UUID, FK a users.id, UNIQUE)
- `variable_name` (VARCHAR, NOT NULL) - ej: 'importancia_atractivo'
- `value_numeric` (INTEGER)
- `value_text` (VARCHAR)

## 5. profile_interactions
El corazón de la generación de datos conductuales (el segundo dataset).
- `id` (UUID, PK)
- `viewer_user_id` (UUID, FK a users.id)
- `shown_user_id` (UUID, FK a users.id)
- `action` (VARCHAR) - ENUM: 'LIKE', 'PASS'
- `timestamp` (TIMESTAMP, DEFAULT NOW())
*Constraint:* UNIQUE(viewer_user_id, shown_user_id) para evitar interacciones repetidas de la misma persona.

## 6. matches
Registra coincidencias consolidadas.
- `id` (UUID, PK)
- `user_a_id` (UUID, FK a users.id)
- `user_b_id` (UUID, FK a users.id)
- `created_at` (TIMESTAMP)
*Constraint:* UNIQUE(user_a_id, user_b_id) asumiendo que user_a_id < user_b_id léxicamente para evitar duplicados invertidos.
