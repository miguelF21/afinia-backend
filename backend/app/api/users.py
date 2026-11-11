"""
AFINIA — API de Usuarios Públicos (BE-03.1).
============================================
Implementa las rutas públicas de usuarios bajo /api/v1/users conforme a OpenAPI v1.
"""

from flask import Blueprint, request, current_app, Response, jsonify
from app.auth.middleware import token_required, admin_required
from app import db
from app.models import ProfilePhoto
from app.services.profile_service import sync_user_lifecycle_status
from app.services.storage_service import storage_adapter
from app.utils.errors import api_response, api_error
from app.services.discovery_service import get_public_profile_by_user_id, DiscoveryError
from app.services.block_service import (
    block_user,
    unblock_user,
    get_my_blocks,
    BlockError
)
from app.services.report_service import (
    create_user_report,
    list_moderation_reports,
    resolve_moderation_report,
    ReportError
)

bp = Blueprint('users', __name__)
admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/photos/pending', methods=['GET'])
@admin_required
def list_pending_photos(current_user):
    """Lista fotos pendientes para revisión manual por administradores."""
    try:
        offset = int(request.args.get('offset', '0'))
        if offset < 0:
            raise ValueError()
    except ValueError:
        return api_error('VALIDATION_ERROR', 'El desplazamiento debe ser un número entero no negativo.', 422)
    photos = ProfilePhoto.query.filter(ProfilePhoto.status.in_(['pending', 'processing'])).order_by(
        ProfilePhoto.created_at.asc(), ProfilePhoto.id.asc()
    ).offset(offset).limit(101).all()
    return api_response({'items': [{'id': str(photo.id), 'is_primary': bool(photo.is_primary)} for photo in photos[:100]],
                         'next_offset': offset + 100 if len(photos) > 100 else None})


@admin_bp.route('/photos/<photo_id>/media', methods=['GET'])
@admin_required
def review_photo_media(current_user, photo_id):
    """Permite al administrador revisar el archivo antes de decidir."""
    photo = db.session.get(ProfilePhoto, photo_id)
    if not photo or photo.status not in ('pending', 'processing'):
        return api_error('NOT_FOUND', 'Foto pendiente no encontrada.', 404)
    path = storage_adapter.get_file_path(photo.storage_key)
    if not path:
        return api_error('NOT_FOUND', 'El archivo de la foto ya no está disponible.', 404)
    with open(path, 'rb') as source:
        response = Response(source.read(), mimetype=photo.content_type or 'image/jpeg')
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@admin_bp.route('/photos/<photo_id>/review', methods=['POST'])
@admin_required
def review_photo(current_user, photo_id):
    """Aprueba o rechaza una foto revisada y sincroniza la cuenta."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'decision'} or data['decision'] not in ('approve', 'reject'):
        return api_error('VALIDATION_ERROR', 'Indica una decisión válida.', 422)
    try:
        photo = ProfilePhoto.query.filter_by(id=photo_id).with_for_update().first()
        if not photo:
            return api_error('NOT_FOUND', 'Foto no encontrada.', 404)
        if photo.status not in ('pending', 'processing'):
            return api_error('CONFLICT', 'La foto ya fue revisada.', 409)
        if data['decision'] == 'approve' and not storage_adapter.get_file_path(photo.storage_key):
            return api_error('CONFLICT', 'El archivo de la foto ya no está disponible.', 409)
        photo.status = 'ready' if data['decision'] == 'approve' else 'rejected'
        db.session.flush()
        sync_user_lifecycle_status(photo.profile.user)
        db.session.commit()
        current_app.logger.info('Revisión de foto completada por administrador: decisión=%s', data['decision'])
        return api_response({'status': photo.status})
    except Exception:
        db.session.rollback()
        current_app.logger.exception('No se pudo completar la revisión de foto')
        return api_error('INTERNAL_ERROR', 'No se pudo completar la revisión de la foto.', 500)


@bp.route('/me/blocks', methods=['GET'])
@token_required
def get_my_blocks_endpoint(current_user):
    """
    GET /api/v1/users/me/blocks
    Consulta la lista de usuarios bloqueados por el usuario autenticado (con paginación por cursor).
    """
    limit_raw = request.args.get('limit', 20)
    cursor_raw = request.args.get('cursor', None)
    try:
        items, next_cursor, has_more = get_my_blocks(current_user, limit_raw=limit_raw, cursor_raw=cursor_raw)
        from flask import jsonify
        return jsonify({
            "data": {
                "items": items
            },
            "meta": {
                "next_cursor": next_cursor,
                "has_more": has_more
            }
        }), 200
    except BlockError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_my_blocks_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar usuarios bloqueados.', 500)


@bp.route('/<userId>/block', methods=['PUT'])
@token_required
def block_user_endpoint(current_user, userId):
    """
    PUT /api/v1/users/{userId}/block
    Bloquea a otro usuario de forma inmediata y bidireccional.
    Idempotente conforme a OpenAPI v1.
    """
    try:
        receipt = block_user(current_user, userId)
        return api_response(receipt, status_code=200)
    except BlockError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en block_user_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al bloquear usuario.', 500)


@bp.route('/<userId>/block', methods=['DELETE'])
@token_required
def unblock_user_endpoint(current_user, userId):
    """
    DELETE /api/v1/users/{userId}/block
    Desbloquea a un usuario previamente bloqueado por el solicitante.
    Retorna 204 No Content.
    """
    try:
        unblock_user(current_user, userId)
        return Response(status=204)
    except BlockError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en unblock_user_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al desbloquear usuario.', 500)


@bp.route('/<userId>', methods=['GET'])
@token_required
def get_user_public_profile(current_user, userId):
    """
    GET /api/v1/users/{userId}
    Retorna el perfil público visible de un usuario (PublicProfile).
    Aplica verificación de bloqueos bidireccionales, cuentas activas y exclusión de datos privados.
    """
    try:
        profile_data = get_public_profile_by_user_id(current_user, userId)
        return api_response(profile_data, status_code=200)
    except DiscoveryError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_user_public_profile: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar el perfil del usuario.', 500)


@bp.route('/<userId>/reports', methods=['POST'])
@token_required
def report_user_endpoint(current_user, userId):
    """
    POST /api/v1/users/{userId}/reports
    Registra una denuncia confidencial contra un perfil conforme a OpenAPI v1.
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'El cuerpo de la petición debe ser JSON válido.', 400)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error('VALIDATION_ERROR', 'El cuerpo de la petición debe ser un objeto JSON.', 422)

    try:
        receipt = create_user_report(current_user, userId, payload)
        return api_response(receipt, status_code=201)
    except ReportError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en report_user_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al registrar el reporte.', 500)


@admin_bp.route('/reports', methods=['GET'])
@admin_required
def list_admin_reports_endpoint(current_user):
    """
    GET /api/v1/admin/reports
    Lista denuncias para moderación administrativa.
    Exclusivo para rol 'admin' verificado en servidor.
    """
    try:
        query_args = request.args.to_dict(flat=True)
        items, next_cursor, has_more = list_moderation_reports(current_user, query_args=query_args)
        return jsonify({
            "data": {
                "items": items
            },
            "meta": {
                "next_cursor": next_cursor,
                "has_more": has_more
            }
        }), 200
    except ReportError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en list_admin_reports_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al listar denuncias de moderación.', 500)


@admin_bp.route('/reports/<reportId>/resolve', methods=['POST'])
@admin_required
def resolve_admin_report_endpoint(current_user, reportId):
    """
    POST /api/v1/admin/reports/{reportId}/resolve
    Resuelve una denuncia administrativa registrando actor, fecha y decisión.
    Exclusivo para rol 'admin' verificado en servidor.
    """
    if not request.is_json:
        return api_error('VALIDATION_ERROR', 'El cuerpo de la petición debe ser un objeto JSON válido.', 422)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error('VALIDATION_ERROR', 'El cuerpo de la petición debe ser un objeto JSON válido.', 422)

    try:
        result = resolve_moderation_report(current_user, reportId, payload)
        return api_response(result, status_code=200)
    except ReportError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en resolve_admin_report_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al resolver la denuncia.', 500)


