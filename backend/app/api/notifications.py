from flask import Blueprint, jsonify, request, current_app, Response
from app import db
from app.auth.middleware import token_required
from app.utils.errors import api_error
from app.services.notification_service import (
    list_user_notifications,
    mark_notification_as_read,
    NotificationError,
)

bp = Blueprint('notifications', __name__)


@bp.route('', methods=['GET'])
@bp.route('/', methods=['GET'])
@token_required
def get_notifications_endpoint(current_user):
    """
    GET /api/v1/notifications
    Lista las notificaciones del usuario autenticado con paginación por cursor
    conforme al contrato OpenAPI v1 (operationId: getNotifications).
    """
    try:
        items, next_cursor, has_more = list_user_notifications(
            current_user=current_user,
            query_args=request.args.to_dict(flat=True),
        )
        return jsonify({
            'data': {
                'items': items,
            },
            'meta': {
                'next_cursor': next_cursor,
                'has_more': has_more,
            },
        }), 200
    except NotificationError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_notifications_endpoint: {e}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar las notificaciones.', 500)


@bp.route('/<notificationId>/read', methods=['POST'])
@token_required
def read_notification_endpoint(current_user, notificationId):
    """
    POST /api/v1/notifications/{notificationId}/read
    Marca como leída una notificación propia del usuario autenticado
    conforme al contrato OpenAPI v1 (operationId: readNotification).
    Retorna 204 No Content.
    """
    if request.content_length and request.content_length > 0:
        if not request.is_json:
            return api_error('BAD_REQUEST', 'El cuerpo de la solicitud no es válido.', 400)
        body = request.get_json(silent=True)
        if body is None or (isinstance(body, dict) and len(body) > 0) or not isinstance(body, dict):
            return api_error('VALIDATION_ERROR', 'Este endpoint no admite cuerpo de datos.', 422)

    try:
        mark_notification_as_read(
            current_user=current_user,
            notification_id_raw=notificationId,
            query_args=request.args.to_dict(flat=True),
        )
        return Response(status=204)
    except NotificationError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error inesperado en read_notification_endpoint: {e}")
        return api_error('INTERNAL_ERROR', 'Error interno al marcar la notificación como leída.', 500)

