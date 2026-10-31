import pytest
import uuid
from datetime import datetime, timezone, timedelta, date
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import (
    User, Profile, ProfilePhoto, DiscoveryPreference,
    Match, ProfileInteraction, AnalyticQuestionnaireAnswer, RefreshToken,
    UserBlock, UserReport, LegalConsent, Message
)


def test_user_role_default_and_allowed_values(app):
    """
    Verifica que:
    1. Un nuevo usuario recibe role='user' por defecto.
    2. Los roles 'moderator' y 'admin' persisten correctamente.
    """
    with app.app_context():
        u_default = User(email='role_default@test.com', password_hash='h1')
        u_mod = User(email='role_mod@test.com', password_hash='h2', role='moderator')
        u_admin = User(email='role_admin@test.com', password_hash='h3', role='admin')
        
        db.session.add_all([u_default, u_mod, u_admin])
        db.session.commit()

        u_def_id = u_default.id
        u_mod_id = u_mod.id
        u_adm_id = u_admin.id

        try:
            r_def = db.session.get(User, u_def_id)
            r_mod = db.session.get(User, u_mod_id)
            r_adm = db.session.get(User, u_adm_id)

            assert r_def.role == 'user', f"Esperado 'user', obtenido '{r_def.role}'"
            assert r_mod.role == 'moderator', f"Esperado 'moderator', obtenido '{r_mod.role}'"
            assert r_adm.role == 'admin', f"Esperado 'admin', obtenido '{r_adm.role}'"
        finally:
            for uid in [u_def_id, u_mod_id, u_adm_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_user_role_invalid_value_rejected(app):
    """Verifica que roles fuera de ('user', 'moderator', 'admin') sean rechazados por ck_users_role."""
    with app.app_context():
        u_invalid = User(email='role_bad@test.com', password_hash='h1', role='superadmin')
        db.session.add(u_invalid)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        u_empty = User(email='role_empty@test.com', password_hash='h2', role='')
        db.session.add(u_empty)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_message_valid_creation_and_fields(app):
    """
    Verifica la inserción de un mensaje válido en un match existente,
    la persistencia de sent_at, read_at y la propiedad computada is_read.
    """
    with app.app_context():
        u1 = User(email='msg_u1@test.com', password_hash='h1')
        u2 = User(email='msg_u2@test.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id = u1.id
        u2_id = u2.id

        # Orden canónico u1 < u2
        a_id, b_id = (u1_id, u2_id) if u1_id < u2_id else (u2_id, u1_id)
        m = Match(user_a_id=a_id, user_b_id=b_id)
        db.session.add(m)
        db.session.commit()
        m_id = m.id

        msg_id = None
        try:
            msg = Message(
                match_id=m_id,
                sender_user_id=u1_id,
                text='¡Hola! ¿Cómo estás?'
            )
            db.session.add(msg)
            db.session.commit()
            msg_id = msg.id

            saved_msg = db.session.get(Message, msg_id)
            assert saved_msg is not None
            assert len(saved_msg.id) == 36
            assert saved_msg.match_id == m_id
            assert saved_msg.sender_user_id == u1_id
            assert saved_msg.text == '¡Hola! ¿Cómo estás?'
            assert saved_msg.sent_at is not None
            assert saved_msg.read_at is None
            assert saved_msg.is_read is False

            # Marcar leído
            now_utc = datetime.now(timezone.utc)
            saved_msg.read_at = now_utc
            db.session.commit()

            reloaded = db.session.get(Message, msg_id)
            assert reloaded.read_at is not None
            assert reloaded.is_read is True
            assert len(reloaded.match.messages) == 1
            assert len(reloaded.sender.messages_sent) == 1
        finally:
            if msg_id:
                m_obj = db.session.get(Message, msg_id)
                if m_obj:
                    db.session.delete(m_obj)
                    db.session.commit()
            match_to_del = db.session.get(Match, m_id)
            if match_to_del:
                db.session.delete(match_to_del)
                db.session.commit()
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_message_whitespace_and_empty_rejected(app):
    """
    Verifica que mensajes vacíos o compuestos exclusivamente por espacios
    sean rechazados por ck_messages_text_length.
    """
    with app.app_context():
        u1 = User(email='msg_sp1@test.com', password_hash='h1')
        u2 = User(email='msg_sp2@test.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id = u1.id
        u2_id = u2.id

        a_id, b_id = (u1_id, u2_id) if u1_id < u2_id else (u2_id, u1_id)
        m = Match(user_a_id=a_id, user_b_id=b_id)
        db.session.add(m)
        db.session.commit()
        m_id = m.id

        try:
            # 1. Texto vacío
            msg_empty = Message(match_id=m_id, sender_user_id=u1_id, text='')
            db.session.add(msg_empty)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # 2. Solo un espacio
            msg_one_space = Message(match_id=m_id, sender_user_id=u1_id, text=' ')
            db.session.add(msg_one_space)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # 3. Múltiples espacios
            msg_spaces = Message(match_id=m_id, sender_user_id=u1_id, text='      ')
            db.session.add(msg_spaces)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            match_to_del = db.session.get(Match, m_id)
            if match_to_del:
                db.session.delete(match_to_del)
                db.session.commit()
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_message_max_length_enforced(app):
    """Verifica que textos de hasta 2000 caracteres sean admitidos y más de 2000 sean rechazados."""
    with app.app_context():
        u1 = User(email='msg_len1@test.com', password_hash='h1')
        u2 = User(email='msg_len2@test.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id, u2_id = u1.id, u2.id

        a_id, b_id = (u1_id, u2_id) if u1_id < u2_id else (u2_id, u1_id)
        m = Match(user_a_id=a_id, user_b_id=b_id)
        db.session.add(m)
        db.session.commit()
        m_id = m.id

        msg_2000_id = None
        try:
            # Exactamente 2000 caracteres -> válido
            msg_2000 = Message(match_id=m_id, sender_user_id=u1_id, text='A' * 2000)
            db.session.add(msg_2000)
            db.session.commit()
            msg_2000_id = msg_2000.id
            assert len(msg_2000.text) == 2000

            # 2001 caracteres -> rechazado
            msg_2001 = Message(match_id=m_id, sender_user_id=u1_id, text='B' * 2001)
            db.session.add(msg_2001)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            if msg_2000_id:
                m_obj = db.session.get(Message, msg_2000_id)
                if m_obj:
                    db.session.delete(m_obj)
                    db.session.commit()
            match_to_del = db.session.get(Match, m_id)
            if match_to_del:
                db.session.delete(match_to_del)
                db.session.commit()
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_message_nonexistent_references_rejected(app):
    """Verifica que mensajes referenciando match o sender inexistentes sean rechazados."""
    with app.app_context():
        u = User(email='msg_ref@test.com', password_hash='h1')
        db.session.add(u)
        db.session.commit()
        u_id = u.id

        try:
            # Match inexistente
            bad_match = Message(match_id=str(uuid.uuid4()), sender_user_id=u_id, text='Hola')
            db.session.add(bad_match)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # Emisor inexistente (match válido ficticio)
            u2 = User(email='msg_ref2@test.com', password_hash='h2')
            db.session.add(u2)
            db.session.commit()
            u2_id = u2.id
            a_id, b_id = (u_id, u2_id) if u_id < u2_id else (u2_id, u_id)
            m = Match(user_a_id=a_id, user_b_id=b_id)
            db.session.add(m)
            db.session.commit()
            m_id = m.id

            bad_sender = Message(match_id=m_id, sender_user_id=str(uuid.uuid4()), text='Hola')
            db.session.add(bad_sender)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            match_to_del = db.session.get(Match, m_id)
            if match_to_del:
                db.session.delete(match_to_del)
                db.session.commit()
            user2_to_del = db.session.get(User, u2_id)
            if user2_to_del:
                db.session.delete(user2_to_del)
                db.session.commit()
        finally:
            u_obj = db.session.get(User, u_id)
            if u_obj:
                db.session.delete(u_obj)
                db.session.commit()


def test_message_deterministic_pagination_ordering(app):
    """
    Verifica que la paginación basada en cursor ordene deterministamente
    por sent_at e identificador id.
    """
    with app.app_context():
        u1 = User(email='msg_ord1@test.com', password_hash='h1')
        u2 = User(email='msg_ord2@test.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id, u2_id = u1.id, u2.id

        a_id, b_id = (u1_id, u2_id) if u1_id < u2_id else (u2_id, u1_id)
        m = Match(user_a_id=a_id, user_b_id=b_id)
        db.session.add(m)
        db.session.commit()
        m_id = m.id

        base_time = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
        created_ids = []

        try:
            # Insertar 5 mensajes con marcas de tiempo espaciadas
            for i in range(5):
                msg = Message(
                    id=str(uuid.uuid4()),
                    match_id=m_id,
                    sender_user_id=u1_id if i % 2 == 0 else u2_id,
                    text=f"Mensaje {i}",
                    sent_at=base_time + timedelta(seconds=i * 10)
                )
                db.session.add(msg)
                created_ids.append(msg.id)
            db.session.commit()

            # Consulta paginada ascendente (chat view tradicional)
            ordered_asc = (
                Message.query
                .filter(Message.match_id == m_id)
                .order_by(Message.sent_at.asc(), Message.id.asc())
                .all()
            )
            assert len(ordered_asc) == 5
            for i in range(5):
                assert ordered_asc[i].text == f"Mensaje {i}"

            # Consulta paginada descendente con cursor (obtener más antiguos a partir del mensaje 3)
            cursor_msg = ordered_asc[3]
            page_before_cursor = (
                Message.query
                .filter(
                    Message.match_id == m_id,
                    Message.sent_at < cursor_msg.sent_at
                )
                .order_by(Message.sent_at.desc(), Message.id.desc())
                .limit(2)
                .all()
            )
            assert len(page_before_cursor) == 2
            assert page_before_cursor[0].text == "Mensaje 2"
            assert page_before_cursor[1].text == "Mensaje 1"
        finally:
            for cid in created_ids:
                m_obj = db.session.get(Message, cid)
                if m_obj:
                    db.session.delete(m_obj)
            db.session.commit()

            match_to_del = db.session.get(Match, m_id)
            if match_to_del:
                db.session.delete(match_to_del)
                db.session.commit()
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_message_referential_integrity_on_delete_restrict(app):
    """
    Verifica que ni el match ni el usuario emisor puedan ser eliminados físicamente
    si tienen mensajes asociados (ON DELETE RESTRICT en claves foráneas).
    """
    with app.app_context():
        u1 = User(email='msg_del1@test.com', password_hash='h1')
        u2 = User(email='msg_del2@test.com', password_hash='h2')
        db.session.add_all([u1, u2])
        db.session.commit()
        u1_id, u2_id = u1.id, u2.id

        a_id, b_id = (u1_id, u2_id) if u1_id < u2_id else (u2_id, u1_id)
        m = Match(user_a_id=a_id, user_b_id=b_id)
        db.session.add(m)
        db.session.commit()
        m_id = m.id

        msg = Message(match_id=m_id, sender_user_id=u1_id, text='Mensaje de prueba')
        db.session.add(msg)
        db.session.commit()
        msg_id = msg.id

        try:
            # Intentar borrar el match directamente -> debe fallar por FK RESTRICT
            db.session.delete(m)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # Intentar borrar el usuario emisor directamente -> debe fallar por FK RESTRICT
            sender_user = db.session.get(User, u1_id)
            db.session.delete(sender_user)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
        finally:
            m_obj = db.session.get(Message, msg_id)
            if m_obj:
                db.session.delete(m_obj)
                db.session.commit()
            match_to_del = db.session.get(Match, m_id)
            if match_to_del:
                db.session.delete(match_to_del)
                db.session.commit()
            for uid in [u1_id, u2_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_user_report_resolution_tightened_consistency(app):
    """
    Verifica la restricción corregida de resolución en user_reports:
    - dismiss -> status='dismissed'
    - warn, suspend -> status='resolved'
    - Combinaciones inconsistentes (dismissed + suspend, resolved + dismiss) deben ser rechazadas.
    """
    with app.app_context():
        u_rep = User(email='rep_tight1@test.com', password_hash='h1')
        u_bad = User(email='rep_tight2@test.com', password_hash='h2')
        u_mod = User(email='rep_tight3@test.com', password_hash='h3', role='moderator')
        db.session.add_all([u_rep, u_bad, u_mod])
        db.session.commit()
        u_rep_id, u_bad_id, u_mod_id = u_rep.id, u_bad.id, u_mod.id

        now = datetime.now(timezone.utc)
        created_report_ids = []

        try:
            # 1. Inconsistente: dismissed con suspend -> RECHAZADO
            r_bad1 = UserReport(
                reporter_user_id=u_rep_id,
                reported_user_id=u_bad_id,
                reason='spam',
                status='dismissed',
                resolution_action='suspend',
                resolved_at=now
            )
            db.session.add(r_bad1)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # 2. Inconsistente: resolved con dismiss -> RECHAZADO
            r_bad2 = UserReport(
                reporter_user_id=u_rep_id,
                reported_user_id=u_bad_id,
                reason='spam',
                status='resolved',
                resolution_action='dismiss',
                resolved_at=now
            )
            db.session.add(r_bad2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

            # 3. Válido: dismissed con dismiss -> ACEPTADO
            r_ok_dismiss = UserReport(
                reporter_user_id=u_rep_id,
                reported_user_id=u_bad_id,
                reason='spam',
                status='dismissed',
                resolution_action='dismiss',
                resolved_at=now,
                resolved_by_user_id=u_mod_id
            )
            db.session.add(r_ok_dismiss)
            db.session.commit()
            created_report_ids.append(r_ok_dismiss.id)

            # 4. Válido: resolved con warn -> ACEPTADO
            r_ok_warn = UserReport(
                reporter_user_id=u_rep_id,
                reported_user_id=u_bad_id,
                reason='acoso',
                status='resolved',
                resolution_action='warn',
                resolved_at=now,
                resolved_by_user_id=u_mod_id
            )
            db.session.add(r_ok_warn)
            db.session.commit()
            created_report_ids.append(r_ok_warn.id)

            # 5. Válido: resolved con suspend -> ACEPTADO
            r_ok_suspend = UserReport(
                reporter_user_id=u_rep_id,
                reported_user_id=u_bad_id,
                reason='suplantacion',
                status='resolved',
                resolution_action='suspend',
                resolved_at=now,
                resolved_by_user_id=u_mod_id
            )
            db.session.add(r_ok_suspend)
            db.session.commit()
            created_report_ids.append(r_ok_suspend.id)
        finally:
            for rid in created_report_ids:
                r_obj = db.session.get(UserReport, rid)
                if r_obj:
                    db.session.delete(r_obj)
            db.session.commit()

            for uid in [u_rep_id, u_bad_id, u_mod_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_no_regression_full_domain_thirteen_models(app):
    """
    Verifica que todos los 13 modelos del dominio coexistan, puedan ser instanciados
    y persistidos sin regresiones en sus esquemas ni claves foráneas.
    
    NOTA ARQUITECTÓNICA - REGLAS DE AUTORIZACIÓN QUE PERTENECERÁN AL SERVICIO FLASK:
    1. Participación activa: Solo miembros legítimos del match pueden enviar o ver mensajes.
    2. Estado de match: Un match desactivado (unmatched) bloquea el envío de nuevos mensajes.
    3. Bloqueo bidireccional: Un bloqueo existente entre dos usuarios oculta el chat e impide mensajes.
    4. Marcado de lectura: Solo el receptor del mensaje puede actualizar read_at.
    """
    with app.app_context():
        # 1. User con rol admin y users normales
        admin = User(email='admin_domain@test.com', password_hash='hash_adm', role='admin')
        user_a = User(email='usera_domain@test.com', password_hash='hash_a', role='user')
        user_b = User(email='userb_domain@test.com', password_hash='hash_b', role='user')
        db.session.add_all([admin, user_a, user_b])
        db.session.commit()

        u_adm_id, ua_id, ub_id = admin.id, user_a.id, user_b.id

        prof = None
        photo = None
        disc = None
        ans = None
        token = None
        inter = None
        match = None
        block = None
        rep = None
        consent = None
        msg = None

        try:
            # 2. Profile
            prof = Profile(user_id=ua_id, first_name='Carlos', birth_date=date(1995, 5, 20), gender='man')
            db.session.add(prof)
            db.session.commit()

            # 3. ProfilePhoto
            photo = ProfilePhoto(profile_id=prof.id, storage_key='photos/ua_1.jpg', position=0, is_primary=True)
            db.session.add(photo)

            # 4. DiscoveryPreference
            disc = DiscoveryPreference(user_id=ua_id, interested_in_genders=['masculino'])
            db.session.add(disc)

            # 5. AnalyticQuestionnaireAnswer
            ans = AnalyticQuestionnaireAnswer(user_id=ua_id, variable_name='extroversion', value_numeric=4)
            db.session.add(ans)

            # 6. RefreshToken
            token = RefreshToken(user_id=ua_id, token_hash='a' * 64, expires_at=datetime.now(timezone.utc) + timedelta(days=7))
            db.session.add(token)

            # 7. ProfileInteraction
            inter = ProfileInteraction(viewer_user_id=ua_id, shown_user_id=ub_id, action='LIKE')
            db.session.add(inter)

            # 8. Match
            pair_a, pair_b = (ua_id, ub_id) if ua_id < ub_id else (ub_id, ua_id)
            match = Match(user_a_id=pair_a, user_b_id=pair_b)
            db.session.add(match)
            db.session.commit()

            # 9. UserBlock
            block = UserBlock(blocker_user_id=ub_id, blocked_user_id=ua_id)
            db.session.add(block)

            # 10. UserReport
            rep = UserReport(reporter_user_id=ua_id, reported_user_id=ub_id, reason='otro', description='Prueba dominio')
            db.session.add(rep)

            # 11. LegalConsent
            consent = LegalConsent(user_id=ua_id, document_type='terms_of_service', document_version='v1.0')
            db.session.add(consent)

            # 12. Message
            msg = Message(match_id=match.id, sender_user_id=ua_id, text='Hola desde test de no regresión')
            db.session.add(msg)

            db.session.commit()

            # Verificaciones
            assert len(match.messages) == 1
            assert match.messages[0].text == 'Hola desde test de no regresión'
            assert admin.role == 'admin'
            assert user_a.role == 'user'
            assert len(user_a.messages_sent) == 1
            assert len(user_a.legal_consents) == 1
        finally:
            # Limpieza ordenada desde hijos a padres
            for entity in [msg, rep, block, consent, ans, token, inter, match, photo, prof]:
                if entity:
                    try:
                        db.session.delete(entity)
                    except Exception:
                        db.session.rollback()
            if disc:
                try:
                    db.session.delete(disc)
                except Exception:
                    db.session.rollback()
            db.session.commit()

            for uid in [u_adm_id, ua_id, ub_id]:
                u = db.session.get(User, uid)
                if u:
                    db.session.delete(u)
            db.session.commit()
