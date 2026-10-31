import json
import pytest
from datetime import datetime, date, timedelta, timezone
from app import db
from app.models.user import User
from app.models.profile import Profile, ProfilePhoto
from app.models.discovery import DiscoveryPreference
from app.services.profile_service import calculate_age, is_onboarding_complete, ProfileError

def _register_and_login(client, email, password='StrongPassword2026!'):
    """Helper para registrar e iniciar sesión obteniendo access token."""
    client.post('/api/v1/auth/register', json={
        'email': email,
        'password': password,
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    })
    login_res = client.post('/api/v1/auth/login', json={
        'email': email,
        'password': password
    }, headers={'X-Client-Platform': 'mobile'})
    assert login_res.status_code == 200
    return login_res.get_json()['data']['access_token']

# =========================================================================
# 1. CREACIÓN DE PERFIL (POST /api/v1/profile/)
# =========================================================================

def test_create_profile_valid(client):
    """1. Crear perfil válido (201 Created) conforme a OpenAPI OwnProfile."""
    token = _register_and_login(client, 'prof.valid@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    payload = {
        'first_name': 'Ana María',
        'birth_date': '2000-05-15',
        'gender': 'femenino',
        'city': 'Villavicencio',
        'bio': 'Amante del senderismo y el café.'
    }
    res = client.post('/api/v1/profile/', json=payload, headers=headers)
    assert res.status_code == 201
    body = res.get_json()
    assert 'data' in body
    data = body['data']
    assert data['first_name'] == 'Ana María'
    assert data['birth_date'] == '2000-05-15'
    assert data['gender'] == 'femenino'
    assert data['city'] == 'Villavicencio'
    assert data['bio'] == 'Amante del senderismo y el café.'
    assert isinstance(data['age'], int)
    assert data['age'] >= 18
    assert data['photos'] == []
    assert data['onboarding_complete'] is False
    assert 'user_id' in data
    # No exponer datos sensibles
    assert 'password_hash' not in data
    assert 'role' not in data

def test_create_profile_unauthenticated(client):
    """2. Crear perfil sin autenticación rechazado con 401 UNAUTHORIZED."""
    payload = {
        'first_name': 'Carlos',
        'birth_date': '1998-03-20',
        'gender': 'masculino'
    }
    res = client.post('/api/v1/profile/', json=payload)
    assert res.status_code == 401
    body = res.get_json()
    assert 'error' in body
    assert body['error']['code'] == 'UNAUTHORIZED'

def test_create_profile_duplicate_conflict(client):
    """3. Intentar crear un segundo perfil rechazado con 409 CONFLICT."""
    token = _register_and_login(client, 'prof.dup@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    payload = {
        'first_name': 'Carlos',
        'birth_date': '1998-03-20',
        'gender': 'masculino'
    }
    res1 = client.post('/api/v1/profile/', json=payload, headers=headers)
    assert res1.status_code == 201

    # Segunda creación idéntica o modificada debe fallar con 409 sin alterar el existente
    payload2 = {
        'first_name': 'Carlos Modificado',
        'birth_date': '1997-01-01',
        'gender': 'masculino'
    }
    res2 = client.post('/api/v1/profile/', json=payload2, headers=headers)
    assert res2.status_code == 409
    body2 = res2.get_json()
    assert 'error' in body2
    assert body2['error']['code'] == 'CONFLICT'

    # Verificar que el perfil original sigue intacto
    get_res = client.get('/api/v1/profile/', headers=headers)
    assert get_res.get_json()['data']['first_name'] == 'Carlos'

# =========================================================================
# 2. VALIDACIÓN DE EDAD Y FECHAS
# =========================================================================

def test_create_profile_underage_17_rejected(client):
    """4. Rechazar menor de 18 años con 422 VALIDATION_ERROR."""
    token = _register_and_login(client, 'prof.underage@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    today = datetime.now(timezone.utc).date()
    # Exactamente 17 años y 364 días
    underage_date = date(today.year - 17, today.month, today.day)
    payload = {
        'first_name': 'Joven',
        'birth_date': underage_date.isoformat(),
        'gender': 'no_binario'
    }
    res = client.post('/api/v1/profile/', json=payload, headers=headers)
    assert res.status_code == 422
    body = res.get_json()
    assert 'error' in body
    assert body['error']['code'] == 'VALIDATION_ERROR'

def test_create_profile_exact_18_today_accepted(client):
    """5. Admitir usuario que cumple exactamente 18 años hoy."""
    token = _register_and_login(client, 'prof.exact18@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    today = datetime.now(timezone.utc).date()
    exact_18_date = date(today.year - 18, today.month, today.day)
    payload = {
        'first_name': 'Mayor Hoy',
        'birth_date': exact_18_date.isoformat(),
        'gender': 'otro'
    }
    res = client.post('/api/v1/profile/', json=payload, headers=headers)
    assert res.status_code == 201
    assert res.get_json()['data']['age'] == 18

def test_create_profile_18_tomorrow_rejected(client):
    """6. Rechazar usuario que cumple 18 años mañana (aún tiene 17)."""
    token = _register_and_login(client, 'prof.tomorrow18@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)
    birth_date = date(tomorrow.year - 18, tomorrow.month, tomorrow.day)
    payload = {
        'first_name': 'Casi Mayor',
        'birth_date': birth_date.isoformat(),
        'gender': 'femenino'
    }
    res = client.post('/api/v1/profile/', json=payload, headers=headers)
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_create_profile_future_date_rejected(client):
    """7. Rechazar fecha de nacimiento futura."""
    token = _register_and_login(client, 'prof.future@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    today = datetime.now(timezone.utc).date()
    future_date = today + timedelta(days=30)
    payload = {
        'first_name': 'Viajero',
        'birth_date': future_date.isoformat(),
        'gender': 'masculino'
    }
    res = client.post('/api/v1/profile/', json=payload, headers=headers)
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_create_profile_invalid_date_format_rejected(client):
    """8. Rechazar fecha en formato incorrecto o inválido."""
    token = _register_and_login(client, 'prof.invdate@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    for bad_date in ('2000/12/31', 'not-a-date', '2000-02-30', '31-12-2000'):
        res = client.post('/api/v1/profile/', json={
            'first_name': 'Formato Invalido',
            'birth_date': bad_date,
            'gender': 'masculino'
        }, headers=headers)
        assert res.status_code == 422

def test_age_calculation_leap_year_feb_29():
    """Prueba exhaustiva de cálculo de edad para nacidos el 29 de febrero."""
    leap_birth = date(2004, 2, 29)
    # En 2022-02-28 (año no bisiesto), tiene 17 años por lo que debe ser rechazado con 422
    with pytest.raises(ProfileError) as exc_info:
        calculate_age(leap_birth, reference_date=date(2022, 2, 28))
    assert exc_info.value.code == 'VALIDATION_ERROR'
    assert exc_info.value.status_code == 422

    # En 2022-03-01 cumple los 18 años exactos y es aceptado
    assert calculate_age(leap_birth, reference_date=date(2022, 3, 1)) == 18
    # En 2024-02-29 (año bisiesto) cumple 20 años exactos
    assert calculate_age(leap_birth, reference_date=date(2024, 2, 29)) == 20

# =========================================================================
# 3. GÉNEROS Y RECHAZO DE MASS ASSIGNMENT
# =========================================================================

def test_create_profile_all_allowed_genders(client):
    """9. Validar que se admiten todos los 5 géneros de OpenAPI y se rechazan inválidos."""
    allowed = ['masculino', 'femenino', 'no_binario', 'otro', 'prefiero_no_indicar']
    for idx, g in enumerate(allowed):
        token = _register_and_login(client, f'gender.{idx}@afinia.com')
        headers = {'Authorization': f'Bearer {token}'}
        res = client.post('/api/v1/profile/', json={
            'first_name': f'Persona {idx}',
            'birth_date': '1995-01-01',
            'gender': g
        }, headers=headers)
        assert res.status_code == 201
        assert res.get_json()['data']['gender'] == g

    # Género no perteneciente al enum
    bad_token = _register_and_login(client, 'bad.gender@afinia.com')
    bad_res = client.post('/api/v1/profile/', json={
        'first_name': 'Invalido',
        'birth_date': '1995-01-01',
        'gender': 'desconocido'
    }, headers={'Authorization': f'Bearer {bad_token}'})
    assert bad_res.status_code == 422
    assert bad_res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_create_profile_rejects_mass_assignment(client):
    """10. Rechazar campos adicionales (user_id, role, lifecycle_status, etc.)."""
    token = _register_and_login(client, 'mass.assign@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    payload = {
        'first_name': 'Hacker',
        'birth_date': '1990-01-01',
        'gender': 'masculino',
        'role': 'admin',
        'lifecycle_status': 'active',
        'onboarding_complete': True,
        'user_id': '00000000-0000-0000-0000-000000000000'
    }
    res = client.post('/api/v1/profile/', json=payload, headers=headers)
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

# =========================================================================
# 4. CONSULTA Y ACTUALIZACIÓN (GET/PUT /api/v1/profile/)
# =========================================================================

def test_get_own_profile_success(client):
    """11. Consultar perfil propio (200 OK) con esquema exacto OwnProfile."""
    token = _register_and_login(client, 'get.profile@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    client.post('/api/v1/profile/', json={
        'first_name': 'Lucía',
        'birth_date': '1996-08-20',
        'gender': 'femenino',
        'city': 'Bogotá',
        'bio': 'Arquitecta de software.'
    }, headers=headers)

    res = client.get('/api/v1/profile/', headers=headers)
    assert res.status_code == 200
    data = res.get_json()['data']
    assert data['first_name'] == 'Lucía'
    assert data['birth_date'] == '1996-08-20'
    assert data['city'] == 'Bogotá'
    assert data['bio'] == 'Arquitecta de software.'
    assert data['photos'] == []
    assert data['onboarding_complete'] is False

def test_get_own_profile_not_found(client):
    """12. Consultar perfil cuando aún no se ha creado retorna 404 NOT_FOUND."""
    token = _register_and_login(client, 'noprofile@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    res = client.get('/api/v1/profile/', headers=headers)
    assert res.status_code == 404
    body = res.get_json()
    assert 'error' in body
    assert body['error']['code'] == 'NOT_FOUND'

def test_update_own_profile_valid(client):
    """13. Actualizar perfil propio con PUT /api/v1/profile/ (200 OK)."""
    token = _register_and_login(client, 'put.profile@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    client.post('/api/v1/profile/', json={
        'first_name': 'David',
        'birth_date': '1992-03-10',
        'gender': 'masculino',
        'city': 'Cali',
        'bio': 'Bio inicial.'
    }, headers=headers)

    # Actualizar datos con PUT
    update_payload = {
        'first_name': 'David Alejandro',
        'birth_date': '1992-03-10',
        'gender': 'masculino',
        'city': 'Medellín',
        'bio': 'Bio actualizada con éxito.'
    }
    put_res = client.put('/api/v1/profile/', json=update_payload, headers=headers)
    assert put_res.status_code == 200
    data = put_res.get_json()['data']
    assert data['first_name'] == 'David Alejandro'
    assert data['city'] == 'Medellín'
    assert data['bio'] == 'Bio actualizada con éxito.'

def test_profile_user_isolation(client):
    """14. Aislamiento entre usuarios: Usuario A no puede acceder ni alterar datos de B."""
    token_a = _register_and_login(client, 'user.a@afinia.com')
    token_b = _register_and_login(client, 'user.b@afinia.com')

    client.post('/api/v1/profile/', json={
        'first_name': 'Usuario A',
        'birth_date': '1990-01-01',
        'gender': 'masculino'
    }, headers={'Authorization': f'Bearer {token_a}'})

    client.post('/api/v1/profile/', json={
        'first_name': 'Usuario B',
        'birth_date': '1995-05-05',
        'gender': 'femenino'
    }, headers={'Authorization': f'Bearer {token_b}'})

    # El token B solo puede consultar y modificar el perfil de B
    res_b = client.get('/api/v1/profile/', headers={'Authorization': f'Bearer {token_b}'})
    assert res_b.get_json()['data']['first_name'] == 'Usuario B'

    client.put('/api/v1/profile/', json={
        'first_name': 'Usuario B Modificado',
        'birth_date': '1995-05-05',
        'gender': 'femenino'
    }, headers={'Authorization': f'Bearer {token_b}'})

    # Verificar que el perfil de A no sufrió ninguna alteración
    res_a = client.get('/api/v1/profile/', headers={'Authorization': f'Bearer {token_a}'})
    assert res_a.get_json()['data']['first_name'] == 'Usuario A'

# =========================================================================
# 5. PREFERENCIAS DE DESCUBRIMIENTO (GET/PUT)
# =========================================================================

def test_save_and_get_discovery_preferences_valid(client):
    """15. Guardar y consultar preferencias de descubrimiento con OpenAPI Preferences."""
    token = _register_and_login(client, 'prefs.valid@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    prefs_payload = {
        'interested_in_genders': ['femenino', 'no_binario'],
        'min_age': 22,
        'max_age': 38,
        'target_relationship_type': 'seria'
    }
    put_res = client.put('/api/v1/profile/discovery-preferences', json=prefs_payload, headers=headers)
    assert put_res.status_code == 200
    data = put_res.get_json()['data']
    assert data['interested_in_genders'] == ['femenino', 'no_binario']
    assert data['min_age'] == 22
    assert data['max_age'] == 38
    assert data['target_relationship_type'] == 'seria'

    # Consultar con GET
    get_res = client.get('/api/v1/profile/discovery-preferences', headers=headers)
    assert get_res.status_code == 200
    get_data = get_res.get_json()['data']
    assert get_data['interested_in_genders'] == ['femenino', 'no_binario']
    assert get_data['min_age'] == 22
    assert get_data['max_age'] == 38
    assert get_data['target_relationship_type'] == 'seria'

def test_discovery_preferences_reject_empty_genders(client):
    """16. Rechazar lista vacía de géneros (422 VALIDATION_ERROR)."""
    token = _register_and_login(client, 'prefs.empty@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    res = client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': [],
        'min_age': 20,
        'max_age': 30
    }, headers=headers)
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_discovery_preferences_reject_duplicates(client):
    """17. Rechazar duplicados en interested_in_genders (422 VALIDATION_ERROR)."""
    token = _register_and_login(client, 'prefs.dupgender@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    res = client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['masculino', 'femenino', 'masculino'],
        'min_age': 20,
        'max_age': 30
    }, headers=headers)
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_discovery_preferences_reject_invalid_gender_item(client):
    """18. Rechazar categorías de género desconocidas (422 VALIDATION_ERROR)."""
    token = _register_and_login(client, 'prefs.unkngender@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    res = client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['femenino', 'extraterrestre'],
        'min_age': 20,
        'max_age': 30
    }, headers=headers)
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_discovery_preferences_reject_min_age_greater_than_max(client):
    """19. Exigir min_age <= max_age (rechazar min > max con 422)."""
    token = _register_and_login(client, 'prefs.minmax@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    res = client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['masculino'],
        'min_age': 40,
        'max_age': 30
    }, headers=headers)
    assert res.status_code == 422
    assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

def test_discovery_preferences_age_bounds_18_to_120(client):
    """20. Rechazar min_age < 18 o max_age > 120."""
    token = _register_and_login(client, 'prefs.bounds@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    # min_age < 18
    res1 = client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['masculino'],
        'min_age': 16,
        'max_age': 25
    }, headers=headers)
    assert res1.status_code == 422

    # max_age > 120
    res2 = client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['masculino'],
        'min_age': 20,
        'max_age': 130
    }, headers=headers)
    assert res2.status_code == 422

def test_discovery_preferences_relationship_types(client):
    """21. Validar tipos de relación objetivo admitidos y rechazar inválidos."""
    token = _register_and_login(client, 'prefs.rel@afinia.com')
    headers = {'Authorization': f'Bearer {token}'}

    for rel in ('seria', 'casual', 'amistad', 'sin_definir', None):
        res = client.put('/api/v1/profile/discovery-preferences', json={
            'interested_in_genders': ['masculino'],
            'min_age': 20,
            'max_age': 30,
            'target_relationship_type': rel
        }, headers=headers)
        assert res.status_code == 200
        assert res.get_json()['data']['target_relationship_type'] == rel

    # Inválido
    bad_res = client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['masculino'],
        'min_age': 20,
        'max_age': 30,
        'target_relationship_type': 'relacion_magica'
    }, headers=headers)
    assert bad_res.status_code == 422

# =========================================================================
# 6. ESTADO DE ONBOARDING Y /AUTH/ME
# =========================================================================

def test_onboarding_lifecycle_and_auth_me_coherence(client):
    """22. Comprobar coherencia de onboarding_complete y lifecycle_status a lo largo de las microfases."""
    email = 'onboard.flow@afinia.com'
    token = _register_and_login(client, email)
    headers = {'Authorization': f'Bearer {token}'}

    # 1. Recién registrado: pending_profile y onboarding_complete False
    me1 = client.get('/api/v1/auth/me', headers=headers)
    assert me1.status_code == 200
    assert me1.get_json()['data']['status'] == 'pending_profile'
    assert me1.get_json()['data']['onboarding_complete'] is False

    # 2. Tras crear perfil básico: sigue en pending_profile y onboarding_complete False
    client.post('/api/v1/profile/', json={
        'first_name': 'Marta',
        'birth_date': '1995-10-10',
        'gender': 'femenino'
    }, headers=headers)

    prof_res = client.get('/api/v1/profile/', headers=headers)
    assert prof_res.get_json()['data']['onboarding_complete'] is False

    me2 = client.get('/api/v1/auth/me', headers=headers)
    assert me2.get_json()['data']['status'] == 'pending_profile'
    assert me2.get_json()['data']['onboarding_complete'] is False

    # 3. Tras guardar preferencias: sigue en pending_profile y onboarding_complete False
    # Porque no hay foto aprobada (requisito C indispensable de la política de seguridad)
    client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['masculino'],
        'min_age': 25,
        'max_age': 40
    }, headers=headers)

    me3 = client.get('/api/v1/auth/me', headers=headers)
    assert me3.get_json()['data']['status'] == 'pending_profile'
    assert me3.get_json()['data']['onboarding_complete'] is False

def test_suspended_and_deactivated_cannot_recover_active_via_profile(client):
    """23. Cuentas suspendidas o desactivadas no pueden operar perfil ni alterar su estado."""
    token = _register_and_login(client, 'suspend.guard@afinia.com')
    user = User.query.filter_by(email='suspend.guard@afinia.com').first()
    user.lifecycle_status = 'suspended'
    db.session.commit()

    headers = {'Authorization': f'Bearer {token}'}
    # Suspendido recibe 403 en endpoints protegidos
    res_get = client.get('/api/v1/profile/', headers=headers)
    assert res_get.status_code == 403

    res_post = client.post('/api/v1/profile/', json={
        'first_name': 'Malicioso',
        'birth_date': '1990-01-01',
        'gender': 'masculino'
    }, headers=headers)
    assert res_post.status_code == 403

    # Estado permanece suspended
    db.session.refresh(user)
    assert user.lifecycle_status == 'suspended'
