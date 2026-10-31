"""
AFINIA — Test Suite BE-04.2: Marcado de Mensajes como Leídos.
============================================================
Pruebas exhaustivas para:
- POST /api/v1/match/{matchId}/read

Cubriendo exactamente los 28 escenarios obligatorios de BE-04.2.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from flask import current_app

from app import db
from app.models import (
    User,
    Profile,
    ProfilePhoto,
    DiscoveryPreference,
    UserBlock,
    Match,
    Message,
)
from app.utils.security import create_access_token


# -------------------------------------------------------------------------
# Fixtures y Helpers
# -------------------------------------------------------------------------

def _create_user(
    email: str = None,
    first_name: str = "TestUser",
    gender: str = "femenino",
    birth_date: date = None,
    interested_in_genders: list = None,
    email_verified: bool = True,
    lifecycle_status: str = "active",
    with_photo: bool = True,
    photo_status: str = "ready",
    city: str = "Bogotá",
    bio: str = "Bio de prueba",
    relationship_goal: str = "seria"
) -> User:
    if not email:
        email = f"user_{uuid.uuid4().hex[:8]}@afinia.test"
    if not birth_date:
        today = datetime.now(timezone.utc).date()
        birth_date = date(today.year - 24, today.month, today.day)
    if interested_in_genders is None:
        interested_in_genders = ["masculino"]

    user = User(
        email=email,
        password_hash="fake_hash",
        email_verified=email_verified,
        lifecycle_status=lifecycle_status,
        role="user",
    )
    db.session.add(user)
    db.session.flush()

    profile = Profile(
        user_id=user.id,
        first_name=first_name,
        birth_date=birth_date,
        gender=gender,
        city=city,
        bio=bio,
    )
    db.session.add(profile)
    db.session.flush()

    if with_photo:
        photo = ProfilePhoto(
            profile_id=profile.id,
            storage_key=f"photos/{user.id}/p_{uuid.uuid4().hex[:8]}.webp",
            position=0,
            is_primary=True,
            status=photo_status,
            byte_size=1024,
            content_type="image/webp",
        )
        db.session.add(photo)

    pref = DiscoveryPreference(
        user_id=user.id,
        interested_in_genders=interested_in_genders,
        min_age=18,
        max_age=50,
        target_relationship_type=relationship_goal,
    )
    db.session.add(pref)
    db.session.commit()
    return user


def _auth_headers(user: User) -> dict:
    token = create_access_token(user.id, user.email, user.role, current_app.config['SECRET_KEY'])
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def _create_match(user_1: User, user_2: User) -> Match:
    id_min, id_max = sorted([user_1.id, user_2.id])
    match_obj = Match(
        id=str(uuid.uuid4()),
        user_a_id=id_min,
        user_b_id=id_max,
        created_at=datetime.now(timezone.utc)
    )
    db.session.add(match_obj)
    db.session.commit()
    return match_obj


def _create_message(match: Match, sender: User, text: str = "Hola", read_at: datetime = None, sent_at: datetime = None) -> Message:
    if sent_at is None:
        sent_at = datetime.now(timezone.utc)
    msg = Message(
        id=str(uuid.uuid4()),
        match_id=match.id,
        sender_user_id=sender.id,
        text=text,
        sent_at=sent_at,
        read_at=read_at
    )
    db.session.add(msg)
    db.session.commit()
    return msg


# -------------------------------------------------------------------------
# Test Cases (28 Escenarios Obligatorios)
# -------------------------------------------------------------------------

class TestReadMessagesAPI:

    def test_01_match_without_messages(self, client):
        """1. Match sin mensajes: retorna 200 con unread_count=0."""
        ua = _create_user(gender="femenino", interested_in_genders=["masculino"])
        ub = _create_user(gender="masculino", interested_in_genders=["femenino"])
        m = _create_match(ua, ub)

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200
        body = res.get_json()
        assert body["data"]["unread_count"] == 0

    def test_02_single_incoming_unread_message(self, client):
        """2. Un mensaje entrante sin leer: se marca con read_at != null y unread_count=0."""
        ua = _create_user(gender="femenino", interested_in_genders=["masculino"])
        ub = _create_user(gender="masculino", interested_in_genders=["femenino"])
        m = _create_match(ua, ub)
        msg = _create_message(m, sender=ub, text="Mensaje de B para A")

        assert msg.read_at is None

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200
        assert res.get_json()["data"]["unread_count"] == 0

        # Verificar en base de datos
        db.session.refresh(msg)
        assert msg.read_at is not None

    def test_03_multiple_incoming_unread_messages(self, client):
        """3. Varios mensajes entrantes sin leer: se marcan todos, unread_count=0."""
        ua = _create_user(gender="femenino", interested_in_genders=["masculino"])
        ub = _create_user(gender="masculino", interested_in_genders=["femenino"])
        m = _create_match(ua, ub)
        m1 = _create_message(m, sender=ub, text="Msg 1")
        m2 = _create_message(m, sender=ub, text="Msg 2")
        m3 = _create_message(m, sender=ub, text="Msg 3")

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200
        assert res.get_json()["data"]["unread_count"] == 0

        for msg in [m1, m2, m3]:
            db.session.refresh(msg)
            assert msg.read_at is not None

    def test_04_own_sent_messages_excluded(self, client):
        """4. Mensajes propios excluidos: no se modifican cuando el emisor llama POST /read."""
        ua = _create_user(gender="femenino", interested_in_genders=["masculino"])
        ub = _create_user(gender="masculino", interested_in_genders=["femenino"])
        m = _create_match(ua, ub)
        msg_from_a = _create_message(m, sender=ua, text="Mensaje propio de A")

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200
        assert res.get_json()["data"]["unread_count"] == 0

        db.session.refresh(msg_from_a)
        assert msg_from_a.read_at is None  # Permanece None para el receptor ub

    def test_05_received_messages_already_read(self, client):
        """5. Mensajes recibidos ya leídos: no generan conflicto ni alteran contadores."""
        ua = _create_user(gender="femenino", interested_in_genders=["masculino"])
        ub = _create_user(gender="masculino", interested_in_genders=["femenino"])
        m = _create_match(ua, ub)
        original_read_at = datetime.now(timezone.utc) - timedelta(hours=1)
        msg = _create_message(m, sender=ub, text="Ya leído", read_at=original_read_at)

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200
        assert res.get_json()["data"]["unread_count"] == 0

    def test_06_repeated_mark_read_idempotent(self, client):
        """6. Marcado repetido: la segunda solicitud no produce cambios ni errores."""
        ua = _create_user(gender="femenino", interested_in_genders=["masculino"])
        ub = _create_user(gender="masculino", interested_in_genders=["femenino"])
        m = _create_match(ua, ub)
        _create_message(m, sender=ub, text="Mensaje")

        res1 = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res1.status_code == 200
        assert res1.get_json()["data"]["unread_count"] == 0

        res2 = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res2.status_code == 200
        assert res2.get_json()["data"]["unread_count"] == 0

    def test_07_read_at_timestamp_not_overwritten(self, client):
        """7. Fecha read_at no sobrescrita: el timestamp original de lectura se preserva."""
        ua = _create_user(gender="femenino", interested_in_genders=["masculino"])
        ub = _create_user(gender="masculino", interested_in_genders=["femenino"])
        m = _create_match(ua, ub)
        past_time = datetime.now(timezone.utc) - timedelta(days=2)
        msg = _create_message(m, sender=ub, text="Mensaje antiguo", read_at=past_time)

        client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))

        db.session.refresh(msg)
        # El timestamp no debe haber cambiado a la fecha actual
        saved_dt = msg.read_at
        if saved_dt.tzinfo is None:
            saved_dt = saved_dt.replace(tzinfo=timezone.utc)
        assert abs((saved_dt - past_time).total_seconds()) < 2.0

    def test_08_nonexistent_match_404(self, client):
        """8. Match inexistente: retorna 404 NOT_FOUND."""
        ua = _create_user()
        fake_match_id = str(uuid.uuid4())

        res = client.post(f"/api/v1/match/{fake_match_id}/read", headers=_auth_headers(ua))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    def test_09_invalid_uuid_422(self, client):
        """9. UUID inválido: retorna 422 VALIDATION_ERROR."""
        ua = _create_user()

        res = client.post("/api/v1/match/not-a-valid-uuid/read", headers=_auth_headers(ua))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_10_unauthenticated_401(self, client):
        """10. Usuario no autenticado: retorna 401 UNAUTHORIZED."""
        match_id = str(uuid.uuid4())
        res = client.post(f"/api/v1/match/{match_id}/read")
        assert res.status_code == 401
        assert res.get_json()["error"]["code"] == "UNAUTHORIZED"

    def test_11_third_party_user_404(self, client):
        """11. Usuario ajeno al match: retorna 404 NOT_FOUND para no revelar existencia."""
        ua = _create_user()
        ub = _create_user()
        uc = _create_user()
        m = _create_match(ua, ub)

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(uc))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    def test_12_pending_profile_forbidden(self, client):
        """12. Cuenta pending_profile: retorna 403 FORBIDDEN."""
        ua = _create_user(lifecycle_status="pending_profile")
        ub = _create_user()
        m = _create_match(ua, ub)

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    def test_13_suspended_forbidden(self, client):
        """13. Cuenta suspended: retorna 403 FORBIDDEN."""
        ua = _create_user(lifecycle_status="suspended")
        ub = _create_user()
        m = _create_match(ua, ub)

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    def test_14_deactivated_forbidden(self, client):
        """14. Cuenta deactivated: retorna 401 o 403."""
        ua = _create_user(lifecycle_status="deactivated")
        ub = _create_user()
        m = _create_match(ua, ub)

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code in (401, 403)

    def test_15_block_a_to_b_404(self, client):
        """15. Bloqueo A hacia B: retorna 404 NOT_FOUND."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)

        block = UserBlock(id=str(uuid.uuid4()), blocker_user_id=ua.id, blocked_user_id=ub.id)
        db.session.add(block)
        db.session.commit()

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    def test_16_block_b_to_a_404(self, client):
        """16. Bloqueo B hacia A: retorna 404 NOT_FOUND."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)

        block = UserBlock(id=str(uuid.uuid4()), blocker_user_id=ub.id, blocked_user_id=ua.id)
        db.session.add(block)
        db.session.commit()

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    def test_17_counterpart_not_eligible_404(self, client):
        """17. Contraparte no habilitada (suspendida): retorna 404 NOT_FOUND."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)

        ub.lifecycle_status = "suspended"
        db.session.commit()

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    def test_18_isolation_between_conversations(self, client):
        """18. Aislamiento entre conversaciones: marcar match 1 no afecta match 2."""
        ua = _create_user()
        ub = _create_user()
        uc = _create_user()
        m1 = _create_match(ua, ub)
        m2 = _create_match(ua, uc)

        msg1 = _create_message(m1, sender=ub, text="Msg en Match 1")
        msg2 = _create_message(m2, sender=uc, text="Msg en Match 2")

        res = client.post(f"/api/v1/match/{m1.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200

        db.session.refresh(msg1)
        db.session.refresh(msg2)
        assert msg1.read_at is not None
        assert msg2.read_at is None  # Mensaje en match 2 sigue sin leer

    def test_19_read_from_participant_a(self, client):
        """19. Lectura desde participante A: marca mensajes enviados por B."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        msg_b = _create_message(m, sender=ub, text="Hola de B")

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200
        db.session.refresh(msg_b)
        assert msg_b.read_at is not None

    def test_20_read_from_participant_b(self, client):
        """20. Lectura desde participante B: marca mensajes enviados por A."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        msg_a = _create_message(m, sender=ua, text="Hola de A")

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ub))
        assert res.status_code == 200
        db.session.refresh(msg_a)
        assert msg_a.read_at is not None

    def test_21_two_sequential_reads_by_both_participants(self, client):
        """21. Dos lecturas por ambos participantes: cada uno marca los mensajes del otro."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        msg_a = _create_message(m, sender=ua, text="De A a B")
        msg_b = _create_message(m, sender=ub, text="De B a A")

        res_a = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res_a.status_code == 200
        res_b = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ub))
        assert res_b.status_code == 200

        db.session.refresh(msg_a)
        db.session.refresh(msg_b)
        assert msg_a.read_at is not None
        assert msg_b.read_at is not None

    def test_22_read_concurrent_with_new_message(self, client):
        """22. Lectura concurrente con un envío: mensaje nuevo posterior al UPDATE permanece sin leer."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        msg1 = _create_message(m, sender=ub, text="Mensaje 1")

        # A marca como leído
        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200
        assert res.get_json()["data"]["unread_count"] == 0

        # Inmediatamente después llega un mensaje nuevo de B
        msg2 = _create_message(m, sender=ub, text="Mensaje 2 nuevo")
        assert msg2.read_at is None

        # El detalle de match debe mostrar unread_count=1 para A
        res_detail = client.get(f"/api/v1/match/{m.id}", headers=_auth_headers(ua))
        assert res_detail.get_json()["data"]["unread_count"] == 1

    def test_23_rollback_on_database_error(self, client):
        """23. Rollback ante error: si falla commit, no quedan modificaciones parciales."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        msg = _create_message(m, sender=ub, text="Mensaje no leído")

        with patch.object(db.session, 'commit', side_effect=Exception("Database crash")):
            res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
            assert res.status_code == 500
            assert res.get_json()["error"]["code"] == "INTERNAL_ERROR"

        db.session.refresh(msg)
        assert msg.read_at is None  # Deshecho por el rollback

    def test_24_openapi_response_schema_exact(self, client):
        """24. Respuesta exacta de OpenAPI: envelope data con unread_count entero."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)

        res = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res.status_code == 200
        body = res.get_json()
        assert "data" in body
        assert set(body["data"].keys()) == {"unread_count"}
        assert isinstance(body["data"]["unread_count"], int)
        assert body["data"]["unread_count"] == 0

    def test_25_integration_get_my_matches(self, client):
        """25. Integración con GET /my-matches: unread_count pasa de 2 a 0 tras POST /read."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        _create_message(m, sender=ub, text="Msg 1")
        _create_message(m, sender=ub, text="Msg 2")

        # Antes de POST /read: unread_count=2
        res_before = client.get("/api/v1/match/my-matches", headers=_auth_headers(ua))
        items_b = res_before.get_json()["data"]["items"]
        assert len(items_b) == 1
        assert items_b[0]["unread_count"] == 2

        # POST /read
        res_read = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res_read.status_code == 200

        # Después de POST /read: unread_count=0
        res_after = client.get("/api/v1/match/my-matches", headers=_auth_headers(ua))
        items_a = res_after.get_json()["data"]["items"]
        assert len(items_a) == 1
        assert items_a[0]["unread_count"] == 0

    def test_26_integration_get_match_detail(self, client):
        """26. Integración con GET /match/{matchId}: unread_count pasa a 0 y last_message no se altera."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        msg = _create_message(m, sender=ub, text="Último mensaje de B")

        # Antes: unread_count=1
        res_det_b = client.get(f"/api/v1/match/{m.id}", headers=_auth_headers(ua))
        assert res_det_b.get_json()["data"]["unread_count"] == 1
        assert res_det_b.get_json()["data"]["last_message"]["id"] == msg.id

        # POST /read
        client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))

        # Después: unread_count=0, last_message idéntico
        res_det_a = client.get(f"/api/v1/match/{m.id}", headers=_auth_headers(ua))
        assert res_det_a.get_json()["data"]["unread_count"] == 0
        assert res_det_a.get_json()["data"]["last_message"]["id"] == msg.id
        assert res_det_a.get_json()["data"]["last_message"]["text"] == "Último mensaje de B"

    def test_27_get_messages_does_not_auto_mark_read(self, client):
        """27. GET /messages sigue sin marcar automáticamente mensajes."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        msg = _create_message(m, sender=ub, text="No leído")

        res_get = client.get(f"/api/v1/match/{m.id}/messages", headers=_auth_headers(ua))
        assert res_get.status_code == 200

        db.session.refresh(msg)
        assert msg.read_at is None  # GET /messages no muta read_at

    def test_28_no_regressions_send_and_list_messages(self, client):
        """28. Cero regresiones en el envío y consulta de mensajes tras marcar lectura."""
        ua = _create_user()
        ub = _create_user()
        m = _create_match(ua, ub)
        _create_message(m, sender=ub, text="Mensaje previo")

        # Marcar lectura
        res_read = client.post(f"/api/v1/match/{m.id}/read", headers=_auth_headers(ua))
        assert res_read.status_code == 200

        # Enviar nuevo mensaje de A hacia B
        res_post = client.post(
            f"/api/v1/match/{m.id}/messages",
            headers=_auth_headers(ua),
            json={"text": "Respuesta posterior a lectura"}
        )
        assert res_post.status_code == 201

        # Consultar historial
        res_list = client.get(f"/api/v1/match/{m.id}/messages", headers=_auth_headers(ua))
        assert res_list.status_code == 200
        items = res_list.get_json()["data"]["items"]
        assert len(items) == 2
        assert items[0]["text"] == "Respuesta posterior a lectura"
