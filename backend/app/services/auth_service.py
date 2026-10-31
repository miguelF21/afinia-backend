import uuid
import secrets
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from flask import current_app
from app import db
from app.models import User, RefreshToken, EmailVerificationToken, LegalConsent, Profile
from app.utils.security import (
    hash_password, verify_password,
    create_access_token, generate_refresh_token, hash_refresh_token,
    normalize_email, validate_email_format, validate_password_policy
)

class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: dict = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

def serialize_user_brief(user: User) -> dict:
    """Serializa un objeto User al esquema OpenAPI UserBrief utilizando la regla centralizada de onboarding."""
    from app.services.profile_service import is_onboarding_complete, sync_user_lifecycle_status
    sync_user_lifecycle_status(user)
    return {
        'id': user.id,
        'email': user.email,
        'onboarding_complete': is_onboarding_complete(user),
        'email_verified': bool(user.email_verified),
        'status': user.lifecycle_status
    }

def register_user(data: dict, ip_address: str = None) -> dict:
    """
    Registra una cuenta de usuario con status inicial 'pending_profile' y rol 'user',
    registrando atómicamente la aceptación de las versiones legales vigentes.
    """
    if not isinstance(data, dict):
        raise AuthError('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    # Prevenir mass assignment: solo se admiten los campos de RegisterInput
    allowed_keys = {'email', 'password', 'accept_terms_version', 'accept_privacy_version'}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        raise AuthError(
            'BAD_REQUEST',
            f'Campos no permitidos en la solicitud: {", ".join(sorted(extra_keys))}.',
            400
        )

    # Validar presencia de campos obligatorios
    for req_field in ('email', 'password', 'accept_terms_version', 'accept_privacy_version'):
        if req_field not in data or data[req_field] is None:
            raise AuthError('VALIDATION_ERROR', f'El campo {req_field} es obligatorio.', 422)

    email = normalize_email(str(data['email']))
    password = str(data['password'])
    terms_version = str(data['accept_terms_version']).strip()
    privacy_version = str(data['accept_privacy_version']).strip()

    # Validar formato y longitud de email
    if not validate_email_format(email):
        raise AuthError('VALIDATION_ERROR', 'Formato de correo electrónico inválido.', 422)

    # Validar longitud y política de contraseña (12-128 caracteres)
    is_valid_pwd, pwd_error = validate_password_policy(password)
    if not is_valid_pwd:
        raise AuthError('VALIDATION_ERROR', pwd_error, 422)

    # Validar versiones legales vigentes
    active_terms = current_app.config.get('LEGAL_TERMS_VERSION', 'v1-draft')
    active_privacy = current_app.config.get('LEGAL_PRIVACY_VERSION', 'v1-draft')

    if terms_version != active_terms or privacy_version != active_privacy:
        raise AuthError(
            'BAD_REQUEST',
            'Las versiones de términos o privacidad aceptadas no coinciden con las versiones vigentes.',
            400,
            details={
                'required_terms_version': active_terms,
                'required_privacy_version': active_privacy
            }
        )

    # Validar duplicados de correo
    if User.query.filter_by(email=email).first():
        raise AuthError('CONFLICT', 'El correo electrónico ya se encuentra registrado.', 409)

    # Persistencia atómica de usuario y consentimientos
    pwd_hash = hash_password(password)
    new_user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=pwd_hash,
        role='user',
        lifecycle_status='pending_profile',
        email_verified=False,
        is_active=True
    )
    db.session.add(new_user)

    consent_terms = LegalConsent(
        user_id=new_user.id,
        document_type='terms_of_service',
        document_version=terms_version,
        ip_address=ip_address
    )
    consent_privacy = LegalConsent(
        user_id=new_user.id,
        document_type='privacy_policy',
        document_version=privacy_version,
        ip_address=ip_address
    )
    db.session.add_all([consent_terms, consent_privacy])

    # Generar token de verificación de uso único (al menos 256 bits de entropía)
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    hours = current_app.config.get('EMAIL_VERIFICATION_TOKEN_HOURS', 24)
    now = datetime.now(timezone.utc)
    verif_token = EmailVerificationToken(
        id=str(uuid.uuid4()),
        user_id=new_user.id,
        token_hash=token_hash,
        created_at=now,
        expires_at=now + timedelta(hours=hours)
    )
    db.session.add(verif_token)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise AuthError('CONFLICT', 'Error de concurrencia al registrar el usuario.', 409)

    # Despachar correo transaccional tras la confirmación exitosa de usuario y consentimientos
    from app.services.email_service import email_service
    try:
        email_service.send_verification_email(new_user.email, raw_token)
    except Exception as e:
        current_app.logger.error(f"Error al enviar correo de verificación inicial a {new_user.email}: {str(e)}")
        # La cuenta permanece en pending_profile y es recuperable mediante reenvío

    return serialize_user_brief(new_user)

def login_user(data: dict, user_agent: str = None, ip_address: str = None) -> tuple[str, str, dict]:
    """
    Autentica credenciales y emite una sesión compuesta por un JWT de acceso (900s)
    y un token criptográfico de renovación rotativo.
    """
    if not isinstance(data, dict):
        raise AuthError('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    allowed_keys = {'email', 'password'}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        raise AuthError('BAD_REQUEST', f'Campos no permitidos: {", ".join(sorted(extra_keys))}.', 400)

    email = normalize_email(str(data.get('email', '')))
    password = str(data.get('password', ''))

    if not email or not password:
        raise AuthError('UNAUTHORIZED', 'Credenciales inválidas.', 401)

    user = User.query.filter_by(email=email).first()

    # Protección contra enumeración de cuentas: mensaje uniforme y verificación segura
    if not user or not verify_password(user.password_hash, password):
        raise AuthError('UNAUTHORIZED', 'Credenciales inválidas.', 401)

    if not user.is_active:
        raise AuthError('UNAUTHORIZED', 'La cuenta se encuentra inactiva.', 401)

    # Validar ciclo de vida
    if user.lifecycle_status == 'suspended':
        raise AuthError('FORBIDDEN', 'La cuenta se encuentra suspendida temporalmente por moderación.', 403)
    if user.lifecycle_status == 'deactivated':
        raise AuthError('UNAUTHORIZED', 'La cuenta ha sido desactivada.', 401)

    # Emisión de tokens
    expires_in = current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', 900)
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        secret_key=current_app.config['SECRET_KEY'],
        expires_in=expires_in
    )

    raw_refresh = generate_refresh_token()
    token_hash = hash_refresh_token(raw_refresh)
    days = current_app.config.get('REFRESH_TOKEN_EXPIRES_DAYS', 30)
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)

    refresh_obj = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address
    )
    db.session.add(refresh_obj)
    db.session.commit()

    return access_token, raw_refresh, serialize_user_brief(user)

def refresh_session(raw_refresh_token: str, user_agent: str = None, ip_address: str = None) -> tuple[str, str, dict]:
    """
    Renueva la sesión de manera segura con rotación atómica y detección de reutilización.
    """
    if not raw_refresh_token:
        raise AuthError('UNAUTHORIZED', 'Sesión de renovación ausente o no provista.', 401)

    token_hash = hash_refresh_token(raw_refresh_token)

    # Uso de SELECT FOR UPDATE en PostgreSQL para prevenir condiciones de carrera simultáneas
    query = RefreshToken.query.filter_by(token_hash=token_hash)
    if db.engine.dialect.name == 'postgresql':
        query = query.with_for_update()

    token_record = query.first()

    if not token_record:
        raise AuthError('UNAUTHORIZED', 'Sesión de renovación inválida.', 401)

    now = datetime.now(timezone.utc)

    # Detección de reutilización (Token Reuse Detection) vs Reintento concurrente legítimo
    if token_record.revoked_at is not None:
        rev_at = token_record.revoked_at
        if rev_at.tzinfo is None:
            rev_at = rev_at.replace(tzinfo=timezone.utc)

        revocation_age = (now - rev_at).total_seconds()
        concurrency_window = current_app.config.get('REFRESH_CONCURRENCY_WINDOW_SECONDS', 15)

        if revocation_age <= concurrency_window:
            # Reintento concurrente legítimo / condición de carrera en vuelo:
            # Se rechaza la solicitud concurrente sin invalidar la nueva sesión ni otras sesiones legítimas.
            raise AuthError(
                'UNAUTHORIZED',
                'La sesión se encuentra en proceso de rotación o ya ha sido actualizada. Utiliza el nuevo token.',
                401
            )
        else:
            # Reutilización sospechosa tardía: posible compromiso o ataque de repetición.
            # Se revoca inmediatamente todo el árbol de sesiones activas del usuario como contención.
            RefreshToken.query.filter(
                RefreshToken.user_id == token_record.user_id,
                RefreshToken.revoked_at.is_(None)
            ).update({'revoked_at': now}, synchronize_session=False)
            db.session.commit()
            raise AuthError('UNAUTHORIZED', 'Sesión revocada o comprometida. Inicia sesión nuevamente.', 401)

    # Validar expiración
    # Asegurar que expires_at tenga zona horaria UTC si viene naive
    exp = token_record.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    if exp < now:
        token_record.revoked_at = now
        db.session.commit()
        raise AuthError('UNAUTHORIZED', 'Sesión de renovación expirada.', 401)

    user = db.session.get(User, token_record.user_id)
    if not user or not user.is_active or user.lifecycle_status in ('suspended', 'deactivated'):
        token_record.revoked_at = now
        db.session.commit()
        raise AuthError('FORBIDDEN', 'La cuenta no tiene acceso para renovar sesiones.', 403)

    # Rotación atómica: revocar el token usado y emitir uno nuevo
    token_record.revoked_at = now

    new_raw_refresh = generate_refresh_token()
    new_hash = hash_refresh_token(new_raw_refresh)
    days = current_app.config.get('REFRESH_TOKEN_EXPIRES_DAYS', 30)
    new_expires = now + timedelta(days=days)

    new_token_record = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=new_hash,
        expires_at=new_expires,
        user_agent=user_agent,
        ip_address=ip_address
    )
    db.session.add(new_token_record)

    expires_in = current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', 900)
    new_access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        secret_key=current_app.config['SECRET_KEY'],
        expires_in=expires_in
    )

    db.session.commit()
    return new_access_token, new_raw_refresh, serialize_user_brief(user)

def logout_session(raw_refresh_token: str = None, user_id: str = None) -> None:
    """Revoca la sesión renovable activa correspondiente."""
    if raw_refresh_token:
        token_hash = hash_refresh_token(raw_refresh_token)
        token_record = RefreshToken.query.filter_by(token_hash=token_hash, revoked_at=None).first()
        if token_record:
            token_record.revoked_at = datetime.now(timezone.utc)
            db.session.commit()
            return

    if user_id:
        # Revocación de la sesión activa más reciente si no se envió refresh_token explícito
        latest = (
            RefreshToken.query
            .filter_by(user_id=user_id, revoked_at=None)
            .order_by(RefreshToken.created_at.desc())
            .first()
        )
        if latest:
            latest.revoked_at = datetime.now(timezone.utc)
            db.session.commit()

def _as_utc(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

_verify_email_mutex = threading.Lock()
_resend_email_mutex = threading.Lock()

def verify_email_token(raw_token: str) -> None:
    """
    POST /api/v1/auth/verify-email
    Valida y consume atómicamente un token de verificación de correo electrónico.
    Si la verificación completa todos los requisitos de onboarding, activa la cuenta.
    Coordina transacciones entre procesos independientes mediante SELECT FOR UPDATE
    bloqueando primero la fila de usuario para evitar deadlocks interproceso.
    """
    if not raw_token or not isinstance(raw_token, str):
        raise AuthError('VALIDATION_ERROR', 'El token de verificación es obligatorio y debe ser una cadena válida.', 422)

    cleaned_token = raw_token.strip()
    if not cleaned_token:
        raise AuthError('VALIDATION_ERROR', 'El token de verificación no puede estar vacío.', 422)

    with _verify_email_mutex:
        token_hash = hashlib.sha256(cleaned_token.encode('utf-8')).hexdigest()
        now = datetime.now(timezone.utc)

        # 1. Obtener user_id asociado al token para ordenar los bloqueos consistentemente
        token_meta = (
            db.session.query(EmailVerificationToken.user_id)
            .filter(EmailVerificationToken.token_hash == token_hash)
            .first()
        )

        if not token_meta:
            raise AuthError('VALIDATION_ERROR', 'Token de verificación no válido o no encontrado.', 422)

        user_id = token_meta[0]

        # 2. Bloqueo pesimista coherente por usuario en PostgreSQL:
        # Tanto verify_email_token como resend_email_verification bloquean primero la fila de User (FOR UPDATE).
        # Esto serializa las operaciones sobre el mismo usuario a nivel de BD, garantizando que procesos
        # independientes no entren en condiciones de carrera ni provoquen bloqueos mutuos (deadlocks).
        user = User.query.filter_by(id=user_id).with_for_update().first()
        if not user or not user.is_active:
            raise AuthError('VALIDATION_ERROR', 'Usuario asociado al token no encontrado o inactivo.', 422)

        if user.lifecycle_status in ('suspended', 'deactivated'):
            # OpenAPI v1 solo admite 204, 400, 409, 422 y 429 para /verify-email.
            # Reportamos 409 CONFLICT ("Conflicto de estado") para cumplir estrictamente el contrato
            # sin filtrar información privada innecesaria sobre sanciones o motivos de la cuenta.
            raise AuthError('CONFLICT', 'No es posible verificar la cuenta debido a un conflicto con su estado actual.', 409)

        # 3. Bloqueo pesimista de fila del token dentro de la transacción
        token_record = (
            EmailVerificationToken.query
            .filter_by(token_hash=token_hash)
            .with_for_update()
            .first()
        )

        if not token_record:
            raise AuthError('VALIDATION_ERROR', 'Token de verificación no válido o no encontrado.', 422)

        if token_record.consumed_at is not None:
            raise AuthError('CONFLICT', 'El token de verificación ya ha sido utilizado.', 409)

        if token_record.revoked_at is not None:
            raise AuthError('VALIDATION_ERROR', 'El token de verificación ha sido revocado. Solicite uno nuevo.', 422)

        if _as_utc(token_record.expires_at) < now:
            raise AuthError('VALIDATION_ERROR', 'El token de verificación ha expirado. Solicite uno nuevo.', 422)

        if user.email_verified:
            token_record.consumed_at = now
            db.session.commit()
            raise AuthError('CONFLICT', 'El correo electrónico ya ha sido verificado anteriormente.', 409)

        # Consumo atómico del token y marcación de verificación
        token_record.consumed_at = now
        user.email_verified = True

        # Sincronización automática de estado de ciclo de vida (activación si se cumplen todos los requisitos)
        from app.services.profile_service import sync_user_lifecycle_status
        sync_user_lifecycle_status(user)

        db.session.commit()

def resend_email_verification(user: User) -> dict:
    """
    POST /api/v1/auth/resend-verification
    Reenvía el correo de verificación para el usuario autenticado,
    revocando tokens previos y aplicando rate limiting estricto.
    Coordina transacciones entre procesos independientes mediante SELECT FOR UPDATE
    y garantiza que no se invalide el enlace anterior si el transporte de correo falla.
    """
    if not user or not user.is_active:
        raise AuthError('UNAUTHORIZED', 'Sesión requerida.', 401)

    if user.lifecycle_status in ('suspended', 'deactivated'):
        raise AuthError('CONFLICT', 'No es posible solicitar reenvío debido a un conflicto con el estado actual de la cuenta.', 409)

    if user.email_verified:
        # Respuesta compatible con el contrato sin reenviar correo innecesario
        return {'status': 'accepted'}

    with _resend_email_mutex:
        now = datetime.now(timezone.utc)
        cooldown = current_app.config.get('RESEND_COOLDOWN_SECONDS', 60)

        # Bloqueo pesimista por usuario en PostgreSQL para coordinar procesos independientes
        user_db = User.query.filter_by(id=user.id).with_for_update().first()
        if not user_db or not user_db.is_active:
            raise AuthError('UNAUTHORIZED', 'Sesión requerida.', 401)

        if user_db.lifecycle_status in ('suspended', 'deactivated'):
            raise AuthError('CONFLICT', 'No es posible solicitar reenvío debido a un conflicto con el estado actual de la cuenta.', 409)

        if user_db.email_verified:
            return {'status': 'accepted'}

        # Rate limiting por usuario: consultar el último token emitido (bloqueado pesimistamente)
        last_token = (
            EmailVerificationToken.query
            .filter_by(user_id=user_db.id)
            .order_by(EmailVerificationToken.created_at.desc())
            .with_for_update()
            .first()
        )

        if last_token and last_token.created_at:
            elapsed = (now - _as_utc(last_token.created_at)).total_seconds()
            if elapsed < cooldown:
                wait_sec = int(cooldown - elapsed)
                raise AuthError(
                    'RATE_LIMITED',
                    f'Por favor espere {wait_sec} segundos antes de solicitar otro reenvío de correo.',
                    429
                )

        # Generación de nuevo token con al menos 256 bits de entropía
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        hours = current_app.config.get('EMAIL_VERIFICATION_TOKEN_HOURS', 24)

        new_token_record = EmailVerificationToken(
            id=str(uuid.uuid4()),
            user_id=user_db.id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + timedelta(hours=hours)
        )

        # Despacho al transporte de correo ANTES de invalidar el enlace previo
        # NOTA DE ARQUITECTURA: PostgreSQL y SMTP no comparten una transacción atómica (2PC).
        # Para evitar invalidar el último enlace funcional antes de que el nuevo envío sea aceptado
        # correctamente por el transporte:
        # 1. Se intenta la entrega al transporte.
        # 2. Si el transporte falla (SMTP down, timeout, error de red), se aborta la transacción:
        #    - El token antiguo NO se revoca (sigue funcional en el buzón del usuario).
        #    - El token nuevo NO se persiste en la BD.
        #    - El cooldown NO se registra, permitiendo al usuario reintentar.
        #    - Se retorna un error HTTP 500 al cliente.
        # 3. Solo tras aceptación exitosa por el transporte se revocan tokens previos y se persiste el nuevo.
        # IMPORTANTE: La aceptación por SMTP solo confirma que el transporte recibió el mensaje;
        # no garantiza entrega final a la bandeja de entrada (asunto sujeto a filtrado o buzones remotos).
        from app.services.email_service import email_service
        try:
            email_service.send_verification_email(user_db.email, raw_token)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fallo en transporte de correo al reenviar a {user_db.email}: {str(e)}")
            raise AuthError(
                'INTERNAL_ERROR',
                'No fue posible enviar el correo de verificación debido a un error en el transporte.',
                500
            )

        # Una vez aceptado por el transporte, revocar tokens anteriores y persistir el nuevo atómicamente
        EmailVerificationToken.query.filter(
            EmailVerificationToken.user_id == user_db.id,
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.revoked_at.is_(None)
        ).update({'revoked_at': now}, synchronize_session=False)

        db.session.add(new_token_record)
        db.session.commit()

        return {'status': 'accepted'}

