"""
AFINIA — Servicio de Documentos y Aceptaciones Legales (BE-11).
===============================================================
Implementa la consulta de versiones legales vigentes y el registro explícito,
idempotente y auditable de consentimientos legales para usuarios autenticados:
- GET /api/v1/legal/current
- POST /api/v1/legal/acceptances

Garantiza:
- Registro exclusivo de aceptaciones explícitas enviadas por el usuario autenticado.
- Validación estricta contra las versiones vigentes configuradas (sin inventar documentos ni versiones).
- Prevención de duplicados e idempotencia ante reintentos o llamadas concurrentes (SELECT FOR UPDATE + UniqueConstraint).
- Conservación íntegra de la fecha original de aceptación (accepted_at) e IP para trazabilidad.
"""

import uuid
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from flask import current_app
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.user import User
from app.models.legal import LegalConsent


_legal_acceptance_mutex = threading.Lock()


class LegalError(Exception):
    """Excepción de dominio para operaciones de documentos y consentimientos legales."""

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


def get_current_legal_documents() -> Dict[str, str]:
    """
    Retorna el esquema `LegalVersions` conforme al contrato OpenAPI v1.
    """
    return {
        "terms_version": current_app.config.get("LEGAL_TERMS_VERSION", "v1-draft"),
        "privacy_version": current_app.config.get("LEGAL_PRIVACY_VERSION", "v1-draft"),
        "terms_url": current_app.config.get("LEGAL_TERMS_URL", "https://legal.example.test/terms"),
        "privacy_url": current_app.config.get("LEGAL_PRIVACY_URL", "https://legal.example.test/privacy"),
    }


def record_legal_acceptance(
    current_user: User,
    payload: Any,
    ip_address: Optional[str] = None,
    query_args: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    POST /api/v1/legal/acceptances
    Registra la aceptación explícita de los documentos legales vigentes (`terms_of_service`
    y `privacy_policy`) por parte del usuario autenticado.
    """
    if query_args:
        extra_q = set(query_args.keys())
        if extra_q:
            raise LegalError(
                "VALIDATION_ERROR",
                f"Parámetros de consulta no permitidos: {', '.join(sorted(extra_q))}.",
                422,
            )

    if not current_user or not getattr(current_user, "id", None):
        raise LegalError("UNAUTHORIZED", "Sesión inválida o ausente.", 401)

    if not isinstance(payload, dict):
        raise LegalError(
            "VALIDATION_ERROR",
            "El cuerpo de la solicitud debe ser un objeto JSON válido.",
            422,
        )

    allowed_keys = {"terms_version", "privacy_version"}
    extra_keys = set(payload.keys()) - allowed_keys
    if extra_keys:
        raise LegalError(
            "VALIDATION_ERROR",
            f"Campos adicionales no permitidos: {', '.join(sorted(extra_keys))}.",
            422,
        )

    missing_keys = allowed_keys - set(payload.keys())
    if missing_keys:
        raise LegalError(
            "VALIDATION_ERROR",
            f"Faltan campos obligatorios: {', '.join(sorted(missing_keys))}.",
            422,
        )

    terms_version = payload.get("terms_version")
    privacy_version = payload.get("privacy_version")

    if not isinstance(terms_version, str) or not terms_version.strip():
        raise LegalError(
            "VALIDATION_ERROR",
            "El campo 'terms_version' debe ser una cadena de texto no vacía.",
            422,
        )

    if not isinstance(privacy_version, str) or not privacy_version.strip():
        raise LegalError(
            "VALIDATION_ERROR",
            "El campo 'privacy_version' debe ser una cadena de texto no vacía.",
            422,
        )

    terms_version = terms_version.strip()
    privacy_version = privacy_version.strip()

    if len(terms_version) > 50 or len(privacy_version) > 50:
        raise LegalError(
            "VALIDATION_ERROR",
            "La versión del documento legal no puede exceder los 50 caracteres.",
            422,
        )

    expected_terms = current_app.config.get("LEGAL_TERMS_VERSION", "v1-draft")
    expected_privacy = current_app.config.get("LEGAL_PRIVACY_VERSION", "v1-draft")

    if terms_version != expected_terms or privacy_version != expected_privacy:
        raise LegalError(
            "VALIDATION_ERROR",
            "Las versiones enviadas no coinciden con los documentos legales vigentes publicados.",
            422,
            details={
                "expected_terms_version": expected_terms,
                "expected_privacy_version": expected_privacy,
            },
        )

    sanitized_ip = str(ip_address).strip()[:45] if ip_address else None
    user_id_str = str(current_user.id)

    with _legal_acceptance_mutex:
        try:
            db.session.expire_all()
            user_query = User.query.filter_by(id=user_id_str).populate_existing()
            if db.engine.dialect.name == "postgresql":
                user_query = user_query.with_for_update()

            user_db = user_query.first()
            if not user_db or not user_db.is_active or user_db.deleted_at is not None:
                raise LegalError("UNAUTHORIZED", "Sesión inválida o cuenta inactiva.", 401)

            if user_db.lifecycle_status in ("suspended", "deactivated"):
                raise LegalError(
                    "CONFLICT",
                    "El estado actual de la cuenta no permite registrar aceptaciones legales.",
                    409,
                )

            existing_consents = LegalConsent.query.filter(
                LegalConsent.user_id == user_id_str,
                LegalConsent.document_type.in_(("terms_of_service", "privacy_policy")),
            ).all()

            existing_map = {
                (c.document_type, c.document_version): c for c in existing_consents
            }

            terms_record = existing_map.get(("terms_of_service", terms_version))
            privacy_record = existing_map.get(("privacy_policy", privacy_version))

            now_utc = datetime.now(timezone.utc)
            created_any = False

            if terms_record is None:
                terms_record = LegalConsent(
                    id=str(uuid.uuid4()),
                    user_id=user_id_str,
                    document_type="terms_of_service",
                    document_version=terms_version,
                    accepted_at=now_utc,
                    ip_address=sanitized_ip,
                )
                db.session.add(terms_record)
                created_any = True

            if privacy_record is None:
                privacy_record = LegalConsent(
                    id=str(uuid.uuid4()),
                    user_id=user_id_str,
                    document_type="privacy_policy",
                    document_version=privacy_version,
                    accepted_at=now_utc,
                    ip_address=sanitized_ip,
                )
                db.session.add(privacy_record)
                created_any = True

            if created_any:
                db.session.commit()
                accepted_dt = now_utc
            else:
                t_dt = terms_record.accepted_at
                p_dt = privacy_record.accepted_at
                if t_dt.tzinfo is None:
                    t_dt = t_dt.replace(tzinfo=timezone.utc)
                if p_dt.tzinfo is None:
                    p_dt = p_dt.replace(tzinfo=timezone.utc)
                accepted_dt = max(t_dt, p_dt)

            return {"accepted_at": _format_utc_iso(accepted_dt)}

        except LegalError:
            db.session.rollback()
            raise
        except IntegrityError as ie:
            db.session.rollback()
            current_app.logger.warning(
                f"Colisión concurrente en legal_consents para user_id={user_id_str}: {ie}"
            )
            terms_record = LegalConsent.query.filter_by(
                user_id=user_id_str,
                document_type="terms_of_service",
                document_version=terms_version,
            ).first()
            privacy_record = LegalConsent.query.filter_by(
                user_id=user_id_str,
                document_type="privacy_policy",
                document_version=privacy_version,
            ).first()
            if terms_record and privacy_record:
                t_dt = terms_record.accepted_at
                p_dt = privacy_record.accepted_at
                if t_dt.tzinfo is None:
                    t_dt = t_dt.replace(tzinfo=timezone.utc)
                if p_dt.tzinfo is None:
                    p_dt = p_dt.replace(tzinfo=timezone.utc)
                return {"accepted_at": _format_utc_iso(max(t_dt, p_dt))}
            raise LegalError(
                "CONFLICT",
                "Conflicto de concurrencia al registrar la aceptación legal.",
                409,
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error inesperado al registrar aceptación legal para user_id={user_id_str}: {e}"
            )
            raise LegalError(
                "INTERNAL_ERROR",
                "Error interno al registrar la aceptación legal.",
                500,
            )

