"""
AFINIA — Servicio de Matches e Interacciones (BE-03.2).
======================================================
Implementa la lógica transaccional de LIKE, PASS, idempotencia y matches recíprocos.
Garantiza:
- Serialización mediante orden determinista de bloqueos en PostgreSQL (SELECT FOR UPDATE sobre User.id).
- Cero deadlocks y prevención absoluta de condiciones de carrera en swipes simultáneos.
- Generación de exactamente un Match con orden canónico user_a_id < user_b_id.
- Idempotencia estricta para reintentos idénticos y rechazo 409 CONFLICT para acciones contradictorias.
- Validación de elegibilidad y preferencias mutuas de descubrimiento.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from flask import current_app
from sqlalchemy import or_, and_, case, func, asc, desc
from sqlalchemy.orm import aliased, joinedload
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    User,
    Profile,
    ProfileInteraction,
    Match,
    Message,
    UserBlock,
    DiscoveryPreference,
    ProfilePhoto,
)
from app.services.profile_service import calculate_age
from app.services.discovery_service import serialize_public_profile


class MatchError(Exception):
    """Excepción para errores de negocio y validación en swipes y matches."""

    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def validate_viewer_can_swipe(viewer: User) -> None:
    """
    Verifica que el usuario solicitante esté habilitado para interactuar (swipe).
    """
    if not viewer:
        raise MatchError("UNAUTHORIZED", "Sesión requerida.", 401)

    if viewer.lifecycle_status in ("suspended", "deactivated"):
        raise MatchError("FORBIDDEN", "Acceso denegado: cuenta no disponible.", 403)

    if viewer.lifecycle_status == "pending_profile" or not viewer.profile:
        raise MatchError(
            "FORBIDDEN",
            "El usuario no accede a discovery ni matches hasta finalizar el perfil y validar edad 18+ en servidor.",
            403
        )

    if not viewer.email_verified:
        raise MatchError(
            "FORBIDDEN",
            "Debe verificar su correo electrónico antes de realizar interacciones.",
            403
        )

    try:
        viewer_age = calculate_age(viewer.profile.birth_date)
        if viewer_age < 18:
            raise MatchError("FORBIDDEN", "Plataforma exclusiva para mayores de 18 años.", 403)
    except Exception as e:
        if isinstance(e, MatchError):
            raise
        raise MatchError("FORBIDDEN", "Perfil no válido para interacciones.", 403)

    has_ready_primary = any(
        photo.is_primary and photo.status == "ready"
        for photo in viewer.profile.photos
    )
    if not has_ready_primary:
        raise MatchError(
            "FORBIDDEN",
            "Debe contar con al menos una fotografía principal aprobada para interactuar.",
            403
        )

    if not viewer.discovery_preference or not viewer.discovery_preference.interested_in_genders:
        raise MatchError(
            "FORBIDDEN",
            "Debe configurar sus preferencias de descubrimiento antes de interactuar.",
            403
        )


def validate_target_user_and_preferences(viewer: User, target_user: Optional[User]) -> None:
    """
    Verifica la existencia, elegibilidad, bloqueos y compatibilidad de preferencias del candidato.
    """
    if not target_user:
        raise MatchError("NOT_FOUND", "Usuario no encontrado.", 404)

    # 1. No auto-like / auto-pass
    if str(target_user.id) == str(viewer.id):
        raise MatchError("VALIDATION_ERROR", "No se permite interactuar con la propia cuenta.", 422)

    # 2. Estado de cuenta del candidato
    if target_user.lifecycle_status != "active" or not target_user.email_verified:
        raise MatchError("NOT_FOUND", "Perfil no disponible.", 404)

    target_profile = target_user.profile
    if not target_profile or not target_profile.birth_date:
        raise MatchError("NOT_FOUND", "Perfil no disponible.", 404)

    try:
        target_age = calculate_age(target_profile.birth_date)
        if target_age < 18:
            raise MatchError("NOT_FOUND", "Perfil no disponible.", 404)
    except Exception:
        raise MatchError("NOT_FOUND", "Perfil no disponible.", 404)

    # 3. Foto principal aprobada
    has_ready_primary = any(
        photo.is_primary and photo.status == "ready"
        for photo in target_profile.photos
    )
    if not has_ready_primary:
        raise MatchError("NOT_FOUND", "Perfil no disponible.", 404)

    # 4. Bloqueo bidireccional
    is_blocked = db.session.query(UserBlock.id).filter(
        or_(
            and_(UserBlock.blocker_user_id == viewer.id, UserBlock.blocked_user_id == target_user.id),
            and_(UserBlock.blocker_user_id == target_user.id, UserBlock.blocked_user_id == viewer.id),
        )
    ).first()
    if is_blocked:
        raise MatchError("FORBIDDEN", "Acceso denegado: interacción no permitida con este perfil.", 403)

    # 5. Compatibilidad de preferencias recíprocas de descubrimiento
    viewer_pref = viewer.discovery_preference
    target_pref = target_user.discovery_preference
    if not target_pref or not target_pref.interested_in_genders:
        raise MatchError("VALIDATION_ERROR", "Candidato fuera de las preferencias válidas.", 422)

    # Reciprocidad de género
    if target_profile.gender not in viewer_pref.interested_in_genders:
        raise MatchError("VALIDATION_ERROR", "Candidato fuera de las preferencias válidas.", 422)

    if viewer.profile.gender not in target_pref.interested_in_genders:
        raise MatchError("VALIDATION_ERROR", "Candidato fuera de las preferencias válidas.", 422)

    # Rango de edad mutuo
    viewer_age = calculate_age(viewer.profile.birth_date)
    v_min = viewer_pref.min_age or 18
    v_max = viewer_pref.max_age or 99
    if not (v_min <= target_age <= v_max):
        raise MatchError("VALIDATION_ERROR", "Candidato fuera de las preferencias válidas.", 422)

    t_min = target_pref.min_age or 18
    t_max = target_pref.max_age or 99
    if not (t_min <= viewer_age <= t_max):
        raise MatchError("VALIDATION_ERROR", "Candidato fuera de las preferencias válidas.", 422)


def process_swipe(viewer: User, target_user_id_raw: Any, action_raw: Any) -> Dict[str, Any]:
    """
    Ejecuta la acción de swipe (LIKE o PASS) bajo aislamiento transaccional seguro.
    
    Estrategia de concurrencia:
    - Adquiere locks a nivel de fila (FOR UPDATE) sobre User en orden determinista id_min, id_max.
    - Esto elimina cualquier riesgo de deadlock cruzado entre procesos concurrentes.
    - Serializa la comprobación e inserción del match, garantizando que exactamente un match sea creado.
    - Soporta reintentos idénticos de manera idempotente (HTTP 200).
    - Rechaza alteraciones contradictorias (LIKE -> PASS o PASS -> LIKE) con HTTP 409 CONFLICT.
    """
    # 1. Validaciones previas de solicitante
    validate_viewer_can_swipe(viewer)

    # 2. Validación estricta del target_user_id (formato UUID)
    if not target_user_id_raw or not isinstance(target_user_id_raw, str):
        raise MatchError("VALIDATION_ERROR", "El parámetro 'target_user_id' es requerido y debe ser una cadena válida.", 422)

    try:
        target_uuid = str(uuid.UUID(str(target_user_id_raw).strip()))
    except (ValueError, AttributeError):
        raise MatchError("VALIDATION_ERROR", "El parámetro 'target_user_id' debe tener un formato UUID válido.", 422)

    viewer_uuid = str(viewer.id)
    if target_uuid == viewer_uuid:
        raise MatchError("VALIDATION_ERROR", "No se permite interactuar con la propia cuenta.", 422)

    # 3. Validación estricta de action ('LIKE' o 'PASS')
    if not action_raw or not isinstance(action_raw, str):
        raise MatchError("VALIDATION_ERROR", "El parámetro 'action' es requerido.", 422)

    action = action_raw.strip()
    if action not in ("LIKE", "PASS"):
        raise MatchError("VALIDATION_ERROR", "La acción debe ser 'LIKE' o 'PASS'.", 422)

    # 4. Orden determinista para bloqueos transaccionales (id_min, id_max)
    id_min = min(viewer_uuid, target_uuid)
    id_max = max(viewer_uuid, target_uuid)

    # Ejecución dentro de transacción segura
    try:
        # En PostgreSQL, serializar la pareja de usuarios para evitar race conditions
        db.session.query(User.id).filter(
            User.id.in_([id_min, id_max])
        ).order_by(User.id.asc()).with_for_update().all()

        # 5. Idempotencia: Verificar interacción existente previa del solicitante hacia el candidato
        existing_interaction = ProfileInteraction.query.filter_by(
            viewer_user_id=viewer_uuid,
            shown_user_id=target_uuid
        ).first()

        if existing_interaction:
            if existing_interaction.action == action:
                # Reintento idéntico: no crear duplicados, conservar ID original
                # Consultar si actualmente existe match entre ambos
                existing_match = Match.query.filter_by(
                    user_a_id=id_min,
                    user_b_id=id_max
                ).first()
                is_match = (existing_match is not None)
                match_id = existing_match.id if existing_match else None
                return {
                    "interaction_id": str(existing_interaction.id),
                    "action": existing_interaction.action,
                    "is_match": is_match,
                    "match_id": match_id
                }
            else:
                # Intento contradictorio: LIKE -> PASS o PASS -> LIKE
                raise MatchError("CONFLICT", "No es posible modificar una interacción previamente registrada.", 409)

        # 6. Para swipe nuevo: Validar que el candidato exista y sea elegible
        target_user = User.query.filter_by(id=target_uuid).first()
        validate_target_user_and_preferences(viewer, target_user)

        # 7. Crear la nueva interacción
        new_interaction = ProfileInteraction(
            id=str(uuid.uuid4()),
            viewer_user_id=viewer_uuid,
            shown_user_id=target_uuid,
            action=action
        )
        db.session.add(new_interaction)
        db.session.flush()

        # 8. Comprobar si se genera Match recíproco
        is_match = False
        match_id: Optional[str] = None

        if action == "LIKE":
            # Buscar si el candidato ya había dado LIKE al solicitante
            mutual_like = ProfileInteraction.query.filter_by(
                viewer_user_id=target_uuid,
                shown_user_id=viewer_uuid,
                action="LIKE"
            ).first()

            if mutual_like:
                # Verificar si ya existe el registro de Match
                match_obj = Match.query.filter_by(
                    user_a_id=id_min,
                    user_b_id=id_max
                ).first()

                if not match_obj:
                    # Crear nuevo match canónico
                    match_obj = Match(
                        id=str(uuid.uuid4()),
                        user_a_id=id_min,
                        user_b_id=id_max
                    )
                    db.session.add(match_obj)
                    try:
                        db.session.flush()
                    except IntegrityError:
                        # Colisión concurrente resuelta por la restricción uq_match_pair
                        db.session.rollback()
                        match_obj = Match.query.filter_by(
                            user_a_id=id_min,
                            user_b_id=id_max
                        ).first()

                if match_obj:
                    is_match = True
                    match_id = str(match_obj.id)

        db.session.commit()

        return {
            "interaction_id": str(new_interaction.id),
            "action": new_interaction.action,
            "is_match": is_match,
            "match_id": match_id
        }

    except MatchError:
        db.session.rollback()
        raise
    except IntegrityError as ie:
        db.session.rollback()
        # En caso de colisión en uq_viewer_shown por reintento concurrente
        existing = ProfileInteraction.query.filter_by(
            viewer_user_id=viewer_uuid,
            shown_user_id=target_uuid
        ).first()
        if existing and existing.action == action:
            existing_match = Match.query.filter_by(
                user_a_id=id_min,
                user_b_id=id_max
            ).first()
            return {
                "interaction_id": str(existing.id),
                "action": existing.action,
                "is_match": (existing_match is not None),
                "match_id": str(existing_match.id) if existing_match else None
            }
        current_app.logger.error(f"Error de integridad en process_swipe: {ie}")
        raise MatchError("CONFLICT", "Conflicto de concurrencia al registrar interacción.", 409)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado en process_swipe: {e}")
        raise


def _get_secret_key() -> str:
    """Obtiene la clave secreta de la aplicación para firmar criptográficamente el cursor."""
    key = current_app.config.get("SECRET_KEY")
    if not key:
        raise RuntimeError("SECRET_KEY no configurada en la aplicación.")
    return key


def format_datetime_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serializa un objeto datetime en formato canónico ISO 8601 UTC."""
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def serialize_message(msg: Optional[Message]) -> Optional[Dict[str, Any]]:
    """
    Serializa una entidad Message conforme al esquema Message de OpenAPI v1.
    Retorna None si no existe mensaje.
    """
    if not msg:
        return None
    return {
        "id": str(msg.id),
        "match_id": str(msg.match_id),
        "sender_user_id": str(msg.sender_user_id),
        "text": msg.text,
        "sent_at": format_datetime_iso(msg.sent_at),
        "read_at": format_datetime_iso(msg.read_at),
    }


def _calculate_match_cursor_signature(
    created_at_iso: str,
    match_id: str,
    viewer_user_id: str,
    secret_key: str
) -> str:
    """Calcula firma HMAC-SHA256 para integridad y no transferibilidad del cursor de matches."""
    msg = f"{created_at_iso}|{match_id}|{viewer_user_id}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def encode_match_cursor(created_at: datetime, match_id: str, viewer_user_id: str) -> str:
    """
    Codifica un cursor opaco con firma HMAC criptográfica vinculado al usuario solicitante.
    """
    secret_key = _get_secret_key()
    created_at_iso = format_datetime_iso(created_at)
    sig = _calculate_match_cursor_signature(created_at_iso, str(match_id), str(viewer_user_id), secret_key)
    payload = {
        "c": created_at_iso,
        "m": str(match_id),
        "v": str(viewer_user_id),
        "s": sig
    }
    raw_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw_bytes).decode('ascii')


def decode_match_cursor(cursor_str: str, expected_viewer_id: str) -> Tuple[datetime, str]:
    """
    Decodifica y valida la firma e integridad del cursor de matches.
    Lanza MatchError('VALIDATION_ERROR', ..., 422) si el cursor está alterado o pertenece a otro usuario.
    """
    if not cursor_str or not isinstance(cursor_str, str):
        raise MatchError("VALIDATION_ERROR", "Cursor de paginación inválido.", 422)
    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.encode('ascii'))
        payload = json.loads(raw_bytes.decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError("Payload no es dict")
        required_keys = {"c", "m", "v", "s"}
        if not required_keys.issubset(payload.keys()):
            raise ValueError("Claves incompletas")
        if str(payload["v"]) != str(expected_viewer_id):
            raise MatchError("VALIDATION_ERROR", "El cursor no pertenece al usuario solicitante.", 422)
        secret_key = _get_secret_key()
        expected_sig = _calculate_match_cursor_signature(
            payload["c"], str(payload["m"]), str(payload["v"]), secret_key
        )
        if not hmac.compare_digest(str(payload["s"]), expected_sig):
            raise MatchError("VALIDATION_ERROR", "Cursor de paginación inválido, alterado o firma no coincidente.", 422)

        created_at = datetime.fromisoformat(payload["c"])
        match_id = str(uuid.UUID(str(payload["m"])))
        return created_at, match_id
    except MatchError:
        raise
    except Exception:
        raise MatchError("VALIDATION_ERROR", "Cursor de paginación inválido o corrupto.", 422)


def validate_viewer_matches_eligibility(viewer: User) -> None:
    """
    Verifica que el usuario solicitante esté habilitado para consultar sus matches.
    """
    if not viewer:
        raise MatchError("UNAUTHORIZED", "Sesión requerida.", 401)

    if viewer.lifecycle_status in ("suspended", "deactivated"):
        raise MatchError("FORBIDDEN", "Acceso denegado: cuenta no disponible.", 403)

    if viewer.lifecycle_status == "pending_profile" or not viewer.profile:
        raise MatchError(
            "FORBIDDEN",
            "El usuario no accede a discovery ni matches hasta finalizar el perfil y validar edad 18+ en servidor.",
            403
        )

    if not viewer.email_verified:
        raise MatchError(
            "FORBIDDEN",
            "Debe verificar su correo electrónico antes de acceder a sus matches.",
            403
        )

    try:
        viewer_age = calculate_age(viewer.profile.birth_date)
        if viewer_age < 18:
            raise MatchError("FORBIDDEN", "Plataforma exclusiva para mayores de 18 años.", 403)
    except Exception as e:
        if isinstance(e, MatchError):
            raise
        raise MatchError("FORBIDDEN", "Perfil no válido para consultar matches.", 403)

    has_ready_primary = any(
        photo.is_primary and photo.status == "ready"
        for photo in viewer.profile.photos
    )
    if not has_ready_primary:
        raise MatchError(
            "FORBIDDEN",
            "Debe contar con al menos una fotografía principal aprobada para consultar matches.",
            403
        )


def get_user_matches(
    current_user: User,
    limit: int = 20,
    cursor: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """
    Retorna la lista de matches activos del usuario con paginación determinista por cursor opaco:
    - Orden: Match.created_at DESC, Match.id ASC.
    - Exclusión estricta de bloqueos bidireccionales y cuentas inactivas/no disponibles.
    - Serialización de PublicProfile para other_user.
    - Lectura batch optimizada de last_message y unread_count sin problemas de N+1.
    """
    validate_viewer_matches_eligibility(current_user)

    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise MatchError("VALIDATION_ERROR", "El parámetro 'limit' debe ser un entero entre 1 y 50.", 422)

    cursor_dt: Optional[datetime] = None
    cursor_mid: Optional[str] = None
    if cursor:
        cursor_dt, cursor_mid = decode_match_cursor(cursor, str(current_user.id))
        if cursor_dt.tzinfo is not None:
            cursor_dt = cursor_dt.astimezone(timezone.utc).replace(tzinfo=None)

    other_id_expr = case(
        (Match.user_a_id == current_user.id, Match.user_b_id),
        else_=Match.user_a_id
    )

    query = db.session.query(Match).filter(
        or_(Match.user_a_id == current_user.id, Match.user_b_id == current_user.id)
    )

    # Exclusión de bloqueos bidireccionales
    query = query.filter(
        ~db.session.query(UserBlock.id).filter(
            or_(
                and_(UserBlock.blocker_user_id == current_user.id, UserBlock.blocked_user_id == other_id_expr),
                and_(UserBlock.blocker_user_id == other_id_expr, UserBlock.blocked_user_id == current_user.id)
            )
        ).exists()
    )

    # Contraparte activa, correo verificado, perfil completo y foto ready
    other_user_alias = aliased(User)
    other_profile_alias = aliased(Profile)

    query = query.join(other_user_alias, other_user_alias.id == other_id_expr)
    query = query.filter(
        other_user_alias.lifecycle_status == 'active',
        other_user_alias.email_verified.is_(True)
    )

    query = query.join(other_profile_alias, other_profile_alias.user_id == other_user_alias.id)
    query = query.filter(other_profile_alias.birth_date.isnot(None))

    query = query.filter(
        db.session.query(ProfilePhoto.id).filter(
            ProfilePhoto.profile_id == other_profile_alias.id,
            ProfilePhoto.is_primary.is_(True),
            ProfilePhoto.status == 'ready'
        ).exists()
    )

    if cursor_dt is not None and cursor_mid is not None:
        query = query.filter(
            or_(
                Match.created_at < cursor_dt,
                and_(Match.created_at == cursor_dt, Match.id > cursor_mid)
            )
        )

    query = query.order_by(Match.created_at.desc(), Match.id.asc())

    raw_matches = query.limit(limit + 1).all()

    has_more = len(raw_matches) > limit
    page_matches = raw_matches[:limit] if has_more else raw_matches

    if not page_matches:
        return [], None, False

    next_cursor = None
    if has_more:
        last_item = page_matches[-1]
        next_cursor = encode_match_cursor(last_item.created_at, last_item.id, str(current_user.id))

    match_ids = [m.id for m in page_matches]

    # Batch unread_count: 1 consulta SQL agrupada
    unread_rows = db.session.query(
        Message.match_id,
        func.count(Message.id).label('unread_count')
    ).filter(
        Message.match_id.in_(match_ids),
        Message.sender_user_id != current_user.id,
        Message.read_at.is_(None)
    ).group_by(Message.match_id).all()
    unread_map = {row.match_id: row.unread_count for row in unread_rows}

    # Batch last_message: 1 consulta SQL vía ROW_NUMBER()
    rn_col = func.row_number().over(
        partition_by=Message.match_id,
        order_by=(Message.sent_at.desc(), Message.id.desc())
    ).label('rn')

    subq = db.session.query(
        Message.id.label('msg_id'),
        rn_col
    ).filter(
        Message.match_id.in_(match_ids)
    ).subquery()

    last_msgs = Message.query.join(
        subq, Message.id == subq.c.msg_id
    ).filter(
        subq.c.rn == 1
    ).all()
    last_msg_map = {msg.match_id: msg for msg in last_msgs}

    # Batch perfiles de contrapartes
    other_uids = [
        m.user_b_id if m.user_a_id == current_user.id else m.user_a_id
        for m in page_matches
    ]
    profiles = Profile.query.filter(
        Profile.user_id.in_(other_uids)
    ).options(
        joinedload(Profile.photos),
        joinedload(Profile.user).joinedload(User.discovery_preference)
    ).all()
    profile_map = {str(p.user_id): p for p in profiles}

    items = []
    for m in page_matches:
        other_uid = m.user_b_id if m.user_a_id == current_user.id else m.user_a_id
        prof = profile_map.get(str(other_uid))
        if not prof:
            continue
        try:
            if calculate_age(prof.birth_date) < 18:
                continue
        except Exception:
            continue

        items.append({
            "id": str(m.id),
            "other_user": serialize_public_profile(prof),
            "created_at": format_datetime_iso(m.created_at),
            "last_message": serialize_message(last_msg_map.get(m.id)),
            "unread_count": max(0, unread_map.get(m.id, 0))
        })

    return items, next_cursor, has_more


def get_match_by_id(current_user: User, match_id_raw: Any) -> Dict[str, Any]:
    """
    Obtiene el detalle de un match activo del usuario conforme al contrato OpenAPI v1.
    Retorna esquema Match o 404 NOT_FOUND si no existe, no pertenece al usuario o está bloqueado/inactivo.
    """
    validate_viewer_matches_eligibility(current_user)

    if not match_id_raw or not isinstance(match_id_raw, str):
        raise MatchError("VALIDATION_ERROR", "El identificador del match debe ser un UUID válido.", 422)

    try:
        match_uuid = str(uuid.UUID(str(match_id_raw).strip()))
    except (ValueError, AttributeError):
        raise MatchError("VALIDATION_ERROR", "El identificador del match debe ser un UUID válido.", 422)

    match_obj = Match.query.filter_by(id=match_uuid).first()
    if not match_obj:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    # Validar pertenencia del usuario (si es ajeno, retornar 404 para no filtrar existencia a terceros)
    if str(current_user.id) not in (str(match_obj.user_a_id), str(match_obj.user_b_id)):
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    other_uid = match_obj.user_b_id if str(match_obj.user_a_id) == str(current_user.id) else match_obj.user_a_id

    # Bloqueos bidireccionales
    is_blocked = db.session.query(UserBlock.id).filter(
        or_(
            and_(UserBlock.blocker_user_id == current_user.id, UserBlock.blocked_user_id == other_uid),
            and_(UserBlock.blocker_user_id == other_uid, UserBlock.blocked_user_id == current_user.id),
        )
    ).first()
    if is_blocked:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    # Contraparte activa y habilitada
    other_user = User.query.filter_by(id=other_uid).first()
    if not other_user or other_user.lifecycle_status != 'active' or not other_user.email_verified:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    other_prof = other_user.profile
    if not other_prof or not other_prof.birth_date:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    try:
        if calculate_age(other_prof.birth_date) < 18:
            raise MatchError("NOT_FOUND", "Match no encontrado.", 404)
    except Exception:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    has_ready_primary = any(p.is_primary and p.status == 'ready' for p in other_prof.photos)
    if not has_ready_primary:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    # Cálculo de unread_count
    unread_count = Message.query.filter(
        Message.match_id == match_obj.id,
        Message.sender_user_id != current_user.id,
        Message.read_at.is_(None)
    ).count()

    # Último mensaje persistido
    last_msg = Message.query.filter_by(
        match_id=match_obj.id
    ).order_by(
        Message.sent_at.desc(), Message.id.desc()
    ).first()

    return {
        "id": str(match_obj.id),
        "other_user": serialize_public_profile(other_prof),
        "created_at": format_datetime_iso(match_obj.created_at),
        "last_message": serialize_message(last_msg),
        "unread_count": max(0, unread_count)
    }


def _calculate_messages_cursor_signature(
    sent_at_iso: str,
    msg_id: str,
    match_id: str,
    viewer_user_id: str,
    secret_key: str
) -> str:
    """Calcula firma HMAC-SHA256 vinculada a fecha, mensaje, match y usuario solicitante."""
    msg = f"{sent_at_iso}|{msg_id}|{match_id}|{viewer_user_id}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def encode_messages_cursor(
    sent_at: datetime,
    msg_id: str,
    match_id: str,
    viewer_user_id: str
) -> str:
    """Codifica un cursor opaco firmado con HMAC para paginación de mensajes."""
    secret_key = _get_secret_key()
    sent_at_iso = format_datetime_iso(sent_at)
    sig = _calculate_messages_cursor_signature(
        sent_at_iso, str(msg_id), str(match_id), str(viewer_user_id), secret_key
    )
    payload = {
        "c": sent_at_iso,
        "m": str(msg_id),
        "mid": str(match_id),
        "v": str(viewer_user_id),
        "s": sig
    }
    raw_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw_bytes).decode('ascii')


def decode_messages_cursor(
    cursor_str: str,
    expected_match_id: str,
    expected_viewer_id: str
) -> Tuple[datetime, str]:
    """
    Decodifica y valida la firma e integridad del cursor de mensajes.
    Lanza MatchError('VALIDATION_ERROR', ..., 422) si el cursor está alterado,
    si pertenece a otro usuario o a otro match.
    """
    if not cursor_str or not isinstance(cursor_str, str):
        raise MatchError("VALIDATION_ERROR", "Cursor de paginación inválido.", 422)
    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.encode('ascii'))
        payload = json.loads(raw_bytes.decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError("Payload no es dict")
        required_keys = {"c", "m", "mid", "v", "s"}
        if not required_keys.issubset(payload.keys()):
            raise ValueError("Claves incompletas")
        if str(payload["v"]) != str(expected_viewer_id):
            raise MatchError("VALIDATION_ERROR", "El cursor no pertenece al usuario solicitante.", 422)
        if str(payload["mid"]) != str(expected_match_id):
            raise MatchError("VALIDATION_ERROR", "El cursor no corresponde a este match.", 422)
        secret_key = _get_secret_key()
        expected_sig = _calculate_messages_cursor_signature(
            payload["c"], str(payload["m"]), str(payload["mid"]), str(payload["v"]), secret_key
        )
        if not hmac.compare_digest(str(payload["s"]), expected_sig):
            raise MatchError("VALIDATION_ERROR", "Cursor de paginación inválido, alterado o firma no coincidente.", 422)

        sent_at = datetime.fromisoformat(payload["c"])
        msg_id = str(uuid.UUID(str(payload["m"])))
        return sent_at, msg_id
    except MatchError:
        raise
    except Exception:
        raise MatchError("VALIDATION_ERROR", "Cursor de paginación inválido o corrupto.", 422)


def validate_match_participant_and_active(current_user: User, match_id_raw: Any) -> Tuple[Match, User]:
    """
    Valida la elegibilidad del solicitante, el formato UUID de match_id, la existencia física del match,
    la pertenencia simétrica de current_user, la ausencia de bloqueos bidireccionales
    y el estado activo de la contraparte.
    Retorna la tupla (match_obj, other_user) o eleva MatchError con 404/422.
    """
    validate_viewer_matches_eligibility(current_user)

    if not match_id_raw or not isinstance(match_id_raw, str):
        raise MatchError("VALIDATION_ERROR", "El identificador del match debe ser un UUID válido.", 422)

    try:
        match_uuid = str(uuid.UUID(str(match_id_raw).strip()))
    except (ValueError, AttributeError):
        raise MatchError("VALIDATION_ERROR", "El identificador del match debe ser un UUID válido.", 422)

    match_obj = Match.query.filter_by(id=match_uuid).first()
    if not match_obj:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    # Validar pertenencia del usuario (si es ajeno, 404 para evitar inferencias a terceros)
    if str(current_user.id) not in (str(match_obj.user_a_id), str(match_obj.user_b_id)):
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    other_uid = match_obj.user_b_id if str(match_obj.user_a_id) == str(current_user.id) else match_obj.user_a_id

    # Bloqueos bidireccionales
    is_blocked = db.session.query(UserBlock.id).filter(
        or_(
            and_(UserBlock.blocker_user_id == current_user.id, UserBlock.blocked_user_id == other_uid),
            and_(UserBlock.blocker_user_id == other_uid, UserBlock.blocked_user_id == current_user.id),
        )
    ).first()
    if is_blocked:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    # Contraparte activa y habilitada
    other_user = User.query.filter_by(id=other_uid).first()
    if not other_user or other_user.lifecycle_status != 'active' or not other_user.email_verified:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    other_prof = other_user.profile
    if not other_prof or not other_prof.birth_date:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    try:
        if calculate_age(other_prof.birth_date) < 18:
            raise MatchError("NOT_FOUND", "Match no encontrado.", 404)
    except Exception:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    has_ready_primary = any(p.is_primary and p.status == 'ready' for p in other_prof.photos)
    if not has_ready_primary:
        raise MatchError("NOT_FOUND", "Match no encontrado.", 404)

    return match_obj, other_user


def send_message(current_user: User, match_id_raw: Any, payload: Any) -> Dict[str, Any]:
    """
    Valida y persiste transaccionalmente un nuevo mensaje de texto en un match activo.
    Cumple con el esquema OpenAPI Message y las restricciones físicas de la tabla messages:
    - Longitud: 1 a 2000 caracteres.
    - Rechazo de espacios en blanco exclusivos.
    - additionalProperties: false.
    - Persistencia en UTC, read_at=null.
    """
    match_obj, other_user = validate_match_participant_and_active(current_user, match_id_raw)

    if not isinstance(payload, dict):
        raise MatchError("VALIDATION_ERROR", "El cuerpo de la petición debe ser un objeto JSON.", 422)

    # Validar additionalProperties: false, required: [text]
    allowed_keys = {"text"}
    if set(payload.keys()) != allowed_keys:
        raise MatchError(
            "VALIDATION_ERROR",
            "La petición debe contener exactamente 'text' sin propiedades adicionales.",
            422
        )

    text = payload.get("text")
    if not isinstance(text, str):
        raise MatchError("VALIDATION_ERROR", "El campo 'text' debe ser una cadena de texto.", 422)

    trimmed = text.strip()
    if len(trimmed) == 0:
        raise MatchError("VALIDATION_ERROR", "El mensaje no puede estar vacío ni contener solo espacios.", 422)

    if len(text) < 1 or len(text) > 2000:
        raise MatchError("VALIDATION_ERROR", "El mensaje debe tener entre 1 y 2000 caracteres.", 422)

    # Persistencia transaccional
    try:
        new_msg = Message(
            id=str(uuid.uuid4()),
            match_id=match_obj.id,
            sender_user_id=current_user.id,
            text=text,
            sent_at=datetime.now(timezone.utc),
            read_at=None
        )
        db.session.add(new_msg)
        db.session.commit()

        serialized = serialize_message(new_msg)
        if not serialized:
            raise RuntimeError("Error al serializar mensaje persistido.")
        return serialized

    except MatchError:
        db.session.rollback()
        raise
    except IntegrityError as ie:
        db.session.rollback()
        current_app.logger.error(f"Error de integridad al guardar mensaje: {ie}")
        raise MatchError("VALIDATION_ERROR", "Violación de restricciones de integridad al enviar mensaje.", 422)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado al enviar mensaje: {e}")
        raise


def get_match_messages(
    current_user: User,
    match_id_raw: Any,
    limit: int = 20,
    cursor: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """
    Retorna el historial de mensajes de un match activo con paginación determinista por cursor opaco:
    - Orden: Message.sent_at DESC, Message.id DESC.
    - Filtro exclusivo por match_id.
    - Paginación continua sin duplicados.
    - No modifica read_at.
    """
    match_obj, other_user = validate_match_participant_and_active(current_user, match_id_raw)

    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise MatchError("VALIDATION_ERROR", "El parámetro 'limit' debe ser un entero entre 1 y 50.", 422)

    cursor_dt: Optional[datetime] = None
    cursor_mid: Optional[str] = None
    if cursor:
        cursor_dt, cursor_mid = decode_messages_cursor(cursor, match_obj.id, str(current_user.id))
        bind = db.session.get_bind()
        if bind.dialect.name == "sqlite" and cursor_dt.tzinfo is not None:
            cursor_dt = cursor_dt.astimezone(timezone.utc).replace(tzinfo=None)

    query = Message.query.filter(Message.match_id == match_obj.id)

    if cursor_dt is not None and cursor_mid is not None:
        query = query.filter(
            or_(
                Message.sent_at < cursor_dt,
                and_(Message.sent_at == cursor_dt, Message.id < cursor_mid)
            )
        )

    # Orden cronológico descendente estable (aprovecha ix_messages_match_id_sent_at_id)
    query = query.order_by(Message.sent_at.desc(), Message.id.desc())

    raw_messages = query.limit(limit + 1).all()

    has_more = len(raw_messages) > limit
    page_messages = raw_messages[:limit] if has_more else raw_messages

    if not page_messages:
        return [], None, False

    next_cursor = None
    if has_more:
        last_msg = page_messages[-1]
        next_cursor = encode_messages_cursor(
            last_msg.sent_at, last_msg.id, match_obj.id, str(current_user.id)
        )

    items = [serialize_message(m) for m in page_messages]
    return items, next_cursor, has_more


def mark_match_messages_as_read(current_user: User, match_id_raw: Any) -> Dict[str, Any]:
    """
    Marca atómica e idempotentemente como leídos todos los mensajes recibidos no leídos
    en el match especificado:
    - Exige sesión activa y pertenencia simétrica al match activo.
    - Actualiza únicamente mensajes donde match_id == match.id, sender_user_id != current_user.id y read_at IS NULL.
    - No modifica mensajes enviados por el solicitante ni mensajes con read_at previo.
    - Retorna {'unread_count': <conteo_remanente>} conforme a OpenAPI v1 (típicamente 0).
    """
    match_obj, other_user = validate_match_participant_and_active(current_user, match_id_raw)

    now_utc = datetime.now(timezone.utc)
    try:
        Message.query.filter(
            Message.match_id == match_obj.id,
            Message.sender_user_id != current_user.id,
            Message.read_at.is_(None)
        ).update(
            {Message.read_at: now_utc},
            synchronize_session='fetch'
        )
        db.session.commit()

        # Recalcular unread_count para el usuario autenticado
        unread_count = Message.query.filter(
            Message.match_id == match_obj.id,
            Message.sender_user_id != current_user.id,
            Message.read_at.is_(None)
        ).count()

        return {
            "unread_count": max(0, unread_count)
        }
    except MatchError:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado al marcar mensajes como leídos en match {match_obj.id}: {e}")
        raise


