from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from config import Config

db = SQLAlchemy()
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    # Configuración estricta de CORS con orígenes explícitos y credenciales (sin comodines abiertos)
    cors_origins = app.config.get('CORS_ORIGINS', [])
    CORS(
        app,
        resources={r"/api/*": {"origins": cors_origins}},
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "X-Client-Platform", "X-Requested-With"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )

    if app.config.get('TRUST_PROXY'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Registro de Blueprints (Rutas API)
    from app.api.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    
    from app.api.profile import bp as profile_bp
    app.register_blueprint(profile_bp, url_prefix='/api/v1/profile')
    
    from app.api.analytics import bp as analytics_bp
    app.register_blueprint(analytics_bp, url_prefix='/api/v1/analytics')

    from app.api.match import bp as match_bp
    app.register_blueprint(match_bp, url_prefix='/api/v1/match')

    from app.api.legal import bp as legal_bp
    app.register_blueprint(legal_bp, url_prefix='/api/v1/legal')

    from app.api.users import bp as users_bp
    app.register_blueprint(users_bp, url_prefix='/api/v1/users')

    @app.route('/health', methods=['GET'])
    def health_check():
        return {'status': 'ok', 'project': 'Afinia API'}

    @app.errorhandler(413)
    def handle_payload_too_large(e):
        from app.utils.errors import api_error
        return api_error('PAYLOAD_TOO_LARGE', 'Archivo demasiado grande. El límite máximo permitido es 10 MB.', 413)

    return app
