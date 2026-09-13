import json

def test_health_check(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json['status'] == 'ok'

def test_register_user(client):
    data = {
        'email': 'test@afinia.com',
        'password': 'password123'
    }
    response = client.post('/api/v1/auth/register', 
                           data=json.dumps(data), 
                           content_type='application/json')
    
    assert response.status_code == 201
    assert 'user_id' in response.json

def test_login_user(client):
    # Crear usuario primero
    client.post('/api/v1/auth/register', 
                data=json.dumps({'email': 'test2@afinia.com', 'password': 'pass'}), 
                content_type='application/json')
                
    # Hacer Login
    response = client.post('/api/v1/auth/login', 
                           data=json.dumps({'email': 'test2@afinia.com', 'password': 'pass'}), 
                           content_type='application/json')
    
    assert response.status_code == 200
    assert 'token' in response.json
