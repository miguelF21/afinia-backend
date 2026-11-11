from app.services.email_service import email_service
from test_be_02_3_email_verification import _create_synthetic_image, _login_user, _register_user
from test_be_10_admin_moderation import _create_user_with_role


def test_photo_review_requires_admin_and_activates_complete_user(client):
    email = 'photo-review-flow@afinia.test'
    assert _register_user(client, email).status_code == 201
    assert client.post('/api/v1/auth/verify-email', json={'token': email_service.get_last_token_for(email)}).status_code == 204
    _, headers = _login_user(client, email)
    assert client.post('/api/v1/profile/', headers=headers, json={
        'first_name': 'Synthetic', 'birth_date': '1990-01-01', 'gender': 'otro'
    }).status_code == 201
    assert client.put('/api/v1/profile/discovery-preferences', headers=headers, json={
        'interested_in_genders': ['otro'], 'min_age': 18, 'max_age': 50
    }).status_code == 200
    photo = client.post('/api/v1/profile/photos', headers=headers, data={
        'file': (_create_synthetic_image(), 'synthetic.jpg', 'image/jpeg'), 'is_primary': 'true'
    }, content_type='multipart/form-data')
    photo_id = photo.get_json()['data']['id']
    assert client.get('/api/v1/match/potential', headers=headers).status_code == 403
    assert client.post(f'/api/v1/admin/photos/{photo_id}/review', headers=headers, json={'decision': 'approve'}).status_code == 403

    admin = _create_user_with_role(client, 'photo-admin@afinia.test', role='admin', lifecycle_status='pending_profile')
    admin_headers = admin['headers']
    pending = client.get('/api/v1/admin/photos/pending', headers=admin_headers)
    assert pending.status_code == 200 and any(item['id'] == photo_id for item in pending.get_json()['data']['items'])
    assert client.get(f'/api/v1/admin/photos/{photo_id}/media', headers=admin_headers).status_code == 200
    assert client.post(f'/api/v1/admin/photos/{photo_id}/review', headers=admin_headers, json={'decision': 'approve'}).status_code == 200
    assert client.post(f'/api/v1/admin/photos/{photo_id}/review', headers=admin_headers, json={'decision': 'approve'}).status_code == 409
    assert client.get('/api/v1/auth/me', headers=headers).get_json()['data']['status'] == 'active'
    assert client.get('/api/v1/match/potential', headers=headers).status_code == 200


def test_preferences_saved_after_photo_approval_activate_user(client):
    email = 'preferences-last@afinia.test'
    assert _register_user(client, email).status_code == 201
    assert client.post('/api/v1/auth/verify-email', json={'token': email_service.get_last_token_for(email)}).status_code == 204
    _, headers = _login_user(client, email)
    assert client.post('/api/v1/profile/', headers=headers, json={
        'first_name': 'Synthetic', 'birth_date': '1990-01-01', 'gender': 'otro'
    }).status_code == 201
    photo = client.post('/api/v1/profile/photos', headers=headers, data={
        'file': (_create_synthetic_image(), 'synthetic.jpg', 'image/jpeg'), 'is_primary': 'true'
    }, content_type='multipart/form-data')
    photo_id = photo.get_json()['data']['id']
    admin = _create_user_with_role(client, 'photo-admin-last@afinia.test', role='admin', lifecycle_status='pending_profile')
    assert client.post(f'/api/v1/admin/photos/{photo_id}/review', headers=admin['headers'], json={'decision': 'approve'}).status_code == 200
    assert client.get('/api/v1/match/potential', headers=headers).status_code == 403
    assert client.put('/api/v1/profile/discovery-preferences', headers=headers, json={
        'interested_in_genders': ['otro'], 'min_age': 18, 'max_age': 50
    }).status_code == 200
    assert client.get('/api/v1/match/potential', headers=headers).status_code == 200
