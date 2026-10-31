from functools import wraps
from flask import request, current_app
import jwt
from app import db
from app.models import User
from app.utils.errors import api_error
from app.utils.security import decode_access_token

def token_required(f):
    """
    Middleware / decorador para autenticación Bearer JWT conforme al contrato OpenAPI.
    Verifica firma, vigencia y estado en base de datos del usuario.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header:
            return api_error('UNAUTHORIZED', 'Cabecera Authorization ausente.', 401)

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return api_error('UNAUTHORIZED', 'Formato de cabecera inválido. Debe ser: Bearer <token>.', 401)

        token = parts[1]

        try:
            payload = decode_access_token(token, current_app.config['SECRET_KEY'])
        except jwt.ExpiredSignatureError:
            return api_error('UNAUTHORIZED', 'Token de acceso expirado.', 401)
        except (jwt.InvalidTokenError, Exception):
            return api_error('UNAUTHORIZED', 'Token de acceso inválido o corrupto.', 401)

        user_id = payload.get('sub')
        if not user_id:
            return api_error('UNAUTHORIZED', 'Token no contiene identificador de sujeto (sub).', 401)

        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return api_error('UNAUTHORIZED', 'Usuario inexistente o cuenta deshabilitada.', 401)

        if user.lifecycle_status == 'suspended':
            return api_error('FORBIDDEN', 'Cuenta suspendida por moderación.', 403)
        if user.lifecycle_status == 'deactivated':
            return api_error('UNAUTHORIZED', 'Cuenta desactivada.', 401)

        # Inyectar en request context y en argumentos
        request.current_user = user
        return f(current_user=user, *args, **kwargs)

    return decorated
