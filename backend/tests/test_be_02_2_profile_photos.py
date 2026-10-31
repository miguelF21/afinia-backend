import io
import os
import pytest
from datetime import datetime, date, timezone
from PIL import Image
from app import db
from app.models.user import User
from app.models.profile import Profile, ProfilePhoto
from app.models.discovery import DiscoveryPreference
from app.models.block import UserBlock
from app.services.profile_service import (
    is_onboarding_complete,
    approve_photo_for_qa
)
from app.services.storage_service import storage_adapter

def _create_synthetic_image(fmt='JPEG', width=120, height=120, orientation=None, with_gps=False) -> io.BytesIO:
    """Genera una imagen sintética en memoria usando Pillow con metadatos EXIF y GPSInfo auténticos."""
    from PIL import ExifTags
    img = Image.new('RGB', (width, height), color=(40, 120, 200))
    buf = io.BytesIO()
    
    exif = img.getexif()
    has_exif = False

    if orientation is not None:
        exif[0x0112] = orientation
        has_exif = True

    if with_gps and fmt == 'JPEG':
        # 0x8825 (34853) es la etiqueta IFD GPSInfo oficial del estándar EXIF
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
        gps_ifd[1] = 'N'                          # GPSLatitudeRef
        gps_ifd[2] = (4.0, 9.0, 0.0)             # GPSLatitude: 4° 9' 0" N (= 4.15)
        gps_ifd[3] = 'W'                          # GPSLongitudeRef
        gps_ifd[4] = (73.0, 37.0, 48.0)          # GPSLongitude: 73° 37' 48" W (= -73.63)
        gps_ifd[5] = b'\x00'                     # GPSAltitudeRef
        gps_ifd[6] = 467.0                       # GPSAltitude
        # Metadatos descriptivos de cámara y autor
        exif[0x010e] = "Sensitive Location Description"  # ImageDescription
        exif[0x010f] = "SecretPhoneBrand"               # Make
        exif[0x0110] = "ModelWithGPS"                   # Model
        exif[0x0132] = "2026:10:28 14:00:00"            # DateTime
        has_exif = True
        
    if has_exif and fmt == 'JPEG':
        img.save(buf, format='JPEG', exif=exif)
    else:
        img.save(buf, format=fmt)
        
    buf.seek(0)
    return buf

def _register_and_create_profile(client, email='photo.test@afinia.com'):
    """Helper para crear usuario y su perfil base."""
    client.post('/api/v1/auth/register', json={
        'email': email,
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    login_res = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    token = login_res.get_json()['data']['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    client.post('/api/v1/profile/', json={
        'first_name': 'Fotógrafo',
        'birth_date': '1998-06-15',
        'gender': 'masculino',
        'city': 'Villavicencio'
    }, headers=headers)

    return token, headers

# =========================================================================
# 1. SUBIDA DE FOTOGRAFÍAS (POST /api/v1/profile/photos)
# =========================================================================

def test_upload_photo_jpeg_valid(client):
    """1. Subida válida de fotografía JPEG conforme a OpenAPI."""
    token, headers = _register_and_create_profile(client, 'photo.jpeg@afinia.com')

    img_buf = _create_synthetic_image('JPEG')
    data = {
        'file': (img_buf, 'test_avatar.jpg', 'image/jpeg'),
        'is_primary': 'true'
    }
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data', headers=headers)
    assert res.status_code == 201
    body = res.get_json()
    assert 'data' in body
    photo = body['data']
    assert 'id' in photo
    assert 'url' in photo
    assert photo['is_primary'] is True
    assert photo['url'].startswith('http')

    # Verificar que el modelo guardó status='pending' y metadatos correctos
    db_photo = db.session.get(ProfilePhoto, photo['id'])
    assert db_photo is not None
    assert db_photo.status == 'pending'
    assert db_photo.position == 0
    assert db_photo.content_type == 'image/jpeg'
    assert db_photo.byte_size > 0

    # Verificar que el archivo físico fue creado en disco
    assert storage_adapter.get_file_path(db_photo.storage_key) is not None

def test_upload_photo_png_valid(client):
    """2. Subida válida de fotografía PNG."""
    token, headers = _register_and_create_profile(client, 'photo.png@afinia.com')

    img_buf = _create_synthetic_image('PNG')
    data = {
        'file': (img_buf, 'avatar.png', 'image/png')
    }
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data', headers=headers)
    assert res.status_code == 201
    photo = res.get_json()['data']
    # Al ser la primera foto, se asigna automáticamente como principal
    assert photo['is_primary'] is True

def test_upload_photo_webp_valid(client):
    """3. Subida válida de fotografía WEBP."""
    token, headers = _register_and_create_profile(client, 'photo.webp@afinia.com')

    img_buf = _create_synthetic_image('WEBP')
    data = {
        'file': (img_buf, 'avatar.webp', 'image/webp')
    }
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data', headers=headers)
    assert res.status_code == 201
    photo = res.get_json()['data']
    assert 'id' in photo

def test_upload_photo_too_large_rejected(client):
    """4. Rechazo de archivo que excede 10 MB con 413 PAYLOAD_TOO_LARGE."""
    token, headers = _register_and_create_profile(client, 'photo.large@afinia.com')

    # Generar buffer simulado mayor a 10 MB (10.1 MB)
    large_bytes = b'X' * (10 * 1024 * 1024 + 1024)
    data = {
        'file': (io.BytesIO(large_bytes), 'huge.jpg', 'image/jpeg')
    }
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data', headers=headers)
    assert res.status_code == 413
    body = res.get_json()
    assert 'error' in body
    assert body['error']['code'] == 'PAYLOAD_TOO_LARGE'

def test_upload_photo_non_image_rejected(client):
    """5. Rechazo de archivo no imagen (ej: texto o pdf) con 415 UNSUPPORTED_MEDIA_TYPE."""
    token, headers = _register_and_create_profile(client, 'photo.notimg@afinia.com')

    fake_text = b'Este es un documento de texto no permitido.'
    data = {
        'file': (io.BytesIO(fake_text), 'documento.txt', 'text/plain')
    }
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data', headers=headers)
    assert res.status_code == 415
    body = res.get_json()
    assert 'error' in body
    assert body['error']['code'] == 'UNSUPPORTED_MEDIA_TYPE'

def test_upload_photo_corrupted_content_rejected(client):
    """6. Rechazo de contenido corrupto con cabecera JPEG falsa pero cuerpo roto."""
    token, headers = _register_and_create_profile(client, 'photo.corrupt@afinia.com')

    corrupted_bytes = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01' + b'CORRUPTED_BYTES_HERE'
    data = {
        'file': (io.BytesIO(corrupted_bytes), 'corrupt.jpg', 'image/jpeg')
    }
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data', headers=headers)
    assert res.status_code == 415
    body = res.get_json()
    assert 'error' in body
    assert body['error']['code'] == 'UNSUPPORTED_MEDIA_TYPE'

def test_upload_photo_exif_gps_stripped(client):
    """7. Verificación de eliminación completa de metadatos EXIF / GPSInfo (0x8825) auténticos."""
    from PIL import ExifTags
    token, headers = _register_and_create_profile(client, 'photo.exif@afinia.com')

    gps_img = _create_synthetic_image('JPEG', with_gps=True)

    # 1. Comprobar que el archivo original sí contiene la etiqueta GPSInfo (0x8825) y coordenadas
    initial_img = Image.open(io.BytesIO(gps_img.getvalue()))
    initial_exif = initial_img.getexif()
    assert 0x8825 in initial_exif or ExifTags.IFD.GPSInfo in initial_exif, "El archivo original debe contener GPSInfo (0x8825)"
    initial_gps = initial_exif.get_ifd(ExifTags.IFD.GPSInfo)
    assert 2 in initial_gps, "GPSLatitude debe existir en la imagen original"
    assert 4 in initial_gps, "GPSLongitude debe existir en la imagen original"

    data = {
        'file': (gps_img, 'with_gps.jpg', 'image/jpeg')
    }
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data', headers=headers)
    assert res.status_code == 201
    photo_id = res.get_json()['data']['id']

    # Inspeccionar el archivo saneado en disco
    photo_record = db.session.get(ProfilePhoto, photo_id)
    saved_path = storage_adapter.get_file_path(photo_record.storage_key)
    assert saved_path is not None

    with Image.open(saved_path) as inspected:
        exif_data = inspected.getexif()
        # Verificar que se eliminó GPSInfo (0x8825) y no quedan coordenadas
        assert 0x8825 not in exif_data
        assert ExifTags.IFD.GPSInfo not in exif_data
        assert len(exif_data.get_ifd(ExifTags.IFD.GPSInfo)) == 0
        # Verificar que se eliminaron los metadatos de autor, cámara y descripción
        assert 0x010e not in exif_data
        assert 0x010f not in exif_data
        assert 0x0110 not in exif_data
        assert len(exif_data) == 0

def test_upload_photo_unauthenticated(client):
    """8. Subida sin autenticación rechazada con 401 UNAUTHORIZED."""
    img_buf = _create_synthetic_image('JPEG')
    data = {'file': (img_buf, 'test.jpg', 'image/jpeg')}
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data')
    assert res.status_code == 401
    assert res.get_json()['error']['code'] == 'UNAUTHORIZED'

def test_upload_photo_without_profile_rejected(client):
    """9. Subida sin perfil previamente creado rechazada con 422 VALIDATION_ERROR."""
    # Registrar usuario pero NO crear perfil
    client.post('/api/v1/auth/register', json={
        'email': 'noprofile.photo@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    login_res = client.post('/api/v1/auth/login', json={
        'email': 'noprofile.photo@afinia.com',
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    token = login_res.get_json()['data']['access_token']

    img_buf = _create_synthetic_image('JPEG')
    data = {'file': (img_buf, 'test.jpg', 'image/jpeg')}
    res = client.post('/api/v1/profile/photos', data=data, content_type='multipart/form-data', headers={'Authorization': f'Bearer {token}'})
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_upload_photo_limit_six_enforced(client):
    """10. Rechazar la séptima fotografía con 422 VALIDATION_ERROR."""
    token, headers = _register_and_create_profile(client, 'photo.limit6@afinia.com')

    # Subir 6 fotos exitosamente (posiciones 0 a 5)
    for i in range(6):
        buf = _create_synthetic_image('JPEG', width=100 + i, height=100 + i)
        res = client.post('/api/v1/profile/photos', data={'file': (buf, f'photo_{i}.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers)
        assert res.status_code == 201

    # Intentar subir la séptima foto
    buf_7 = _create_synthetic_image('JPEG')
    res_7 = client.post('/api/v1/profile/photos', data={'file': (buf_7, 'photo_7.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers)
    assert res_7.status_code == 422
    assert res_7.get_json()['error']['code'] == 'VALIDATION_ERROR'

# =========================================================================
# 2. SELECCIÓN DE FOTO PRINCIPAL (PUT /api/v1/profile/photos/{photoId}/primary)
# =========================================================================

def test_set_primary_photo_valid_and_uniqueness(client):
    """11. Establecer foto principal y garantizar unicidad estricta."""
    token, headers = _register_and_create_profile(client, 'photo.primary@afinia.com')

    # Subir foto 1 (queda como principal)
    buf1 = _create_synthetic_image('JPEG')
    p1 = client.post('/api/v1/profile/photos', data={'file': (buf1, 'p1.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    assert p1['is_primary'] is True

    # Subir foto 2 (no es principal)
    buf2 = _create_synthetic_image('PNG')
    p2 = client.post('/api/v1/profile/photos', data={'file': (buf2, 'p2.png', 'image/png'), 'is_primary': 'false'}, content_type='multipart/form-data', headers=headers).get_json()['data']
    assert p2['is_primary'] is False

    # Marcar foto 2 como principal mediante PUT /primary
    put_res = client.put(f"/api/v1/profile/photos/{p2['id']}/primary", headers=headers)
    assert put_res.status_code == 200
    assert put_res.get_json()['data']['is_primary'] is True

    # Verificar en BD que exactamente una foto tenga is_primary=True
    user = User.query.filter_by(email='photo.primary@afinia.com').first()
    primaries = [p for p in user.profile.photos if p.is_primary]
    assert len(primaries) == 1
    assert primaries[0].id == p2['id']

def test_set_primary_photo_forbidden_on_other_user(client):
    """12. Rechazar cambiar foto principal si pertenece a otro usuario con 403 FORBIDDEN."""
    token_a, headers_a = _register_and_create_profile(client, 'owner.a@afinia.com')
    token_b, headers_b = _register_and_create_profile(client, 'owner.b@afinia.com')

    buf = _create_synthetic_image('JPEG')
    photo_a = client.post('/api/v1/profile/photos', data={'file': (buf, 'pa.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers_a).get_json()['data']

    # Usuario B intenta marcar como principal la foto de A
    res = client.put(f"/api/v1/profile/photos/{photo_a['id']}/primary", headers=headers_b)
    assert res.status_code == 403
    assert res.get_json()['error']['code'] == 'FORBIDDEN'

# =========================================================================
# 3. ELIMINACIÓN DE FOTOGRAFÍA (DELETE /api/v1/profile/photos/{photoId})
# =========================================================================

def test_delete_photo_valid_and_storage_cleanup(client):
    """13. Eliminar fotografía (204 No Content), verificar limpieza física y promoción de nueva principal."""
    token, headers = _register_and_create_profile(client, 'photo.delete@afinia.com')

    buf1 = _create_synthetic_image('JPEG')
    p1 = client.post('/api/v1/profile/photos', data={'file': (buf1, 'p1.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    
    buf2 = _create_synthetic_image('JPEG')
    p2 = client.post('/api/v1/profile/photos', data={'file': (buf2, 'p2.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']

    db_p1 = db.session.get(ProfilePhoto, p1['id'])
    saved_key_1 = db_p1.storage_key
    assert storage_adapter.get_file_path(saved_key_1) is not None

    # Eliminar foto 1 (que era la principal)
    del_res = client.delete(f"/api/v1/profile/photos/{p1['id']}", headers=headers)
    assert del_res.status_code == 204
    assert del_res.data == b''

    # Verificar que el registro en BD ya no existe
    assert db.session.get(ProfilePhoto, p1['id']) is None

    # Verificar que el archivo físico en almacenamiento fue eliminado
    assert storage_adapter.get_file_path(saved_key_1) is None

    # Verificar que la foto 2 fue promovida a principal de forma determinista
    db_p2 = db.session.get(ProfilePhoto, p2['id'])
    assert db_p2.is_primary is True

def test_delete_photo_forbidden_on_other_user(client):
    """14. Rechazar eliminar fotografía ajena con 403 FORBIDDEN."""
    token_a, headers_a = _register_and_create_profile(client, 'del.a@afinia.com')
    token_b, headers_b = _register_and_create_profile(client, 'del.b@afinia.com')

    buf = _create_synthetic_image('JPEG')
    photo_a = client.post('/api/v1/profile/photos', data={'file': (buf, 'pa.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers_a).get_json()['data']

    res = client.delete(f"/api/v1/profile/photos/{photo_a['id']}", headers=headers_b)
    assert res.status_code == 403
    assert res.get_json()['error']['code'] == 'FORBIDDEN'

# =========================================================================
# 4. INTEGRACIÓN CON OWNPROFILE, PREVISUALIZACIÓN Y CONTROL DE ACCESO
# =========================================================================

def test_own_profile_photos_integration(client):
    """15. GET /api/v1/profile/ serializa la lista de fotos del usuario con URLs reales utilizables."""
    token, headers = _register_and_create_profile(client, 'photo.own@afinia.com')

    buf = _create_synthetic_image('JPEG')
    client.post('/api/v1/profile/photos', data={'file': (buf, 'p1.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers)

    res = client.get('/api/v1/profile/', headers=headers)
    assert res.status_code == 200
    data = res.get_json()['data']
    assert len(data['photos']) == 1
    photo = data['photos'][0]
    assert photo['is_primary'] is True
    assert '/api/v1/profile/photos/media/' in photo['url']

def test_photo_media_endpoint_access_control(client):
    """16. Servir imagen con control de acceso: foto pending solo visible para propietario."""
    token_a, headers_a = _register_and_create_profile(client, 'media.owner@afinia.com')
    token_b, headers_b = _register_and_create_profile(client, 'media.intruder@afinia.com')

    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'p1.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers_a).get_json()['data']
    photo_id = photo['id']

    # 1. Propietario con token puede acceder a su foto en estado pending
    res_owner = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=headers_a)
    assert res_owner.status_code == 200
    assert res_owner.content_type == 'image/jpeg'
    assert len(res_owner.data) > 0

    # 2. Usuario ajeno no puede ver la foto mientras esté en status pending (403 FORBIDDEN)
    res_intruder = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=headers_b)
    assert res_intruder.status_code == 403

    # 3. Transicionar controladamente a 'ready' (aprobada por moderación)
    approve_photo_for_qa(photo_id)

    # 4. Ahora la foto aprobada es accesible públicamente para usuarios del sistema
    res_public = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=headers_b)
    assert res_public.status_code == 200

# =========================================================================
# 5. POLÍTICA DE ONBOARDING
# =========================================================================

def test_onboarding_lifecycle_with_photos_and_email_verification(client):
    """17. Comprobar condiciones de onboarding: perfil + preferencias + foto ready + email verificado."""
    email = 'onboard.full@afinia.com'
    token, headers = _register_and_create_profile(client, email)

    # 1. Perfil creado, pero sin preferencias: onboarding_complete = False
    me1 = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me1['onboarding_complete'] is False
    assert me1['status'] == 'pending_profile'

    # 2. Guardar preferencias válidas
    client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['femenino'],
        'min_age': 20,
        'max_age': 30
    }, headers=headers)

    # Aún sin fotos: onboarding_complete = False
    me2 = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me2['onboarding_complete'] is False

    # 3. Subir fotografía (queda en pending)
    buf = _create_synthetic_image('JPEG')
    photo_res = client.post('/api/v1/profile/photos', data={'file': (buf, 'avatar.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers)
    photo_id = photo_res.get_json()['data']['id']

    # La foto está en pending: NO satisface el onboarding
    me3 = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me3['onboarding_complete'] is False

    # 4. Aprobar la fotografía a 'ready' pero email_verified sigue en False
    approve_photo_for_qa(photo_id)
    me4 = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me4['onboarding_complete'] is False  # Falta verificación de correo

    # 5. Caso positivo sintético controlado: simular email verificado
    user = User.query.filter_by(email=email).first()
    user.email_verified = True
    db.session.commit()

    # Ahora sí se satisfacen todas las condiciones de onboarding
    me5 = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me5['onboarding_complete'] is True

# =========================================================================
# 6. PRUEBAS DE AUDITORÍA BE-02.2.1
# =========================================================================

def test_image_dimension_limits_and_decompression_bomb_protection(client):
    """18. Rechazo explícito de imágenes con dimensiones excesivas (>8192 px) o datos corruptos."""
    token, headers = _register_and_create_profile(client, 'pillow.limits@afinia.com')

    # A. Imagen que excede la dimensión máxima por eje (8200 x 50 píxeles)
    huge_dim_img = Image.new('RGB', (8200, 50), color=(100, 100, 100))
    huge_buf = io.BytesIO()
    huge_dim_img.save(huge_buf, format='JPEG')
    huge_buf.seek(0)

    res_dim = client.post(
        '/api/v1/profile/photos',
        data={'file': (huge_buf, 'huge_dim.jpg', 'image/jpeg')},
        content_type='multipart/form-data',
        headers=headers
    )
    assert res_dim.status_code == 422
    assert res_dim.get_json()['error']['code'] == 'VALIDATION_ERROR'

    # B. Archivo con cabecera de imagen pero contenido truncado/corrupto
    corrupt_buf = io.BytesIO(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00corrupted_payload_bytes_here')
    res_corrupt = client.post(
        '/api/v1/profile/photos',
        data={'file': (corrupt_buf, 'corrupt.jpg', 'image/jpeg')},
        content_type='multipart/form-data',
        headers=headers
    )
    assert res_corrupt.status_code in (415, 422)

def test_image_exif_orientation_preserved_and_gps_stripped(client):
    """19. Respetar la orientación visual (exif_transpose) antes de descartar metadatos EXIF / GPSInfo auténticos."""
    from PIL import ExifTags
    token, headers = _register_and_create_profile(client, 'exif.orientation@afinia.com')

    # Crear imagen 200 de ancho x 100 de alto con orientación EXIF = 6 (rotación 90° en sentido horario) y GPSInfo real
    # Al aplicar exif_transpose, la imagen visual debe transformarse en 100 x 200
    img_buf = _create_synthetic_image('JPEG', width=200, height=100, orientation=6, with_gps=True)

    # 1. Verificar que la imagen original contiene la etiqueta 0x8825 (GPSInfo) y orientación 6
    orig_img = Image.open(io.BytesIO(img_buf.getvalue()))
    orig_exif = orig_img.getexif()
    assert orig_exif[0x0112] == 6
    assert 0x8825 in orig_exif or ExifTags.IFD.GPSInfo in orig_exif

    res = client.post(
        '/api/v1/profile/photos',
        data={'file': (img_buf, 'oriented.jpg', 'image/jpeg')},
        content_type='multipart/form-data',
        headers=headers
    )
    assert res.status_code == 201
    photo_id = res.get_json()['data']['id']

    # Descargar la imagen saneada resultante mediante Bearer token
    media_res = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=headers)
    assert media_res.status_code == 200

    clean_img = Image.open(io.BytesIO(media_res.data))
    # 2. Verificar que la orientación se respetó (200x100 rotada 90° es 100x200)
    assert clean_img.size == (100, 200)

    # 3. Verificar que los metadatos GPSInfo y EXIF sensibles fueron totalmente eliminados
    clean_exif = clean_img.getexif()
    assert 0x8825 not in clean_exif
    assert ExifTags.IFD.GPSInfo not in clean_exif
    assert len(clean_exif.get_ifd(ExifTags.IFD.GPSInfo)) == 0
    assert 0x010e not in clean_exif
    assert 0x010f not in clean_exif
    assert len(clean_exif) == 0

def test_photo_media_unauthenticated_and_rejected_access(client):
    """20. Todas las fotos requieren autenticación (401 si anónimo) y se protegen fotos rechazadas."""
    token_a, headers_a = _register_and_create_profile(client, 'media.unauth.a@afinia.com')
    token_b, headers_b = _register_and_create_profile(client, 'media.unauth.b@afinia.com')

    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'photo.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers_a).get_json()['data']
    photo_id = photo['id']

    # 1. Petición sin autenticación a foto 'pending' -> 401 UNAUTHORIZED
    res_no_auth_pending = client.get(f"/api/v1/profile/photos/media/{photo_id}")
    assert res_no_auth_pending.status_code == 401

    # 2. Petición con status 'rejected':
    db_photo = db.session.get(ProfilePhoto, photo_id)
    db_photo.status = 'rejected'
    db.session.commit()

    # Usuario anónimo -> 401 UNAUTHORIZED
    assert client.get(f"/api/v1/profile/photos/media/{photo_id}").status_code == 401
    # Usuario ajeno -> 403 FORBIDDEN
    assert client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=headers_b).status_code == 403
    # Propietario con token -> 200 OK (puede verla para saber cuál fue rechazada y sustituirla)
    res_owner_rejected = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=headers_a)
    assert res_owner_rejected.status_code == 200

    # 3. Transicionar a 'ready':
    db_photo.status = 'ready'
    db.session.commit()

    # Petición anónima a foto 'ready' -> 401 UNAUTHORIZED (¡Ninguna foto es pública anónimamente!)
    res_ready_anon = client.get(f"/api/v1/profile/photos/media/{photo_id}")
    assert res_ready_anon.status_code == 401

    # Petición autenticada de usuario ajeno a foto 'ready' sin bloqueo -> 200 OK
    res_ready_auth = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=headers_b)
    assert res_ready_auth.status_code == 200
    assert 'private' in res_ready_auth.headers.get('Cache-Control', '')
    assert 'public' not in res_ready_auth.headers.get('Cache-Control', '')
    assert res_ready_auth.headers.get('X-Content-Type-Options') == 'nosniff'

def test_photo_media_blob_download_with_bearer(client):
    """21. Descarga binaria autenticada con Bearer JWT (simulación HttpClient / Blob en Ionic)."""
    token, headers = _register_and_create_profile(client, 'media.blob@afinia.com')

    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'blob_photo.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    photo_id = photo['id']

    # Solicitud HTTP GET con cabecera Authorization: Bearer <token>
    res_media = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=headers)
    assert res_media.status_code == 200
    assert res_media.content_type == 'image/jpeg'
    assert res_media.headers.get('Cache-Control') == 'private, no-cache, no-store, must-revalidate'
    assert res_media.headers.get('Pragma') == 'no-cache'
    assert res_media.headers.get('X-Content-Type-Options') == 'nosniff'

    # Verificar que el payload binario es una imagen íntegra y decodificable
    downloaded_img = Image.open(io.BytesIO(res_media.data))
    assert downloaded_img.format == 'JPEG'
    assert downloaded_img.size == (120, 120)

def test_photo_media_user_block_privacy_restriction(client):
    """22. Restricción de bloqueos en ambas direcciones y comprobación de elusión anónima imposible."""
    token_a, headers_a = _register_and_create_profile(client, 'blocker.a@afinia.com')
    token_b, headers_b = _register_and_create_profile(client, 'blocked.b@afinia.com')

    user_a = User.query.filter_by(email='blocker.a@afinia.com').first()
    user_b = User.query.filter_by(email='blocked.b@afinia.com').first()

    # Usuario A sube foto ready
    buf_a = _create_synthetic_image('JPEG')
    photo_a = client.post('/api/v1/profile/photos', data={'file': (buf_a, 'photo_a.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers_a).get_json()['data']
    photo_a_id = photo_a['id']
    approve_photo_for_qa(photo_a_id)

    # Usuario B sube foto ready
    buf_b = _create_synthetic_image('JPEG')
    photo_b = client.post('/api/v1/profile/photos', data={'file': (buf_b, 'photo_b.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers_b).get_json()['data']
    photo_b_id = photo_b['id']
    approve_photo_for_qa(photo_b_id)

    # Antes del bloqueo: ambos usuarios autenticados pueden ver la foto del otro
    assert client.get(f"/api/v1/profile/photos/media/{photo_a_id}", headers=headers_b).status_code == 200
    assert client.get(f"/api/v1/profile/photos/media/{photo_b_id}", headers=headers_a).status_code == 200

    # Crear bloqueo: Usuario A bloquea a Usuario B
    block = UserBlock(blocker_user_id=user_a.id, blocked_user_id=user_b.id)
    db.session.add(block)
    db.session.commit()

    # PRUEBA OBLIGATORIA:
    # 1. B intenta consultar la foto ready de A con su JWT -> 403 FORBIDDEN
    res_b_with_jwt = client.get(f"/api/v1/profile/photos/media/{photo_a_id}", headers=headers_b)
    assert res_b_with_jwt.status_code == 403
    assert res_b_with_jwt.get_json()['error']['code'] == 'FORBIDDEN'

    # 2. B intenta consultar la misma URL sin credenciales -> 401 UNAUTHORIZED (Imposible eludir el bloqueo)
    res_b_anon = client.get(f"/api/v1/profile/photos/media/{photo_a_id}")
    assert res_b_anon.status_code == 401
    assert res_b_anon.get_json()['error']['code'] == 'UNAUTHORIZED'

    # 3. Bidireccionalidad: A intenta consultar la foto ready de B -> 403 FORBIDDEN
    res_a_with_jwt = client.get(f"/api/v1/profile/photos/media/{photo_b_id}", headers=headers_a)
    assert res_a_with_jwt.status_code == 403
    assert res_a_with_jwt.get_json()['error']['code'] == 'FORBIDDEN'

def test_onboarding_lifecycle_status_coherence_and_suspended_isolation(client):
    """23. Coherencia de onboarding y ciclo de vida: suspended y deactivated nunca completan onboarding."""
    email = 'onboard.lifecycle@afinia.com'
    token, headers = _register_and_create_profile(client, email)

    client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['femenino'],
        'min_age': 22,
        'max_age': 32
    }, headers=headers)

    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'main.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    approve_photo_for_qa(photo['id'])

    user = User.query.filter_by(email=email).first()
    user.email_verified = True
    db.session.commit()

    # Caso completo positivo: al cumplirse todos los requisitos, se activa atómicamente a 'active'
    me_data = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me_data['onboarding_complete'] is True
    assert me_data['status'] == 'active'  # Coherente con BE-02.3: se activa automáticamente al estar completo

    # Si la cuenta está suspendida por moderación:
    user.lifecycle_status = 'suspended'
    db.session.commit()
    assert is_onboarding_complete(user) is False

    # Si la cuenta está desactivada por el usuario:
    user.lifecycle_status = 'deactivated'
    db.session.commit()
    assert is_onboarding_complete(user) is False
