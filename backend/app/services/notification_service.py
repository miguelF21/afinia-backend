"""
AFINIA — Servicio de Notificaciones del Usuario (BE-11).
========================================================
Implementa la generación transaccional, consulta paginada y marcación de lectura
de notificaciones propias del usuario conforme al contrato OpenAPI v1:
- GET /api/v1/notifications
- POST /api/v1/notifications/{notificationId}/read

Garantiza:
- Autenticación obligatoria y aislamiento estricto por usuario (`Notification.user_id == current_user.id`).
- Eventos soportados según contrato: `new_match` ("Tienes un nuevo match") y `new_message` ("Tienes un nuevo mensaje").
- Protección de privacidad: títulos estandarizados sin exponer contenido privado de mensajes ni PII de terceros.
- Paginación por cursor opaco firmado con HMAC-SHA256 y orden determinista (`created_at DESC, id DESC`).
- Marcación de lectura idempotente y segura bajo concurrencia (`SELECT ... FOR UPDATE`).
"""

import uuid
import json
import hmac
import hashlib
import base64
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from flask import current_app
import sqlalchemy as sa
from sqlalchemy import and_, or_, desc
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.user import User
from app.models.notification import Notification


_read_notification_mutex = threading.Lock()


class NotificationError(Exception):
    """Excepción de dominio para operaciones de notificaciones."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _format_utc_iso(dt: Optional[datetime]) -> str:
    """Formatea un datetime a ISO-8601 UTC canónico terminado en 'Z'."""
    if dt is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _get_cursor_secret() -> str:
    try:
        return str(current_app.config.get("SECRET_KEY", "afinia-default-secret"))
    except RuntimeError:
        return "afinia-default-secret"


def notifications_table_exists() -> bool:
    """
    Comprueba si la tabla física `notifications` existe en el motor conectado.
    Permite operar de forma segura cuando la migración `a7b3c9d1e5f2` aún está
    pendiente de autorización en PostgreSQL QA.
    """
    try:
        return bool(sa.inspect(db.engine).has_table("notifications"))
    except Exception:
        return False


def _assert_active_user(user: Optional[User]) -> User:
    if not user or not getattr(user, "id", None):
        raise NotificationError("UNAUTHORIZED", "Sesión inválida o ausente.", 401)

    user_db = db.session.get(User, str(user.id))
    if not user_db or not user_db.is_active or user_db.deleted_at is not None:
        raise NotificationError("UNAUTHORIZED", "Sesión inválida o cuenta inactiva.", 401)

    if user_db.lifecycle_status == "suspended":
        raise NotificationError("FORBIDDEN", "Cuenta suspendida por moderación.", 403)
    if user_db.lifecycle_status == "deactivated":
        raise NotificationError("UNAUTHORIZED", "Cuenta desactivada.", 401)

    return user_db


def serialize_notification(notif: Notification) -> Dict[str, Any]:
    """
    Serializa una notificación estrictamente conforme al esquema OpenAPI `Notification`:
    - id (uuid)
    - type ('new_match' | 'new_message')
    - title (string)
    - created_at (date-time ISO-8601 UTC)
    - read (boolean)
    """
    return {
        "id": str(notif.id),
        "type": notif.type,
        "title": notif.title,
        "created_at": _format_utc_iso(notif.created_at),
        "read": notif.read_at is not None,
    }


def _sign_notification_cursor(
    created_iso: str,
    notification_id: str,
    user_id: str,
    secret_key: str,
) -> str:
    msg = f"notifications|{created_iso}|{notification_id}|{user_id}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:24]


def encode_notification_cursor(
    created_at: datetime,
    notification_id: str,
    user_id: str,
) -> str:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)
    created_iso = created_at.isoformat()
    secret_key = _get_cursor_secret()
    sig = _sign_notification_cursor(created_iso, str(notification_id), str(user_id), secret_key)
    payload = {
        "c": created_iso,
        "n": str(notification_id),
        "u": str(user_id),
        "s": sig,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_notification_cursor(cursor_str: Any, expected_user_id: str) -> Tuple[datetime, str]:
    if not cursor_str or not isinstance(cursor_str, str):
        raise NotificationError("VALIDATION_ERROR", "Cursor de paginación inválido.", 422)
    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.strip().encode("ascii"))
        payload = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Cursor payload is not dict")
        if not {"c", "n", "u", "s"}.issubset(payload.keys()):
            raise ValueError("Missing cursor keys")
        if str(payload["u"]) != str(expected_user_id):
            raise NotificationError(
                "VALIDATION_ERROR",
                "El cursor de paginación no pertenece al usuario autenticado.",
                422,
            )
        secret_key = _get_cursor_secret()
        expected_sig = _sign_notification_cursor(
            str(payload["c"]),
            str(payload["n"]),
            str(payload["u"]),
            secret_key,
        )
        if not hmac.compare_digest(str(payload["s"]), expected_sig):
            raise NotificationError("VALIDATION_ERROR", "Cursor de paginación inválido o alterado.", 422)

        created_at = datetime.fromisoformat(str(payload["c"]))
        notif_id = str(uuid.UUID(str(payload["n"])))
        return created_at, notif_id
    except NotificationError:
        raise
    except Exception:
        raise NotificationError("VALIDATION_ERROR", "Cursor de paginación inválido o corrupto.", 422)


def emit_match_notifications(
    user_a_id: str,
    user_b_id: str,
    match_id: str,
    created_at: Optional[datetime] = None,
) -> None:
    """
    Registra en la sesión SQL actual las notificaciones de tipo `new_match`
    para ambos participantes cuando se forma un match mutuo.
    """
    if not notifications_table_exists():
        return

    now_utc = created_at or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    ref_id = str(match_id)
    for uid in (str(user_a_id), str(user_b_id)):
        exists = Notification.query.filter_by(
            user_id=uid,
            type="new_match",
            reference_id=ref_id,
        ).first()
        if not exists:
            db.session.add(
                Notification(
                    id=str(uuid.uuid4()),
                    user_id=uid,
                    type="new_match",
                    title="Tienes un nuevo match",
                    reference_id=ref_id,
                    created_at=now_utc,
                    read_at=None,
                )
            )


def emit_message_notification(
    recipient_user_id: str,
    message_id: str,
    created_at: Optional[datetime] = None,
) -> None:
    """
    Registra en la sesión SQL actual la notificación de tipo `new_message`
    para el destinatario de un mensaje enviado en un match activo.
    """
    if not notifications_table_exists():
        return

    now_utc = created_at or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    uid = str(recipient_user_id)
    ref_id = str(message_id)
    exists = Notification.query.filter_by(
        user_id=uid,
        type="new_message",
        reference_id=ref_id,
    ).first()
    if not exists:
        db.session.add(
            Notification(
                id=str(uuid.uuid4()),
                user_id=uid,
                type="new_message",
                title="Tienes un nuevo mensaje",
                reference_id=ref_id,
                created_at=now_utc,
                read_at=None,
            )
        )


def list_user_notifications(
    current_user: User,
    query_args: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """
    GET /api/v1/notifications
    Lista las notificaciones propias del usuario autenticado con paginación por cursor
    y ordenamiento determinista (`created_at DESC, id DESC`).
    """
    actor = _assert_active_user(current_user)
    user_id_str = str(actor.id)
    args = dict(query_args or {})

    allowed_params = {"limit", "cursor"}
    extra_params = set(args.keys()) - allowed_params
    if extra_params:
        raise NotificationError(
            "VALIDATION_ERROR",
            f"Parámetros de consulta no permitidos: {', '.join(sorted(extra_params))}.",
            422,
        )

    limit_raw = args.get("limit", 20)
    if isinstance(limit_raw, bool):
        raise NotificationError(
            "VALIDATION_ERROR",
            "El parámetro 'limit' debe ser un número entero entre 1 y 50.",
            422,
        )
    try:
        limit = int(str(limit_raw).strip()) if limit_raw is not None else 20
    except (ValueError, TypeError):
        raise NotificationError(
            "VALIDATION_ERROR",
            "El parámetro 'limit' debe ser un número entero entre 1 y 50.",
            422,
        )

    if limit < 1 or limit > 50:
        raise NotificationError(
            "VALIDATION_ERROR",
            "El parámetro 'limit' debe estar comprendido entre 1 y 50.",
            422,
        )

    cursor_raw = args.get("cursor")
    cursor_dt: Optional[datetime] = None
    cursor_id: Optional[str] = None
    if cursor_raw is not None:
        if not isinstance(cursor_raw, str) or not cursor_raw.strip():
            raise NotificationError("VALIDATION_ERROR", "Cursor de paginación inválido.", 422)
        cursor_dt, cursor_id = decode_notification_cursor(cursor_raw, user_id_str)

    if not notifications_table_exists():
        raise NotificationError(
            "SERVICE_UNAVAILABLE",
            "La tabla de notificaciones requiere aplicar la migración pendiente en PostgreSQL.",
            503,
        )

    query = Notification.query.filter(Notification.user_id == user_id_str)

    if cursor_dt is not None and cursor_id is not None:
        if db.engine.dialect.name == "sqlite" and cursor_dt.tzinfo is not None:
            cursor_dt_cmp = cursor_dt.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            cursor_dt_cmp = cursor_dt

        query = query.filter(
            or_(
                Notification.created_at < cursor_dt_cmp,
                and_(Notification.created_at == cursor_dt_cmp, Notification.id < cursor_id),
            )
        )

    query = query.order_by(desc(Notification.created_at), desc(Notification.id))

    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items = [serialize_notification(n) for n in page_rows]

    next_cursor = None
    if has_more and page_rows:
        last_row = page_rows[-1]
        next_cursor = encode_notification_cursor(last_row.created_at, str(last_row.id), user_id_str)

    return items, next_cursor, has_more


def mark_notification_as_read(
    current_user: User,
    notification_id_raw: Any,
    query_args: Optional[Dict[str, Any]] = None,
) -> None:
    """
    POST /api/v1/notifications/{notificationId}/read
    Marca como leída una notificación propia del usuario autenticado de forma
    idempotente y segura bajo concurrencia.
    """
    actor = _assert_active_user(current_user)
    user_id_str = str(actor.id)

    if query_args:
        extra_q = set(query_args.keys())
        if extra_q:
            raise NotificationError(
                "VALIDATION_ERROR",
                f"Parámetros de consulta no permitidos: {', '.join(sorted(extra_q))}.",
                422,
            )

    if not notification_id_raw or not isinstance(notification_id_raw, str):
        raise NotificationError(
            "VALIDATION_ERROR",
            "El identificador de la notificación debe ser un UUID válido.",
            422,
        )

    try:
        notif_uuid = str(uuid.UUID(str(notification_id_raw).strip()))
    except (ValueError, AttributeError):
        raise NotificationError(
            "VALIDATION_ERROR",
            "El identificador de la notificación debe ser un UUID válido.",
            422,
        )

    if not notifications_table_exists():
        raise NotificationError(
            "SERVICE_UNAVAILABLE",
            "La tabla de notificaciones requiere aplicar la migración pendiente en PostgreSQL.",
            503,
        )

    with _read_notification_mutex:
        try:
            db.session.expire_all()
            notif_query = Notification.query.filter_by(
                id=notif_uuid,
                user_id=user_id_str,
            ).populate_existing()
            if db.engine.dialect.name == "postgresql":
                notif_query = notif_query.with_for_update()

            notif = notif_query.first()
            if not notif:
                raise NotificationError("NOT_FOUND", "Notificación no encontrada.", 404)

            if notif.read_at is None:
                with db.session.no_autoflush:
                    notif.read_at = datetime.now(timezone.utc)
                db.session.commit()

            return None

        except NotificationError:
            db.session.rollback()
            raise
        except IntegrityError:
            db.session.rollback()
            raise NotificationError("CONFLICT", "Conflicto de concurrencia al actualizar la notificación.", 409)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error inesperado al marcar notificación {notif_uuid} como leída: {e}")
            raise NotificationError("INTERNAL_ERROR", "Error interno al actualizar la notificación.", 500)

