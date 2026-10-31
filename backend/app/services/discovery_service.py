"""
AFINIA — Servicio de Descubrimiento de Perfiles (BE-03.1 / BE-03.1.1).
=====================================================================
Implementa la lógica determinista de elegibilidad, filtros de preferencias recíprocas,
operadores nativos JSONB para PostgreSQL, paginación con integridad criptográfica HMAC
por cursor opaco y serialización pública segura (PublicProfile).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from sqlalchemy import String, cast, desc, or_, and_

from app import db
from app.models import (
    DiscoveryPreference,
    Match,
    Profile,
    ProfileInteraction,
    ProfilePhoto,
    User,
    UserBlock,
)
from app.services.profile_service import calculate_age, serialize_photo


class DiscoveryError(Exception):
    """Excepción para errores de negocio y validación en descubrimiento."""

    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _get_secret_key() -> str:
    """Obtiene la clave secreta de la aplicación para firmar criptográficamente el cursor."""
    key = current_app.config.get("SECRET_KEY")
    if not key:
        raise RuntimeError("SECRET_KEY no configurada en la aplicación.")
    return key


def _calculate_cursor_signature(
    created_at_iso: str,
    target_user_id: str,
    viewer_user_id: str,
    secret_key: str
) -> str:
    """Calcula la firma HMAC-SHA256 para garantizar la integridad y no transferibilidad del cursor."""
    msg = f"{created_at_iso}|{target_user_id}|{viewer_user_id}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def encode_cursor(created_at: datetime, target_user_id: str, viewer_user_id: str) -> str:
    """
    Codifica un cursor opaco con firma HMAC criptográfica vinculado al usuario solicitante.
    Preserva la precisión temporal completa de microsegundos en formato ISO 8601.
    """
    secret_key = _get_secret_key()
    created_at_iso = created_at.isoformat()
    sig = _calculate_cursor_signature(created_at_iso, str(target_user_id), str(viewer_user_id), secret_key)

    payload = {
        "c": created_at_iso,
        "u": str(target_user_id),
        "v": str(viewer_user_id),
        "s": sig
    }
    raw_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw_bytes).decode('ascii')


def decode_cursor(cursor_str: str, expected_viewer_id: str) -> Tuple[datetime, str]:
    """
    Decodifica y valida la firma e integridad del cursor opaco.
    Garantiza:
    - Que el cursor no haya sido manipulado o alterado.
    - Que no sea reutilizado por un usuario distinto al que se le emitió.
    Lanza DiscoveryError('VALIDATION_ERROR', ..., 422) si falla cualquier verificación.
    """
    if not cursor_str or not isinstance(cursor_str, str):
        raise DiscoveryError("VALIDATION_ERROR", "Cursor inválido o malformado.", 422)

    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.encode('ascii'))
        payload = json.loads(raw_bytes.decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError("Payload no es dict")

        required_keys = {"c", "u", "v", "s"}
        if not required_keys.issubset(payload.keys()):
            raise ValueError("Claves incompletas")

        # Verificar que el cursor pertenezca al usuario solicitante autenticado
        if str(payload["v"]) != str(expected_viewer_id):
            raise DiscoveryError(
                "VALIDATION_ERROR",
                "El cursor no pertenece al usuario solicitante.",
                422
            )

        # Verificar firma criptográfica HMAC
        secret_key = _get_secret_key()
        expected_sig = _calculate_cursor_signature(
            payload["c"], str(payload["u"]), str(payload["v"]), secret_key
        )
        if not hmac.compare_digest(str(payload["s"]), expected_sig):
            raise DiscoveryError(
                "VALIDATION_ERROR",
                "Cursor de paginación inválido, alterado o firma no coincidente.",
                422
            )

        created_at = datetime.fromisoformat(payload["c"])
        user_id = str(uuid.UUID(str(payload["u"])))
        return created_at, user_id
    except DiscoveryError:
        raise
    except Exception:
        raise DiscoveryError("VALIDATION_ERROR", "Cursor de paginación inválido o corrupto.", 422)


def build_jsonb_gender_filter(target_gender: str):
    """
    Construye la expresión SQL de filtrado para discovery_preferences.interested_in_genders.
    - En PostgreSQL: Utiliza el operador nativo JSONB de contención (@>).
    - En SQLite (entornos de pruebas unitarias en memoria): Utiliza coincidencia segura.
    """
    bind = db.session.get_bind()
    if bind.dialect.name == "postgresql":
        # Operador nativo JSONB de contención (@>) en PostgreSQL
        return DiscoveryPreference.interested_in_genders.contains([target_gender])
    else:
        # Fallback para SQLite en pruebas unitarias
        return cast(DiscoveryPreference.interested_in_genders, String).like(f'%"{target_gender}"%')


def serialize_public_profile(profile: Profile) -> Dict[str, Any]:
    """
    Serializa una entidad Profile conforme al esquema OpenAPI PublicProfile.
    Garantiza:
    - Exclusivamente fotografías con status == 'ready'.
    - Exclusión estricta de email, birth_date, password_hash, role, tokens, storage_key y respuestas analíticas.
    - URL de fotografías obtenida de build_photo_url (/api/v1/profile/photos/media/{photoId}).
    """
    ready_photos = [
        serialize_photo(p)
        for p in sorted(profile.photos, key=lambda p: p.position)
        if p.status == "ready"
    ]

    goal: Optional[str] = None
    if profile.user and profile.user.discovery_preference:
        goal = profile.user.discovery_preference.target_relationship_type

    return {
        "user_id": str(profile.user_id),
        "first_name": profile.first_name,
        "age": calculate_age(profile.birth_date),
        "gender": profile.gender,
        "city": profile.city,
        "bio": profile.bio,
        "photos": ready_photos,
        "relationship_goal": goal,
    }


def validate_viewer_discovery_eligibility(viewer: User) -> None:
    """
    Verifica que el usuario solicitante esté habilitado para participar en el descubrimiento.
    """
    if not viewer:
        raise DiscoveryError("UNAUTHORIZED", "Sesión requerida.", 401)

    if viewer.lifecycle_status in ("suspended", "deactivated"):
        raise DiscoveryError("FORBIDDEN", "Acceso denegado: cuenta no disponible.", 403)

    if viewer.lifecycle_status == "pending_profile" or not viewer.profile:
        raise DiscoveryError(
            "FORBIDDEN",
            "El usuario no accede a discovery ni matches hasta finalizar el perfil y validar edad 18+ en servidor.",
            403
        )

    if not viewer.email_verified:
        raise DiscoveryError(
            "FORBIDDEN",
            "Debe verificar su correo electrónico antes de acceder a la sección de descubrimiento.",
            403
        )

    # Verificar que el propio solicitante sea mayor de edad
    try:
        viewer_age = calculate_age(viewer.profile.birth_date)
        if viewer_age < 18:
            raise DiscoveryError("FORBIDDEN", "Plataforma exclusiva para mayores de 18 años.", 403)
    except Exception as e:
        if isinstance(e, DiscoveryError):
            raise
        raise DiscoveryError("FORBIDDEN", "Perfil no válido para descubrimiento.", 403)

    # Verificar que el solicitante tenga fotografía principal en estado ready
    has_ready_primary = any(
        photo.is_primary and photo.status == "ready"
        for photo in viewer.profile.photos
    )
    if not has_ready_primary:
        raise DiscoveryError(
            "FORBIDDEN",
            "Debe contar con al menos una fotografía principal aprobada para acceder al descubrimiento.",
            403
        )

    # Verificar que el solicitante tenga preferencias de descubrimiento
    if not viewer.discovery_preference or viewer.discovery_preference.interested_in_genders is None:
        raise DiscoveryError(
            "FORBIDDEN",
            "Debe configurar sus preferencias de descubrimiento antes de explorar candidatos.",
            403
        )


def get_potential_candidates(
    current_user: User,
    limit: int = 20,
    cursor: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """
    Retorna los candidatos elegibles para el usuario autenticado según la política
    determinista de filtrado, reciprocidad JSONB y paginación con integridad HMAC.
    """
    # 1. Comprobación de elegibilidad del solicitante
    validate_viewer_discovery_eligibility(current_user)

    # 2. Validación del parámetro limit (1 a 50)
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise DiscoveryError("VALIDATION_ERROR", "El parámetro 'limit' debe ser un entero entre 1 y 50.", 422)

    cursor_created_at: Optional[datetime] = None
    cursor_user_id: Optional[str] = None
    if cursor:
        cursor_created_at, cursor_user_id = decode_cursor(cursor, str(current_user.id))

    viewer_pref = current_user.discovery_preference
    viewer_profile = current_user.profile
    viewer_age = calculate_age(viewer_profile.birth_date)
    viewer_gender = viewer_profile.gender
    viewer_target_goal = viewer_pref.target_relationship_type

    # 3. Subconsultas de exclusión estricta
    # Exclusión de bloqueos bidireccionales
    blocked_by_me = db.session.query(UserBlock.blocked_user_id).filter(
        UserBlock.blocker_user_id == current_user.id
    )
    blocked_me = db.session.query(UserBlock.blocker_user_id).filter(
        UserBlock.blocked_user_id == current_user.id
    )

    # Exclusión de interacciones previas del solicitante (LIKE o PASS ya emitidos por current_user)
    already_interacted = db.session.query(ProfileInteraction.shown_user_id).filter(
        ProfileInteraction.viewer_user_id == current_user.id
    )

    # Exclusión de matches ya existentes
    matches_as_a = db.session.query(Match.user_b_id).filter(
        Match.user_a_id == current_user.id
    )
    matches_as_b = db.session.query(Match.user_a_id).filter(
        Match.user_b_id == current_user.id
    )

    # Candidatos con al menos una fotografía principal 'ready'
    candidates_with_ready_primary_photo = db.session.query(ProfilePhoto.profile_id).filter(
        ProfilePhoto.is_primary.is_(True),
        ProfilePhoto.status == "ready"
    )

    # 4. Construcción de consulta principal sobre Profile
    query = (
        db.session.query(Profile)
        .join(User, Profile.user_id == User.id)
        .join(DiscoveryPreference, User.id == DiscoveryPreference.user_id)
        .filter(
            User.id != current_user.id,
            User.lifecycle_status == "active",
            User.email_verified.is_(True),
            Profile.id.in_(candidates_with_ready_primary_photo),
            ~User.id.in_(blocked_by_me),
            ~User.id.in_(blocked_me),
            ~User.id.in_(already_interacted),
            ~User.id.in_(matches_as_a),
            ~User.id.in_(matches_as_b),
        )
    )

    # 5. Filtros de preferencias del Solicitante hacia el Candidato
    today = datetime.now(timezone.utc).date()

    # Edad mínima legal (18+)
    legal_max_birth = date(today.year - 18, today.month, today.day)
    query = query.filter(Profile.birth_date <= legal_max_birth)

    # Rango de edad solicitado por el solicitante
    s_min_age = viewer_pref.min_age or 18
    s_max_age = viewer_pref.max_age or 99

    # Candidato debe tener al menos s_min_age años
    c_max_birth_for_min_age = date(today.year - s_min_age, today.month, today.day)
    query = query.filter(Profile.birth_date <= c_max_birth_for_min_age)

    # Candidato debe tener como máximo s_max_age años (cumplir s_max_age + 1 excluye)
    c_min_birth_for_max_age = date(today.year - (s_max_age + 1), today.month, today.day)
    query = query.filter(Profile.birth_date > c_min_birth_for_max_age)

    # Género del candidato solicitado por el solicitante
    s_genders = viewer_pref.canonical_interested_in_genders
    if s_genders and len(s_genders) > 0:
        query = query.filter(Profile.gender.in_(s_genders))

    # 6. Reciprocidad de preferencias: El Solicitante debe ser elegible para el Candidato
    # El candidato debe aceptar la edad del solicitante
    query = query.filter(
        DiscoveryPreference.min_age <= viewer_age,
        DiscoveryPreference.max_age >= viewer_age
    )

    # El candidato debe aceptar el género del solicitante utilizando el operador nativo JSONB (@>)
    jsonb_gender_filter = build_jsonb_gender_filter(viewer_gender)
    query = query.filter(jsonb_gender_filter)

    # Política determinista del objetivo relacional (target_relationship_type)
    # Si ambos especificaron un objetivo definido (distinto de 'sin_definir' y no nulo), deben coincidir.
    # Si alguno tiene 'sin_definir' o None, se consideran compatibles.
    if viewer_target_goal and viewer_target_goal != "sin_definir":
        query = query.filter(
            or_(
                DiscoveryPreference.target_relationship_type.is_(None),
                DiscoveryPreference.target_relationship_type == "sin_definir",
                DiscoveryPreference.target_relationship_type == viewer_target_goal
            )
        )

    # 7. Condición de cursor opaco con desempate (ORDER BY Profile.created_at DESC, Profile.user_id ASC)
    if cursor_created_at and cursor_user_id:
        query = query.filter(
            or_(
                Profile.created_at < cursor_created_at,
                and_(
                    Profile.created_at == cursor_created_at,
                    Profile.user_id > cursor_user_id
                )
            )
        )

    # Ordenación estable y determinista
    query = query.order_by(desc(Profile.created_at), Profile.user_id.asc())

    # Traer limit + 1 para determinar si hay más páginas
    candidates = query.limit(limit + 1).all()

    has_more = len(candidates) > limit
    paged_profiles = candidates[:limit]

    next_cursor: Optional[str] = None
    if has_more and paged_profiles:
        last_profile = paged_profiles[-1]
        next_cursor = encode_cursor(last_profile.created_at, last_profile.user_id, current_user.id)

    items = [serialize_public_profile(p) for p in paged_profiles]

    return items, next_cursor, has_more


def get_public_profile_by_user_id(viewer: User, target_user_id_raw: str) -> Dict[str, Any]:
    """
    Retorna el perfil público visible de un usuario específico según las reglas
    de privacidad y bloqueos bidireccionales de OpenAPI.
    """
    if not viewer:
        raise DiscoveryError("UNAUTHORIZED", "Sesión requerida.", 401)

    if viewer.lifecycle_status in ("suspended", "deactivated"):
        raise DiscoveryError("FORBIDDEN", "Acceso denegado: cuenta no disponible.", 403)

    # Validar formato UUID
    try:
        valid_uuid = str(uuid.UUID(str(target_user_id_raw).strip()))
    except (ValueError, AttributeError):
        raise DiscoveryError("NOT_FOUND", "Usuario no encontrado.", 404)

    # Buscar usuario objetivo
    target_user = User.query.filter_by(id=valid_uuid).first()
    if not target_user:
        raise DiscoveryError("NOT_FOUND", "Usuario no encontrado.", 404)

    # Si es el propio usuario solicitante y tiene perfil, permitir ver su propio PublicProfile
    if target_user.id == viewer.id:
        if not target_user.profile:
            raise DiscoveryError("NOT_FOUND", "Perfil no encontrado.", 404)
        return serialize_public_profile(target_user.profile)

    # Para otros usuarios: debe estar activo y con correo verificado
    if target_user.lifecycle_status != "active" or not target_user.email_verified:
        raise DiscoveryError("NOT_FOUND", "Usuario no encontrado o no disponible.", 404)

    target_profile = target_user.profile
    if not target_profile or not target_profile.birth_date:
        raise DiscoveryError("NOT_FOUND", "Perfil no disponible.", 404)

    # Verificar mayoría de edad
    try:
        age = calculate_age(target_profile.birth_date)
        if age < 18:
            raise DiscoveryError("NOT_FOUND", "Perfil no disponible.", 404)
    except Exception:
        raise DiscoveryError("NOT_FOUND", "Perfil no disponible.", 404)

    # Verificar que el usuario tenga al menos una foto principal aprobada ('ready')
    has_ready_primary = any(
        photo.is_primary and photo.status == "ready"
        for photo in target_profile.photos
    )
    if not has_ready_primary:
        raise DiscoveryError("NOT_FOUND", "Perfil no disponible.", 404)

    # Verificar bloqueos bidireccionales
    is_blocked = db.session.query(UserBlock.id).filter(
        or_(
            and_(UserBlock.blocker_user_id == viewer.id, UserBlock.blocked_user_id == target_user.id),
            and_(UserBlock.blocker_user_id == target_user.id, UserBlock.blocked_user_id == viewer.id),
        )
    ).first()

    if is_blocked:
        # Responder 404 Not Found para proteger la privacidad sin indicar existencia de bloqueo
        raise DiscoveryError("NOT_FOUND", "Usuario no encontrado.", 404)

    return serialize_public_profile(target_profile)
