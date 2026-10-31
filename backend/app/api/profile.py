from flask import Blueprint, request, current_app, Response, send_file
from app.auth.middleware import token_required
from app.utils.errors import api_response, api_error
from app.services.profile_service import (
    ProfileError,
    create_profile,
    get_own_profile,
    update_profile,
    get_discovery_preferences,
    save_discovery_preferences,
    upload_profile_photo,
    set_primary_photo,
    delete_profile_photo,
    get_photo_media
)

bp = Blueprint('profile', __name__)

@bp.route('/', methods=['GET'])
@token_required
def get_my_profile(current_user):
    """
    GET /api/v1/profile/
    Retorna el perfil propio del usuario autenticado (OwnProfile).
    """
    try:
        data = get_own_profile(current_user)
        return api_response(data, status_code=200)
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_my_profile: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar el perfil.', 500)

@bp.route('/', methods=['POST'])
@token_required
def create_my_profile(current_user):
    """
    POST /api/v1/profile/
    Crea el perfil del usuario autenticado a partir de ProfileWrite.
    Retorna 201 Created con OwnProfile o 409 Conflict si ya existe.
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)
    
    data = request.get_json(silent=True)
    if data is None:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    try:
        profile_data = create_profile(current_user, data)
        return api_response(profile_data, status_code=201)
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en create_my_profile: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al crear el perfil.', 500)

@bp.route('/', methods=['PUT'])
@token_required
def replace_my_profile(current_user):
    """
    PUT /api/v1/profile/
    Actualiza completamente el perfil del usuario autenticado a partir de ProfileWrite.
    Retorna 200 OK con OwnProfile o 404 Not Found si no existe.
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)
    
    data = request.get_json(silent=True)
    if data is None:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    try:
        profile_data = update_profile(current_user, data)
        return api_response(profile_data, status_code=200)
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en replace_my_profile: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al actualizar el perfil.', 500)

@bp.route('/discovery-preferences', methods=['GET'])
@token_required
def get_preferences(current_user):
    """
    GET /api/v1/profile/discovery-preferences
    Consulta las preferencias de búsqueda del usuario autenticado.
    Retorna 200 OK con Preferences.
    """
    try:
        prefs = get_discovery_preferences(current_user)
        return api_response(prefs, status_code=200)
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en get_preferences: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar las preferencias.', 500)

@bp.route('/discovery-preferences', methods=['PUT'])
@token_required
def put_preferences(current_user):
    """
    PUT /api/v1/profile/discovery-preferences
    Guarda o actualiza las preferencias de búsqueda del usuario autenticado a partir de Preferences.
    Retorna 200 OK con Preferences.
    """
    if not request.is_json:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)
    
    data = request.get_json(silent=True)
    if data is None:
        return api_error('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    try:
        prefs = save_discovery_preferences(current_user, data)
        return api_response(prefs, status_code=200)
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en put_preferences: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al guardar las preferencias.', 500)

# =========================================================================
# ENDPOINTS DE FOTOGRAFÍAS DE PERFIL (BE-02.2)
# =========================================================================

@bp.route('/photos', methods=['POST'])
@token_required
def upload_photo_endpoint(current_user):
    """
    POST /api/v1/profile/photos
    Sube una fotografía multipart/form-data para el perfil propio.
    Retorna 201 Created con esquema Photo.
    """
    if 'file' not in request.files:
        return api_error('BAD_REQUEST', 'El campo multipart "file" es obligatorio.', 400)

    file_storage = request.files['file']
    if not file_storage or file_storage.filename == '':
        return api_error('BAD_REQUEST', 'Archivo no seleccionado o nombre de archivo vacío.', 400)

    # is_primary opcional en form data (default false)
    raw_primary = request.form.get('is_primary', 'false').lower()
    is_primary = raw_primary in ('true', '1', 'yes')

    try:
        photo_data = upload_profile_photo(current_user, file_storage, is_primary_requested=is_primary)
        return api_response(photo_data, status_code=201)
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en upload_photo_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al procesar la fotografía.', 500)

@bp.route('/photos/<photo_id>/primary', methods=['PUT'])
@token_required
def set_primary_photo_endpoint(current_user, photo_id):
    """
    PUT /api/v1/profile/photos/{photoId}/primary
    Establece la fotografía como principal del perfil propio.
    Retorna 200 OK con esquema Photo.
    """
    try:
        photo_data = set_primary_photo(current_user, photo_id)
        return api_response(photo_data, status_code=200)
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en set_primary_photo_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al actualizar la fotografía principal.', 500)

@bp.route('/photos/<photo_id>', methods=['DELETE'])
@token_required
def delete_photo_endpoint(current_user, photo_id):
    """
    DELETE /api/v1/profile/photos/{photoId}
    Elimina una fotografía del perfil propio y su archivo en almacenamiento.
    Retorna 204 No Content.
    """
    try:
        delete_profile_photo(current_user, photo_id)
        return Response(status=204)
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error inesperado en delete_photo_endpoint: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al eliminar la fotografía.', 500)

@bp.route('/photos/media/<photo_id>', methods=['GET'])
@token_required
def serve_photo_media_endpoint(current_user, photo_id):
    """
    GET /api/v1/profile/photos/media/{photoId}
    Ruta interna protegida para servir archivos de imagen autenticados:
    - Todas las fotografías requieren autenticación Bearer JWT válida.
    - Fotos 'ready': Accesibles para cualquier usuario autenticado activo salvo que exista bloqueo mutuo con el propietario.
    - Fotos 'pending', 'processing', 'rejected': Accesibles exclusivamente para el propietario del perfil.
    - Todas las respuestas utilizan Cache-Control privado para prevenir almacenamiento en cachés compartidas o intermedias.
    """
    try:
        file_path, content_type, photo_status = get_photo_media(current_user, photo_id)
        with open(file_path, 'rb') as f:
            file_data = f.read()

        response = Response(file_data, mimetype=content_type)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'private, no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'

        return response
    except ProfileError as e:
        return api_error(e.code, e.message, status_code=e.status_code, details=e.details)
    except Exception as e:
        current_app.logger.error(f"Error al servir fotografía media {photo_id}: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al servir la imagen.', 500)
