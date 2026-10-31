from flask import Blueprint, jsonify, request, current_app
from app.auth.middleware import token_required
from app.models import Profile, Match, ProfileInteraction
from app import db
from app.utils.errors import api_error
from app.services.discovery_service import get_potential_candidates, DiscoveryError

bp = Blueprint('match', __name__)


@bp.route('/potential', methods=['GET'])
@token_required
def get_potential_matches(current_user):
    """
    GET /api/v1/match/potential
    Retorna candidatos filtrados y paginados por cursor determinista conforme a OpenAPI v1.
    """
    # 1. Parsear y validar parámetros query
    limit_raw = request.args.get('limit', '20')
    cursor = request.args.get('cursor', None)

    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        return api_error('VALIDATION_ERROR', "El parámetro 'limit' debe ser un número entero válido.", 422)

    if limit < 1 or limit > 50:
        return api_error('VALIDATION_ERROR', "El parámetro 'limit' debe estar comprendido entre 1 y 50.", 422)

    try:
        items, next_cursor, has_more = get_potential_candidates(current_user, limit=limit, cursor=cursor)
        return jsonify({
            'data': {
                'items': items
            },
            'meta': {
                'next_cursor': next_cursor,
                'has_more': has_more
            }
        }), 200
    except DiscoveryError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_potential_matches: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar candidatos de descubrimiento.', 500)


from app.services.match_service import (
    process_swipe,
    MatchError,
    get_user_matches,
    get_match_by_id,
    send_message,
    get_match_messages,
    mark_match_messages_as_read,
)


@bp.route('/swipe', methods=['POST'])
@token_required
def swipe(current_user):
    """
    POST /api/v1/match/swipe
    Registra LIKE o PASS de otro perfil de forma determinista, idempotente y segura bajo concurrencia.
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'El cuerpo de la petición debe ser JSON válido.', 400)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error('VALIDATION_ERROR', 'El cuerpo de la petición debe ser un objeto JSON.', 422)

    # Contrato OpenAPI: additionalProperties: false, required: [target_user_id, action]
    expected_keys = {'target_user_id', 'action'}
    if set(data.keys()) != expected_keys:
        return api_error(
            'VALIDATION_ERROR',
            "La petición debe contener exactamente 'target_user_id' y 'action' sin campos adicionales.",
            422
        )

    target_user_id = data.get('target_user_id')
    action = data.get('action')

    try:
        result = process_swipe(current_user, target_user_id, action)
        return jsonify({
            'data': {
                'interaction_id': result['interaction_id'],
                'action': result['action'],
                'is_match': result['is_match'],
                'match_id': result['match_id']
            }
        }), 200
    except MatchError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado en swipe: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al procesar swipe.', 500)


@bp.route('/my-matches', methods=['GET'])
@token_required
def my_matches(current_user):
    """
    GET /api/v1/match/my-matches
    Retorna la lista de matches activos del usuario con paginación por cursor conforme a OpenAPI v1.
    """
    limit_raw = request.args.get('limit', '20')
    cursor = request.args.get('cursor', None)

    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        return api_error('VALIDATION_ERROR', "El parámetro 'limit' debe ser un número entero válido.", 422)

    if limit < 1 or limit > 50:
        return api_error('VALIDATION_ERROR', "El parámetro 'limit' debe estar comprendido entre 1 y 50.", 422)

    try:
        items, next_cursor, has_more = get_user_matches(current_user, limit=limit, cursor=cursor)
        return jsonify({
            'data': {
                'items': items
            },
            'meta': {
                'next_cursor': next_cursor,
                'has_more': has_more
            }
        }), 200
    except MatchError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en my_matches: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar matches.', 500)


@bp.route('/<match_id>', methods=['GET'])
@token_required
def get_match_detail(current_user, match_id):
    """
    GET /api/v1/match/{matchId}
    Retorna el detalle de un match activo del usuario conforme a OpenAPI v1.
    """
    try:
        data = get_match_by_id(current_user, match_id)
        return jsonify({
            'data': data
        }), 200
    except MatchError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_match_detail: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar detalle de match.', 500)


@bp.route('/<match_id>/messages', methods=['GET'])
@token_required
def list_match_messages(current_user, match_id):
    """
    GET /api/v1/match/{matchId}/messages
    Retorna el historial de mensajes de un match activo con paginación por cursor conforme a OpenAPI v1.
    """
    limit_raw = request.args.get('limit', '20')
    cursor = request.args.get('cursor', None)

    try:
        limit = int(limit_raw)
    except (ValueError, TypeError):
        return api_error('VALIDATION_ERROR', "El parámetro 'limit' debe ser un número entero válido.", 422)

    if limit < 1 or limit > 50:
        return api_error('VALIDATION_ERROR', "El parámetro 'limit' debe estar comprendido entre 1 y 50.", 422)

    try:
        items, next_cursor, has_more = get_match_messages(current_user, match_id, limit=limit, cursor=cursor)
        return jsonify({
            'data': {
                'items': items
            },
            'meta': {
                'next_cursor': next_cursor,
                'has_more': has_more
            }
        }), 200
    except MatchError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en list_match_messages: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar mensajes.', 500)


@bp.route('/<match_id>/messages', methods=['POST'])
@token_required
def send_match_message(current_user, match_id):
    """
    POST /api/v1/match/{matchId}/messages
    Envía un mensaje de texto plano en un match activo conforme a OpenAPI v1.
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'El cuerpo de la petición debe ser JSON válido.', 400)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error('VALIDATION_ERROR', 'El cuerpo de la petición debe ser un objeto JSON.', 422)

    try:
        data = send_message(current_user, match_id, payload)
        return jsonify({
            'data': data
        }), 201
    except MatchError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado en send_match_message: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al enviar mensaje.', 500)


@bp.route('/<match_id>/read', methods=['POST'])
@token_required
def mark_messages_read(current_user, match_id):
    """
    POST /api/v1/match/{matchId}/read
    Marca como leídos los mensajes recibidos no leídos de un match activo conforme a OpenAPI v1.
    """
    try:
        data = mark_match_messages_as_read(current_user, match_id)
        return jsonify({
            'data': data
        }), 200
    except MatchError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado en mark_messages_read: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al marcar mensajes como leídos.', 500)


