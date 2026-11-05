"""
AFINIA — Servicio de Bloqueo y Desbloqueo de Usuarios (BE-04.3.1).
==================================================================
Implementa la lógica de negocio y el protocolo transaccional compartido
para bloqueo, desbloqueo y consulta de usuarios bloqueados.
Garantiza:
- Control estricto de identidad vía JWT (blocker = current_user).
- Prohibición de autobloqueo y autodesbloqueo.
- Idempotencia en la solicitud de bloqueo.
- Protocolo transaccional de bloqueo canónico con SELECT FOR UPDATE
  sobre la tabla `users` para eliminar condiciones de carrera con mensajería.
- Compatibilidad nativa con PostgreSQL 15 y SQLite (:memory:).
"""

import uuid
import time
import hmac
import hashlib
import json
import base64
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

from flask import current_app
from sqlalchemy import or_, and_, desc
from sqlalchemy.exc import IntegrityError, OperationalError, DatabaseError

from app import db
from app.models.user import User
from app.models.block import UserBlock
from app.models.profile import Profile
from app.services.discovery_service import serialize_public_profile


class BlockError(Exception):
    """Excepción de dominio para operaciones de bloqueo y desbloqueo."""
    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _get_secret_key() -> str:
    key = current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY")
    if not key:
        return "afinia_default_cursor_secret_key"
    return str(key)


def _format_datetime_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _calculate_block_cursor_signature(created_at_iso: str, block_id: str, viewer_id: str, secret_key: str) -> str:
    msg = f"{created_at_iso}|{block_id}|{viewer_id}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]


def encode_block_cursor(created_at: datetime, block_id: str, viewer_id: str) -> str:
    secret_key = _get_secret_key()
    created_at_iso = _format_datetime_iso(created_at)
    sig = _calculate_block_cursor_signature(created_at_iso, str(block_id), str(viewer_id), secret_key)
    payload = {
        "c": created_at_iso,
        "b": str(block_id),
        "v": str(viewer_id),
        "s": sig
    }
    raw_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw_bytes).decode('ascii')


def decode_block_cursor(cursor_str: str, expected_viewer_id: str) -> Tuple[datetime, str]:
    if not cursor_str or not isinstance(cursor_str, str):
        raise BlockError("VALIDATION_ERROR", "Cursor de paginación inválido.", 422)
    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.encode('ascii'))
        payload = json.loads(raw_bytes.decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError("Payload no es dict")
        required_keys = {"c", "b", "v", "s"}
        if not required_keys.issubset(payload.keys()):
            raise ValueError("Claves incompletas")
        if str(payload["v"]) != str(expected_viewer_id):
            raise BlockError("VALIDATION_ERROR", "El cursor no pertenece al usuario solicitante.", 422)
        secret_key = _get_secret_key()
        expected_sig = _calculate_block_cursor_signature(
            payload["c"], str(payload["b"]), str(payload["v"]), secret_key
        )
        if not hmac.compare_digest(str(payload["s"]), expected_sig):
            raise BlockError("VALIDATION_ERROR", "Cursor de paginación inválido o alterado.", 422)

        created_at = datetime.fromisoformat(payload["c"])
        block_id = str(payload["b"])
        return created_at, block_id
    except BlockError:
        raise
    except Exception:
        raise BlockError("VALIDATION_ERROR", "Cursor de paginación inválido o corrupto.", 422)


def lock_user_pair_for_update(uid_a: str, uid_b: str) -> None:
    """
    Protocolo transaccional canónico compartido:
    Adquiere bloqueos de fila exclusivos (SELECT FOR UPDATE) sobre la tabla `users`
    en orden estrictamente determinista (alfabético por UUID).
    
    Garantiza:
    1. Prevención matemática absoluta de deadlocks entre transacciones concurrentes
       que involucren al mismo par de usuarios.
    2. Serialización estricta entre operaciones de bloqueo, desbloqueo y mensajería
       a través de múltiples procesos independientes de Flask y conexiones PostgreSQL.
    """
    if not uid_a or not uid_b or uid_a == uid_b:
        return

    low_id, high_id = (uid_a, uid_b) if uid_a < uid_b else (uid_b, uid_a)

    # Bloquear ambas entidades en orden canónico estricto mediante una sola consulta ordenada
    db.session.query(User.id).filter(
        User.id.in_([low_id, high_id])
    ).order_by(User.id.asc()).with_for_update().all()


def block_user(current_user: User, target_user_id_raw: Any) -> Dict[str, Any]:
    """
    PUT /api/v1/users/{userId}/block
    Bloquea a otro usuario de forma inmediata y bidireccional.
    Operación idempotente conforme a OpenAPI v1.
    Retorna {'data': {'blocked_user_id': UUID, 'blocked': True}}.
    """
    if not target_user_id_raw or not isinstance(target_user_id_raw, str):
        raise BlockError("BAD_REQUEST", "Identificador de usuario inválido.", 400)

    try:
        target_uuid = str(uuid.UUID(str(target_user_id_raw).strip()))
    except (ValueError, AttributeError):
        raise BlockError("BAD_REQUEST", "El identificador del usuario debe ser un UUID válido.", 400)

    if str(current_user.id) == target_uuid:
        raise BlockError("BAD_REQUEST", "No puedes bloquearte a ti mismo.", 400)

    # Validar existencia física del usuario objetivo
    target_user = User.query.filter_by(id=target_uuid).first()
    if not target_user or target_user.deleted_at is not None:
        raise BlockError("NOT_FOUND", "Usuario objetivo no encontrado.", 404)

    # Ejecutar protocolo transaccional canónico
    try:
        lock_user_pair_for_update(str(current_user.id), target_uuid)

        # Verificar si el bloqueo ya fue registrado previamente (idempotencia)
        existing = UserBlock.query.filter_by(
            blocker_user_id=str(current_user.id),
            blocked_user_id=target_uuid
        ).first()

        if existing:
            # Idempotente: retornar éxito sin duplicar inserción
            return {
                "blocked_user_id": target_uuid,
                "blocked": True
            }

        # Registrar nuevo bloqueo
        new_block = UserBlock(
            id=str(uuid.uuid4()),
            blocker_user_id=str(current_user.id),
            blocked_user_id=target_uuid,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(new_block)
        db.session.commit()

        return {
            "blocked_user_id": target_uuid,
            "blocked": True
        }

    except (IntegrityError, OperationalError, DatabaseError):
        try:
            db.session.rollback()
        except Exception:
            pass
        # En caso de colisión simultánea que supere la verificación previa, reintentar lectura idempotente
        for _ in range(5):
            existing = UserBlock.query.filter_by(
                blocker_user_id=str(current_user.id),
                blocked_user_id=target_uuid
            ).first()
            if existing:
                return {
                    "blocked_user_id": target_uuid,
                    "blocked": True
                }
            time.sleep(0.03)

        # Si no existía y el error fue colisión transaccional concurrente, reintentar inserción una vez
        try:
            new_block = UserBlock(
                id=str(uuid.uuid4()),
                blocker_user_id=str(current_user.id),
                blocked_user_id=target_uuid,
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(new_block)
            db.session.commit()
            return {
                "blocked_user_id": target_uuid,
                "blocked": True
            }
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            existing = UserBlock.query.filter_by(
                blocker_user_id=str(current_user.id),
                blocked_user_id=target_uuid
            ).first()
            if existing:
                return {
                    "blocked_user_id": target_uuid,
                    "blocked": True
                }
        raise BlockError("BAD_REQUEST", "Error de integridad al registrar el bloqueo.", 400)
    except BlockError:
        try:
            db.session.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error(f"Error inesperado al bloquear usuario {target_uuid}: {e}")
        raise


def unblock_user(current_user: User, target_user_id_raw: Any) -> None:
    """
    DELETE /api/v1/users/{userId}/block
    Desbloquea al usuario objetivo si existe un bloqueo activo emitido por current_user.
    Retorna 204 No Content.
    """
    if not target_user_id_raw or not isinstance(target_user_id_raw, str):
        raise BlockError("BAD_REQUEST", "Identificador de usuario inválido.", 400)

    try:
        target_uuid = str(uuid.UUID(str(target_user_id_raw).strip()))
    except (ValueError, AttributeError):
        raise BlockError("BAD_REQUEST", "El identificador del usuario debe ser un UUID válido.", 400)

    if str(current_user.id) == target_uuid:
        raise BlockError("BAD_REQUEST", "No puedes desbloquearte a ti mismo.", 400)

    # Validar existencia física del usuario objetivo
    target_user = User.query.filter_by(id=target_uuid).first()
    if not target_user:
        raise BlockError("NOT_FOUND", "Usuario objetivo no encontrado.", 404)

    try:
        # Protocolo transaccional canónico
        lock_user_pair_for_update(str(current_user.id), target_uuid)

        # Buscar bloqueo emitido exclusivamente por current_user hacia target_uuid
        existing = UserBlock.query.filter_by(
            blocker_user_id=str(current_user.id),
            blocked_user_id=target_uuid
        ).first()

        if not existing:
            raise BlockError("NOT_FOUND", "No existe un bloqueo activo hacia este usuario.", 404)

        db.session.delete(existing)
        db.session.commit()
        return None

    except BlockError:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado al desbloquear usuario {target_uuid}: {e}")
        raise


def get_my_blocks(
    current_user: User,
    limit_raw: Any = 20,
    cursor_raw: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """
    GET /api/v1/users/me/blocks
    Retorna la lista paginada de usuarios bloqueados por el usuario autenticado.
    Cada elemento se serializa según el esquema OpenAPI PublicProfile.
    """
    try:
        limit = int(limit_raw) if limit_raw is not None else 20
    except (ValueError, TypeError):
        raise BlockError("VALIDATION_ERROR", "El parámetro 'limit' debe ser un número entero.", 422)

    if limit < 1 or limit > 50:
        raise BlockError("VALIDATION_ERROR", "El parámetro 'limit' debe estar comprendido entre 1 y 50.", 422)

    cursor_dt: Optional[datetime] = None
    cursor_id: Optional[str] = None
    if cursor_raw:
        cursor_dt, cursor_id = decode_block_cursor(cursor_raw, str(current_user.id))

    query = UserBlock.query.filter(UserBlock.blocker_user_id == str(current_user.id))

    if cursor_dt and cursor_id:
        query = query.filter(
            or_(
                UserBlock.created_at < cursor_dt,
                and_(UserBlock.created_at == cursor_dt, UserBlock.id < cursor_id)
            )
        )

    # Orden determinista: created_at DESC, id DESC
    query = query.order_by(desc(UserBlock.created_at), desc(UserBlock.id))

    blocks_page = query.limit(limit + 1).all()

    has_more = len(blocks_page) > limit
    results = blocks_page[:limit]

    items: List[Dict[str, Any]] = []
    for b in results:
        blocked_user = User.query.filter_by(id=b.blocked_user_id).first()
        if blocked_user and blocked_user.profile:
            items.append(serialize_public_profile(blocked_user.profile))
        elif blocked_user:
            items.append({
                "user_id": blocked_user.id,
                "first_name": "Usuario",
                "age": 18,
                "gender": "prefiero_no_indicar",
                "city": None,
                "bio": None,
                "photos": [],
                "relationship_goal": None
            })

    next_cursor = None
    if has_more and results:
        last_block = results[-1]
        next_cursor = encode_block_cursor(last_block.created_at, last_block.id, str(current_user.id))

    return items, next_cursor, has_more
