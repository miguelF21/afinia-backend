import json
import time
import pytest
from datetime import datetime, timedelta, timezone
from app import db
from app.models.user import User
from app.models.auth import RefreshToken
from app.models.legal import LegalConsent
from app.utils.security import create_access_token, hash_refresh_token

def test_register_valid(client):
    """1. Registro válido con contrato OpenAPI UserBrief."""
    payload = {
        'email': 'valid.user@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    res = client.post('/api/v1/auth/register', json=payload)
    assert res.status_code == 201
    body = res.get_json()
    assert 'data' in body
    data = body['data']
    assert data['email'] == 'valid.user@afinia.com'
    assert data['status'] == 'pending_profile'
    assert data['onboarding_complete'] is False
    assert data['email_verified'] is False
    assert 'id' in data
    # No exponer campos sensibles
    assert 'password_hash' not in data
    assert 'role' not in data

def test_register_duplicate_email(client):
    """2. Registro con correo duplicado (mismo correo en distintas mayúsculas)."""
    payload1 = {
        'email': 'duplicate@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    res1 = client.post('/api/v1/auth/register', json=payload1)
    assert res1.status_code == 201

    payload2 = {
        'email': 'DUPLICATE@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    res2 = client.post('/api/v1/auth/register', json=payload2)
    assert res2.status_code == 409
    body2 = res2.get_json()
    assert 'error' in body2
    assert body2['error']['code'] == 'CONFLICT'

def test_register_password_policy(client):
    """3. Validación de longitud de contraseña (mínimo 12, máximo 128 según OpenAPI)."""
    # Menor a 12
    short_payload = {
        'email': 'shortpass@afinia.com',
        'password': 'Short1!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    res_short = client.post('/api/v1/auth/register', json=short_payload)
    assert res_short.status_code == 422
    assert res_short.get_json()['error']['code'] == 'VALIDATION_ERROR'

    # Mayor a 128
    long_payload = {
        'email': 'longpass@afinia.com',
        'password': 'A' * 129,
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    res_long = client.post('/api/v1/auth/register', json=long_payload)
    assert res_long.status_code == 422
    assert res_long.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_register_reject_malicious_role(client):
    """4. Rechazo de campo role malicioso (prevención mass assignment)."""
    payload = {
        'email': 'hacker@afinia.com',
        'password': 'StrongPassword2026!',
        'role': 'admin',
        'lifecycle_status': 'active',
        'is_active': False,
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    res = client.post('/api/v1/auth/register', json=payload)
    assert res.status_code == 400
    assert res.get_json()['error']['code'] == 'BAD_REQUEST'
    # Confirmar que no se creó ningún registro
    user = User.query.filter_by(email='hacker@afinia.com').first()
    assert user is None

def test_register_missing_consents(client):
    """5. Registro sin consentimientos legales requeridos."""
    payload_no_terms = {
        'email': 'noterms@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_privacy_version': 'v1-draft'
    }
    res = client.post('/api/v1/auth/register', json=payload_no_terms)
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_register_unapproved_legal_versions(client):
    """6. Rechazo de versiones legales no vigentes o no aprobadas."""
    payload = {
        'email': 'badversion@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v99-unapproved',
        'accept_privacy_version': 'v1-draft'
    }
    res = client.post('/api/v1/auth/register', json=payload)
    assert res.status_code == 400
    assert res.get_json()['error']['code'] == 'BAD_REQUEST'

def test_register_atomic_persistence(client):
    """7. Persistencia atómica de usuario y consentimientos (User + 2 LegalConsent)."""
    payload = {
        'email': 'atomic@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    res = client.post('/api/v1/auth/register', json=payload)
    assert res.status_code == 201
    user = User.query.filter_by(email='atomic@afinia.com').first()
    assert user is not None
    assert user.role == 'user'
    assert user.lifecycle_status == 'pending_profile'
    consents = LegalConsent.query.filter_by(user_id=user.id).all()
    assert len(consents) == 2
    consent_types = {c.document_type for c in consents}
    assert consent_types == {'terms_of_service', 'privacy_policy'}

def test_login_valid(client):
    """8. Login válido y generación de AuthSession."""
    reg = client.post('/api/v1/auth/register', json={
        'email': 'login.valid@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    assert reg.status_code == 201

    res = client.post('/api/v1/auth/login', json={
        'email': 'login.valid@afinia.com',
        'password': 'StrongPassword2026!'
    })
    assert res.status_code == 200
    body = res.get_json()
    assert 'data' in body
    auth_session = body['data']
    assert 'access_token' in auth_session
    assert auth_session['token_type'] == 'Bearer'
    assert auth_session['expires_in'] == 900
    assert auth_session['user']['email'] == 'login.valid@afinia.com'
    # Cookie por defecto para web
    cookies = res.headers.getlist('Set-Cookie')
    assert any('refresh_token=' in c and 'HttpOnly' in c for c in cookies)

def test_login_invalid_credentials_anti_enumeration(client):
    """9. Login incorrecto: respuesta genérica anti-enumeración tanto para usuario inexistente como clave errónea."""
    # Usuario inexistente
    res1 = client.post('/api/v1/auth/login', json={
        'email': 'nonexistent@afinia.com',
        'password': 'StrongPassword2026!'
    })
    assert res1.status_code == 401
    body1 = res1.get_json()
    assert body1['error']['code'] == 'UNAUTHORIZED'

    # Usuario existente con clave errónea
    client.post('/api/v1/auth/register', json={
        'email': 'existspasswrong@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    res2 = client.post('/api/v1/auth/login', json={
        'email': 'existspasswrong@afinia.com',
        'password': 'WrongPassword123!'
    })
    assert res2.status_code == 401
    body2 = res2.get_json()
    assert body2['error']['code'] == 'UNAUTHORIZED'
    # Mensaje idéntico para evitar enumeración
    assert body1['error']['message'] == body2['error']['message']

def test_login_pending_profile(client):
    """10. Login de usuario pending_profile permitido para completar onboarding."""
    client.post('/api/v1/auth/register', json={
        'email': 'pending@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    res = client.post('/api/v1/auth/login', json={
        'email': 'pending@afinia.com',
        'password': 'StrongPassword2026!'
    })
    assert res.status_code == 200
    assert res.get_json()['data']['user']['status'] == 'pending_profile'

def test_login_suspended_account(client):
    """11. Login de usuario suspendido rechazado con 403 FORBIDDEN."""
    client.post('/api/v1/auth/register', json={
        'email': 'suspended@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    user = User.query.filter_by(email='suspended@afinia.com').first()
    user.lifecycle_status = 'suspended'
    db.session.commit()

    res = client.post('/api/v1/auth/login', json={
        'email': 'suspended@afinia.com',
        'password': 'StrongPassword2026!'
    })
    assert res.status_code == 403
    assert res.get_json()['error']['code'] == 'FORBIDDEN'

def test_login_deactivated_account(client):
    """12. Login de usuario desactivado rechazado con 401 UNAUTHORIZED."""
    client.post('/api/v1/auth/register', json={
        'email': 'deactivated@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    user = User.query.filter_by(email='deactivated@afinia.com').first()
    user.lifecycle_status = 'deactivated'
    db.session.commit()

    res = client.post('/api/v1/auth/login', json={
        'email': 'deactivated@afinia.com',
        'password': 'StrongPassword2026!'
    })
    assert res.status_code == 401
    assert res.get_json()['error']['code'] == 'UNAUTHORIZED'

def test_access_token_expired(client):
    """13. Access token vencido rechazado con 401 TOKEN_EXPIRED."""
    client.post('/api/v1/auth/register', json={
        'email': 'expiredjwt@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    user = User.query.filter_by(email='expiredjwt@afinia.com').first()
    expired_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        secret_key=client.application.config['SECRET_KEY'],
        expires_in=-10
    )

    res = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {expired_token}'})
    assert res.status_code == 401
    assert res.get_json()['error']['code'] == 'UNAUTHORIZED'
    assert 'expirado' in res.get_json()['error']['message'].lower()

def test_refresh_valid_rotation(client):
    """14. Refresh válido con rotación atómica y revocación del token previo."""
    client.post('/api/v1/auth/register', json={
        'email': 'refresh.user@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    login_res = client.post('/api/v1/auth/login', json={
        'email': 'refresh.user@afinia.com',
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    assert login_res.status_code == 200
    mobile_data = login_res.get_json()['data']
    old_refresh_token = mobile_data['refresh_token']
    assert old_refresh_token is not None

    # Ejecutar refresh
    ref_res = client.post('/api/v1/auth/refresh', json={
        'refresh_token': old_refresh_token
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref_res.status_code == 200
    ref_data = ref_res.get_json()['data']
    assert 'access_token' in ref_data
    new_refresh_token = ref_data['refresh_token']
    assert new_refresh_token != old_refresh_token

    # Verificar en BD que el viejo token esté revocado
    old_hash = hash_refresh_token(old_refresh_token)
    old_db_token = RefreshToken.query.filter_by(token_hash=old_hash).first()
    assert old_db_token.revoked_at is not None

def test_refresh_expired(client):
    """15. Refresh vencido rechazado con 401 UNAUTHORIZED."""
    client.post('/api/v1/auth/register', json={
        'email': 'expiredref@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    login_res = client.post('/api/v1/auth/login', json={
        'email': 'expiredref@afinia.com',
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    ref_token = login_res.get_json()['data']['refresh_token']

    # Forzar expiración en BD
    token_h = hash_refresh_token(ref_token)
    db_token = RefreshToken.query.filter_by(token_hash=token_h).first()
    db_token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.session.commit()

    ref_res = client.post('/api/v1/auth/refresh', json={
        'refresh_token': ref_token
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref_res.status_code == 401
    assert ref_res.get_json()['error']['code'] == 'UNAUTHORIZED'

def test_refresh_concurrent_retry_preserves_valid_session(client):
    """16.a Reintento concurrente inmediato: se rechaza la duplicada pero se preserva la sesión recién emitida."""
    client.post('/api/v1/auth/register', json={
        'email': 'concur.retry@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    log1 = client.post('/api/v1/auth/login', json={
        'email': 'concur.retry@afinia.com',
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    token_1 = log1.get_json()['data']['refresh_token']

    # Refresh exitoso: rota token_1 a token_2
    ref1 = client.post('/api/v1/auth/refresh', json={
        'refresh_token': token_1
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref1.status_code == 200
    token_2 = ref1.get_json()['data']['refresh_token']

    # Reintento concurrente inmediato con token_1 (dentro de los 15s de ventana de gracia)
    ref_retry = client.post('/api/v1/auth/refresh', json={
        'refresh_token': token_1
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref_retry.status_code == 401
    assert ref_retry.get_json()['error']['code'] == 'UNAUTHORIZED'

    # Verificar que token_2 NO fue revocado por el reintento y sigue siendo perfectamente válido
    ref2 = client.post('/api/v1/auth/refresh', json={
        'refresh_token': token_2
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref2.status_code == 200
    token_3 = ref2.get_json()['data']['refresh_token']
    assert token_3 != token_2

def test_refresh_delayed_reuse_triggers_compromise_revocation(client):
    """16.b Reutilización tardía sospechosa (>15s): detecta posible robo y revoca todas las sesiones."""
    client.post('/api/v1/auth/register', json={
        'email': 'delayed.reuse@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    log1 = client.post('/api/v1/auth/login', json={
        'email': 'delayed.reuse@afinia.com',
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    token_a = log1.get_json()['data']['refresh_token']

    # Rotación legítima
    ref1 = client.post('/api/v1/auth/refresh', json={
        'refresh_token': token_a
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref1.status_code == 200
    token_b = ref1.get_json()['data']['refresh_token']

    # Simular paso del tiempo: alterar revoked_at de token_a a 30 segundos en el pasado
    token_a_hash = hash_refresh_token(token_a)
    db_token = RefreshToken.query.filter_by(token_hash=token_a_hash).first()
    db_token.revoked_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    db.session.commit()

    # Reutilización tardía con token_a
    ref_delayed = client.post('/api/v1/auth/refresh', json={
        'refresh_token': token_a
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref_delayed.status_code == 401
    assert ref_delayed.get_json()['error']['code'] == 'UNAUTHORIZED'

    # Ahora token_b DEBE haber sido revocado como medida de contención de compromiso
    ref_b = client.post('/api/v1/auth/refresh', json={
        'refresh_token': token_b
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref_b.status_code == 401
    assert ref_b.get_json()['error']['code'] == 'UNAUTHORIZED'

def test_logout(client):
    """18. Logout revoca sesión, elimina cookie web y devuelve 204 No Content."""
    client.post('/api/v1/auth/register', json={
        'email': 'logout.user@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    login_res = client.post('/api/v1/auth/login', json={
        'email': 'logout.user@afinia.com',
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    data = login_res.get_json()['data']
    access_token = data['access_token']
    ref_token = data['refresh_token']

    # Logout
    logout_res = client.post('/api/v1/auth/logout', json={
        'refresh_token': ref_token
    }, headers={'Authorization': f'Bearer {access_token}'})
    assert logout_res.status_code == 204
    assert logout_res.data == b''

    # Verificar que el refresh token quedó revocado
    token_h = hash_refresh_token(ref_token)
    db_token = RefreshToken.query.filter_by(token_hash=token_h).first()
    assert db_token.revoked_at is not None

def test_me_authenticated(client):
    """19. Consulta /auth/me autenticada devuelve UserBrief estricto."""
    client.post('/api/v1/auth/register', json={
        'email': 'me.user@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    login_res = client.post('/api/v1/auth/login', json={
        'email': 'me.user@afinia.com',
        'password': 'StrongPassword2026!'
    })
    token = login_res.get_json()['data']['access_token']

    res = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert res.status_code == 200
    user_brief = res.get_json()['data']
    assert user_brief['email'] == 'me.user@afinia.com'
    assert user_brief['status'] == 'pending_profile'
    assert user_brief['onboarding_complete'] is False
    assert user_brief['email_verified'] is False
    assert 'id' in user_brief
    # Confirmar no exposición de datos privados
    assert 'password_hash' not in user_brief
    assert 'role' not in user_brief

def test_me_unauthenticated(client):
    """20. Consulta /auth/me sin token devuelve 401 UNAUTHORIZED."""
    res = client.get('/api/v1/auth/me')
    assert res.status_code == 401
    assert res.get_json()['error']['code'] == 'UNAUTHORIZED'

def test_web_vs_mobile_transport(client):
    """23. Dual transport: Cookie HttpOnly para Web vs JSON body para Mobile."""
    # Web (default)
    client.post('/api/v1/auth/register', json={
        'email': 'dual@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    res_web = client.post('/api/v1/auth/login', json={
        'email': 'dual@afinia.com',
        'password': 'StrongPassword2026!'
    })
    assert res_web.status_code == 200
    web_body = res_web.get_json()['data']
    assert 'refresh_token' not in web_body
    cookies = res_web.headers.getlist('Set-Cookie')
    assert any('refresh_token=' in c and 'HttpOnly' in c for c in cookies)

    # Mobile
    res_mobile = client.post('/api/v1/auth/login', json={
        'email': 'dual@afinia.com',
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    assert res_mobile.status_code == 200
    mobile_body = res_mobile.get_json()['data']
    assert mobile_body.get('refresh_token') is not None
    mobile_cookies = res_mobile.headers.getlist('Set-Cookie')
    assert not any('refresh_token=' in c for c in mobile_cookies)

def test_legal_current_endpoint(client):
    """Consulta de documentos legales vigentes GET /api/v1/legal/current."""
    res = client.get('/api/v1/legal/current')
    assert res.status_code == 200
    body = res.get_json()
    assert 'data' in body
    legal_data = body['data']
    assert legal_data['terms_version'] == 'v1-draft'
    assert legal_data['privacy_version'] == 'v1-draft'
    assert 'terms_url' in legal_data
    assert 'privacy_url' in legal_data

def test_csrf_cookie_rejected_for_unauthorized_origin(client):
    """24. Protección CSRF: Operación con cookie desde origen no autorizado es rechazada con 403."""
    client.post('/api/v1/auth/register', json={
        'email': 'csrf.victim@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    # Login web (establece cookie)
    res_log = client.post('/api/v1/auth/login', json={
        'email': 'csrf.victim@afinia.com',
        'password': 'StrongPassword2026!'
    })
    assert res_log.status_code == 200

    # Intento de refresh con cookie enviada automáticamente desde origen malicioso
    res_csrf = client.post('/api/v1/auth/refresh', headers={'Origin': 'http://malicious-attacker.com'})
    assert res_csrf.status_code == 403
    assert res_csrf.get_json()['error']['code'] == 'FORBIDDEN'

def test_csrf_cookie_allowed_for_legitimate_origin(client):
    """25. Petición con cookie desde origen legítimo (ej. Ionic web localhost:8100) es aceptada."""
    client.post('/api/v1/auth/register', json={
        'email': 'legit.ionic@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    client.post('/api/v1/auth/login', json={
        'email': 'legit.ionic@afinia.com',
        'password': 'StrongPassword2026!'
    })

    res_ok = client.post('/api/v1/auth/refresh', headers={'Origin': 'http://localhost:8100'})
    assert res_ok.status_code == 200
    assert 'access_token' in res_ok.get_json()['data']

def test_web_session_cannot_leak_refresh_token_in_json(client):
    """26. Sesión web con cookie nunca revela el refresh_token en JSON aunque se envíe X-Client-Platform: mobile."""
    client.post('/api/v1/auth/register', json={
        'email': 'noleak@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    client.post('/api/v1/auth/login', json={
        'email': 'noleak@afinia.com',
        'password': 'StrongPassword2026!'
    })

    # El cliente web simula ser móvil en los encabezados, pero utiliza la cookie de sesión
    res_ref = client.post('/api/v1/auth/refresh', headers={
        'X-Client-Platform': 'mobile',
        'Origin': 'http://localhost:8100'
    })
    assert res_ref.status_code == 200
    ref_body = res_ref.get_json()['data']
    assert 'refresh_token' not in ref_body, "El refresh_token no debe exponerse en JSON si la sesión es web (cookie)"
    # La cookie debe haber sido actualizada
    cookies = res_ref.headers.getlist('Set-Cookie')
    assert any('refresh_token=' in c and 'HttpOnly' in c for c in cookies)

def test_logout_and_jwt_residual_validity(client):
    """27. Logout revoca el refresh token; el access token conserva validez residual hasta exp (stateless)."""
    client.post('/api/v1/auth/register', json={
        'email': 'logout.jwt@afinia.com',
        'password': 'StrongPassword2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    log = client.post('/api/v1/auth/login', json={
        'email': 'logout.jwt@afinia.com',
        'password': 'StrongPassword2026!'
    }, headers={'X-Client-Platform': 'mobile'})
    data = log.get_json()['data']
    access_token = data['access_token']
    refresh_token = data['refresh_token']

    # Logout revoca refresh
    logout_res = client.post('/api/v1/auth/logout', json={
        'refresh_token': refresh_token
    }, headers={'Authorization': f'Bearer {access_token}'})
    assert logout_res.status_code == 204

    # Refresh token queda revocado inmediatamente
    ref_res = client.post('/api/v1/auth/refresh', json={
        'refresh_token': refresh_token
    }, headers={'X-Client-Platform': 'mobile'})
    assert ref_res.status_code == 401

    # Access token JWT: al ser sin estado (stateless) según OpenAPI, sigue siendo válido hasta expirar (900s)
    me_res = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {access_token}'})
    assert me_res.status_code == 200
    assert me_res.get_json()['data']['email'] == 'logout.jwt@afinia.com'
