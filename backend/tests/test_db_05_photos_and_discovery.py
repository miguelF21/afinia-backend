import pytest
import uuid
from datetime import datetime, timezone, timedelta, date
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import (
    User, Profile, ProfilePhoto, DiscoveryPreference,
    Match, ProfileInteraction, AnalyticQuestionnaireAnswer, RefreshToken
)

def test_profile_photo_valid_insertion(app):
    with app.app_context():
        user = User(email='photo_owner@afinia.com', password_hash='hash123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            profile = Profile(
                user_id=user_id,
                first_name='Camila',
                birth_date=date(1997, 8, 14),
                gender='femenino'
            )
            db.session.add(profile)
            db.session.commit()
            profile_id = profile.id

            photo = ProfilePhoto(
                profile_id=profile_id,
                storage_key=f'profiles/{profile_id}/photo_0.webp',
                position=0,
                is_primary=True,
                file_name='selfie.webp',
                content_type='image/webp',
                byte_size=102400
            )
            db.session.add(photo)
            db.session.commit()
            photo_id = photo.id

            # Verify saved photo and defaults
            saved = db.session.get(ProfilePhoto, photo_id)
            assert saved is not None
            assert len(saved.id) == 36
            assert saved.profile_id == profile_id
            assert saved.storage_key == f'profiles/{profile_id}/photo_0.webp'
            assert saved.position == 0
            assert saved.is_primary is True
            assert saved.status == 'pending'  # Estado inicial seguro por defecto
            assert saved.file_name == 'selfie.webp'
            assert saved.content_type == 'image/webp'
            assert saved.byte_size == 102400
            assert saved.created_at is not None
            assert saved.updated_at is not None
            assert saved.profile.first_name == 'Camila'
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_profile_photo_invalid_profile_rejected(app):
    with app.app_context():
        nonexistent_profile_id = str(uuid.uuid4())
        photo = ProfilePhoto(
            profile_id=nonexistent_profile_id,
            storage_key='orphan.webp',
            position=0
        )
        db.session.add(photo)
        try:
            with pytest.raises(IntegrityError):
                db.session.commit()
        finally:
            db.session.rollback()


def test_profile_photo_second_primary_rejected(app):
    with app.app_context():
        user = User(email='two_primaries@afinia.com', password_hash='hash123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            profile = Profile(
                user_id=user_id,
                first_name='Carlos',
                birth_date=date(1995, 3, 10),
                gender='masculino'
            )
            db.session.add(profile)
            db.session.commit()

            # First primary photo (position 0)
            p1 = ProfilePhoto(
                profile_id=profile.id,
                storage_key='photo_primary_1.webp',
                position=0,
                is_primary=True
            )
            db.session.add(p1)
            db.session.commit()

            # Attempt second primary photo (position 1) for same profile
            p2 = ProfilePhoto(
                profile_id=profile.id,
                storage_key='photo_primary_2.webp',
                position=1,
                is_primary=True
            )
            db.session.add(p2)
            with pytest.raises(IntegrityError):
                db.session.commit()
        finally:
            db.session.rollback()
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_profile_photo_position_ordering_and_duplicates_rejected(app):
    with app.app_context():
        user = User(email='dup_pos@afinia.com', password_hash='hash123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            profile = Profile(
                user_id=user_id,
                first_name='Mariana',
                birth_date=date(2000, 1, 1),
                gender='femenino'
            )
            db.session.add(profile)
            db.session.commit()

            p1 = ProfilePhoto(
                profile_id=profile.id,
                storage_key='photo_pos0_a.webp',
                position=0,
                is_primary=False
            )
            db.session.add(p1)
            db.session.commit()

            # Attempt duplicate position 0
            p2 = ProfilePhoto(
                profile_id=profile.id,
                storage_key='photo_pos0_b.webp',
                position=0,
                is_primary=False
            )
            db.session.add(p2)
            with pytest.raises(IntegrityError):
                db.session.commit()
        finally:
            db.session.rollback()
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_profile_photo_invalid_status_rejected(app):
    with app.app_context():
        user = User(email='bad_status@afinia.com', password_hash='hash123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            profile = Profile(
                user_id=user_id,
                first_name='Esteban',
                birth_date=date(1996, 6, 21),
                gender='masculino'
            )
            db.session.add(profile)
            db.session.commit()

            photo = ProfilePhoto(
                profile_id=profile.id,
                storage_key='photo.webp',
                position=0,
                status='invalid_status_xyz'
            )
            db.session.add(photo)
            with pytest.raises(IntegrityError):
                db.session.commit()
        finally:
            db.session.rollback()
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_profile_photo_position_range_and_max_six_enforcement(app):
    with app.app_context():
        user = User(email='six_photos@afinia.com', password_hash='hash123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            profile = Profile(
                user_id=user_id,
                first_name='Valentina',
                birth_date=date(1999, 11, 5),
                gender='femenino'
            )
            db.session.add(profile)
            db.session.commit()

            # Insert exactly 6 valid photos (positions 0, 1, 2, 3, 4, 5)
            for pos in range(6):
                p = ProfilePhoto(
                    profile_id=profile.id,
                    storage_key=f'photo_{pos}.webp',
                    position=pos,
                    is_primary=(pos == 0)
                )
                db.session.add(p)
            db.session.commit()

            # Verify all 6 photos stored in profile
            refreshed_prof = db.session.get(Profile, profile.id)
            assert len(refreshed_prof.photos) == 6
            assert [photo.position for photo in refreshed_prof.photos] == [0, 1, 2, 3, 4, 5]

            # Attempt 7th photo at position 6 (forbidden by CHECK position >= 0 AND position <= 5)
            p7 = ProfilePhoto(
                profile_id=profile.id,
                storage_key='photo_overflow.webp',
                position=6,
                is_primary=False
            )
            db.session.add(p7)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # Attempt negative position (forbidden by CHECK position >= 0)
            p_neg = ProfilePhoto(
                profile_id=profile.id,
                storage_key='photo_neg.webp',
                position=-1,
                is_primary=False
            )
            db.session.add(p_neg)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

        finally:
            db.session.rollback()
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_discovery_preferences_multiple_genders_storage(app):
    with app.app_context():
        user = User(email='multi_genders@afinia.com', password_hash='hash123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            genders_list = ['masculino', 'no_binario']
            pref = DiscoveryPreference(
                user_id=user_id,
                interested_in_genders=genders_list,
                min_age=20,
                max_age=30
            )
            db.session.add(pref)
            db.session.commit()

            queried = DiscoveryPreference.query.filter_by(user_id=user_id).first()
            assert queried is not None
            assert queried.interested_in_genders == ['masculino', 'no_binario']
            assert isinstance(queried.interested_in_genders, list)
            assert len(queried.interested_in_genders) == 2
            # Fuente canónica única para OpenAPI v1
            assert queried.canonical_interested_in_genders == ['masculino', 'no_binario']
            # Para combinaciones no binarias no se inventa equivalencia escalar; debe ser None
            assert queried.interested_in_gender is None
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_discovery_preferences_invalid_gender_rejected(app):
    with app.app_context():
        user = User(email='invalid_genders@afinia.com', password_hash='hash123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            # 1. Invalid gender value
            with pytest.raises(ValueError, match="Invalid gender value"):
                DiscoveryPreference(
                    user_id=user_id,
                    interested_in_genders=['masculino', 'alien_gender']
                )

            # 2. Empty array (violates minItems: 1)
            with pytest.raises(ValueError, match="at least 1 item"):
                DiscoveryPreference(
                    user_id=user_id,
                    interested_in_genders=[]
                )

            # 3. Duplicate values (violates uniqueItems: true)
            with pytest.raises(ValueError, match="no duplicates"):
                DiscoveryPreference(
                    user_id=user_id,
                    interested_in_genders=['masculino', 'masculino']
                )
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_discovery_preferences_legacy_conversion(app):
    with app.app_context():
        u1 = User(email='legacy_f@afinia.com', password_hash='hash123')
        u2 = User(email='legacy_ambos@afinia.com', password_hash='hash123')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id = u1.id
        u2_id = u2.id

        try:
            # Legacy single gender 'femenino' -> ['femenino']
            pref1 = DiscoveryPreference(
                user_id=u1_id,
                interested_in_gender='femenino'
            )
            db.session.add(pref1)

            # Legacy 'ambos' -> ['masculino', 'femenino']
            pref2 = DiscoveryPreference(
                user_id=u2_id,
                interested_in_gender='ambos'
            )
            db.session.add(pref2)
            db.session.commit()

            q1 = DiscoveryPreference.query.filter_by(user_id=u1_id).first()
            assert q1.interested_in_genders == ['femenino']
            assert q1.interested_in_gender == 'femenino'

            q2 = DiscoveryPreference.query.filter_by(user_id=u2_id).first()
            assert q2.interested_in_genders == ['masculino', 'femenino']
            assert q2.interested_in_gender == 'ambos'
        finally:
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_no_regression_full_domain(app):
    with app.app_context():
        u1 = User(email='full1@afinia.com', password_hash='h1', lifecycle_status='active')
        u2 = User(email='full2@afinia.com', password_hash='h2', lifecycle_status='pending_profile')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id = u1.id
        u2_id = u2.id

        ans = None
        inter = None
        match = None
        token = None
        pref = None
        photo1 = None
        photo2 = None
        prof1 = None
        prof2 = None

        try:
            # 1. Profiles & Photos
            prof1 = Profile(user_id=u1_id, first_name='Ana', birth_date=date(1996, 4, 12), gender='femenino')
            prof2 = Profile(user_id=u2_id, first_name='Mateo', birth_date=date(1994, 9, 28), gender='masculino')
            db.session.add_all([prof1, prof2])
            db.session.commit()

            photo1 = ProfilePhoto(profile_id=prof1.id, storage_key='ana_0.webp', position=0, is_primary=True)
            photo2 = ProfilePhoto(profile_id=prof2.id, storage_key='mateo_0.webp', position=0, is_primary=True)
            db.session.add_all([photo1, photo2])

            # 2. RefreshToken
            token = RefreshToken(
                user_id=u1_id,
                token_hash='e' * 64,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
            db.session.add(token)

            # 3. DiscoveryPreference
            pref = DiscoveryPreference(
                user_id=u1_id,
                interested_in_genders=['masculino'],
                min_age=25,
                max_age=35
            )
            db.session.add(pref)

            # 4. Match
            u_min = min(u1_id, u2_id)
            u_max = max(u1_id, u2_id)
            match = Match(user_a_id=u_min, user_b_id=u_max)
            db.session.add(match)

            # 5. ProfileInteraction
            inter = ProfileInteraction(viewer_user_id=u1_id, shown_user_id=u2_id, action='LIKE')
            db.session.add(inter)

            # 6. Analytic Answer
            ans = AnalyticQuestionnaireAnswer(user_id=u1_id, variable_name='openness', value_numeric=5)
            db.session.add(ans)

            db.session.commit()

            # Assert all exist
            assert db.session.get(User, u1_id).lifecycle_status == 'active'
            assert db.session.get(User, u2_id).lifecycle_status == 'pending_profile'
            assert db.session.get(Profile, prof1.id).first_name == 'Ana'
            assert len(db.session.get(Profile, prof1.id).photos) == 1
            assert db.session.get(ProfilePhoto, photo1.id).is_primary is True
            assert db.session.get(RefreshToken, token.id) is not None
            assert db.session.get(DiscoveryPreference, pref.id).interested_in_genders == ['masculino']
            assert db.session.get(Match, match.id) is not None
            assert db.session.get(ProfileInteraction, inter.id).action == 'LIKE'
            assert db.session.get(AnalyticQuestionnaireAnswer, ans.id).value_numeric == 5
        finally:
            for entity in [ans, inter, match, token, pref, photo1, photo2, prof1, prof2]:
                if entity:
                    db.session.delete(entity)
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_profile_photo_on_delete_cascade_orm(app):
    """
    Verifica la eliminación en cascada en el ORM: al eliminar un Profile,
    sus ProfilePhotos asociadas son eliminadas automáticamente.
    """
    with app.app_context():
        user = User(email='cascade_photo@afinia.com', password_hash='hash123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            profile = Profile(
                user_id=user_id,
                first_name='Sofia',
                birth_date=date(2001, 7, 7),
                gender='femenino'
            )
            db.session.add(profile)
            db.session.commit()
            profile_id = profile.id

            photo = ProfilePhoto(
                profile_id=profile_id,
                storage_key='sofia_0.webp',
                position=0,
                is_primary=True
            )
            db.session.add(photo)
            db.session.commit()
            photo_id = photo.id

            # Delete profile -> ORM cascade should delete photo
            db.session.delete(profile)
            db.session.commit()

            assert db.session.get(ProfilePhoto, photo_id) is None
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_profile_photo_storage_key_unique(app):
    """Verifica que storage_key no puede reutilizarse entre fotos."""
    with app.app_context():
        user = User(email='storage_key_test@afinia.com', password_hash='h123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            profile = Profile(
                user_id=user_id,
                first_name='Laura',
                birth_date=date(1998, 5, 20),
                gender='femenino'
            )
            db.session.add(profile)
            db.session.commit()

            p1 = ProfilePhoto(profile_id=profile.id, storage_key='shared_object.webp', position=0)
            db.session.add(p1)
            db.session.commit()

            # Intentar reutilizar la misma storage_key
            p2 = ProfilePhoto(profile_id=profile.id, storage_key='shared_object.webp', position=1)
            db.session.add(p2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_profile_public_photos_filter(app):
    """Verifica que public_photos expone únicamente fotos con status 'ready'."""
    with app.app_context():
        user = User(email='filter_status@afinia.com', password_hash='h123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            profile = Profile(
                user_id=user_id,
                first_name='Gabriel',
                birth_date=date(1995, 2, 14),
                gender='masculino'
            )
            db.session.add(profile)
            db.session.commit()

            # Foto 0: ready
            p0 = ProfilePhoto(profile_id=profile.id, storage_key='p0.webp', position=0, status='ready', is_primary=True)
            # Foto 1: pending (aún no aprobada por moderación/subida)
            p1 = ProfilePhoto(profile_id=profile.id, storage_key='p1.webp', position=1, status='pending')
            # Foto 2: rejected (rechazada por moderación)
            p2 = ProfilePhoto(profile_id=profile.id, storage_key='p2.webp', position=2, status='rejected')
            db.session.add_all([p0, p1, p2])
            db.session.commit()

            refreshed = db.session.get(Profile, profile.id)
            assert len(refreshed.photos) == 3
            # Solo la foto aprobada debe figurar para perfiles públicos
            assert len(refreshed.public_photos) == 1
            assert refreshed.public_photos[0].storage_key == 'p0.webp'
            assert refreshed.public_photos[0].status == 'ready'
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_discovery_preferences_mutation_in_place_persisted(app):
    """Verifica que las mutaciones in-place en la lista JSONB son detectadas por MutableList y persistidas."""
    with app.app_context():
        user = User(email='inplace_mutation@afinia.com', password_hash='h123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            pref = DiscoveryPreference(
                user_id=user_id,
                interested_in_genders=['masculino'],
                min_age=20,
                max_age=30
            )
            db.session.add(pref)
            db.session.commit()
            pref_id = pref.id

            # Mutación in-place (append)
            pref_obj = db.session.get(DiscoveryPreference, pref_id)
            pref_obj.interested_in_genders.append('no_binario')
            db.session.commit()

            # Limpiar sesión y consultar desde la base de datos
            db.session.expire_all()
            reloaded = db.session.get(DiscoveryPreference, pref_id)
            assert reloaded.interested_in_genders == ['masculino', 'no_binario']
            assert 'no_binario' in reloaded.canonical_interested_in_genders

            # Mutación in-place (index assignment)
            reloaded.interested_in_genders[0] = 'femenino'
            db.session.commit()

            db.session.expire_all()
            reloaded2 = db.session.get(DiscoveryPreference, pref_id)
            assert reloaded2.interested_in_genders == ['femenino', 'no_binario']
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_discovery_preferences_reassignment_persisted(app):
    """Verifica que la reasignación completa de la lista JSONB es persistida."""
    with app.app_context():
        user = User(email='reassignment@afinia.com', password_hash='h123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            pref = DiscoveryPreference(
                user_id=user_id,
                interested_in_genders=['femenino'],
                min_age=22,
                max_age=35
            )
            db.session.add(pref)
            db.session.commit()
            pref_id = pref.id

            pref_obj = db.session.get(DiscoveryPreference, pref_id)
            pref_obj.interested_in_genders = ['masculino', 'no_binario', 'otro']
            db.session.commit()

            db.session.expire_all()
            reloaded = db.session.get(DiscoveryPreference, pref_id)
            assert reloaded.interested_in_genders == ['masculino', 'no_binario', 'otro']
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_discovery_preferences_semantic_contradiction_rejected(app):
    """Verifica que combinaciones semánticamente incompatibles entre interested_in_gender y genders sean rechazadas."""
    with app.app_context():
        user = User(email='contradiction@afinia.com', password_hash='h123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            # Caso observado en auditoría: interested_in_gender='ambos' con ['masculino', 'no_binario']
            with pytest.raises(ValueError, match="Conflicto semántico"):
                DiscoveryPreference(
                    user_id=user_id,
                    interested_in_gender='ambos',
                    interested_in_genders=['masculino', 'no_binario']
                )

            # interested_in_gender='femenino' con ['masculino']
            with pytest.raises(ValueError, match="Conflicto semántico"):
                DiscoveryPreference(
                    user_id=user_id,
                    interested_in_gender='femenino',
                    interested_in_genders=['masculino']
                )
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()


def test_discovery_preferences_unconfigured_null(app):
    """Verifica que NULL representa preferencias todavía no configuradas."""
    with app.app_context():
        user = User(email='unconfigured@afinia.com', password_hash='h123')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        try:
            pref = DiscoveryPreference(
                user_id=user_id,
                interested_in_genders=None,
                interested_in_gender=None,
                min_age=18,
                max_age=99
            )
            db.session.add(pref)
            db.session.commit()

            reloaded = db.session.get(DiscoveryPreference, pref.id)
            assert reloaded.interested_in_genders is None
            assert reloaded.interested_in_gender is None
            # canonical_interested_in_genders retorna None cuando no están configuradas
            assert reloaded.canonical_interested_in_genders is None
        finally:
            u = db.session.get(User, user_id)
            if u:
                db.session.delete(u)
                db.session.commit()
