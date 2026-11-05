"""
AFINIA — Servicio de Denuncias y Moderación de Usuarios (BE-04.3.2 y BE-10).
===========================================================================
Implementa la lógica de negocio y persistencia para la denuncia de usuarios
y su moderación administrativa conforme al contrato OpenAPI v1:
- POST /api/v1/users/{userId}/reports
- GET /api/v1/admin/reports
- POST /api/v1/admin/reports/{reportId}/resolve
Garantiza:
- Identidad del reportante y del administrador obtenida exclusivamente de la sesión (JWT + BD).
- Autorización administrativa estricta (role == 'admin') en servidor.
- Rechazo estricto de auto-denuncias (ck_user_reports_no_self).
- Validación de motivos permitidos ('acoso', 'contenido_inapropiado', 'suplantacion', 'spam', 'otro').
- Validación de longitud máxima de comentarios/notas (1000 caracteres) y prohibición de campos extra.
- Idempotencia en denuncias pendientes repetidas con el mismo motivo.
- Confidencialidad total y exposición mínima de PII en listados administrativos.
- Control transaccional y bloqueo pesimista (SELECT FOR UPDATE) al resolver denuncias,
  impidiendo sobrescribir resoluciones previas (409 CONFLICT).
- Sin suspensión, bloqueo o eliminación automática de cuentas denunciadas.
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
from sqlalchemy import and_, or_, desc
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.user import User
from app.models.report import UserReport


_resolve_report_mutex = threading.Lock()


class ReportError(Exception):
    """Excepción de dominio para operaciones de denuncia y moderación."""
    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[Dict[str, Any]] = None):
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


def _sign_admin_report_cursor(
    created_iso: str,
    report_id: str,
    filter_sig: str,
    secret_key: str,
) -> str:
    msg = f"admin_reports|{created_iso}|{report_id}|{filter_sig}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:24]


def encode_admin_report_cursor(
    created_at: datetime,
    report_id: str,
    filter_sig: str,
) -> str:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)
    created_iso = created_at.isoformat()
    secret_key = _get_cursor_secret()
    sig = _sign_admin_report_cursor(created_iso, str(report_id), filter_sig, secret_key)
    payload = {
        "c": created_iso,
        "r": str(report_id),
        "f": filter_sig,
        "s": sig,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_admin_report_cursor(cursor_str: Any, expected_filter_sig: str) -> Tuple[datetime, str]:
    if not cursor_str or not isinstance(cursor_str, str):
        raise ReportError("VALIDATION_ERROR", "Cursor de paginación inválido.", 422)
    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.strip().encode("ascii"))
        payload = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Cursor payload is not dict")
        if not {"c", "r", "f", "s"}.issubset(payload.keys()):
            raise ValueError("Missing cursor keys")
        if str(payload["f"]) != expected_filter_sig:
            raise ReportError(
                "VALIDATION_ERROR",
                "El cursor de paginación no corresponde a los filtros actuales.",
                422,
            )
        secret_key = _get_cursor_secret()
        expected_sig = _sign_admin_report_cursor(
            str(payload["c"]),
            str(payload["r"]),
            str(payload["f"]),
            secret_key,
        )
        if not hmac.compare_digest(str(payload["s"]), expected_sig):
            raise ReportError("VALIDATION_ERROR", "Cursor de paginación inválido o alterado.", 422)

        created_at = datetime.fromisoformat(str(payload["c"]))
        report_id = str(uuid.UUID(str(payload["r"])))
        return created_at, report_id
    except ReportError:
        raise
    except Exception:
        raise ReportError("VALIDATION_ERROR", "Cursor de paginación inválido o corrupto.", 422)


def _assert_admin_actor(actor: Optional[User]) -> User:
    """
    Verificación defensiva en capa de servicio de que el actor sea un administrador
    activo y autorizado en base de datos.
    """
    if not actor or not getattr(actor, "id", None):
        raise ReportError("UNAUTHORIZED", "Sesión inválida o ausente.", 401)

    user_db = db.session.get(User, str(actor.id))
    if not user_db or not user_db.is_active or user_db.deleted_at is not None:
        raise ReportError("UNAUTHORIZED", "Usuario inexistente o cuenta deshabilitada.", 401)

    if user_db.lifecycle_status == "suspended":
        raise ReportError("FORBIDDEN", "Cuenta suspendida por moderación.", 403)
    if user_db.lifecycle_status == "deactivated":
        raise ReportError("UNAUTHORIZED", "Cuenta desactivada.", 401)

    if user_db.role != "admin":
        raise ReportError("FORBIDDEN", "Acceso denegado: se requieren privilegios de administrador.", 403)

    return user_db


def create_user_report(current_user: User, target_user_id_raw: Any, payload: Any) -> Dict[str, Any]:
    """
    POST /api/v1/users/{userId}/reports
    Crea un reporte sobre un usuario conforme a OpenAPI v1.
    Retorna {'report_id': UUID, 'status': 'received'}.
    """
    # 1. Validar estado de la cuenta solicitante
    if current_user.lifecycle_status in ("suspended", "deactivated"):
        raise ReportError("FORBIDDEN", "Acceso denegado: cuenta no disponible.", 403)

    # 2. Validar formato UUID del target_user_id
    if not target_user_id_raw or not isinstance(target_user_id_raw, str):
        raise ReportError("VALIDATION_ERROR", "El identificador del usuario debe ser un UUID válido.", 422)

    try:
        target_uuid = str(uuid.UUID(str(target_user_id_raw).strip()))
    except (ValueError, AttributeError):
        raise ReportError("VALIDATION_ERROR", "El identificador del usuario debe ser un UUID válido.", 422)

    # 3. Prohibir auto-denuncias
    if str(current_user.id) == target_uuid:
        raise ReportError("BAD_REQUEST", "No puedes denunciar tu propio perfil.", 400)

    # 4. Validar existencia física del usuario denunciado
    target_user = User.query.filter_by(id=target_uuid).first()
    if not target_user or target_user.deleted_at is not None:
        raise ReportError("NOT_FOUND", "Usuario a denunciar no encontrado.", 404)

    # 5. Validar cuerpo de la petición
    if not isinstance(payload, dict):
        raise ReportError("VALIDATION_ERROR", "El cuerpo de la petición debe ser un objeto JSON.", 422)

    # additionalProperties: false, required: [reason]
    allowed_keys = {"reason", "description"}
    if not set(payload.keys()).issubset(allowed_keys):
        raise ReportError("VALIDATION_ERROR", "La petición contiene campos no permitidos.", 422)

    if "reason" not in payload:
        raise ReportError("VALIDATION_ERROR", "El campo 'reason' es obligatorio.", 422)

    reason = payload.get("reason")
    if not isinstance(reason, str) or reason not in UserReport.ALLOWED_REASONS:
        raise ReportError(
            "VALIDATION_ERROR",
            f"Motivo de reporte inválido. Permitidos: {list(UserReport.ALLOWED_REASONS)}.",
            422
        )

    description = payload.get("description")
    if description is not None:
        if not isinstance(description, str):
            raise ReportError("VALIDATION_ERROR", "La descripción debe ser una cadena de texto.", 422)
        if len(description) > 1000:
            raise ReportError("VALIDATION_ERROR", "La descripción no puede exceder los 1000 caracteres.", 422)
        description = description.strip()
        if len(description) == 0:
            description = None

    # 6. Idempotencia: si ya existe un reporte pendiente idéntico del mismo usuario
    existing_report = UserReport.query.filter_by(
        reporter_user_id=str(current_user.id),
        reported_user_id=target_uuid,
        reason=reason,
        status="pending"
    ).first()

    if existing_report:
        return {
            "report_id": str(existing_report.id),
            "status": "received"
        }

    # 7. Persistir el nuevo reporte
    new_report = UserReport(
        id=str(uuid.uuid4()),
        reporter_user_id=str(current_user.id),
        reported_user_id=target_uuid,
        reason=reason,
        description=description,
        status="pending"
    )

    try:
        db.session.add(new_report)
        db.session.commit()
        return {
            "report_id": str(new_report.id),
            "status": "received"
        }
    except IntegrityError as ie:
        db.session.rollback()
        current_app.logger.error(f"Error de integridad al registrar denuncia: {ie}")
        raise ReportError("BAD_REQUEST", "Error de integridad al persistir el reporte.", 400)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado al registrar denuncia: {e}")
        raise


def serialize_moderation_report(report: UserReport) -> Dict[str, Any]:
    """
    Serializa una denuncia estrictamente conforme al esquema OpenAPI `ModerationReport`:
    - id, reporter_user_id, reported_user_id, reason, status, created_at.
    - Minimización de datos: NUNCA expone emails, nombres, fecha de nacimiento, fotos,
      respuestas del cuestionario, direcciones IP ni tokens.
    """
    return {
        "id": str(report.id),
        "reporter_user_id": str(report.reporter_user_id),
        "reported_user_id": str(report.reported_user_id),
        "reason": report.reason,
        "status": report.status,
        "created_at": _format_utc_iso(report.created_at),
    }


def list_moderation_reports(
    admin_user: User,
    query_args: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """
    GET /api/v1/admin/reports
    Lista denuncias para moderación administrativa con validación estricta de permisos,
    filtros opcionales, paginación por cursor firmada y ordenamiento determinista.
    """
    actor = _assert_admin_actor(admin_user)
    args = dict(query_args or {})

    allowed_params = {"limit", "cursor", "status", "reason", "reported_user_id", "reporter_user_id"}
    extra_params = set(args.keys()) - allowed_params
    if extra_params:
        raise ReportError(
            "VALIDATION_ERROR",
            f"Parámetros de consulta no permitidos: {', '.join(sorted(extra_params))}.",
            422,
        )

    limit_raw = args.get("limit", 20)
    if isinstance(limit_raw, bool):
        raise ReportError("VALIDATION_ERROR", "El parámetro 'limit' debe ser un número entero entre 1 y 50.", 422)
    try:
        limit = int(str(limit_raw).strip()) if limit_raw is not None else 20
    except (ValueError, TypeError):
        raise ReportError("VALIDATION_ERROR", "El parámetro 'limit' debe ser un número entero entre 1 y 50.", 422)

    if limit < 1 or limit > 50:
        raise ReportError("VALIDATION_ERROR", "El parámetro 'limit' debe estar comprendido entre 1 y 50.", 422)

    status_filter = args.get("status")
    if status_filter is not None:
        if not isinstance(status_filter, str) or status_filter.strip() not in UserReport.ALLOWED_STATUSES:
            raise ReportError(
                "VALIDATION_ERROR",
                f"Filtro 'status' inválido. Valores permitidos: {list(UserReport.ALLOWED_STATUSES)}.",
                422,
            )
        status_filter = status_filter.strip()

    reason_filter = args.get("reason")
    if reason_filter is not None:
        if not isinstance(reason_filter, str) or reason_filter.strip() not in UserReport.ALLOWED_REASONS:
            raise ReportError(
                "VALIDATION_ERROR",
                f"Filtro 'reason' inválido. Valores permitidos: {list(UserReport.ALLOWED_REASONS)}.",
                422,
            )
        reason_filter = reason_filter.strip()

    reported_uid_filter = args.get("reported_user_id")
    if reported_uid_filter is not None:
        try:
            reported_uid_filter = str(uuid.UUID(str(reported_uid_filter).strip()))
        except (ValueError, AttributeError):
            raise ReportError("VALIDATION_ERROR", "El filtro 'reported_user_id' debe ser un UUID válido.", 422)

    reporter_uid_filter = args.get("reporter_user_id")
    if reporter_uid_filter is not None:
        try:
            reporter_uid_filter = str(uuid.UUID(str(reporter_uid_filter).strip()))
        except (ValueError, AttributeError):
            raise ReportError("VALIDATION_ERROR", "El filtro 'reporter_user_id' debe ser un UUID válido.", 422)

    filter_sig = f"{status_filter or '*'}|{reason_filter or '*'}|{reported_uid_filter or '*'}|{reporter_uid_filter or '*'}"

    cursor_raw = args.get("cursor")
    cursor_dt: Optional[datetime] = None
    cursor_id: Optional[str] = None
    if cursor_raw is not None:
        if not isinstance(cursor_raw, str) or not cursor_raw.strip():
            raise ReportError("VALIDATION_ERROR", "Cursor de paginación inválido.", 422)
        cursor_dt, cursor_id = decode_admin_report_cursor(cursor_raw, filter_sig)

    query = UserReport.query

    if status_filter:
        query = query.filter(UserReport.status == status_filter)
    if reason_filter:
        query = query.filter(UserReport.reason == reason_filter)
    if reported_uid_filter:
        query = query.filter(UserReport.reported_user_id == reported_uid_filter)
    if reporter_uid_filter:
        query = query.filter(UserReport.reporter_user_id == reporter_uid_filter)

    if cursor_dt is not None and cursor_id is not None:
        if db.engine.dialect.name == "sqlite" and cursor_dt.tzinfo is not None:
            cursor_dt_cmp = cursor_dt.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            cursor_dt_cmp = cursor_dt

        query = query.filter(
            or_(
                UserReport.created_at < cursor_dt_cmp,
                and_(UserReport.created_at == cursor_dt_cmp, UserReport.id < cursor_id),
            )
        )

    # Ordenamiento estrictamente determinista: created_at DESC, id DESC
    query = query.order_by(desc(UserReport.created_at), desc(UserReport.id))

    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items = [serialize_moderation_report(r) for r in page_rows]

    next_cursor = None
    if has_more and page_rows:
        last_row = page_rows[-1]
        next_cursor = encode_admin_report_cursor(last_row.created_at, str(last_row.id), filter_sig)

    current_app.logger.info(
        f"[ADMIN-REPORTS-LIST] admin_user_id={actor.id} count={len(items)} "
        f"has_more={has_more} filters={filter_sig}"
    )
    return items, next_cursor, has_more


def resolve_moderation_report(
    admin_user: User,
    report_id_raw: Any,
    payload: Any,
) -> Dict[str, str]:
    """
    POST /api/v1/admin/reports/{reportId}/resolve
    Resuelve una denuncia administrativa de forma transaccional y segura:
    - Autoriza exclusivamente al rol 'admin' activo en base de datos.
    - Valida UUID del reporte y esquema OpenAPI `ReportResolution` (action: dismiss|warn|suspend, notes <= 1000).
    - Adquiere bloqueo pesimista (SELECT FOR UPDATE) para evitar condiciones de carrera entre administradores.
    - Prohíbe sobrescribir resoluciones previas: si status != 'pending', retorna 409 CONFLICT.
    - Registra resolved_by_user_id, resolved_at, resolution_action, resolution_notes y nuevo status.
    - No suspende, bloquea ni elimina automáticamente la cuenta denunciada.
    """
    actor = _assert_admin_actor(admin_user)
    actor_id = str(actor.id)

    if not report_id_raw or not isinstance(report_id_raw, str):
        raise ReportError("VALIDATION_ERROR", "El identificador del reporte debe ser un UUID válido.", 422)

    try:
        report_uuid = str(uuid.UUID(str(report_id_raw).strip()))
    except (ValueError, AttributeError):
        raise ReportError("VALIDATION_ERROR", "El identificador del reporte debe ser un UUID válido.", 422)

    if not isinstance(payload, dict):
        raise ReportError("VALIDATION_ERROR", "El cuerpo de la petición debe ser un objeto JSON válido.", 422)

    allowed_keys = {"action", "notes"}
    extra_keys = set(payload.keys()) - allowed_keys
    if extra_keys:
        raise ReportError(
            "VALIDATION_ERROR",
            f"Campos no permitidos en la resolución: {', '.join(sorted(extra_keys))}.",
            422,
        )

    if "action" not in payload or payload.get("action") is None:
        raise ReportError("VALIDATION_ERROR", "El campo 'action' es obligatorio.", 422)

    action = payload.get("action")
    if not isinstance(action, str) or action not in UserReport.ALLOWED_ACTIONS:
        raise ReportError(
            "VALIDATION_ERROR",
            f"Acción de resolución inválida. Permitidas: {list(UserReport.ALLOWED_ACTIONS)}.",
            422,
        )

    notes = payload.get("notes")
    if notes is not None:
        if not isinstance(notes, str):
            raise ReportError("VALIDATION_ERROR", "El campo 'notes' debe ser una cadena de texto.", 422)
        if len(notes) > 1000:
            raise ReportError("VALIDATION_ERROR", "El campo 'notes' no puede exceder los 1000 caracteres.", 422)
        notes = notes.strip()
        if not notes:
            notes = None

    with _resolve_report_mutex:
        try:
            db.session.expire_all()
            report_query = UserReport.query.filter_by(id=report_uuid).populate_existing()
            if db.engine.dialect.name == "postgresql":
                report_query = report_query.with_for_update()

            report = report_query.first()
            if not report:
                raise ReportError("NOT_FOUND", "Denuncia no encontrada.", 404)

            if report.status != "pending" or report.resolved_at is not None:
                raise ReportError(
                    "CONFLICT",
                    f"La denuncia ya fue resuelta previamente con estado '{report.status}'.",
                    409,
                )

            now = datetime.now(timezone.utc)
            new_status = "dismissed" if action == "dismiss" else "resolved"

            with db.session.no_autoflush:
                report.resolved_at = now
                report.resolved_by_user_id = actor_id
                report.resolution_action = action
                report.resolution_notes = notes
                report.status = new_status

            db.session.commit()

            current_app.logger.info(
                f"[ADMIN-REPORT-RESOLVED] report_id={report.id} admin_user_id={actor_id} "
                f"action={action} status={new_status} resolved_at={_format_utc_iso(now)}"
            )
            return {"status": new_status}

        except ReportError:
            db.session.rollback()
            raise
        except IntegrityError as ie:
            db.session.rollback()
            current_app.logger.error(f"Error de integridad al resolver denuncia {report_uuid}: {ie}")
            raise ReportError("CONFLICT", "Conflicto de integridad al resolver la denuncia.", 409)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error inesperado al resolver denuncia {report_uuid}: {e}")
            raise ReportError("INTERNAL_ERROR", "Error interno al resolver la denuncia.", 500)

