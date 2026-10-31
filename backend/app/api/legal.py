from flask import Blueprint, current_app
from app.utils.errors import api_response

bp = Blueprint('legal', __name__)

@bp.route('/current', methods=['GET'])
def get_current_legal_versions():
    """
    GET /api/v1/legal/current
    Devuelve las versiones y URLs de los documentos legales vigentes (LegalVersions).
    Permite al frontend consultar las versiones requeridas antes del registro.
    """
    data = {
        'terms_version': current_app.config.get('LEGAL_TERMS_VERSION', 'v1-draft'),
        'privacy_version': current_app.config.get('LEGAL_PRIVACY_VERSION', 'v1-draft'),
        'terms_url': current_app.config.get('LEGAL_TERMS_URL', 'https://legal.example.test/terms'),
        'privacy_url': current_app.config.get('LEGAL_PRIVACY_URL', 'https://legal.example.test/privacy')
    }
    return api_response(data, status_code=200)
