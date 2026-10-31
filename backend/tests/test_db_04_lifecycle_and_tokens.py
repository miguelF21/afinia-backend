import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import (
    User, Profile, DiscoveryPreference, Match,
    ProfileInteraction, AnalyticQuestionnaireAnswer, RefreshToken
)

def test_user_new_columns_and_defaults(app):
    with app.app_context():
        user = User(
            email='test_defaults@afinia.com',
            password_hash='dummy_hash'
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            queried = db.session.get(User, user_id)
            assert queried is not None
            assert isinstance(queried.id, str)
            assert len(queried.id) == 36
            assert queried.email_verified is False
            assert queried.lifecycle_status == 'pending_profile'
            assert queried.deleted_at is None
            assert queried.is_active is True
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_user_lifecycle_status_allowed_values(app):
    with app.app_context():
        allowed = ['pending_profile', 'active', 'suspended', 'deactivated']
        created_users = []
        for i, status in enumerate(allowed):
            u = User(
                email=f'user_status_{i}@afinia.com',
                password_hash='hash123',
                lifecycle_status=status
            )
            db.session.add(u)
            created_users.append((u, status))
        db.session.commit()

        try:
            for u, expected_status in created_users:
                refreshed = db.session.get(User, u.id)
                assert refreshed is not None
                # Verificación estricta: debe coincidir exactamente con el estado asignado
                assert refreshed.lifecycle_status == expected_status, (
                    f"User {u.id} lifecycle_status mismatch: expected '{expected_status}', got '{refreshed.lifecycle_status}'"
                )
        finally:
            for u, _ in created_users:
                if u and u.id:
                    user_to_del = db.session.get(User, u.id)
                    if user_to_del:
                        db.session.delete(user_to_del)
            db.session.commit()


def test_user_lifecycle_status_invalid_value_rejected(app):
    with app.app_context():
        invalid_user = User(
            email='invalid_status@afinia.com',
            password_hash='hash123',
            lifecycle_status='deleted'  # Prohibido por contrato y CHECK
        )
        db.session.add(invalid_user)
        try:
            with pytest.raises(IntegrityError):
                db.session.commit()
        finally:
            db.session.rollback()


def test_refresh_token_valid_insertion(app):
    with app.app_context():
        user = User(email='token_owner@afinia.com', password_hash='hash')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            exp = datetime.now(timezone.utc) + timedelta(days=7)
            token = RefreshToken(
                user_id=user.id,
                token_hash='a' * 64,
                expires_at=exp,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                ip_address='127.0.0.1'
            )
            db.session.add(token)
            db.session.commit()

            queried_token = RefreshToken.query.filter_by(token_hash='a' * 64).first()
            assert queried_token is not None
            assert queried_token.user_id == user.id
            assert queried_token.user.email == 'token_owner@afinia.com'
            assert queried_token.revoked_at is None
            assert queried_token.user_agent == 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            assert queried_token.ip_address == '127.0.0.1'
            assert len(queried_token.id) == 36
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_refresh_token_duplicate_hash_rejected(app):
    with app.app_context():
        user = User(email='dup_token_owner@afinia.com', password_hash='hash')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            exp = datetime.now(timezone.utc) + timedelta(days=7)
            token1 = RefreshToken(
                user_id=user.id,
                token_hash='b' * 64,
                expires_at=exp
            )
            db.session.add(token1)
            db.session.commit()

            token2 = RefreshToken(
                user_id=user.id,
                token_hash='b' * 64,  # Duplicado
                expires_at=exp
            )
            db.session.add(token2)
            with pytest.raises(IntegrityError):
                db.session.commit()
        finally:
            db.session.rollback()
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_refresh_token_revocation_and_expiration(app):
    with app.app_context():
        user = User(email='revoke_test@afinia.com', password_hash='hash')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            exp = datetime.now(timezone.utc) + timedelta(minutes=15)
            token = RefreshToken(
                user_id=user.id,
                token_hash='c' * 64,
                expires_at=exp
            )
            db.session.add(token)
            db.session.commit()

            now = datetime.now(timezone.utc)
            token.revoked_at = now
            db.session.commit()

            refreshed = RefreshToken.query.filter_by(token_hash='c' * 64).first()
            assert refreshed is not None
            assert refreshed.revoked_at is not None
            # Handle SQLite stripping tzinfo on roundtrip
            exp_ts = exp.timestamp()
            refreshed_exp_ts = refreshed.expires_at.replace(tzinfo=timezone.utc).timestamp() if refreshed.expires_at.tzinfo is None else refreshed.expires_at.timestamp()
            assert abs(refreshed_exp_ts - exp_ts) < 1.0
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_foreign_key_varchar36_cascade(app):
    """
    Verifica la cascada del ORM de SQLAlchemy (cascade='all, delete-orphan').
    NOTA DE DIFERENCIACIÓN ARQUITECTÓNICA:
    Esta prueba se ejecuta en la suite unitaria rápida sobre SQLite en memoria y valida
    el comportamiento del Unit of Work del ORM de SQLAlchemy.
    El constraint físico real 'ON DELETE CASCADE' a nivel de motor de base de datos
    es responsabilidad del servidor PostgreSQL y se valida exhaustiva y directamente
    en 'test_qa_physical_integrity.py' (PASS 8) sobre PostgreSQL QA (puerto 55433).
    Una prueba en SQLite NO demuestra el comportamiento nativo de PostgreSQL.
    """
    with app.app_context():
        user = User(email='cascade_test@afinia.com', password_hash='hash')
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        token_id = None

        try:
            token = RefreshToken(
                user_id=user.id,
                token_hash='d' * 64,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1)
            )
            db.session.add(token)
            db.session.commit()

            token_id = token.id
            assert isinstance(token.user_id, str)
            assert len(token.user_id) == 36

            # Delete user -> SQLAlchemy ORM cascade deletes child tokens
            db.session.delete(user)
            db.session.commit()

            assert db.session.get(RefreshToken, token_id) is None
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()
            if token_id:
                t = db.session.get(RefreshToken, token_id)
                if t:
                    db.session.delete(t)
                    db.session.commit()


def test_no_regression_existing_tables(app):
    with app.app_context():
        u1 = User(email='reg1@afinia.com', password_hash='h1')
        u2 = User(email='reg2@afinia.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id = u1.id
        u2_id = u2.id

        try:
            # 1. Profile
            prof = Profile(
                user_id=u1.id,
                first_name='Laura',
                birth_date=datetime(1998, 5, 20).date(),
                gender='femenino'
            )
            db.session.add(prof)

            # 2. Discovery Preference
            pref = DiscoveryPreference(
                user_id=u1.id,
                interested_in_gender='masculino',
                min_age=21,
                max_age=35
            )
            db.session.add(pref)

            # 3. Match (canonical ordering user_a_id < user_b_id)
            u_min = min(u1.id, u2.id)
            u_max = max(u1.id, u2.id)
            match = Match(user_a_id=u_min, user_b_id=u_max)
            db.session.add(match)

            # 4. Profile Interaction
            inter = ProfileInteraction(
                viewer_user_id=u1.id,
                shown_user_id=u2.id,
                action='LIKE'
            )
            db.session.add(inter)

            # 5. Analytic Answer
            ans = AnalyticQuestionnaireAnswer(
                user_id=u1.id,
                variable_name='extroversion',
                value_numeric=4
            )
            db.session.add(ans)

            db.session.commit()

            # Verify all retrieved
            assert Profile.query.filter_by(user_id=u1.id).first() is not None
            assert DiscoveryPreference.query.filter_by(user_id=u1.id).first() is not None
            assert Match.query.filter_by(user_a_id=u_min, user_b_id=u_max).first() is not None
            assert ProfileInteraction.query.filter_by(viewer_user_id=u1.id).first() is not None
            assert AnalyticQuestionnaireAnswer.query.filter_by(user_id=u1.id).first() is not None
        finally:
            for entity in [ans, inter, match, pref, prof]:
                if entity:
                    db.session.delete(entity)
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()
