import json

def test_health_check(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json['status'] == 'ok'

def test_register_user(client):
    data = {
        'email': 'test@afinia.com',
        'password': 'ClaveSegura2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    response = client.post(
        '/api/v1/auth/register',
        data=json.dumps(data),
        content_type='application/json'
    )
    assert response.status_code == 201
    assert 'data' in response.json
    assert response.json['data']['email'] == 'test@afinia.com'
    assert response.json['data']['status'] == 'pending_profile'

def test_login_user(client):
    # Crear usuario primero
    reg_data = {
        'email': 'test2@afinia.com',
        'password': 'ClaveSegura2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft'
    }
    client.post(
        '/api/v1/auth/register',
        data=json.dumps(reg_data),
        content_type='application/json'
    )
                
    # Hacer Login
    login_data = {
        'email': 'test2@afinia.com',
        'password': 'ClaveSegura2026!'
    }
    response = client.post(
        '/api/v1/auth/login',
        data=json.dumps(login_data),
        content_type='application/json'
    )
    assert response.status_code == 200
    assert 'data' in response.json
    assert 'access_token' in response.json['data']
    assert response.json['data']['token_type'] == 'Bearer'
    assert response.json['data']['expires_in'] == 900
    assert response.json['data']['user']['email'] == 'test2@afinia.com'
