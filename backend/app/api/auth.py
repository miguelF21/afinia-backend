from flask import Blueprint, request, current_app, Response
from sqlalchemy.exc import DatabaseError, OperationalError, IntegrityError
from app import db
from app.auth.middleware import token_required
from app.utils.errors import api_response, api_error
from app.utils.rate_limit import rate_limit, get_trusted_client_ip
from app.services.auth_service import (
    register_user, login_user, refresh_session, logout_session,
    serialize_user_brief, verify_email_token, resend_email_verification,
    AuthError
)

bp = Blueprint('auth', __name__)

def _is_mobile_client() -> bool:
    """
    Indica si el cliente declara ser una plataforma móvil nativa.
    NOTA DE SEGURIDAD: Esta cabecera no confiere privilegios ni sustituye la autenticación.
    Solo selecciona el medio de transporte (JSON body) cuando no existe transporte por cookie.
    """
    platform_header = request.headers.get('X-Client-Platform', '').lower()
    if platform_header == 'mobile':
        return True
    ua = request.headers.get('User-Agent', '')
    return any(agent in ua for agent in ('Capacitor', 'Cordova', 'okhttp', 'CFNetwork'))

def _validate_csrf_for_cookie() -> tuple[bool, str | None]:
    """
    Protección CSRF para peticiones autenticadas mediante cookie (Web).
    Verifica que Origin o Referer coincidan estrictamente con los orígenes autorizados en CORS_ORIGINS.
    """
    if not request.cookies.get('refresh_token'):
        return True, None

    origin = request.headers.get('Origin')
    referer = request.headers.get('Referer')
    allowed_origins = current_app.config.get('CORS_ORIGINS', [])

    if origin:
        if origin in allowed_origins:
            return True, None
        return False, f"Origen no autorizado para operaciones con credenciales de cookie."

    if referer:
        if any(referer.startswith(allowed) for allowed in allowed_origins):
            return True, None
        return False, f"Referente no autorizado para operaciones con credenciales de cookie."

    # En pruebas unitarias se tolera la omisión de Origin/Referer salvo prueba explícita
    if current_app.config.get('TESTING'):
        return True, None

    return False, "Cabecera Origin o Referer requerida en peticiones autenticadas por cookie."

@bp.route('/register', methods=['POST'])
@rate_limit(limit=10, window_seconds=60, key_prefix='register')
def register():
    """
    POST /api/v1/auth/register
    Registra una cuenta de usuario pendiente de onboarding junto a la aceptación
    de las versiones vigentes de términos y privacidad.
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'La solicitud debe tener Content-Type application/json.', 400)

    data = request.get_json(silent=True)
    if data is None:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud no contiene un JSON válido.', 400)

    try:
        user_brief = register_user(data, ip_address=get_trusted_client_ip())
        return api_response(user_brief, status_code=201)
    except AuthError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en registro: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al procesar el registro.', 500)

@bp.route('/login', methods=['POST'])
@rate_limit(limit=15, window_seconds=60, key_prefix='login')
def login():
    """
    POST /api/v1/auth/login
    Inicia sesión verificando credenciales, emitiendo JWT de acceso (900s)
    y gestionando el refresh token en cookie HttpOnly (Web) o en cuerpo JSON (Móvil).
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'La solicitud debe tener Content-Type application/json.', 400)

    data = request.get_json(silent=True)
    if data is None:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud no contiene un JSON válido.', 400)

    user_agent = request.headers.get('User-Agent', '')
    client_ip = get_trusted_client_ip()

    try:
        access_token, raw_refresh, user_brief = login_user(data, user_agent=user_agent, ip_address=client_ip)

        session_data = {
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', 900),
            'user': user_brief
        }

        # Regla de seguridad: Si la solicitud proviene de web (o no es móvil explícito),
        # el refresh token se transporta ÚNICAMENTE en cookie HttpOnly y se omite del JSON.
        is_mobile = _is_mobile_client()
        if is_mobile:
            session_data['refresh_token'] = raw_refresh

        response = api_response(session_data, status_code=200)

        # En web (clientes no móviles) se almacena en cookie HttpOnly segura
        if not is_mobile:
            secure_cookie = current_app.config.get('SESSION_COOKIE_SECURE', False)
            response.set_cookie(
                'refresh_token',
                raw_refresh,
                max_age=current_app.config.get('REFRESH_TOKEN_EXPIRES_DAYS', 30) * 86400,
                httponly=True,
                samesite='Lax',
                secure=secure_cookie,
                path='/api/v1/auth'
            )

        return response
    except AuthError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en login: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al procesar el inicio de sesión.', 500)

@bp.route('/refresh', methods=['POST'])
@rate_limit(limit=30, window_seconds=60, key_prefix='refresh')
def refresh():
    """
    POST /api/v1/auth/refresh
    Renueva la sesión rotando atómicamente el refresh token y emitiendo un nuevo access token.
    Aplica protección CSRF en solicitudes autenticadas por cookie.
    """
    # 1. Validación CSRF para transporte web con cookies
    is_valid_csrf, csrf_err = _validate_csrf_for_cookie()
    if not is_valid_csrf:
        return api_error('FORBIDDEN', csrf_err, 403)

    # 2. Identificar procedencia del refresh token
    # Si viene en cookie, se trata estrictamente de una sesión web
    cookie_token = request.cookies.get('refresh_token')
    body_token = None
    if request.is_json:
        body = request.get_json(silent=True) or {}
        body_token = body.get('refresh_token')

    used_cookie = bool(cookie_token)
    raw_refresh = cookie_token if used_cookie else body_token

    if not raw_refresh:
        return api_error('UNAUTHORIZED', 'Sesión de renovación ausente o no provista.', 401)

    user_agent = request.headers.get('User-Agent', '')
    client_ip = get_trusted_client_ip()

    try:
        new_access, new_refresh, user_brief = refresh_session(
            raw_refresh_token=raw_refresh,
            user_agent=user_agent,
            ip_address=client_ip
        )

        session_data = {
            'access_token': new_access,
            'token_type': 'Bearer',
            'expires_in': current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', 900),
            'user': user_brief
        }

        # REGLA DE SEGURIDAD ESTRICTA: Si la sesión utilizó cookie, NUNCA revelar el nuevo
        # refresh token en el cuerpo JSON, impidiendo exfiltración o almacenamiento en localStorage.
        if not used_cookie and _is_mobile_client():
            session_data['refresh_token'] = new_refresh

        response = api_response(session_data, status_code=200)

        # En web (si se utilizó cookie), se actualiza la cookie HttpOnly
        if used_cookie or not _is_mobile_client():
            secure_cookie = current_app.config.get('SESSION_COOKIE_SECURE', False)
            response.set_cookie(
                'refresh_token',
                new_refresh,
                max_age=current_app.config.get('REFRESH_TOKEN_EXPIRES_DAYS', 30) * 86400,
                httponly=True,
                samesite='Lax',
                secure=secure_cookie,
                path='/api/v1/auth'
            )

        return response
    except AuthError as e:
        err_res = api_error(e.code, e.message, status_code=e.status_code, details=e.details)
        if used_cookie:
            err_res.delete_cookie('refresh_token', path='/api/v1/auth')
        return err_res
    except Exception as e:
        current_app.logger.error(f"Error inesperado en refresh: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al renovar la sesión.', 500)

@bp.route('/logout', methods=['POST'])
@token_required
def logout(current_user):
    """
    POST /api/v1/auth/logout
    Cierra la sesión activa revocando el refresh token asociado y eliminando la cookie web.
    """
    is_valid_csrf, csrf_err = _validate_csrf_for_cookie()
    if not is_valid_csrf:
        return api_error('FORBIDDEN', csrf_err, 403)

    raw_refresh = request.cookies.get('refresh_token')
    if not raw_refresh and request.is_json:
        body = request.get_json(silent=True) or {}
        raw_refresh = body.get('refresh_token')

    try:
        logout_session(raw_refresh_token=raw_refresh, user_id=current_user.id)
    except Exception as e:
        current_app.logger.error(f"Error en logout_session: {str(e)}")

    secure_cookie = current_app.config.get('SESSION_COOKIE_SECURE', False)
    response = Response(status=204)
    response.delete_cookie(
        'refresh_token',
        path='/api/v1/auth',
        httponly=True,
        samesite='Lax',
        secure=secure_cookie
    )
    return response

@bp.route('/me', methods=['GET'])
@token_required
def get_me(current_user):
    """
    GET /api/v1/auth/me
    Devuelve los datos esenciales de la cuenta autenticada (UserBrief)
    para rehidratar el estado en el frontend sin exponer información sensible.
    """
    return api_response(serialize_user_brief(current_user), status_code=200)

@bp.route('/verify-email', methods=['POST'])
@rate_limit(limit=15, window_seconds=60, key_prefix='verify_email')
def verify_email():
    """
    POST /api/v1/auth/verify-email
    Verifica la dirección de correo electrónico mediante un token de un solo uso.
    Respuesta exitosa: HTTP 204 No Content (sin cuerpo).
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'La solicitud debe tener Content-Type application/json.', 400)

    data = request.get_json(silent=True)
    if data is None:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud no contiene un JSON válido.', 400)

    if not isinstance(data, dict):
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    # OpenAPI: additionalProperties: false, required: [token]
    extra_keys = set(data.keys()) - {'token'}
    if extra_keys:
        return api_error('BAD_REQUEST', f'Campos no permitidos en la solicitud: {", ".join(sorted(extra_keys))}.', 400)

    if 'token' not in data or data['token'] is None:
        return api_error('VALIDATION_ERROR', 'El campo token es obligatorio.', 422)

    raw_token = str(data['token'])

    try:
        verify_email_token(raw_token)
        return Response(status=204)
    except AuthError as e:
        db.session.rollback()
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except (DatabaseError, OperationalError, IntegrityError) as e:
        db.session.rollback()
        current_app.logger.warning(f"Conflicto de concurrencia en verify_email: {str(e)}")
        try:
            import hashlib
            from app.models.auth import EmailVerificationToken
            token_hash = hashlib.sha256(raw_token.strip().encode('utf-8')).hexdigest()
            consumed = EmailVerificationToken.query.filter(
                EmailVerificationToken.token_hash == token_hash,
                EmailVerificationToken.consumed_at.isnot(None)
            ).first()
            if consumed:
                return api_error('CONFLICT', 'El token de verificación ya ha sido utilizado.', 409)
        except Exception:
            pass
        return api_error('CONFLICT', 'Conflicto de concurrencia al procesar el token. Intente nuevamente.', 409)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado en verify_email: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al procesar la verificación de correo.', 500)

@bp.route('/resend-verification', methods=['POST'])
@token_required
@rate_limit(limit=5, window_seconds=60, key_prefix='resend_verification')
def resend_verification(current_user):
    """
    POST /api/v1/auth/resend-verification
    Reenvía el correo de verificación para el usuario autenticado (Bearer JWT requerido).
    Respuesta exitosa: HTTP 202 Accepted {"data": {"status": "accepted"}}.
    """
    try:
        result = resend_email_verification(current_user)
        return api_response(result, status_code=202)
    except AuthError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en resend_verification: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al solicitar el reenvío de verificación.', 500)

