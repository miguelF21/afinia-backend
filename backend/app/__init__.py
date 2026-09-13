from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    # Registro de Blueprints (Rutas API)
    from app.api.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    
    from app.api.profile import bp as profile_bp
    app.register_blueprint(profile_bp, url_prefix='/api/v1/profile')

    @app.route('/health', methods=['GET'])
    def health_check():
        return {'status': 'ok', 'project': 'Afinia API'}

    return app
