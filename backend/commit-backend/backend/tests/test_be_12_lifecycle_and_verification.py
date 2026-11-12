"""
Regresiones del handoff de corrección general:

1. Coherencia entre el estado informado por /auth/me y el persistido en BD
   (antes: /auth/me -> 'active' en memoria, BD -> 'pending_profile', Discovery -> 403).
2. Registro fuera del modo test: el correo NO puede quedar verificado sin abrir el enlace.

Todas las cuentas son sintéticas y se crean en una base SQLite aislada.
"""
import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.pool import NullPool

from app import create_app, db
from app.models import DiscoveryPreference, Profile, ProfilePhoto, User
from app.services.email_service import email_service
from app.utils.security import create_access_token
from config import Config


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _headers(user):
    from flask import current_app
    token = create_access_token(user.id, user.email, user.role, current_app.config['SECRET_KEY'])
    return {'Authorization': f'Bearer {token}', 'X-Client-Platform': 'mobile'}


def _build_user(
    *,
    lifecycle_status='pending_profile',
    email_verified=True,
    with_profile=True,
    with_prefs=True,
    photo_status='ready',  # None => sin foto
):
    """Crea un usuario sintético escribiendo directamente en BD (sin pasar por la sincronización)."""
    today = datetime.now(timezone.utc).date()
    user = User(
        email=f'syn_{uuid.uuid4().hex[:10]}@afinia.test',
        password_hash='fake_hash',
        email_verified=email_verified,
        lifecycle_status=lifecycle_status,
        role='user',
    )
    db.session.add(user)
    db.session.flush()

    if with_profile:
        profile = Profile(
            user_id=user.id,
            first_name='Sintetica',
            birth_date=date(today.year - 25, today.month, today.day),
            gender='femenino',
            city='Villavicencio',
            bio='Cuenta sintética de prueba',
        )
        db.session.add(profile)
        db.session.flush()
        if photo_status is not None:
            db.session.add(ProfilePhoto(
                profile_id=profile.id,
                storage_key=f'photos/{user.id}/{uuid.uuid4().hex[:8]}.webp',
                position=0,
                is_primary=True,
                status=photo_status,
                byte_size=1024,
                content_type='image/webp',
            ))
    if with_prefs:
        db.session.add(DiscoveryPreference(
            user_id=user.id,
            interested_in_genders=['masculino'],
            min_age=18,
            max_age=40,
            target_relationship_type='seria',
        ))
    db.session.commit()
    return user


def _persisted_status(user_id):
    """Lee el estado directamente de la BD, ignorando la sesión/identidad cacheada."""
    db.session.expire_all()
    row = db.session.execute(
        db.text('SELECT lifecycle_status FROM users WHERE id = :i'), {'i': user_id}
    ).first()
    return row[0]


# -------------------------------------------------------------------------
# 1. Coherencia /auth/me <-> BD <-> Discovery / matches
# -------------------------------------------------------------------------

class TestLifecycleCoherence:
    def test_me_active_is_persisted_and_discovery_is_200(self, client):
        """Cuenta elegible con estado persistido desfasado: /auth/me, BD y Discovery deben coincidir."""
        user = _build_user(lifecycle_status='pending_profile')
        uid, h = user.id, _headers(user)
        assert _persisted_status(uid) == 'pending_profile'

        me = client.get('/api/v1/auth/me', headers=h)
        assert me.status_code == 200
        assert me.get_json()['data']['status'] == 'active'
        assert me.get_json()['data']['onboarding_complete'] is True

        # El estado informado DEBE estar persistido (antes quedaba solo en memoria)
        assert _persisted_status(uid) == 'active'

        assert client.get('/api/v1/match/potential', headers=h).status_code == 200
        assert client.get('/api/v1/match/my-matches', headers=h).status_code == 200

    def test_discovery_self_heals_without_calling_me(self, client):
        """Aunque el cliente nunca llame a /auth/me, una cuenta elegible no recibe 403."""
        user = _build_user(lifecycle_status='pending_profile')
        h = _headers(user)
        assert client.get('/api/v1/match/potential', headers=h).status_code == 200
        assert _persisted_status(user.id) == 'active'

    def test_swipe_gate_self_heals(self, client):
        """validate_viewer_can_swipe también debe reconciliar el estado antes de rechazar."""
        viewer = _build_user(lifecycle_status='pending_profile')
        res = client.post(
            '/api/v1/match/swipe',
            json={'target_user_id': str(uuid.uuid4()), 'action': 'like'},
            headers=_headers(viewer),
        )
        # El objetivo no existe => 404/422; lo importante es que NO sea el 403 de perfil incompleto.
        assert res.status_code != 403

    @pytest.mark.parametrize('missing', ['photo_pending', 'no_photo', 'no_prefs', 'unverified', 'no_profile'])
    def test_incomplete_account_is_consistently_blocked(self, client, missing):
        """Si falta un requisito real, /auth/me, BD y Discovery coinciden en 'pending_profile' / 403."""
        kwargs = {
            'photo_pending': dict(photo_status='pending'),
            'no_photo': dict(photo_status=None),
            'no_prefs': dict(with_prefs=False),
            'unverified': dict(email_verified=False),
            'no_profile': dict(with_profile=False, with_prefs=False, photo_status=None),
        }[missing]
        user = _build_user(lifecycle_status='pending_profile', **kwargs)
        h = _headers(user)

        me = client.get('/api/v1/auth/me', headers=h).get_json()['data']
        assert me['status'] == 'pending_profile'
        assert me['onboarding_complete'] is False
        assert _persisted_status(user.id) == 'pending_profile'
        assert client.get('/api/v1/match/potential', headers=h).status_code == 403

    def test_active_account_losing_photo_is_demoted_and_persisted(self, client):
        """Cuenta 'active' cuya foto deja de estar aprobada vuelve a pending_profile (persistido)."""
        user = _build_user(lifecycle_status='active', photo_status='pending')
        h = _headers(user)
        assert client.get('/api/v1/auth/me', headers=h).get_json()['data']['status'] == 'pending_profile'
        assert _persisted_status(user.id) == 'pending_profile'
        assert client.get('/api/v1/match/potential', headers=h).status_code == 403

    @pytest.mark.parametrize('status', ['suspended', 'deactivated'])
    def test_sanctioned_accounts_are_never_reactivated(self, client, status):
        user = _build_user(lifecycle_status=status)
        h = _headers(user)
        client.get('/api/v1/auth/me', headers=h)
        client.get('/api/v1/match/potential', headers=h)
        assert _persisted_status(user.id) == status

    def test_completion_order_photo_approved_last(self, client):
        """Orden de finalización: la foto se aprueba al final -> pasa de 403 a 200 sin intervención manual."""
        user = _build_user(photo_status='pending')
        h = _headers(user)
        assert client.get('/api/v1/match/potential', headers=h).status_code == 403

        photo = ProfilePhoto.query.filter_by(profile_id=user.profile.id).first()
        photo.status = 'ready'          # aprobación externa (p.ej. moderación) sin sincronizar estado
        db.session.commit()

        assert client.get('/api/v1/match/potential', headers=h).status_code == 200
        assert _persisted_status(user.id) == 'active'

    def test_completion_order_email_verified_last(self, client):
        user = _build_user(email_verified=False)
        h = _headers(user)
        assert client.get('/api/v1/match/potential', headers=h).status_code == 403
        user = db.session.get(User, user.id)
        user.email_verified = True
        db.session.commit()
        assert client.get('/api/v1/match/potential', headers=h).status_code == 200


# -------------------------------------------------------------------------
# 2. Registro fuera del modo test
# -------------------------------------------------------------------------

def _non_test_app(**overrides):
    test_dir = tempfile.mkdtemp(prefix='afinia_nt_env_')
    db_path = os.path.join(test_dir, 'nt.db')

    attrs = dict(
        TESTING=False,
        SECRET_KEY='non-test-secret-key-for-unit-tests-0123456789',
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}',
        SQLALCHEMY_ENGINE_OPTIONS={'poolclass': NullPool, 'connect_args': {'check_same_thread': False}},
        MAIL_BACKEND='in_memory',
        FLASK_ENV='development',
    )
    attrs.update(overrides)
    cfg = type('NonTestConfig', (Config,), attrs)
    return create_app(cfg), test_dir


def _register(client, email):
    return client.post('/api/v1/auth/register', json={
        'email': email,
        'password': 'ContrasenaSegura2026!',
        'accept_terms_version': 'v1-draft',
        'accept_privacy_version': 'v1-draft',
    })


@pytest.mark.parametrize('overrides,expected', [
    # Sin opt-in explícito: nunca se auto-verifica, ni siquiera con mail in_memory
    (dict(), False),
    # Producción con SMTP: jamás se auto-verifica
    (dict(FLASK_ENV='production', MAIL_BACKEND='smtp', SMTP_HOST='smtp.example.test'), False),
    # Producción ignora AUTO_VERIFY_EMAIL aunque esté activado por error
    (dict(FLASK_ENV='production', MAIL_BACKEND='smtp', SMTP_HOST='smtp.example.test', AUTO_VERIFY_EMAIL=True), False),
    # Solo opt-in explícito fuera de producción
    (dict(AUTO_VERIFY_EMAIL=True), True),
])
def test_register_outside_test_mode_requires_opening_the_link(overrides, expected, monkeypatch):
    # Sin red: el transporte real (SMTP) no se invoca en pruebas
    monkeypatch.setattr(email_service, 'send_verification_email', lambda *a, **k: None)
    app, test_dir = _non_test_app(**overrides)
    try:
        with app.app_context():
            db.create_all()
            email_service.clear_sent_messages()
            res = _register(app.test_client(), f'nt_{uuid.uuid4().hex[:8]}@afinia.test')
            assert res.status_code == 201
            assert res.get_json()['data']['email_verified'] is expected
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
