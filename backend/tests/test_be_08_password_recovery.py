import time
import uuid
import threading
from datetime import datetime, timezone, timedelta
import pytest

from app import db
from app.models import User, RefreshToken, PasswordResetToken
from app.services.email_service import email_service
from app.utils.security import verify_password, hash_password

def _as_utc(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _create_user(email='test.recover@afinia.com', password='InitialPassword2026!'):
    """Crea y persiste un usuario sintético activo para pruebas de recuperación."""
    user = User(
        id=str(uuid.uuid4()),
        email=email.strip().lower(),
        password_hash=hash_password(password),
        role='user',
        lifecycle_status='active',
        email_verified=True,
        is_active=True
    )
    db.session.add(user)
    db.session.commit()
    return user

# =========================================================================
# PRUEBAS BE-08: RECUPERACIÓN SEGURA DE CONTRASEÑA
# =========================================================================

def test_01_forgot_password_registered_email(client):
    """1. Correo registrado: responde 202 Accepted, encola correo y persiste token seguro."""
    email_service.clear_sent_messages()
    email = 'user.registered@afinia.com'
    user = _create_user(email=email)

    res = client.post('/api/v1/auth/forgot-password', json={'email': email})
    assert res.status_code == 202
    data = res.get_json()['data']
    assert data['status'] == 'accepted'

    # Verificar que el servicio de correo capturó el token en memoria
    raw_token = email_service.get_last_password_reset_token_for(email)
    assert raw_token is not None
    assert len(raw_token) >= 32

    # Verificar registro en base de datos
    tokens = PasswordResetToken.query.filter_by(user_id=user.id).all()
    assert len(tokens) == 1
    t = tokens[0]
    assert t.consumed_at is None
    assert t.revoked_at is None
    assert _as_utc(t.expires_at) > datetime.now(timezone.utc)


def test_02_forgot_password_nonexistent_email_anti_enumeration(client):
    """2. Correo inexistente: responde exactamente 202 Accepted sin enviar correo ni filtrar datos."""
    email_service.clear_sent_messages()
    nonexistent = 'nonexistent.ghost.account@afinia.com'

    res = client.post('/api/v1/auth/forgot-password', json={'email': nonexistent})
    assert res.status_code == 202
    data = res.get_json()['data']
    assert data['status'] == 'accepted'

    # No se debe encolar ningún mensaje para cuentas inexistentes
    raw_token = email_service.get_last_password_reset_token_for(nonexistent)
    assert raw_token is None
    assert len(email_service.get_sent_messages()) == 0


def test_03_forgot_password_invalid_email_format(client):
    """3. Correo con formato inválido: responde 422 VALIDATION_ERROR."""
    res = client.post('/api/v1/auth/forgot-password', json={'email': 'correo-sin-arroba-ni-dominio'})
    assert res.status_code == 422
    err = res.get_json()['error']
    assert err['code'] == 'VALIDATION_ERROR'


def test_04_forgot_password_prohibits_extra_fields(client):
    """4. Campos adicionales en forgot-password: responde 400 BAD_REQUEST conforme a OpenAPI."""
    res = client.post('/api/v1/auth/forgot-password', json={
        'email': 'user@afinia.com',
        'extra_field': 'not_allowed'
    })
    assert res.status_code == 400
    err = res.get_json()['error']
    assert err['code'] == 'BAD_REQUEST'


def test_05_valid_token_resets_password_successfully(client):
    """5. Token válido: responde 204 No Content, cambia contraseña y consume token."""
    email_service.clear_sent_messages()
    email = 'reset.success@afinia.com'
    user = _create_user(email=email, password='OldPassword2026!')

    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)
    assert raw_token is not None

    new_pwd = 'BrandNewPassword2026!'
    res_reset = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': new_pwd
    })
    assert res_reset.status_code == 204
    assert res_reset.data == b''  # 204 sin cuerpo

    # Verificar que el token quedó marcado como consumido
    t = PasswordResetToken.query.filter_by(user_id=user.id).first()
    assert t.consumed_at is not None

    # Verificar que la contraseña cambió en BD
    db.session.refresh(user)
    assert verify_password(user.password_hash, new_pwd) is True
    assert verify_password(user.password_hash, 'OldPassword2026!') is False


def test_06_expired_token_rejected(client):
    """6. Token expirado: responde 422 VALIDATION_ERROR."""
    email = 'expired.token@afinia.com'
    user = _create_user(email=email)

    import hashlib
    raw_token = 'token_expirado_mock_12345678901234'
    h = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    now = datetime.now(timezone.utc)
    expired_t = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=h,
        created_at=now - timedelta(minutes=30),
        expires_at=now - timedelta(minutes=10)
    )
    db.session.add(expired_t)
    db.session.commit()

    res = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': 'ValidNewPassword2026!'
    })
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'


def test_07_nonexistent_token_rejected(client):
    """7. Token inexistente: responde 422 VALIDATION_ERROR."""
    res = client.post('/api/v1/auth/reset-password', json={
        'token': 'token_completamente_falso_que_no_existe',
        'new_password': 'ValidNewPassword2026!'
    })
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'


def test_08_already_used_token_rejected(client):
    """8. Token previamente utilizado: responde 409 CONFLICT."""
    email_service.clear_sent_messages()
    email = 'already.used@afinia.com'
    user = _create_user(email=email)

    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)

    # Primer uso: 204 No Content
    res1 = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': 'PasswordFirstReset2026!'
    })
    assert res1.status_code == 204

    # Segundo uso del mismo token: 422 VALIDATION_ERROR (conforme al contrato OpenAPI)
    res2 = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': 'PasswordSecondReset2026!'
    })
    assert res2.status_code == 422
    assert res2.get_json()['error']['code'] == 'VALIDATION_ERROR'


def test_09_revoked_token_by_new_request_rejected(client, monkeypatch):
    """9. Token revocado por reenvío posterior: responde 422 VALIDATION_ERROR."""
    email_service.clear_sent_messages()
    email = 'revoked.resend@afinia.com'
    user = _create_user(email=email)

    # Reducir cooldown para permitir segundo envío inmediato en la prueba
    client.application.config['PASSWORD_RESET_COOLDOWN_SECONDS'] = 0

    client.post('/api/v1/auth/forgot-password', json={'email': email})
    first_token = email_service.get_last_password_reset_token_for(email)

    # Segundo envío revoca el token anterior
    client.post('/api/v1/auth/forgot-password', json={'email': email})
    second_token = email_service.get_last_password_reset_token_for(email)
    assert first_token != second_token

    # El primer token debe ser rechazado como revocado
    res = client.post('/api/v1/auth/reset-password', json={
        'token': first_token,
        'new_password': 'NewPasswordValid2026!'
    })
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

    # El segundo token debe funcionar
    res2 = client.post('/api/v1/auth/reset-password', json={
        'token': second_token,
        'new_password': 'NewPasswordValid2026!'
    })
    assert res2.status_code == 204


def test_10_concurrent_reuse_same_token(client):
    """10. Reutilización concurrente: solo una petición tiene éxito (204) y la otra es rechazada (422)."""
    email_service.clear_sent_messages()
    email = 'concurrent.reset@afinia.com'
    user = _create_user(email=email)

    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)

    results = []

    def _worker(suffix):
        with client.application.app_context():
            try:
                c = client.application.test_client()
                res = c.post('/api/v1/auth/reset-password', json={
                    'token': raw_token,
                    'new_password': f'NewSecurePassword{suffix}2026!'
                })
                results.append((res.status_code, suffix))
            finally:
                db.session.remove()

    t1 = threading.Thread(target=_worker, args=('A',))
    t2 = threading.Thread(target=_worker, args=('B',))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    status_codes = [code for code, _ in results]
    assert 204 in status_codes, f"Al menos una petición debió completar con 204: {results}"
    assert 422 in status_codes, f"La segunda petición debió ser rechazada con 422: {results}"
    assert status_codes.count(204) == 1, "Exactamente una operación debió ganar la carrera"


def test_11_password_length_policies(client):
    """11. Validación de política de contraseña: 12 a 128 caracteres."""
    email_service.clear_sent_messages()
    email = 'pwd.policy@afinia.com'
    _create_user(email=email)

    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)

    # Menor a 12 caracteres (11 chars)
    res_short = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': 'Corta12345!'
    })
    assert res_short.status_code == 422
    assert res_short.get_json()['error']['code'] == 'VALIDATION_ERROR'

    # Mayor a 128 caracteres (129 chars)
    res_long = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': 'A' * 129
    })
    assert res_long.status_code == 422
    assert res_long.get_json()['error']['code'] == 'VALIDATION_ERROR'


def test_12_login_with_old_and_new_password_after_reset(client):
    """12. Comprobación de login: clave antigua rechazada (401), clave nueva aceptada (200)."""
    email_service.clear_sent_messages()
    email = 'login.check@afinia.com'
    old_pwd = 'OldSecurePassword2026!'
    new_pwd = 'BrandNewPassword2026!'
    _create_user(email=email, password=old_pwd)

    # Restablecer
    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)

    res_reset = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': new_pwd
    })
    assert res_reset.status_code == 204

    # Intento de login con clave antigua -> 401 UNAUTHORIZED
    res_old = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': old_pwd
    })
    assert res_old.status_code == 401

    # Intento de login con clave nueva -> 200 OK
    res_new = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': new_pwd
    })
    assert res_new.status_code == 200
    assert 'access_token' in res_new.get_json()['data']


def test_13_all_refresh_tokens_revoked_after_reset(client):
    """13. Revocación de refresh tokens: los tokens de renovación previos quedan revocados."""
    email_service.clear_sent_messages()
    email = 'refresh.revoke@afinia.com'
    pwd = 'InitialSecurePassword2026!'
    user = _create_user(email=email, password=pwd)

    # Login previo para obtener refresh token
    res_login = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': pwd
    }, headers={'X-Client-Platform': 'mobile'})
    assert res_login.status_code == 200
    old_refresh = res_login.get_json()['data']['refresh_token']

    # Restablecer contraseña
    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)
    client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': 'BrandNewPassword2026!'
    })

    # El refresh token previo debe fallar al intentar renovar sesión
    res_ref = client.post('/api/v1/auth/refresh', json={
        'refresh_token': old_refresh
    })
    assert res_ref.status_code == 401


def test_14_previous_jwt_access_tokens_invalidated_after_reset(client):
    """14. Invalidez de JWT access tokens anteriores: los access tokens emitidos antes del reset son rechazados inmediatamente sin sleeps."""
    email_service.clear_sent_messages()
    email = 'access.revoke@afinia.com'
    pwd = 'InitialSecurePassword2026!'
    user = _create_user(email=email, password=pwd)

    # Iniciar sesión antes del reset
    res_login = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': pwd
    }, headers={'X-Client-Platform': 'mobile'})
    old_access = res_login.get_json()['data']['access_token']

    # Verificar que el token viejo funciona en /me
    res_me_before = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {old_access}'})
    assert res_me_before.status_code == 200

    # Restablecer contraseña inmediatamente (sin ningún sleep)
    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)
    new_pwd = 'BrandNewPassword2026!'
    res_reset = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': new_pwd
    })
    assert res_reset.status_code == 204

    # El viejo access token ahora debe ser rechazado con 401 UNAUTHORIZED inmediatamente
    res_me_after = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {old_access}'})
    assert res_me_after.status_code == 401
    assert 'revocada' in res_me_after.get_json()['error']['message'].lower()

    # Login con la nueva contraseña emite un nuevo token funcional inmediatamente
    res_new_login = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': new_pwd
    }, headers={'X-Client-Platform': 'mobile'})
    new_access = res_new_login.get_json()['data']['access_token']

    res_me_new = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {new_access}'})
    assert res_me_new.status_code == 200


def test_15_email_delivery_failure_rollbacks_token(client):
    """15. Fallo en el transporte de correo no persiste tokens huérfanos ni altera estado."""
    email_service.clear_sent_messages()
    email = 'mail.failure@afinia.com'
    user = _create_user(email=email)

    email_service.set_simulate_failure(True)
    try:
        res = client.post('/api/v1/auth/forgot-password', json={'email': email})
        assert res.status_code == 500
        assert res.get_json()['error']['code'] == 'INTERNAL_ERROR'

        # Verificar que la transacción se revirtió y no hay tokens persistidos
        tokens = PasswordResetToken.query.filter_by(user_id=user.id).all()
        assert len(tokens) == 0
    finally:
        email_service.set_simulate_failure(False)


def test_16_transaction_rollback_on_reset_error(client):
    """16. Integridad transaccional: si ocurre un fallo al resetear, la clave previa permanece intacta."""
    email_service.clear_sent_messages()
    email = 'rollback.reset@afinia.com'
    initial_pwd = 'InitialSecurePassword2026!'
    user = _create_user(email=email, password=initial_pwd)

    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)

    # Enviar contraseña que viola política -> 422
    res = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': 'corta'
    })
    assert res.status_code == 422

    # Verificar que el token NO fue consumido y la contraseña sigue siendo la inicial
    t = PasswordResetToken.query.filter_by(user_id=user.id).first()
    assert t.consumed_at is None
    db.session.refresh(user)
    assert verify_password(user.password_hash, initial_pwd) is True


def test_17_immediate_same_second_jwt_invalidation_and_reissuance(client):
    """17. Escenario temporal estricto BE-08.1:
    A. Emitir JWT antiguo.
    B. Restablecer contraseña.
    C. Emitir JWT nuevo inmediatamente dentro del mismo segundo (sin sleeps).
    D. Comprobar que el JWT antiguo falla con 401 y el nuevo funciona con 200.
    E. Repetir con múltiples restablecimientos y sesiones consecutivas.
    """
    email_service.clear_sent_messages()
    email = 'strict.same.second@afinia.com'
    pwd = 'PasswordCycle0_2026!'
    user = _create_user(email=email, password=pwd)

    # Permitir múltiples solicitudes consecutivas sin cooldown en la prueba
    client.application.config['PASSWORD_RESET_COOLDOWN_SECONDS'] = 0

    current_pwd = pwd
    for cycle in range(1, 4):
        # A. Emitir JWTs de sesiones activas concurrentes (web y mobile)
        res_login_web = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': current_pwd
        }, headers={'X-Client-Platform': 'web'})
        assert res_login_web.status_code == 200
        old_jwt_web = res_login_web.get_json()['data']['access_token']

        res_login_mob = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': current_pwd
        }, headers={'X-Client-Platform': 'mobile'})
        assert res_login_mob.status_code == 200
        old_jwt_mob = res_login_mob.get_json()['data']['access_token']

        # Verificar que ambos tokens funcionan
        assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {old_jwt_web}'}).status_code == 200
        assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {old_jwt_mob}'}).status_code == 200

        # B. Restablecer contraseña de forma inmediata
        client.post('/api/v1/auth/forgot-password', json={'email': email})
        raw_token = email_service.get_last_password_reset_token_for(email)
        next_pwd = f'NewSecurePasswordCycle{cycle}_2026!'

        res_reset = client.post('/api/v1/auth/reset-password', json={
            'token': raw_token,
            'new_password': next_pwd
        })
        assert res_reset.status_code == 204

        # C. Emitir JWT nuevo inmediatamente (en el mismo instante/milisegundo, cero sleep)
        res_new_login = client.post('/api/v1/auth/login', json={
            'email': email,
            'password': next_pwd
        }, headers={'X-Client-Platform': 'web'})
        assert res_new_login.status_code == 200
        new_jwt = res_new_login.get_json()['data']['access_token']

        # D. Comprobar que los JWTs antiguos fallan con 401 y el nuevo funciona con 200
        res_old_web = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {old_jwt_web}'})
        assert res_old_web.status_code == 401
        assert 'revocada' in res_old_web.get_json()['error']['message'].lower()

        res_old_mob = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {old_jwt_mob}'})
        assert res_old_mob.status_code == 401
        assert 'revocada' in res_old_mob.get_json()['error']['message'].lower()

        res_new_me = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {new_jwt}'})
        assert res_new_me.status_code == 200

        # Actualizar contraseña corriente para el siguiente ciclo
        current_pwd = next_pwd


def test_18_legacy_jwt_without_pwd_fp_rejected_and_refresh_emits_pwd_fp(client):
    """18. Verificación BE-08.2:
    - El middleware rechaza cualquier JWT que no contenga el claim pwd_fp.
    - Tanto login como refresh emiten JWT con pwd_fp válido.
    - Un JWT emitido por refresh queda invalidado inmediatamente tras restablecer contraseña.
    """
    import jwt as pyjwt
    email_service.clear_sent_messages()
    email = 'pwd.fp.check@afinia.com'
    pwd = 'InitialSecurePassword2026!'
    user = _create_user(email=email, password=pwd)

    # 1. Construir un JWT firmado válidamente con SECRET_KEY pero sin claim pwd_fp
    now_ts = datetime.now(timezone.utc).timestamp()
    legacy_payload = {
        'sub': user.id,
        'email': user.email,
        'role': user.role,
        'type': 'access',
        'iss': 'afinia-api',
        'iat': now_ts,
        'exp': now_ts + 900
    }
    legacy_jwt = pyjwt.encode(legacy_payload, client.application.config['SECRET_KEY'], algorithm='HS256')

    res_legacy = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {legacy_jwt}'})
    assert res_legacy.status_code == 401
    assert res_legacy.get_json()['error']['code'] == 'UNAUTHORIZED'

    # 2. Verificar que login emite JWT con pwd_fp y refresh también emite JWT con pwd_fp
    res_login = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': pwd
    }, headers={'X-Client-Platform': 'mobile'})
    assert res_login.status_code == 200
    login_data = res_login.get_json()['data']
    login_jwt = login_data['access_token']
    refresh_tok = login_data['refresh_token']

    decoded_login = pyjwt.decode(login_jwt, client.application.config['SECRET_KEY'], algorithms=['HS256'], issuer='afinia-api')
    assert 'pwd_fp' in decoded_login and len(decoded_login['pwd_fp']) == 16

    res_refresh = client.post('/api/v1/auth/refresh', json={
        'refresh_token': refresh_tok
    }, headers={'X-Client-Platform': 'mobile'})
    assert res_refresh.status_code == 200
    refreshed_jwt = res_refresh.get_json()['data']['access_token']

    decoded_refresh = pyjwt.decode(refreshed_jwt, client.application.config['SECRET_KEY'], algorithms=['HS256'], issuer='afinia-api')
    assert 'pwd_fp' in decoded_refresh and decoded_refresh['pwd_fp'] == decoded_login['pwd_fp']
    assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {refreshed_jwt}'}).status_code == 200

    # 3. Restablecer contraseña e invalidar inmediatamente también el JWT proveniente de refresh
    client.post('/api/v1/auth/forgot-password', json={'email': email})
    raw_token = email_service.get_last_password_reset_token_for(email)
    res_reset = client.post('/api/v1/auth/reset-password', json={
        'token': raw_token,
        'new_password': 'UpdatedSecurePassword2026!'
    })
    assert res_reset.status_code == 204

    assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {refreshed_jwt}'}).status_code == 401


