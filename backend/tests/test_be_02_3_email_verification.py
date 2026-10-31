import io
import time
import uuid
import threading
from datetime import datetime, timezone, timedelta
from PIL import Image
import pytest

from app import db
from app.models import User, Profile, ProfilePhoto, DiscoveryPreference, RefreshToken, EmailVerificationToken
from app.services.email_service import email_service
from app.services.profile_service import is_onboarding_complete, approve_photo_for_qa, sync_user_lifecycle_status

def _as_utc(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _create_synthetic_image(fmt='JPEG', color=(100, 150, 200), width=100, height=100) -> io.BytesIO:
    img = Image.new('RGB', (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf

def _register_user(client, email='verify.user@afinia.com', password='SecurePassword2026!'):
    email_service.clear_sent_messages()
    res = client.post('/api/v1/auth/register', json={
        'email': email,
        'password': password,
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    return res

def _login_user(client, email='verify.user@afinia.com', password='SecurePassword2026!'):
    res = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': password
    }, headers={'X-Client-Platform': 'mobile'})
    token = res.get_json()['data']['access_token']
    return token, {'Authorization': f'Bearer {token}'}

# =========================================================================
# PRUEBAS BE-02.3: VERIFICACIÓN DE CORREO Y ACTIVACIÓN DE CUENTAS
# =========================================================================

def test_register_generates_verification_request_and_captures_token(client):
    """1. Registro genera solicitud de verificación en BD y captura de token desacoplado."""
    email = 'reg.token@afinia.com'
    res = _register_user(client, email)
    assert res.status_code == 201

    user = User.query.filter_by(email=email).first()
    assert user is not None

    tokens = EmailVerificationToken.query.filter_by(user_id=user.id).all()
    assert len(tokens) == 1
    token_record = tokens[0]
    assert token_record.consumed_at is None
    assert token_record.revoked_at is None
    assert _as_utc(token_record.expires_at) > datetime.now(timezone.utc)

    # Token capturable en memoria por la infraestructura de pruebas desacoplada
    raw_token = email_service.get_last_token_for(email)
    assert raw_token is not None
    assert len(raw_token) >= 32

def test_new_account_maintains_email_verified_false(client):
    """2. Cuenta nueva mantiene email_verified=False y status='pending_profile'."""
    email = 'unverified.initial@afinia.com'
    res = _register_user(client, email)
    data = res.get_json()['data']

    assert data['email_verified'] is False
    assert data['status'] == 'pending_profile'
    assert data['onboarding_complete'] is False

    user = User.query.filter_by(email=email).first()
    assert user.email_verified is False
    assert user.lifecycle_status == 'pending_profile'

def test_valid_token_verifies_email_successfully(client):
    """3. Token válido confirma correo y responde 204 No Content sin cuerpo."""
    email = 'valid.token@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)

    res_verify = client.post('/api/v1/auth/verify-email', json={'token': raw_token})
    assert res_verify.status_code == 204
    assert res_verify.data == b''  # Sin cuerpo JSON

    user = User.query.filter_by(email=email).first()
    assert user.email_verified is True

    token_record = EmailVerificationToken.query.filter_by(user_id=user.id).first()
    assert token_record.consumed_at is not None

def test_invalid_token_rejected_422(client):
    """4. Token inválido, inexistente o vacío es rechazado con 422 VALIDATION_ERROR."""
    res_fake = client.post('/api/v1/auth/verify-email', json={'token': 'non-existent-token-12345'})
    assert res_fake.status_code == 422
    assert res_fake.get_json()['error']['code'] == 'VALIDATION_ERROR'

    res_empty = client.post('/api/v1/auth/verify-email', json={'token': '   '})
    assert res_empty.status_code == 422
    assert res_empty.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_expired_token_rejected_422(client):
    """5. Token caducado es rechazado con 422 VALIDATION_ERROR."""
    email = 'expired.token@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)

    user = User.query.filter_by(email=email).first()
    token_record = EmailVerificationToken.query.filter_by(user_id=user.id).first()
    # Simular expiración en el pasado
    token_record.expires_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.session.commit()

    res_verify = client.post('/api/v1/auth/verify-email', json={'token': raw_token})
    assert res_verify.status_code == 422
    assert res_verify.get_json()['error']['code'] == 'VALIDATION_ERROR'
    assert 'expirado' in res_verify.get_json()['error']['message'].lower()

    # Usuario permanece sin verificar
    assert User.query.filter_by(email=email).first().email_verified is False

def test_consumed_token_cannot_be_reused_409(client):
    """6. Token consumido no puede reutilizarse (409 CONFLICT)."""
    email = 'reuse.token@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)

    # Primer consumo exitoso
    assert client.post('/api/v1/auth/verify-email', json={'token': raw_token}).status_code == 204

    # Segundo intento con el mismo token -> 409 CONFLICT
    res_reuse = client.post('/api/v1/auth/verify-email', json={'token': raw_token})
    assert res_reuse.status_code == 409
    assert res_reuse.get_json()['error']['code'] == 'CONFLICT'

def test_resend_revokes_previous_token(client):
    """7. Reenvío revoca el token anterior del mismo usuario y emite uno nuevo funcional."""
    email = 'resend.revoke@afinia.com'
    _register_user(client, email)
    initial_token = email_service.get_last_token_for(email)

    _, headers = _login_user(client, email)

    # Simular que transcurrió el cooldown de reenvío
    user = User.query.filter_by(email=email).first()
    first_token_record = EmailVerificationToken.query.filter_by(user_id=user.id).first()
    first_token_record.created_at = datetime.now(timezone.utc) - timedelta(seconds=70)
    db.session.commit()

    # Solicitar reenvío
    res_resend = client.post('/api/v1/auth/resend-verification', headers=headers)
    assert res_resend.status_code == 202
    assert res_resend.get_json()['data']['status'] == 'accepted'

    new_token = email_service.get_last_token_for(email)
    assert new_token != initial_token

    # Verificar que el token inicial quedó revocado en BD
    db.session.refresh(first_token_record)
    assert first_token_record.revoked_at is not None

    # Intentar verificar con el token viejo -> 422 VALIDATION_ERROR (revocado)
    res_old = client.post('/api/v1/auth/verify-email', json={'token': initial_token})
    assert res_old.status_code == 422
    assert 'revocado' in res_old.get_json()['error']['message'].lower()

    # Verificar con el nuevo token -> 204 No Content exitoso
    res_new = client.post('/api/v1/auth/verify-email', json={'token': new_token})
    assert res_new.status_code == 204
    assert User.query.filter_by(email=email).first().email_verified is True

def test_resend_rate_limiting_enforced_429(client):
    """8. Rate limiting de reenvíos: rechaza solicitudes dentro de la ventana de cooldown."""
    email = 'resend.ratelimit@afinia.com'
    _register_user(client, email)
    _, headers = _login_user(client, email)

    # El registro acaba de emitir un token hace < 60 segundos
    res_early = client.post('/api/v1/auth/resend-verification', headers=headers)
    assert res_early.status_code == 429
    assert res_early.get_json()['error']['code'] == 'RATE_LIMITED'

def test_concurrent_verification_single_success(app):
    """9. Verificación concurrente del mismo token: exactamente una solicitud consume exitosamente."""
    with app.test_client() as client:
        email = 'concurrent.verify@afinia.com'
        _register_user(client, email)
        raw_token = email_service.get_last_token_for(email)

    results = []

    def attempt_verify():
        with app.app_context():
            try:
                c = app.test_client()
                r = c.post('/api/v1/auth/verify-email', json={'token': raw_token})
                results.append(r.status_code)
            finally:
                db.session.remove()

    t1 = threading.Thread(target=attempt_verify)
    t2 = threading.Thread(target=attempt_verify)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Un thread debe obtener 204 y el otro 409 (token ya consumido)
    assert 204 in results
    assert 409 in results

def test_concurrent_resend_isolation(app):
    """10. Reenvíos concurrentes manejan la revocación atómica."""
    with app.test_client() as client:
        email = 'concurrent.resend@afinia.com'
        _register_user(client, email)
        token_auth, headers = _login_user(client, email)

        # Ajustar fecha del token inicial para que no bloquee por cooldown
        user = User.query.filter_by(email=email).first()
        t0 = EmailVerificationToken.query.filter_by(user_id=user.id).first()
        t0.created_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        db.session.commit()

    results = []

    def attempt_resend():
        with app.app_context():
            try:
                c = app.test_client()
                r = c.post('/api/v1/auth/resend-verification', headers=headers)
                results.append(r.status_code)
            finally:
                db.session.remove()

    t1 = threading.Thread(target=attempt_resend)
    t2 = threading.Thread(target=attempt_resend)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Al menos una es aceptada con 202, y si coinciden rápidamente la segunda recibe 429 por cooldown
    assert 202 in results

def test_tokens_not_exposed_in_http_responses(client):
    """11. Ausencia absoluta de tokens o hashes en respuestas HTTP JSON o cabeceras."""
    email = 'no.leak@afinia.com'
    res_reg = _register_user(client, email)
    reg_json = res_reg.get_json()

    assert 'token' not in reg_json['data']
    assert 'token_hash' not in reg_json['data']
    assert 'verification' not in reg_json['data']

    # Login
    res_log = client.post('/api/v1/auth/login', json={'email': email, 'password': 'SecurePassword2026!'}, headers={'X-Client-Platform': 'mobile'})
    log_json = res_log.get_json()
    assert 'verification_token' not in log_json['data']

    # /auth/me
    token = log_json['data']['access_token']
    res_me = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
    me_json = res_me.get_json()
    assert 'token' not in me_json['data']

def test_email_transport_failure_resilience(client):
    """12. Fallo de transporte de correo: cuenta permanece pending_profile y recuperable por reenvío."""
    email = 'transport.fail@afinia.com'
    email_service.set_simulate_failure(True)

    try:
        res = _register_user(client, email)
        # El registro concluye exitosamente con 201 (el fallo en transporte se absorbe en logger)
        assert res.status_code == 201
        assert res.get_json()['data']['email_verified'] is False
    finally:
        email_service.set_simulate_failure(False)

    # La cuenta existe en BD y puede iniciar sesión
    token, headers = _login_user(client, email)

    # Cooldown vencido para permitir reenvío
    user = User.query.filter_by(email=email).first()
    t0 = EmailVerificationToken.query.filter_by(user_id=user.id).first()
    t0.created_at = datetime.now(timezone.utc) - timedelta(seconds=70)
    db.session.commit()

    # Reenvío ahora funciona normalmente
    res_resend = client.post('/api/v1/auth/resend-verification', headers=headers)
    assert res_resend.status_code == 202
    assert email_service.get_last_token_for(email) is not None

def test_verification_before_completing_profile(client):
    """13. Verificación de correo antes de completar perfil: email_verified=True pero status sigue pending_profile."""
    email = 'verify.first@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)

    assert client.post('/api/v1/auth/verify-email', json={'token': raw_token}).status_code == 204

    token, headers = _login_user(client, email)
    me_data = client.get('/api/v1/auth/me', headers=headers).get_json()['data']

    assert me_data['email_verified'] is True
    assert me_data['onboarding_complete'] is False
    assert me_data['status'] == 'pending_profile'

def test_complete_profile_before_verification(client):
    """14. Perfil completo antes de verificar correo: status sigue pending_profile hasta verificar correo."""
    email = 'profile.first@afinia.com'
    _register_user(client, email)
    token, headers = _login_user(client, email)

    # Crear perfil
    client.post('/api/v1/profile/', json={
        'first_name': 'Camila',
        'birth_date': '1998-05-20',
        'gender': 'femenino'
    }, headers=headers)

    # Guardar preferencias
    client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['masculino'],
        'min_age': 20,
        'max_age': 35
    }, headers=headers)

    # Subir y aprobar foto principal
    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'photo.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    approve_photo_for_qa(photo['id'])

    # Aún sin verificar correo -> status pending_profile
    me_data = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me_data['email_verified'] is False
    assert me_data['onboarding_complete'] is False
    assert me_data['status'] == 'pending_profile'

def test_activation_when_all_requirements_met(client):
    """15. Activación atómica tras cumplirse todos los requisitos: pending_profile -> active."""
    email = 'full.activation@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)
    token, headers = _login_user(client, email)

    client.post('/api/v1/profile/', json={
        'first_name': 'Mateo',
        'birth_date': '1995-10-15',
        'gender': 'masculino'
    }, headers=headers)

    client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['femenino'],
        'min_age': 21,
        'max_age': 30
    }, headers=headers)

    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'photo.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    approve_photo_for_qa(photo['id'])

    # Verificar correo (último requisito que faltaba)
    res_v = client.post('/api/v1/auth/verify-email', json={'token': raw_token})
    assert res_v.status_code == 204

    # Estado ahora debe ser 'active' y onboarding_complete=True
    me_data = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me_data['email_verified'] is True
    assert me_data['onboarding_complete'] is True
    assert me_data['status'] == 'active'

def test_activation_when_ready_photo_arrives_after_email_verification(client):
    """16. Activación cuando la foto ready llega después de la verificación del correo."""
    email = 'photo.last@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)
    token, headers = _login_user(client, email)

    # 1. Verificar correo primero
    assert client.post('/api/v1/auth/verify-email', json={'token': raw_token}).status_code == 204

    # 2. Crear perfil
    client.post('/api/v1/profile/', json={
        'first_name': 'Lucia',
        'birth_date': '2000-01-01',
        'gender': 'femenino'
    }, headers=headers)

    # 3. Guardar preferencias
    client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['masculino', 'femenino'],
        'min_age': 18,
        'max_age': 40
    }, headers=headers)

    # 4. Subir foto (queda en pending)
    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'photo.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    photo_id = photo['id']

    # En este punto falta la aprobación de la foto -> pending_profile
    assert client.get('/api/v1/auth/me', headers=headers).get_json()['data']['status'] == 'pending_profile'

    # 5. La foto es aprobada por moderación/QA -> dispara activación a 'active'
    approve_photo_for_qa(photo_id)

    me_data = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me_data['status'] == 'active'
    assert me_data['onboarding_complete'] is True

def test_suspended_account_cannot_reactivate(client):
    """17. Cuenta suspendida por moderación jamás se reactiva automáticamente."""
    email = 'suspended.lock@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)

    user = User.query.filter_by(email=email).first()
    user.lifecycle_status = 'suspended'
    db.session.commit()

    # Intentar verificar email con token válido en cuenta suspendida -> 409 CONFLICT (OpenAPI v1)
    res_v = client.post('/api/v1/auth/verify-email', json={'token': raw_token})
    assert res_v.status_code == 409
    assert res_v.get_json()['error']['code'] == 'CONFLICT'

    # Estado permanece suspendido
    db.session.refresh(user)
    assert user.lifecycle_status == 'suspended'
    assert is_onboarding_complete(user) is False

def test_deactivated_account_cannot_reactivate(client):
    """18. Cuenta desactivada por el usuario jamás se reactiva automáticamente."""
    email = 'deactivated.lock@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)

    user = User.query.filter_by(email=email).first()
    user.lifecycle_status = 'deactivated'
    db.session.commit()

    res_v = client.post('/api/v1/auth/verify-email', json={'token': raw_token})
    assert res_v.status_code == 409
    assert res_v.get_json()['error']['code'] == 'CONFLICT'

    db.session.refresh(user)
    assert user.lifecycle_status == 'deactivated'
    assert is_onboarding_complete(user) is False

def test_auth_me_coherence_with_lifecycle_and_onboarding(client):
    """19. Coherencia integral entre /auth/me y /profile/."""
    email = 'coherence.user@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)
    token, headers = _login_user(client, email)

    client.post('/api/v1/profile/', json={'first_name': 'Daniel', 'birth_date': '1992-03-10', 'gender': 'masculino'}, headers=headers)
    client.put('/api/v1/profile/discovery-preferences', json={'interested_in_genders': ['femenino'], 'min_age': 25, 'max_age': 35}, headers=headers)
    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'photo.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    approve_photo_for_qa(photo['id'])
    client.post('/api/v1/auth/verify-email', json={'token': raw_token})

    me_res = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    prof_res = client.get('/api/v1/profile/', headers=headers).get_json()['data']

    assert me_res['status'] == 'active'
    assert me_res['onboarding_complete'] is True
    assert prof_res['onboarding_complete'] is True

def test_subsequent_loss_of_activation_requirement(client):
    """20. Pérdida posterior de requisito: cuenta active vuelve a pending_profile de forma controlada."""
    email = 'loss.req@afinia.com'
    _register_user(client, email)
    raw_token = email_service.get_last_token_for(email)
    token, headers = _login_user(client, email)

    client.post('/api/v1/profile/', json={'first_name': 'Sofia', 'birth_date': '1996-08-14', 'gender': 'femenino'}, headers=headers)
    client.put('/api/v1/profile/discovery-preferences', json={'interested_in_genders': ['masculino'], 'min_age': 20, 'max_age': 30}, headers=headers)
    buf = _create_synthetic_image('JPEG')
    photo = client.post('/api/v1/profile/photos', data={'file': (buf, 'photo.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers).get_json()['data']
    photo_id = photo['id']
    approve_photo_for_qa(photo_id)
    client.post('/api/v1/auth/verify-email', json={'token': raw_token})

    # Cuenta activa
    assert client.get('/api/v1/auth/me', headers=headers).get_json()['data']['status'] == 'active'

    # El usuario elimina su única foto ready
    del_res = client.delete(f'/api/v1/profile/photos/{photo_id}', headers=headers)
    assert del_res.status_code == 204

    # Estado debe retroceder a pending_profile para impedir descubrimiento sin foto
    me_after = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me_after['status'] == 'pending_profile'
    assert me_after['onboarding_complete'] is False

def test_openapi_http_contract_compliance(client):
    """21. Cumplimiento estricto de esquemas y códigos HTTP según OpenAPI v1."""
    # 21.1 /verify-email sin Content-Type JSON -> 400
    res_no_json = client.post('/api/v1/auth/verify-email', data='token=abc')
    assert res_no_json.status_code == 400

    # 21.2 /verify-email con campos adicionales no permitidos -> 400 BAD_REQUEST
    res_extra = client.post('/api/v1/auth/verify-email', json={'token': 'test', 'extra_field': 'not_allowed'})
    assert res_extra.status_code == 400
    assert res_extra.get_json()['error']['code'] == 'BAD_REQUEST'

    # 21.3 /verify-email sin token -> 422 VALIDATION_ERROR
    res_missing = client.post('/api/v1/auth/verify-email', json={})
    assert res_missing.status_code == 422
    assert res_missing.get_json()['error']['code'] == 'VALIDATION_ERROR'

    # 21.4 /resend-verification sin autenticación -> 401 UNAUTHORIZED
    res_unauth = client.post('/api/v1/auth/resend-verification')
    assert res_unauth.status_code == 401
    assert res_unauth.get_json()['error']['code'] == 'UNAUTHORIZED'

def test_no_regression_authentication_and_photos(client):
    """22. No regresión en el flujo completo de autenticación y fotos."""
    email = 'regression.check@afinia.com'
    _register_user(client, email)
    token, headers = _login_user(client, email)

    client.post('/api/v1/profile/', json={'first_name': 'Esteban', 'birth_date': '1990-12-05', 'gender': 'masculino'}, headers=headers)
    buf = _create_synthetic_image('JPEG')
    photo_res = client.post('/api/v1/profile/photos', data={'file': (buf, 'reg_photo.jpg', 'image/jpeg')}, content_type='multipart/form-data', headers=headers)
    assert photo_res.status_code == 201

    # Descarga binaria con Bearer
    photo_id = photo_res.get_json()['data']['id']
    media_res = client.get(f'/api/v1/profile/photos/media/{photo_id}', headers=headers)
    assert media_res.status_code == 200
    assert media_res.content_type == 'image/jpeg'

def test_resend_smtp_failure_preserves_old_token_and_does_not_persist_new_token(client):
    """23. Fallo en transporte SMTP durante reenvío: no invalida token anterior ni persiste token huérfano."""
    email = 'smtp.resend.fail@afinia.com'
    _register_user(client, email)
    initial_token = email_service.get_last_token_for(email)
    user = User.query.filter_by(email=email).first()
    t0 = EmailVerificationToken.query.filter_by(user_id=user.id).first()

    # Vencer cooldown
    t0.created_at = datetime.now(timezone.utc) - timedelta(seconds=70)
    db.session.commit()

    token, headers = _login_user(client, email)

    # Simular fallo en transporte de correo
    email_service.set_simulate_failure(True)
    try:
        res_resend = client.post('/api/v1/auth/resend-verification', headers=headers)
        assert res_resend.status_code == 500
        assert res_resend.get_json()['error']['code'] == 'INTERNAL_ERROR'
    finally:
        email_service.set_simulate_failure(False)

    # El token inicial permanece intacto y NO revocado
    db.session.refresh(t0)
    assert t0.revoked_at is None
    assert t0.consumed_at is None

    # NO se persistió un nuevo token en BD
    total_tokens = EmailVerificationToken.query.filter_by(user_id=user.id).count()
    assert total_tokens == 1

    # El usuario todavía puede verificar su cuenta con el token inicial que tiene en su buzón
    res_verify = client.post('/api/v1/auth/verify-email', json={'token': initial_token})
    assert res_verify.status_code == 204
    db.session.refresh(user)
    assert user.email_verified is True

def test_production_mode_forbids_in_memory_mail_backend():
    """24. Modo producción prohíbe terminantemente el adaptador in_memory sin SMTP."""
    import os
    import importlib
    import config

    old_env = os.environ.get('ENVIRONMENT')
    old_backend = os.environ.get('MAIL_BACKEND')
    old_host = os.environ.get('SMTP_HOST')
    old_sec = os.environ.get('SECRET_KEY')

    try:
        os.environ['ENVIRONMENT'] = 'production'
        os.environ['SECRET_KEY'] = 'a-very-long-production-cryptographic-secret-key-32chars!'
        os.environ['DATABASE_URL'] = 'postgresql://afinia_user:afinia_password@localhost:5432/afinia_db'
        os.environ['MAIL_BACKEND'] = 'in_memory'
        os.environ.pop('SMTP_HOST', None)

        with pytest.raises(RuntimeError) as exc_info:
            importlib.reload(config)
        assert 'in_memory' in str(exc_info.value).lower()
    finally:
        if old_env is not None:
            os.environ['ENVIRONMENT'] = old_env
        else:
            os.environ.pop('ENVIRONMENT', None)
        if old_backend is not None:
            os.environ['MAIL_BACKEND'] = old_backend
        else:
            os.environ.pop('MAIL_BACKEND', None)
        if old_host is not None:
            os.environ['SMTP_HOST'] = old_host
        else:
            os.environ.pop('SMTP_HOST', None)
        if old_sec is not None:
            os.environ['SECRET_KEY'] = old_sec
        else:
            os.environ.pop('SECRET_KEY', None)
        importlib.reload(config)

