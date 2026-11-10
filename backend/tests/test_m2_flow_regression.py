from app.services.email_service import email_service
from app.services.profile_service import approve_photo_for_qa
from test_be_02_3_email_verification import _create_synthetic_image, _login_user, _register_user


def test_verified_profile_retry_and_discovery_after_fresh_login(client):
    email = 'm2.synthetic@afinia.test'
    assert _register_user(client, email).status_code == 201
    verification = email_service.get_last_token_for(email)
    assert client.post('/api/v1/auth/verify-email', json={'token': verification}).status_code == 204
    _, headers = _login_user(client, email)
    me = client.get('/api/v1/auth/me', headers=headers)
    assert me.status_code == 200
    assert me.get_json()['data']['email_verified'] is True

    original = {'first_name': 'Synthetic', 'birth_date': '1990-01-01', 'gender': 'otro', 'city': 'Test'}
    updated = {**original, 'city': 'Updated', 'bio': 'Test'}
    assert client.post('/api/v1/profile/', json=original, headers=headers).status_code == 201
    assert client.post('/api/v1/profile/', json=updated, headers=headers).status_code == 409
    assert client.put('/api/v1/profile/', json=updated, headers=headers).status_code == 200
    assert client.put('/api/v1/profile/discovery-preferences', json={
        'interested_in_genders': ['otro'], 'min_age': 18, 'max_age': 80,
        'target_relationship_type': 'amistad'
    }, headers=headers).status_code == 200
    assert client.get('/api/v1/match/potential', headers=headers).status_code == 403
    upload = client.post('/api/v1/profile/photos', data={
        'file': (_create_synthetic_image(), 'synthetic.jpg', 'image/jpeg'), 'is_primary': 'true'
    }, content_type='multipart/form-data', headers=headers)
    assert upload.status_code == 201
    assert client.get('/api/v1/match/potential', headers=headers).status_code == 403
    approve_photo_for_qa(upload.get_json()['data']['id'])

    # A new login and subsequent requests use fresh sessions, not an ORM cache.
    _, headers = _login_user(client, email)
    me = client.get('/api/v1/auth/me', headers=headers).get_json()['data']
    assert me['email_verified'] is True and me['status'] == 'active' and me['onboarding_complete'] is True
    loaded = client.get('/api/v1/profile/', headers=headers)
    assert loaded.status_code == 200
    assert all(loaded.get_json()['data'][key] == value for key, value in updated.items())
    assert client.get('/api/v1/match/potential', headers=headers).status_code == 200
