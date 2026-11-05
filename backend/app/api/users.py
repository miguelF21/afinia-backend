"""
AFINIA — API de Usuarios Públicos (BE-03.1).
============================================
Implementa las rutas públicas de usuarios bajo /api/v1/users conforme a OpenAPI v1.
"""

from flask import Blueprint, request, current_app, Response
from app.auth.middleware import token_required
from app.utils.errors import api_response, api_error
from app.services.discovery_service import get_public_profile_by_user_id, DiscoveryError
from app.services.block_service import (
    block_user,
    unblock_user,
    get_my_blocks,
    BlockError
)
from app.services.report_service import (
    create_user_report,
    ReportError
)

bp = Blueprint('users', __name__)


@bp.route('/me/blocks', methods=['GET'])
@token_required
def get_my_blocks_endpoint(current_user):
    """
    GET /api/v1/users/me/blocks
    Consulta la lista de usuarios bloqueados por el usuario autenticado (con paginación por cursor).
    """
    limit_raw = request.args.get('limit', 20)
    cursor_raw = request.args.get('cursor', None)
    try:
        items, next_cursor, has_more = get_my_blocks(current_user, limit_raw=limit_raw, cursor_raw=cursor_raw)
        from flask import jsonify
        return jsonify({
            "data": {
                "items": items
            },
            "meta": {
                "next_cursor": next_cursor,
                "has_more": has_more
            }
        }), 200
    except BlockError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_my_blocks_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar usuarios bloqueados.', 500)


@bp.route('/<userId>/block', methods=['PUT'])
@token_required
def block_user_endpoint(current_user, userId):
    """
    PUT /api/v1/users/{userId}/block
    Bloquea a otro usuario de forma inmediata y bidireccional.
    Idempotente conforme a OpenAPI v1.
    """
    try:
        receipt = block_user(current_user, userId)
        return api_response(receipt, status_code=200)
    except BlockError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en block_user_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al bloquear usuario.', 500)


@bp.route('/<userId>/block', methods=['DELETE'])
@token_required
def unblock_user_endpoint(current_user, userId):
    """
    DELETE /api/v1/users/{userId}/block
    Desbloquea a un usuario previamente bloqueado por el solicitante.
    Retorna 204 No Content.
    """
    try:
        unblock_user(current_user, userId)
        return Response(status=204)
    except BlockError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en unblock_user_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al desbloquear usuario.', 500)


@bp.route('/<userId>', methods=['GET'])
@token_required
def get_user_public_profile(current_user, userId):
    """
    GET /api/v1/users/{userId}
    Retorna el perfil público visible de un usuario (PublicProfile).
    Aplica verificación de bloqueos bidireccionales, cuentas activas y exclusión de datos privados.
    """
    try:
        profile_data = get_public_profile_by_user_id(current_user, userId)
        return api_response(profile_data, status_code=200)
    except DiscoveryError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_user_public_profile: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar el perfil del usuario.', 500)


@bp.route('/<userId>/reports', methods=['POST'])
@token_required
def report_user_endpoint(current_user, userId):
    """
    POST /api/v1/users/{userId}/reports
    Registra una denuncia confidencial contra un perfil conforme a OpenAPI v1.
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'El cuerpo de la petición debe ser JSON válido.', 400)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error('VALIDATION_ERROR', 'El cuerpo de la petición debe ser un objeto JSON.', 422)

    try:
        receipt = create_user_report(current_user, userId, payload)
        return api_response(receipt, status_code=201)
    except ReportError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en report_user_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al registrar el reporte.', 500)

