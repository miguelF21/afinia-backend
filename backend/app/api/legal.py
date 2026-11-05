from flask import Blueprint, current_app, request
from app import db
from app.auth.middleware import token_required
from app.utils.errors import api_response, api_error
from app.utils.rate_limit import get_trusted_client_ip
from app.services.legal_service import (
    get_current_legal_documents,
    record_legal_acceptance,
    LegalError,
)

bp = Blueprint('legal', __name__)


@bp.route('/current', methods=['GET'])
def get_current_legal_versions():
    """
    GET /api/v1/legal/current
    Devuelve las versiones y URLs de los documentos legales vigentes (LegalVersions).
    Permite al frontend consultar las versiones requeridas antes del registro.
    """
    data = get_current_legal_documents()
    return api_response(data, status_code=200)


@bp.route('/acceptances', methods=['POST'])
@token_required
def record_legal_acceptance_endpoint(current_user):
    """
    POST /api/v1/legal/acceptances
    Registra la aceptación explícita de las versiones vigentes de términos y privacidad
    para el usuario autenticado (operationId: recordLegalAcceptance).
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'La solicitud debe tener Content-Type application/json.', 400)

    payload = request.get_json(silent=True)
    if payload is None:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud no contiene un JSON válido.', 400)

    try:
        result = record_legal_acceptance(
            current_user=current_user,
            payload=payload,
            ip_address=get_trusted_client_ip(),
            query_args=request.args.to_dict(flat=True),
        )
        return api_response(result, status_code=200)
    except LegalError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado en record_legal_acceptance_endpoint: {e}")
        return api_error('INTERNAL_ERROR', 'Error interno al registrar la aceptación legal.', 500)
