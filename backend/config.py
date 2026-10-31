import os
from dotenv import load_dotenv

load_dotenv()

INSECURE_SECRETS = {
    'super-secret-key-for-afinia',
    'f3b9f8e7c2a1d0b9a8f7c6e5d4b3a2f1e0d9c8b7a6f5e4d3c2b1a0f9e8d7c6b5',
    'changeme',
    'secret'
}

class Config:
    FLASK_ENV = (os.environ.get('ENVIRONMENT') or os.environ.get('APP_ENV') or os.environ.get('FLASK_ENV') or 'development').lower()
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Parámetros de sesión y seguridad de tokens
    JWT_ACCESS_TOKEN_EXPIRES = int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', 900))
    REFRESH_TOKEN_EXPIRES_DAYS = int(os.environ.get('REFRESH_TOKEN_EXPIRES_DAYS', 30))
    REFRESH_CONCURRENCY_WINDOW_SECONDS = int(os.environ.get('REFRESH_CONCURRENCY_WINDOW_SECONDS', 15))
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'true' if FLASK_ENV in ('production', 'prod') else 'false').lower() in ('true', '1')

    # Configuración de proxies y mitigación de spoofing de IP
    TRUST_PROXY = os.environ.get('TRUST_PROXY', 'false').lower() in ('true', '1')

    # Orígenes CORS permitidos (Frontend Ionic/Angular web y móvil)
    _default_cors = 'http://localhost:8100,http://127.0.0.1:8100,http://localhost:4200,http://127.0.0.1:4200,capacitor://localhost,ionic://localhost'
    CORS_ORIGINS = [
        o.strip() for o in os.environ.get('CORS_ORIGINS', _default_cors).split(',') if o.strip()
    ]

    # Versiones legales activas y URLs (para pruebas / staging / producción)
    LEGAL_TERMS_VERSION = os.environ.get('LEGAL_TERMS_VERSION', 'v1-draft')
    LEGAL_PRIVACY_VERSION = os.environ.get('LEGAL_PRIVACY_VERSION', 'v1-draft')
    LEGAL_TERMS_URL = os.environ.get('LEGAL_TERMS_URL', 'https://legal.example.test/terms')
    LEGAL_PRIVACY_URL = os.environ.get('LEGAL_PRIVACY_URL', 'https://legal.example.test/privacy')

    # Configuración de verificación de correo electrónico (BE-02.3)
    EMAIL_VERIFICATION_TOKEN_HOURS = int(os.environ.get('EMAIL_VERIFICATION_TOKEN_HOURS', 24))
    RESEND_COOLDOWN_SECONDS = int(os.environ.get('RESEND_COOLDOWN_SECONDS', 60))
    FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:8100')

    # Configuración del transporte de correo (in_memory para QA/tests, smtp para producción)
    MAIL_BACKEND = os.environ.get('MAIL_BACKEND', 'in_memory')
    SMTP_HOST = os.environ.get('SMTP_HOST')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USER = os.environ.get('SMTP_USER')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
    SMTP_FROM = os.environ.get('SMTP_FROM', 'Afinia <no-reply@afinia.app>')
    SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('true', '1')

    # Validación de seguridad estricta para entornos productivos
    if FLASK_ENV in ('production', 'prod'):
        if not SECRET_KEY or SECRET_KEY.strip() in INSECURE_SECRETS or len(SECRET_KEY.strip()) < 32:
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: "
                "Production environment requires an explicitly configured, cryptographically secure SECRET_KEY "
                "(minimum 32 characters, not using known defaults)."
            )
        if not SQLALCHEMY_DATABASE_URI:
            raise RuntimeError(
                "CRITICAL CONFIGURATION ERROR: "
                "Production environment requires an explicitly configured DATABASE_URL."
            )
        if MAIL_BACKEND not in ('smtp',) or not SMTP_HOST:
            raise RuntimeError(
                "CRITICAL CONFIGURATION ERROR: "
                "Production environment requires an active transactional mail provider ('smtp') with SMTP_HOST configured. "
                "The 'in_memory' mail transport is strictly forbidden in production."
            )
    else:
        # Fallbacks tolerados únicamente para desarrollo local / pruebas no productivas
        if not SECRET_KEY:
            SECRET_KEY = 'dev-insecure-key-do-not-use-in-production'
        if not SQLALCHEMY_DATABASE_URI:
            SQLALCHEMY_DATABASE_URI = 'postgresql://afinia_user:afinia_password@localhost:5432/afinia_db'

