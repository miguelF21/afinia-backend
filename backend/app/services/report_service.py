"""
AFINIA — Servicio de Denuncias y Moderación de Usuarios (BE-04.3.2).
==================================================================
Implementa la lógica de negocio y persistencia para la denuncia de usuarios
conforme al contrato OpenAPI v1:
- POST /api/v1/users/{userId}/reports
Garantiza:
- Identidad del reportante obtenida exclusivamente de la sesión (JWT).
- Rechazo estricto de auto-denuncias (ck_user_reports_no_self).
- Validación de motivos permitidos ('acoso', 'contenido_inapropiado', 'suplantacion', 'spam', 'otro').
- Validación de longitud máxima de comentarios (1000 caracteres) y prohibición de campos extra.
- Idempotencia en denuncias pendientes repetidas con el mismo motivo.
- Confidencialidad total: el usuario denunciado nunca es notificado ni expuesto.
- Sin suspensión automática de cuentas por recepción de denuncia.
- Persistencia real en la tabla física `user_reports`.
"""

import uuid
from typing import Any, Dict, Optional
from flask import current_app
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.user import User
from app.models.report import UserReport


class ReportError(Exception):
    """Excepción de dominio para operaciones de denuncia de usuarios."""
    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


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
