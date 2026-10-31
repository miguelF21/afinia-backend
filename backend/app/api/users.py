"""
AFINIA — API de Usuarios Públicos (BE-03.1).
============================================
Implementa las rutas públicas de usuarios bajo /api/v1/users conforme a OpenAPI v1.
"""

from flask import Blueprint, current_app
from app.auth.middleware import token_required
from app.utils.errors import api_response, api_error
from app.services.discovery_service import get_public_profile_by_user_id, DiscoveryError

bp = Blueprint('users', __name__)


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
