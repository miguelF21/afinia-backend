import pytest
import uuid
from datetime import datetime, timezone, timedelta, date
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import (
    User, Profile, ProfilePhoto, DiscoveryPreference,
    Match, ProfileInteraction, AnalyticQuestionnaireAnswer, RefreshToken,
    UserBlock, UserReport, LegalConsent
)


def test_user_block_creation_and_bidirectional_persistence(app):
    """
    Verifica la creación de un bloqueo válido y que bloqueos recíprocos
    persisten como registros independientes sin colisionar.
    """
    with app.app_context():
        u1 = User(email='blocker@test.com', password_hash='h1')
        u2 = User(email='blocked@test.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id = u1.id
        u2_id = u2.id

        try:
            # 1. Bloqueo u1 -> u2
            block1 = UserBlock(blocker_user_id=u1_id, blocked_user_id=u2_id)
            db.session.add(block1)
            db.session.commit()
            assert block1.id is not None
            assert len(block1.id) == 36
            assert block1.created_at is not None

            # 2. Bloqueo recíproco u2 -> u1 (persistencia distinta)
            block2 = UserBlock(blocker_user_id=u2_id, blocked_user_id=u1_id)
            db.session.add(block2)
            db.session.commit()
            assert block2.id is not None
            assert block1.id != block2.id

            # Comprobar relaciones desde User
            u1_reloaded = db.session.get(User, u1_id)
            assert len(u1_reloaded.blocks_issued) == 1
            assert len(u1_reloaded.blocks_received) == 1
            assert u1_reloaded.blocks_issued[0].blocked_user_id == u2_id
        finally:
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_user_block_self_block_rejected(app):
    """Verifica que un usuario no pueda bloquearse a sí mismo (ck_user_blocks_no_self)."""
    with app.app_context():
        u = User(email='self_block@test.com', password_hash='h1')
        db.session.add(u)
        db.session.commit()
        u_id = u.id

        try:
            block = UserBlock(blocker_user_id=u_id, blocked_user_id=u_id)
            db.session.add(block)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            user = db.session.get(User, u_id)
            if user:
                db.session.delete(user)
                db.session.commit()


def test_user_block_duplicate_rejected(app):
    """Verifica que no se puedan insertar bloqueos duplicados en la misma dirección (uq_user_blocks_pair)."""
    with app.app_context():
        u1 = User(email='dup_block_1@test.com', password_hash='h1')
        u2 = User(email='dup_block_2@test.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id = u1.id
        u2_id = u2.id

        try:
            b1 = UserBlock(blocker_user_id=u1_id, blocked_user_id=u2_id)
            db.session.add(b1)
            db.session.commit()

            # Intentar duplicar
            b2 = UserBlock(blocker_user_id=u1_id, blocked_user_id=u2_id)
            db.session.add(b2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            for uid in [u1_id, u2_id]:
                user = db.session.get(User, uid)
                if user:
                    db.session.delete(user)
            db.session.commit()


def test_user_block_nonexistent_user_rejected(app):
    """Verifica que referencias a usuarios inexistentes sean rechazadas por clave foránea."""
    with app.app_context():
        u1 = User(email='existing_blocker@test.com', password_hash='h1')
        db.session.add(u1)
        db.session.commit()
        u1_id = u1.id

        try:
            fake_id = str(uuid.uuid4())
            block = UserBlock(blocker_user_id=u1_id, blocked_user_id=fake_id)
            db.session.add(block)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            user = db.session.get(User, u1_id)
            if user:
                db.session.delete(user)
                db.session.commit()


def test_user_report_valid_creation_and_defaults(app):
    """Verifica la creación de un reporte de moderación válido con estado inicial pending."""
    with app.app_context():
        u_rep = User(email='reporter@test.com', password_hash='h1')
        u_bad = User(email='reported@test.com', password_hash='h2')
        db.session.add_all([u_rep, u_bad])
        db.session.commit()
        rep_id = u_rep.id
        bad_id = u_bad.id

        try:
            report = UserReport(
                reporter_user_id=rep_id,
                reported_user_id=bad_id,
                reason='acoso',
                description='Envía mensajes agresivos reiteradamente.'
            )
            db.session.add(report)
            db.session.commit()

            saved = db.session.get(UserReport, report.id)
            assert saved is not None
            assert saved.status == 'pending'
            assert saved.reason == 'acoso'
            assert saved.created_at is not None
            assert saved.resolved_at is None
            assert saved.resolved_by_user_id is None
            assert saved.resolution_action is None
        finally:
            rep = db.session.get(UserReport, report.id) if 'report' in locals() else None
            if rep:
                db.session.delete(rep)
            for uid in [rep_id, bad_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_user_report_self_report_rejected(app):
    """Verifica que un usuario no pueda denunciarse a sí mismo (ck_user_reports_no_self)."""
    with app.app_context():
        u = User(email='self_report@test.com', password_hash='h1')
        db.session.add(u)
        db.session.commit()
        u_id = u.id

        try:
            report = UserReport(
                reporter_user_id=u_id,
                reported_user_id=u_id,
                reason='spam'
            )
            db.session.add(report)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            user = db.session.get(User, u_id)
            if user:
                db.session.delete(user)
                db.session.commit()


def test_user_report_invalid_reason_or_status_rejected(app):
    """Verifica que motivos o estados no contemplados por OpenAPI sean rechazados."""
    with app.app_context():
        u1 = User(email='r_inv_1@test.com', password_hash='h1')
        u2 = User(email='r_inv_2@test.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id = u1.id
        u2_id = u2.id

        try:
            # 1. Motivo inválido
            r_bad_reason = UserReport(
                reporter_user_id=u1_id,
                reported_user_id=u2_id,
                reason='motivo_no_existente'
            )
            db.session.add(r_bad_reason)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # 2. Estado inválido
            r_bad_status = UserReport(
                reporter_user_id=u1_id,
                reported_user_id=u2_id,
                reason='spam',
                status='in_progress'
            )
            db.session.add(r_bad_status)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_user_report_resolution_consistency_enforced(app):
    """Verifica la restricción de coherencia entre status y los campos de resolución."""
    with app.app_context():
        u_rep = User(email='rep_cons_1@test.com', password_hash='h1')
        u_bad = User(email='rep_cons_2@test.com', password_hash='h2')
        u_mod = User(email='rep_mod@test.com', password_hash='h3')
        db.session.add_all([u_rep, u_bad, u_mod])
        db.session.commit()
        u_rep_id = u_rep.id
        u_bad_id = u_bad.id
        u_mod_id = u_mod.id

        try:
            # Caso inválido 1: status='pending' pero con resolution_action especificada
            r_incons1 = UserReport(
                reporter_user_id=u_rep_id,
                reported_user_id=u_bad_id,
                reason='spam',
                status='pending',
                resolution_action='warn'
            )
            db.session.add(r_incons1)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # Caso inválido 2: status='resolved' pero sin resolution_action ni resolved_at
            r_incons2 = UserReport(
                reporter_user_id=u_rep_id,
                reported_user_id=u_bad_id,
                reason='spam',
                status='resolved'
            )
            db.session.add(r_incons2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # Caso válido: resolución correcta mediante método de dominio
            report = UserReport(
                reporter_user_id=u_rep_id,
                reported_user_id=u_bad_id,
                reason='suplantacion',
                description='Usa fotos de otra persona.'
            )
            db.session.add(report)
            db.session.commit()

            # Resolver con moderador
            report.resolve(moderator_id=u_mod_id, action='suspend', notes='Perfil falso verificado.')
            db.session.commit()

            saved = db.session.get(UserReport, report.id)
            assert saved.status == 'resolved'
            assert saved.resolution_action == 'suspend'
            assert saved.resolved_by_user_id == u_mod_id
            assert saved.resolved_at is not None
            assert saved.resolution_notes == 'Perfil falso verificado.'
        finally:
            reps = UserReport.query.filter(UserReport.reporter_user_id == u_rep_id).all()
            for r in reps:
                db.session.delete(r)
            for uid in [u_rep_id, u_bad_id, u_mod_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_legal_consent_creation_and_immutability(app):
    """Verifica la persistencia de consentimientos legales y el registro de versiones."""
    with app.app_context():
        u = User(email='legal_user@test.com', password_hash='h1')
        db.session.add(u)
        db.session.commit()
        u_id = u.id

        try:
            # 1. Aceptación de términos v1.0
            c_terms = LegalConsent(
                user_id=u_id,
                document_type='terms_of_service',
                document_version='v1.0',
                ip_address='192.168.1.50'
            )
            # 2. Aceptación de privacidad v1.0
            c_priv = LegalConsent(
                user_id=u_id,
                document_type='privacy_policy',
                document_version='v1.0',
                ip_address='192.168.1.50'
            )
            db.session.add_all([c_terms, c_priv])
            db.session.commit()

            assert c_terms.id is not None
            assert c_priv.id is not None
            assert c_terms.accepted_at is not None

            # 3. Rechazo de duplicado de la misma versión por el mismo usuario
            c_dup = LegalConsent(
                user_id=u_id,
                document_type='terms_of_service',
                document_version='v1.0'
            )
            db.session.add(c_dup)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # 4. Aceptación de nueva versión v1.1 aceptada y conservando historial
            c_terms_v2 = LegalConsent(
                user_id=u_id,
                document_type='terms_of_service',
                document_version='v1.1'
            )
            db.session.add(c_terms_v2)
            db.session.commit()

            u_reloaded = db.session.get(User, u_id)
            assert len(u_reloaded.legal_consents) == 3
            terms_versions = [c.document_version for c in u_reloaded.legal_consents if c.document_type == 'terms_of_service']
            assert 'v1.0' in terms_versions
            assert 'v1.1' in terms_versions
        finally:
            consents = LegalConsent.query.filter_by(user_id=u_id).all()
            for c in consents:
                db.session.delete(c)
            user = db.session.get(User, u_id)
            if user:
                db.session.delete(user)
            db.session.commit()


def test_legal_consent_invalid_doc_type_rejected(app):
    """Verifica el rechazo de tipos de documentos no contemplados por ck_legal_consents_doc_type."""
    with app.app_context():
        u = User(email='bad_doc@test.com', password_hash='h1')
        db.session.add(u)
        db.session.commit()
        u_id = u.id

        try:
            bad_consent = LegalConsent(
                user_id=u_id,
                document_type='contrato_no_autorizado',
                document_version='v1.0'
            )
            db.session.add(bad_consent)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            user = db.session.get(User, u_id)
            if user:
                db.session.delete(user)
                db.session.commit()


def test_no_regression_domain_with_all_twelve_models(app):
    """
    Verifica que la integración de los 3 nuevos modelos coexiste sin regresiones
    con los 9 modelos y tablas anteriores.
    """
    with app.app_context():
        u1 = User(email='domain12_u1@afinia.com', password_hash='h1', lifecycle_status='active')
        u2 = User(email='domain12_u2@afinia.com', password_hash='h2', lifecycle_status='active')
        u_mod = User(email='domain12_mod@afinia.com', password_hash='hm', lifecycle_status='active')
        db.session.add_all([u1, u2, u_mod])
        db.session.commit()
        u1_id, u2_id, mod_id = u1.id, u2.id, u_mod.id

        entities = []
        try:
            # 1. Profile & Photo
            p1 = Profile(user_id=u1_id, first_name='Elena', birth_date=date(1996, 5, 10), gender='femenino')
            p2 = Profile(user_id=u2_id, first_name='Tomás', birth_date=date(1994, 8, 20), gender='masculino')
            db.session.add_all([p1, p2])
            db.session.commit()
            entities.extend([p1, p2])

            photo = ProfilePhoto(profile_id=p1.id, storage_key='elena_0.webp', position=0, is_primary=True, status='ready')
            db.session.add(photo)

            # 2. Discovery
            pref = DiscoveryPreference(user_id=u1_id, interested_in_genders=['masculino'], min_age=25, max_age=35)
            db.session.add(pref)

            # 3. Match & Interaction
            match = Match(user_a_id=min(u1_id, u2_id), user_b_id=max(u1_id, u2_id))
            inter = ProfileInteraction(viewer_user_id=u1_id, shown_user_id=u2_id, action='LIKE')
            token = RefreshToken(user_id=u1_id, token_hash='f' * 64, expires_at=datetime.now(timezone.utc) + timedelta(days=7))
            ans = AnalyticQuestionnaireAnswer(user_id=u1_id, variable_name='extroversion', value_numeric=4)
            db.session.add_all([match, inter, token, ans])

            # 4. DB-06 Models: Block, Report, Consent
            block = UserBlock(blocker_user_id=u1_id, blocked_user_id=u2_id)
            report = UserReport(reporter_user_id=u2_id, reported_user_id=u1_id, reason='otro', description='Prueba dominio')
            consent = LegalConsent(user_id=u1_id, document_type='terms_of_service', document_version='v1.0')
            db.session.add_all([block, report, consent])
            db.session.commit()

            # Verify all 12 entities persist and load cleanly
            assert db.session.get(User, u1_id) is not None
            assert db.session.get(Profile, p1.id) is not None
            assert db.session.get(ProfilePhoto, photo.id).status == 'ready'
            assert db.session.get(DiscoveryPreference, pref.id).interested_in_genders == ['masculino']
            assert db.session.get(Match, match.id) is not None
            assert db.session.get(ProfileInteraction, inter.id) is not None
            assert db.session.get(RefreshToken, token.id) is not None
            assert db.session.get(AnalyticQuestionnaireAnswer, ans.id) is not None
            assert db.session.get(UserBlock, block.id) is not None
            assert db.session.get(UserReport, report.id) is not None
            assert db.session.get(LegalConsent, consent.id) is not None
        finally:
            for entity in [report, block, consent, ans, token, inter, match, photo, p1, p2]:
                if entity:
                    try:
                        db.session.delete(entity)
                    except Exception:
                        db.session.rollback()
            for uid in [u1_id, u2_id, mod_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()
