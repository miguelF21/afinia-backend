import re
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
import jwt
from werkzeug.security import generate_password_hash, check_password_hash

# Expresión regular estándar para validación de formato RFC 5322 simplificado
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

def hash_password(password: str) -> str:
    """Genera un hash criptográficamente seguro para la contraseña."""
    return generate_password_hash(password, method='scrypt')

def verify_password(password_hash: str, password: str) -> bool:
    """Verifica la contraseña contra el hash de manera segura contra ataques de temporización."""
    if not password_hash or not password:
        return False
    return check_password_hash(password_hash, password)

def create_access_token(user_id: str, email: str, role: str, secret_key: str, expires_in: int = 900) -> str:
    """Genera un JWT Access Token firmado con expiración corta (por defecto 900s / 15m)."""
    now = datetime.now(timezone.utc)
    payload = {
        'sub': user_id,
        'email': email,
        'role': role,
        'type': 'access',
        'iss': 'afinia-api',
        'iat': now,
        'exp': now + timedelta(seconds=expires_in)
    }
    return jwt.encode(payload, secret_key, algorithm='HS256')

def decode_access_token(token: str, secret_key: str) -> dict:
    """Decodifica y valida la firma y vigencia de un JWT Access Token."""
    return jwt.decode(
        token,
        secret_key,
        algorithms=['HS256'],
        issuer='afinia-api',
        options={'require': ['exp', 'iat', 'sub']}
    )

def generate_refresh_token() -> str:
    """Genera un refresh token aleatorio de alta entropía (64 caracteres urlsafe)."""
    return secrets.token_urlsafe(48)

def hash_refresh_token(token: str) -> str:
    """Obtiene el hash SHA-256 (64 hex caracteres) para almacenamiento seguro en la BD."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def normalize_email(email: str) -> str:
    """Limpia y normaliza el correo electrónico a minúsculas canónicas."""
    return email.strip().lower() if email else ''

def validate_email_format(email: str) -> bool:
    """Valida sintaxis y longitud máxima conforme a OpenAPI y RFC (hasta 254 caracteres)."""
    if not email or len(email) > 254:
        return False
    return bool(EMAIL_REGEX.match(email))

def validate_password_policy(password: str) -> tuple[bool, str]:
    """Valida la longitud de la contraseña según OpenAPI (12 a 128 caracteres)."""
    if not password:
        return False, "La contraseña es requerida."
    if len(password) < 12:
        return False, "La contraseña debe contener al menos 12 caracteres."
    if len(password) > 128:
        return False, "La contraseña no puede superar los 128 caracteres."
    return True, ""
