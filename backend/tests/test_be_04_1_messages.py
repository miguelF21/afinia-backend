"""
AFINIA — Test Suite BE-04.1: Envío y Consulta de Mensajes (Chat).
==================================================================
Pruebas exhaustivas para:
- POST /api/v1/match/{matchId}/messages
- GET /api/v1/match/{matchId}/messages

Cubriendo los 40 escenarios requeridos en la especificación BE-04.1.
"""

import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from flask import current_app
from sqlalchemy.exc import IntegrityError

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
from app.services.match_service import encode_messages_cursor


# -------------------------------------------------------------------------
# Fixtures y Helpers
# -------------------------------------------------------------------------

def _create_user(
    email: str = None,
    first_name: str = "ChatUser",
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


def _create_match(user_1: User, user_2: User, created_at: datetime = None) -> Match:
    id_min = min(str(user_1.id), str(user_2.id))
    id_max = max(str(user_1.id), str(user_2.id))
    m = Match(
        id=str(uuid.uuid4()),
        user_a_id=id_min,
        user_b_id=id_max,
        created_at=created_at or datetime.utcnow()
    )
    db.session.add(m)
    db.session.commit()
    return m


# -------------------------------------------------------------------------
# Test Suite BE-04.1
# -------------------------------------------------------------------------

class TestMessagesAPI:

    # 1. Enviar mensaje válido (201 Created)
    def test_01_send_valid_message(self, client):
        u1 = _create_user(first_name="Alice")
        u2 = _create_user(first_name="Bob")
        match = _create_match(u1, u2)

        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "Hola Bob, ¿cómo estás?"}
        )
        assert res.status_code == 201
        data = res.get_json()["data"]
        assert data["match_id"] == str(match.id)
        assert data["sender_user_id"] == str(u1.id)
        assert data["text"] == "Hola Bob, ¿cómo estás?"
        assert data["read_at"] is None
        assert data["sent_at"] is not None
        assert uuid.UUID(data["id"])

    # 2. Enviar mensaje de 1 carácter
    def test_02_send_message_single_char(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "A"}
        )
        assert res.status_code == 201
        assert res.get_json()["data"]["text"] == "A"

    # 3. Enviar mensaje de 2000 caracteres
    def test_03_send_message_exact_2000_chars(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        text_2000 = "x" * 2000
        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": text_2000}
        )
        assert res.status_code == 201
        assert len(res.get_json()["data"]["text"]) == 2000

    # 4. Rechazar mensaje de 2001 caracteres
    def test_04_reject_message_2001_chars(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        text_2001 = "x" * 2001
        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": text_2001}
        )
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 5. Rechazar mensaje vacío
    def test_05_reject_empty_message(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": ""}
        )
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 6. Rechazar solo espacios
    def test_06_reject_whitespace_only(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "   \t \n  "}
        )
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 7. Rechazar body no JSON
    def test_07_reject_non_json_body(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        headers = _auth_headers(u1)
        headers["Content-Type"] = "text/plain"
        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=headers,
            data="text=Hola"
        )
        assert res.status_code in (400, 422)

    # 8. Rechazar text no string
    def test_08_reject_non_string_text(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": 12345}
        )
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 9. Rechazar propiedades adicionales
    def test_09_reject_additional_properties(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        # Intento de enviar sender_user_id o campos adicionales
        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "Hola", "sender_user_id": str(u2.id)}
        )
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 10. Texto con tildes y emojis
    def test_10_unicode_tildes_and_emojis(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        unicode_text = "¡Hola! ¿Cómo estás? Me gusta el café ☕ y la música 🎶. ¡Vamos! 🚀🌟"
        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": unicode_text}
        )
        assert res.status_code == 201
        assert res.get_json()["data"]["text"] == unicode_text

    # 11. Usuario sin JWT (401)
    def test_11_unauthorized_without_jwt(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res_post = client.post(f"/api/v1/match/{match.id}/messages", json={"text": "Hola"})
        assert res_post.status_code == 401
        assert res_post.get_json()["error"]["code"] == "UNAUTHORIZED"

        res_get = client.get(f"/api/v1/match/{match.id}/messages")
        assert res_get.status_code == 401
        assert res_get.get_json()["error"]["code"] == "UNAUTHORIZED"

    # 12. Usuario pending_profile (403)
    def test_12_pending_profile_forbidden(self, client):
        u1 = _create_user(lifecycle_status="pending_profile")
        u2 = _create_user()
        match = _create_match(u1, u2)

        res_post = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "Hola"}
        )
        assert res_post.status_code == 403

        res_get = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        assert res_get.status_code == 403

    # 13. Usuario suspended (403)
    def test_13_suspended_forbidden(self, client):
        u1 = _create_user(lifecycle_status="suspended")
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "Hola"}
        )
        assert res.status_code == 403

    # 14. Usuario deactivated (401 o 403)
    def test_14_deactivated_rejected(self, client):
        u1 = _create_user(lifecycle_status="deactivated")
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "Hola"}
        )
        assert res.status_code in (401, 403)

    # 15. Match inexistente (404)
    def test_15_nonexistent_match_404(self, client):
        u1 = _create_user()
        fake_uuid = str(uuid.uuid4())

        res_post = client.post(
            f"/api/v1/match/{fake_uuid}/messages",
            headers=_auth_headers(u1),
            json={"text": "Hola"}
        )
        assert res_post.status_code == 404
        assert res_post.get_json()["error"]["code"] == "NOT_FOUND"

        res_get = client.get(f"/api/v1/match/{fake_uuid}/messages", headers=_auth_headers(u1))
        assert res_get.status_code == 404

    # 16. UUID inválido (422)
    def test_16_invalid_uuid_422(self, client):
        u1 = _create_user()

        res_post = client.post(
            "/api/v1/match/uuid-invalido/messages",
            headers=_auth_headers(u1),
            json={"text": "Hola"}
        )
        assert res_post.status_code == 422
        assert res_post.get_json()["error"]["code"] == "VALIDATION_ERROR"

        res_get = client.get("/api/v1/match/uuid-invalido/messages", headers=_auth_headers(u1))
        assert res_get.status_code == 422

    # 17. Usuario ajeno al match (404)
    def test_17_third_party_user_404(self, client):
        u1 = _create_user()
        u2 = _create_user()
        alien = _create_user()
        match = _create_match(u1, u2)

        res_post = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(alien),
            json={"text": "Espía"}
        )
        assert res_post.status_code == 404
        assert res_post.get_json()["error"]["code"] == "NOT_FOUND"

        res_get = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(alien))
        assert res_get.status_code == 404

    # 18. Bloqueo A hacia B (404)
    def test_18_block_a_to_b_404(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        # U1 bloquea a U2
        block = UserBlock(id=str(uuid.uuid4()), blocker_user_id=u1.id, blocked_user_id=u2.id)
        db.session.add(block)
        db.session.commit()

        # U1 no puede enviar ni ver mensajes
        res1_post = client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "H"})
        assert res1_post.status_code == 404
        res1_get = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        assert res1_get.status_code == 404

    # 19. Bloqueo B hacia A (404)
    def test_19_block_b_to_a_404(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        # U2 bloquea a U1
        block = UserBlock(id=str(uuid.uuid4()), blocker_user_id=u2.id, blocked_user_id=u1.id)
        db.session.add(block)
        db.session.commit()

        # U1 no puede enviar ni ver mensajes
        res1_post = client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "H"})
        assert res1_post.status_code == 404
        res1_get = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        assert res1_get.status_code == 404

    # 20. Contraparte suspendida (404)
    def test_20_counterpart_suspended_404(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        u2.lifecycle_status = "suspended"
        db.session.commit()

        res_post = client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "H"})
        assert res_post.status_code == 404

        res_get = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        assert res_get.status_code == 404

    # 21. Consulta de chat sin mensajes
    def test_21_list_messages_empty(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        assert res.status_code == 200
        body = res.get_json()
        assert body["data"]["items"] == []
        assert body["meta"]["next_cursor"] is None
        assert body["meta"]["has_more"] is False

    # 22. Consulta con un mensaje
    def test_22_list_messages_single_message(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        # Enviar 1 mensaje
        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "Mensaje único"})

        res = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        assert res.status_code == 200
        body = res.get_json()
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["text"] == "Mensaje único"
        assert body["meta"]["has_more"] is False

    # 23. Consulta con múltiples mensajes
    def test_23_list_multiple_messages(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "M1"})
        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u2), json={"text": "M2"})
        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "M3"})

        res = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 3

    # 24. Orden descendente correcto (sent_at DESC, id DESC)
    def test_24_chronological_desc_order(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        t1 = datetime.utcnow() - timedelta(minutes=15)
        t2 = datetime.utcnow() - timedelta(minutes=10)
        t3 = datetime.utcnow() - timedelta(minutes=5)

        m1 = Message(id=str(uuid.uuid4()), match_id=match.id, sender_user_id=u1.id, text="Primero", sent_at=t1)
        m2 = Message(id=str(uuid.uuid4()), match_id=match.id, sender_user_id=u2.id, text="Segundo", sent_at=t2)
        m3 = Message(id=str(uuid.uuid4()), match_id=match.id, sender_user_id=u1.id, text="Tercero", sent_at=t3)
        db.session.add_all([m1, m2, m3])
        db.session.commit()

        res = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        items = res.get_json()["data"]["items"]
        assert [i["id"] for i in items] == [str(m3.id), str(m2.id), str(m1.id)]

    # 25. Mensajes con sent_at idéntico (desempate por id DESC)
    def test_25_same_timestamp_tie_breaker_id_desc(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        same_t = datetime(2026, 10, 30, 15, 0, 0)
        m1 = Message(id=str(uuid.uuid4()), match_id=match.id, sender_user_id=u1.id, text="Msg1", sent_at=same_t)
        m2 = Message(id=str(uuid.uuid4()), match_id=match.id, sender_user_id=u2.id, text="Msg2", sent_at=same_t)
        db.session.add_all([m1, m2])
        db.session.commit()

        res = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        items = res.get_json()["data"]["items"]
        expected_ids = sorted([str(m1.id), str(m2.id)], reverse=True)
        actual_ids = [items[0]["id"], items[1]["id"]]
        assert actual_ids == expected_ids

    # 26. Paginación con limit=1
    def test_26_pagination_limit_one(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "Msg A"})
        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u2), json={"text": "Msg B"})

        res = client.get(f"/api/v1/match/{match.id}/messages?limit=1", headers=_auth_headers(u1))
        assert res.status_code == 200
        body = res.get_json()
        assert len(body["data"]["items"]) == 1
        assert body["meta"]["has_more"] is True
        assert body["meta"]["next_cursor"] is not None

    # 27. Paginación profunda con varias páginas
    def test_27_deep_pagination_multiple_pages(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        # Crear 5 mensajes
        msg_ids = []
        for i in range(5):
            t = datetime.utcnow() - timedelta(minutes=(5 - i))
            m = Message(id=str(uuid.uuid4()), match_id=match.id, sender_user_id=u1.id, text=f"Msg {i}", sent_at=t)
            db.session.add(m)
            msg_ids.append(m.id)
        db.session.commit()

        # Página 1: limit=2
        res1 = client.get(f"/api/v1/match/{match.id}/messages?limit=2", headers=_auth_headers(u1))
        b1 = res1.get_json()
        assert len(b1["data"]["items"]) == 2
        assert b1["meta"]["has_more"] is True
        cur1 = b1["meta"]["next_cursor"]

        # Página 2: limit=2
        res2 = client.get(f"/api/v1/match/{match.id}/messages?limit=2&cursor={cur1}", headers=_auth_headers(u1))
        b2 = res2.get_json()
        assert len(b2["data"]["items"]) == 2
        assert b2["meta"]["has_more"] is True
        cur2 = b2["meta"]["next_cursor"]

        # Página 3: limit=2
        res3 = client.get(f"/api/v1/match/{match.id}/messages?limit=2&cursor={cur2}", headers=_auth_headers(u1))
        b3 = res3.get_json()
        assert len(b3["data"]["items"]) == 1
        assert b3["meta"]["has_more"] is False
        assert b3["meta"]["next_cursor"] is None

        # Verificar que no hay duplicados entre páginas
        all_retrieved = [i["id"] for i in b1["data"]["items"] + b2["data"]["items"] + b3["data"]["items"]]
        assert len(all_retrieved) == 5
        assert len(set(all_retrieved)) == 5

    # 28. Cursor manipulado (422)
    def test_28_tampered_cursor_422(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        m = Message(id=str(uuid.uuid4()), match_id=match.id, sender_user_id=u1.id, text="Msg", sent_at=datetime.utcnow())
        db.session.add(m)
        db.session.commit()

        valid_cur = encode_messages_cursor(m.sent_at, m.id, match.id, str(u1.id))
        bad_cur = valid_cur[:-4] + "ZZZZ"

        res = client.get(f"/api/v1/match/{match.id}/messages?cursor={bad_cur}", headers=_auth_headers(u1))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 29. Cursor de otro usuario (422)
    def test_29_cursor_used_by_different_user_422(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        m = Message(id=str(uuid.uuid4()), match_id=match.id, sender_user_id=u1.id, text="Msg", sent_at=datetime.utcnow())
        db.session.add(m)
        db.session.commit()

        # Cursor emitido para u1
        cur_u1 = encode_messages_cursor(m.sent_at, m.id, match.id, str(u1.id))

        # u2 intenta usar el cursor de u1
        res = client.get(f"/api/v1/match/{match.id}/messages?cursor={cur_u1}", headers=_auth_headers(u2))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 30. Cursor de otro match (422)
    def test_30_cursor_from_different_match_422(self, client):
        u1 = _create_user()
        u2 = _create_user()
        u3 = _create_user()
        m1 = _create_match(u1, u2)
        m2 = _create_match(u1, u3)

        msg1 = Message(id=str(uuid.uuid4()), match_id=m1.id, sender_user_id=u1.id, text="M1", sent_at=datetime.utcnow())
        db.session.add(msg1)
        db.session.commit()

        # Cursor emitido para m1
        cur_m1 = encode_messages_cursor(msg1.sent_at, msg1.id, m1.id, str(u1.id))

        # Intentar usarlo en m2
        res = client.get(f"/api/v1/match/{m2.id}/messages?cursor={cur_m1}", headers=_auth_headers(u1))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 31. Ausencia de mensajes ajenos
    def test_31_no_cross_match_leakage(self, client):
        u1 = _create_user()
        u2 = _create_user()
        u3 = _create_user()
        match1 = _create_match(u1, u2)
        match2 = _create_match(u1, u3)

        client.post(f"/api/v1/match/{match1.id}/messages", headers=_auth_headers(u1), json={"text": "Mensaje en Match 1"})
        client.post(f"/api/v1/match/{match2.id}/messages", headers=_auth_headers(u1), json={"text": "Mensaje en Match 2"})

        res1 = client.get(f"/api/v1/match/{match1.id}/messages", headers=_auth_headers(u1))
        items1 = res1.get_json()["data"]["items"]
        assert len(items1) == 1
        assert items1[0]["text"] == "Mensaje en Match 1"

    # 32. GET no actualiza read_at
    def test_32_get_does_not_mutate_read_at(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u2), json={"text": "No leído aún"})

        # Consultar historial repetidamente
        client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))

        # Verificar en base de datos que read_at sigue siendo None
        msg = Message.query.filter_by(match_id=match.id).first()
        assert msg.read_at is None
        assert msg.is_read is False

    # 33. El remitente no puede falsificarse
    def test_33_sender_cannot_be_spoofed(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        # U1 envía un mensaje pero el token autentica a U1. El remitente en la BD debe ser U1.
        res = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "Intento de envío genuino"}
        )
        assert res.status_code == 201
        data = res.get_json()["data"]
        assert data["sender_user_id"] == str(u1.id)
        assert data["sender_user_id"] != str(u2.id)

    # 34. Rollback ante fallo de base de datos
    def test_34_rollback_on_commit_failure(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        with patch("app.db.session.commit", side_effect=Exception("Database connection dropped")):
            res = client.post(
                f"/api/v1/match/{match.id}/messages",
                headers=_auth_headers(u1),
                json={"text": "Mensaje que fallará"}
            )
            assert res.status_code == 500

        # Verificar que no quedaron mensajes parciales
        assert Message.query.filter_by(match_id=match.id).count() == 0

    # 35. Actualización real de last_message
    def test_35_last_message_updated_in_match_detail(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        # Inicialmente last_message es None
        res_init = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res_init.get_json()["data"]["last_message"] is None

        # Enviar mensaje
        client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "¡Nuevo mensaje!"}
        )

        # Ahora GET /match/{matchId} refleja el last_message
        res_after = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        last_msg = res_after.get_json()["data"]["last_message"]
        assert last_msg is not None
        assert last_msg["text"] == "¡Nuevo mensaje!"

        # Y en /my-matches también se refleja
        res_list = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
        assert res_list.get_json()["data"]["items"][0]["last_message"]["text"] == "¡Nuevo mensaje!"

    # 36. unread_count correcto para emisor
    def test_36_unread_count_zero_for_sender(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "Msg de u1"})

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.get_json()["data"]["unread_count"] == 0

    # 37. unread_count correcto para destinatario
    def test_37_unread_count_increments_for_recipient(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "Msg 1 de u1"})
        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "Msg 2 de u1"})

        # Para u2 (destinatario), unread_count debe ser 2
        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u2))
        assert res.get_json()["data"]["unread_count"] == 2

    # 38. Respuestas HTTP y JSON compatibles con OpenAPI
    def test_38_openapi_envelope_and_schema_compliance(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res_post = client.post(
            f"/api/v1/match/{match.id}/messages",
            headers=_auth_headers(u1),
            json={"text": "Prueba esquema"}
        )
        assert res_post.status_code == 201
        data = res_post.get_json()["data"]
        expected_msg_keys = {"id", "match_id", "sender_user_id", "text", "sent_at", "read_at"}
        assert set(data.keys()) == expected_msg_keys

        res_get = client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        assert res_get.status_code == 200
        get_body = res_get.get_json()
        assert set(get_body.keys()) == {"data", "meta"}
        assert set(get_body["data"].keys()) == {"items"}
        assert set(get_body["meta"].keys()) == {"next_cursor", "has_more"}

    # 39. Ausencia de regresiones en tests de swipe y matches
    def test_39_no_regressions_swipe_and_matches(self, client):
        u1 = _create_user(gender="masculino", interested_in_genders=["femenino"])
        u2 = _create_user(gender="femenino", interested_in_genders=["masculino"])

        res_swipe = client.post(
            "/api/v1/match/swipe",
            headers=_auth_headers(u1),
            json={"target_user_id": str(u2.id), "action": "LIKE"}
        )
        assert res_swipe.status_code == 200

    # 40. Idempotencia de lectura y sin mutaciones residuales
    def test_40_read_idempotence_and_no_residual_side_effects(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        client.post(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1), json={"text": "Mensaje único"})

        cnt_before = Message.query.count()
        client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u1))
        client.get(f"/api/v1/match/{match.id}/messages", headers=_auth_headers(u2))
        cnt_after = Message.query.count()

        assert cnt_before == cnt_after
