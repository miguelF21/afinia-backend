from functools import wraps
from datetime import timezone
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
    Invalida access tokens emitidos antes de una actualización de credenciales (ej. restablecimiento de contraseña).
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
        if not user or not user.is_active or user.deleted_at is not None:
            return api_error('UNAUTHORIZED', 'Usuario inexistente o cuenta deshabilitada.', 401)

        if user.lifecycle_status == 'suspended':
            return api_error('FORBIDDEN', 'Cuenta suspendida por moderación.', 403)
        if user.lifecycle_status == 'deactivated':
            return api_error('UNAUTHORIZED', 'Cuenta desactivada.', 401)

        token_type = payload.get('type')
        if token_type is not None and token_type != 'access':
            return api_error('UNAUTHORIZED', 'Tipo de token inválido para autenticación de API.', 401)

        # Verificación de revocación por cambio de credenciales mediante huella de hash
        token_fp = payload.get('pwd_fp')
        if not token_fp or not isinstance(token_fp, str):
            return api_error('UNAUTHORIZED', 'Sesión revocada o token emitido sin huella de credenciales.', 401)

        import hashlib
        current_fp = hashlib.sha256(user.password_hash.encode('utf-8')).hexdigest()[:16]
        if token_fp != current_fp:
            return api_error('UNAUTHORIZED', 'Sesión revocada debido a un cambio de credenciales.', 401)

        # Inyectar en request context y en argumentos
        request.current_user = user
        request.jwt_payload = payload
        return f(current_user=user, *args, **kwargs)

    return decorated


def admin_required(f):
    """
    Decorador de autorización administrativa estricta en servidor (RBAC).
    Exige:
    1. Autenticación JWT válida, vigente y con huella de credenciales (pwd_fp) íntegra (@token_required).
    2. Cuenta activa en base de datos (is_active=True, deleted_at=None, lifecycle_status no suspendido/desactivado).
    3. Verificación explícita en base de datos de `user.role == 'admin'` y coherencia con el claim `role` del JWT.
    4. Registra accesos administrativos autorizados y rechazos por permisos insuficientes (403 FORBIDDEN).
    """
    @wraps(f)
    @token_required
    def decorated(current_user: User, *args, **kwargs):
        # Asegurar lectura fresca del estado y rol en base de datos
        try:
            db.session.refresh(current_user)
        except Exception:
            current_user = db.session.get(User, str(current_user.id))

        if not current_user or not current_user.is_active or current_user.deleted_at is not None:
            return api_error('UNAUTHORIZED', 'Usuario inexistente o cuenta deshabilitada.', 401)

        if current_user.lifecycle_status == 'suspended':
            return api_error('FORBIDDEN', 'Cuenta suspendida por moderación.', 403)
        if current_user.lifecycle_status == 'deactivated':
            return api_error('UNAUTHORIZED', 'Cuenta desactivada.', 401)

        jwt_payload = getattr(request, 'jwt_payload', None) or {}
        token_role = jwt_payload.get('role')

        if current_user.role != 'admin' or token_role != 'admin':
            current_app.logger.warning(
                f"[ADMIN-AUTHZ-DENIED] Acceso administrativo denegado para user_id={current_user.id} "
                f"(db_role={current_user.role}, token_role={token_role}) en {request.method} {request.path}"
            )
            return api_error(
                'FORBIDDEN',
                'Acceso denegado: se requieren privilegios de administrador.',
                403
            )

        current_app.logger.info(
            f"[ADMIN-AUDIT] Acceso administrativo autorizado: admin_user_id={current_user.id} "
            f"endpoint={request.method} {request.path}"
        )
        return f(current_user=current_user, *args, **kwargs)

    return decorated
