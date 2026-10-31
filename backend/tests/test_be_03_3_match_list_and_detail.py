"""
AFINIA — Test Suite BE-03.3: Listado y Detalle de Matches.
===========================================================
Pruebas exhaustivas para:
- GET /api/v1/match/my-matches
- GET /api/v1/match/{matchId}

Cubriendo los 34 escenarios requeridos en la especificación BE-03.3.
"""

import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone
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
from app.services.match_service import encode_match_cursor


# -------------------------------------------------------------------------
# Helpers
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


def _create_message(
    match_id: str,
    sender_id: str,
    text: str = "Hola",
    sent_at: datetime = None,
    read_at: datetime = None
) -> Message:
    msg = Message(
        id=str(uuid.uuid4()),
        match_id=match_id,
        sender_user_id=sender_id,
        text=text,
        sent_at=sent_at or datetime.utcnow(),
        read_at=read_at
    )
    db.session.add(msg)
    db.session.commit()
    return msg


# -------------------------------------------------------------------------
# Test Suite BE-03.3 (34 Escenarios)
# -------------------------------------------------------------------------

class TestMatchListAndDetail:

    # 1. Usuario sin matches
    def test_01_user_without_matches(self, client):
        user = _create_user()
        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(user))
        assert res.status_code == 200
        body = res.get_json()
        assert "data" in body and "meta" in body
        assert body["data"]["items"] == []
        assert body["meta"]["next_cursor"] is None
        assert body["meta"]["has_more"] is False

    # 2. Usuario con un match
    def test_02_user_with_one_match(self, client):
        u1 = _create_user(first_name="Camila")
        u2 = _create_user(first_name="David")
        match = _create_match(u1, u2)

        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
        assert res.status_code == 200
        body = res.get_json()
        items = body["data"]["items"]
        assert len(items) == 1
        assert items[0]["id"] == str(match.id)
        assert items[0]["other_user"]["first_name"] == "David"
        assert items[0]["other_user"]["user_id"] == str(u2.id)
        assert items[0]["last_message"] is None
        assert items[0]["unread_count"] == 0

    # 3. Usuario con varios matches
    def test_03_user_with_multiple_matches_order(self, client):
        main_user = _create_user(first_name="MainUser")
        t0 = datetime.utcnow() - timedelta(hours=3)
        t1 = datetime.utcnow() - timedelta(hours=2)
        t2 = datetime.utcnow() - timedelta(hours=1)

        c1 = _create_user(first_name="Candidata1")
        c2 = _create_user(first_name="Candidata2")
        c3 = _create_user(first_name="Candidata3")

        m1 = _create_match(main_user, c1, created_at=t0)
        m2 = _create_match(main_user, c2, created_at=t1)
        m3 = _create_match(main_user, c3, created_at=t2)

        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(main_user))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 3
        # Orden descendente por created_at: m3, m2, m1
        assert items[0]["id"] == str(m3.id)
        assert items[1]["id"] == str(m2.id)
        assert items[2]["id"] == str(m1.id)

    # 4. Relación donde el solicitante es user_a_id
    def test_04_requester_is_user_a(self, client):
        u1 = _create_user(first_name="UserSmallUUID")
        u2 = _create_user(first_name="UserBigUUID")
        # Aseguramos quién es user_a
        m = _create_match(u1, u2)
        user_a = u1 if str(u1.id) == m.user_a_id else u2
        user_b = u2 if str(u1.id) == m.user_a_id else u1

        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(user_a))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["other_user"]["user_id"] == str(user_b.id)
        assert items[0]["other_user"]["user_id"] != str(user_a.id)

    # 5. Relación donde el solicitante es user_b_id
    def test_05_requester_is_user_b(self, client):
        u1 = _create_user(first_name="User1")
        u2 = _create_user(first_name="User2")
        m = _create_match(u1, u2)
        user_a = u1 if str(u1.id) == m.user_a_id else u2
        user_b = u2 if str(u1.id) == m.user_a_id else u1

        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(user_b))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["other_user"]["user_id"] == str(user_a.id)
        assert items[0]["other_user"]["user_id"] != str(user_b.id)

    # 6. Consulta sin JWT (401)
    def test_06_unauthorized_without_jwt(self, client):
        u = _create_user()
        m = _create_match(u, _create_user())
        res1 = client.get("/api/v1/match/my-matches")
        assert res1.status_code == 401
        assert res1.get_json()["error"]["code"] == "UNAUTHORIZED"

        res2 = client.get(f"/api/v1/match/{m.id}")
        assert res2.status_code == 401
        assert res2.get_json()["error"]["code"] == "UNAUTHORIZED"

    # 7. Cuenta pending_profile (403)
    def test_07_pending_profile_forbidden(self, client):
        user = _create_user(lifecycle_status="pending_profile")
        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(user))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    # 8. Cuenta suspended (403)
    def test_08_suspended_forbidden(self, client):
        user = _create_user(lifecycle_status="suspended")
        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(user))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    # 9. Cuenta deactivated (401 o 403)
    def test_09_deactivated_rejected(self, client):
        user = _create_user(lifecycle_status="deactivated")
        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(user))
        assert res.status_code in (401, 403)

    # 10. Match de dos usuarios ajenos (404)
    def test_10_third_party_match_returns_404(self, client):
        u1 = _create_user()
        u2 = _create_user()
        third_party = _create_user()
        match = _create_match(u1, u2)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(third_party))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    # 11. Match inexistente (404)
    def test_11_nonexistent_match_returns_404(self, client):
        user = _create_user()
        fake_uuid = str(uuid.uuid4())
        res = client.get(f"/api/v1/match/{fake_uuid}", headers=_auth_headers(user))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    # 12. UUID inválido (422)
    def test_12_invalid_uuid_returns_422(self, client):
        user = _create_user()
        res = client.get("/api/v1/match/not-a-valid-uuid", headers=_auth_headers(user))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 13. Bloqueo en dirección A -> B
    def test_13_block_direction_a_to_b(self, client):
        u1 = _create_user(first_name="Blocker")
        u2 = _create_user(first_name="Blocked")
        match = _create_match(u1, u2)

        # u1 bloquea a u2
        block = UserBlock(id=str(uuid.uuid4()), blocker_user_id=u1.id, blocked_user_id=u2.id)
        db.session.add(block)
        db.session.commit()

        # En listado de u1: no aparece
        res1 = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
        assert res1.status_code == 200
        assert res1.get_json()["data"]["items"] == []

        # En detalle de u1: 404
        res1_detail = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res1_detail.status_code == 404

        # En listado de u2: no aparece
        res2 = client.get("/api/v1/match/my-matches", headers=_auth_headers(u2))
        assert res2.status_code == 200
        assert res2.get_json()["data"]["items"] == []

        # En detalle de u2: 404
        res2_detail = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u2))
        assert res2_detail.status_code == 404

    # 14. Bloqueo en dirección B -> A
    def test_14_block_direction_b_to_a(self, client):
        u1 = _create_user(first_name="UserA")
        u2 = _create_user(first_name="UserB")
        match = _create_match(u1, u2)

        # u2 bloquea a u1
        block = UserBlock(id=str(uuid.uuid4()), blocker_user_id=u2.id, blocked_user_id=u1.id)
        db.session.add(block)
        db.session.commit()

        res1 = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
        assert res1.status_code == 200
        assert res1.get_json()["data"]["items"] == []

        res1_detail = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res1_detail.status_code == 404

    # 15. Contraparte no habilitada
    def test_15_counterpart_not_active_hidden(self, client):
        u1 = _create_user(first_name="ActiveRequester")
        u2 = _create_user(first_name="Counterpart", lifecycle_status="active")
        match = _create_match(u1, u2)

        # La contraparte es suspendida por moderación
        u2.lifecycle_status = "suspended"
        db.session.commit()

        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
        assert res.status_code == 200
        assert res.get_json()["data"]["items"] == []

        res_detail = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res_detail.status_code == 404

    # 16. Serialización de PublicProfile completa
    def test_16_public_profile_serialization(self, client):
        u1 = _create_user(first_name="User1")
        u2 = _create_user(
            first_name="Sofia",
            gender="femenino",
            city="Medellín",
            bio="Desarrolladora de software",
            relationship_goal="amistad"
        )
        match = _create_match(u1, u2)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.status_code == 200
        data = res.get_json()["data"]
        other = data["other_user"]
        assert other["user_id"] == str(u2.id)
        assert other["first_name"] == "Sofia"
        assert other["gender"] == "femenino"
        assert other["city"] == "Medellín"
        assert other["bio"] == "Desarrolladora de software"
        assert other["relationship_goal"] == "amistad"
        assert isinstance(other["age"], int)
        assert other["age"] >= 18
        assert isinstance(other["photos"], list)
        assert len(other["photos"]) >= 1

    # 17. Ausencia de email, birth_date, password_hash en PublicProfile
    def test_17_no_private_data_in_public_profile(self, client):
        u1 = _create_user()
        u2 = _create_user(email="private_email@afinia.test")
        match = _create_match(u1, u2)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.status_code == 200
        other = res.get_json()["data"]["other_user"]
        assert "email" not in other
        assert "birth_date" not in other
        assert "password_hash" not in other
        assert "storage_key" not in other
        assert "role" not in other

    # 18. Fotografías ready únicamente
    def test_18_only_ready_photos_serialized(self, client):
        u1 = _create_user()
        u2 = _create_user()
        # Agregar una segunda foto en estado 'pending' a u2
        pending_photo = ProfilePhoto(
            profile_id=u2.profile.id,
            storage_key=f"photos/{u2.id}/p_pending.webp",
            position=1,
            is_primary=False,
            status="pending",
            byte_size=1024,
            content_type="image/webp",
        )
        db.session.add(pending_photo)
        db.session.commit()

        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 0  # match no creado aún
        match = _create_match(u1, u2)

        res2 = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        photos = res2.get_json()["data"]["other_user"]["photos"]
        assert len(photos) == 1
        assert photos[0]["is_primary"] is True

    # 19. URL de fotografía protegida funcional
    def test_19_photo_url_conforms_to_contract(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        photo = res.get_json()["data"]["other_user"]["photos"][0]
        assert "/api/v1/profile/photos/media/" in photo["url"]
        assert photo["id"] is not None

        # Verificar que la URL corresponda a un recurso protegido con Bearer JWT
        media_path = f"/api/v1/profile/photos/media/{photo['id']}"
        res_no_auth = client.get(media_path)
        assert res_no_auth.status_code == 401

    # 20. last_message=null sin mensajes
    def test_20_last_message_null_when_empty(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.status_code == 200
        assert res.get_json()["data"]["last_message"] is None

    # 21. Último mensaje correcto con varios mensajes
    def test_21_last_message_correct_selection(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        t1 = datetime.utcnow() - timedelta(minutes=15)
        t2 = datetime.utcnow() - timedelta(minutes=10)
        t3 = datetime.utcnow() - timedelta(minutes=5)

        _create_message(match.id, u1.id, text="Mensaje 1", sent_at=t1)
        _create_message(match.id, u2.id, text="Mensaje 2", sent_at=t2)
        msg3 = _create_message(match.id, u2.id, text="Mensaje 3 último", sent_at=t3)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.status_code == 200
        last = res.get_json()["data"]["last_message"]
        assert last is not None
        assert last["id"] == str(msg3.id)
        assert last["text"] == "Mensaje 3 último"
        assert last["sender_user_id"] == str(u2.id)

    # 22. unread_count=0 sin mensajes entrantes
    def test_22_unread_count_zero(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.get_json()["data"]["unread_count"] == 0

    # 23. Mensajes entrantes no leídos sumados
    def test_23_incoming_unread_messages_counted(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        _create_message(match.id, u2.id, text="Hola u1", read_at=None)
        _create_message(match.id, u2.id, text="¿Cómo estás?", read_at=None)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.get_json()["data"]["unread_count"] == 2

    # 24. Mensajes propios excluidos del contador unread_count
    def test_24_outgoing_messages_excluded_from_unread(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        # Mensajes enviados por u1 hacia u2 (no leídos por u2)
        _create_message(match.id, u1.id, text="Mensaje de u1", read_at=None)
        _create_message(match.id, u1.id, text="Otro mensaje de u1", read_at=None)

        # Para u1, sus propios mensajes no deben contarse como unread
        res1 = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res1.get_json()["data"]["unread_count"] == 0

        # Para u2, son entrantes y deben contarse como unread=2
        res2 = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u2))
        assert res2.get_json()["data"]["unread_count"] == 2

    # 25. Mensajes ya leídos excluidos de unread_count
    def test_25_read_messages_excluded_from_unread(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)

        _create_message(match.id, u2.id, text="Leído", read_at=datetime.utcnow())
        _create_message(match.id, u2.id, text="No leído", read_at=None)

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.get_json()["data"]["unread_count"] == 1

    # 26. Paginación con limit=1
    def test_26_pagination_limit_one(self, client):
        main_user = _create_user()
        c1 = _create_user()
        c2 = _create_user()

        t0 = datetime.utcnow() - timedelta(minutes=20)
        t1 = datetime.utcnow() - timedelta(minutes=10)

        _create_match(main_user, c1, created_at=t0)
        _create_match(main_user, c2, created_at=t1)

        res = client.get("/api/v1/match/my-matches?limit=1", headers=_auth_headers(main_user))
        assert res.status_code == 200
        body = res.get_json()
        assert len(body["data"]["items"]) == 1
        assert body["meta"]["has_more"] is True
        assert body["meta"]["next_cursor"] is not None

    # 27. Paginación con múltiples páginas sin duplicados
    def test_27_pagination_multi_page_continuity(self, client):
        main_user = _create_user()
        c1 = _create_user()
        c2 = _create_user()
        c3 = _create_user()

        t0 = datetime.utcnow() - timedelta(minutes=30)
        t1 = datetime.utcnow() - timedelta(minutes=20)
        t2 = datetime.utcnow() - timedelta(minutes=10)

        m1 = _create_match(main_user, c1, created_at=t0)
        m2 = _create_match(main_user, c2, created_at=t1)
        m3 = _create_match(main_user, c3, created_at=t2)

        # Página 1: limit=2
        res1 = client.get("/api/v1/match/my-matches?limit=2", headers=_auth_headers(main_user))
        assert res1.status_code == 200
        b1 = res1.get_json()
        assert len(b1["data"]["items"]) == 2
        assert b1["meta"]["has_more"] is True
        cursor1 = b1["meta"]["next_cursor"]
        assert cursor1 is not None

        ids_p1 = [i["id"] for i in b1["data"]["items"]]
        assert ids_p1 == [str(m3.id), str(m2.id)]

        # Página 2: usando cursor1
        res2 = client.get(f"/api/v1/match/my-matches?limit=2&cursor={cursor1}", headers=_auth_headers(main_user))
        assert res2.status_code == 200
        b2 = res2.get_json()
        assert len(b2["data"]["items"]) == 1
        assert b2["meta"]["has_more"] is False
        assert b2["meta"]["next_cursor"] is None

        ids_p2 = [i["id"] for i in b2["data"]["items"]]
        assert ids_p2 == [str(m1.id)]

        # Ningún duplicado entre páginas
        assert set(ids_p1).isdisjoint(set(ids_p2))

    # 28. Empates de created_at resueltos por id ASC
    def test_28_tie_breaking_by_id_asc(self, client):
        main_user = _create_user()
        c1 = _create_user()
        c2 = _create_user()

        same_time = datetime(2026, 10, 20, 12, 0, 0)
        m1 = _create_match(main_user, c1, created_at=same_time)
        m2 = _create_match(main_user, c2, created_at=same_time)

        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(main_user))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 2
        # Orden por id ASC
        expected_ids = sorted([str(m1.id), str(m2.id)])
        actual_ids = [items[0]["id"], items[1]["id"]]
        assert actual_ids == expected_ids

    # 29. Cursor manipulado rechazado con 422
    def test_29_tampered_cursor_rejected(self, client):
        main_user = _create_user()
        c1 = _create_user()
        m1 = _create_match(main_user, c1)

        valid_cursor = encode_match_cursor(m1.created_at, m1.id, str(main_user.id))
        # Alterar base64
        tampered_cursor = valid_cursor[:-4] + "AAAA"

        res = client.get(f"/api/v1/match/my-matches?cursor={tampered_cursor}", headers=_auth_headers(main_user))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 30. Cursor utilizado por otra cuenta rechazado con 422
    def test_30_cursor_used_by_different_user_rejected(self, client):
        u1 = _create_user()
        u2 = _create_user()
        c1 = _create_user()
        m1 = _create_match(u1, c1)

        # Cursor emitido para u1
        cursor_u1 = encode_match_cursor(m1.created_at, m1.id, str(u1.id))

        # u2 intenta usar el cursor de u1
        res = client.get(f"/api/v1/match/my-matches?cursor={cursor_u1}", headers=_auth_headers(u2))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # 31. Resultado vacío
    def test_31_empty_results_structure(self, client):
        user = _create_user()
        res = client.get("/api/v1/match/my-matches", headers=_auth_headers(user))
        assert res.status_code == 200
        body = res.get_json()
        assert body == {
            "data": {"items": []},
            "meta": {"next_cursor": None, "has_more": False}
        }

    # 32. GET no modifica la base de datos
    def test_32_get_endpoints_do_not_mutate_db(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)
        _create_message(match.id, u2.id, text="No leído")

        # Estado inicial
        count_matches_before = Match.query.count()
        count_messages_before = Message.query.count()
        unread_before = Message.query.filter_by(read_at=None).count()

        # Ejecutar peticiones GET
        client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
        client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))

        # Estado posterior idéntico
        assert Match.query.count() == count_matches_before
        assert Message.query.count() == count_messages_before
        assert Message.query.filter_by(read_at=None).count() == unread_before

    # 33. Respuestas compatibles con OpenAPI
    def test_33_exact_openapi_contract_schema(self, client):
        u1 = _create_user()
        u2 = _create_user()
        match = _create_match(u1, u2)
        msg = _create_message(match.id, u2.id, text="¡Hola!")

        res = client.get(f"/api/v1/match/{match.id}", headers=_auth_headers(u1))
        assert res.status_code == 200
        data = res.get_json()["data"]

        # Validar claves exactas de Match
        assert set(data.keys()) == {"id", "other_user", "created_at", "last_message", "unread_count"}
        # Validar claves de other_user (PublicProfile)
        assert set(data["other_user"].keys()) == {
            "user_id", "first_name", "age", "gender", "city", "bio", "photos", "relationship_goal"
        }
        # Validar claves de last_message (Message)
        assert set(data["last_message"].keys()) == {
            "id", "match_id", "sender_user_id", "text", "sent_at", "read_at"
        }

    # 34. Ausencia de regresiones en tests anteriores
    def test_34_no_regressions_swipe_still_works(self, client):
        u1 = _create_user(gender="masculino", interested_in_genders=["femenino"])
        u2 = _create_user(gender="femenino", interested_in_genders=["masculino"])

        # u1 swipe LIKE u2
        res1 = client.post(
            "/api/v1/match/swipe",
            headers=_auth_headers(u1),
            json={"target_user_id": str(u2.id), "action": "LIKE"}
        )
        assert res1.status_code == 200
        assert res1.get_json()["data"]["is_match"] is False

        # u2 swipe LIKE u1 -> match recíproco
        res2 = client.post(
            "/api/v1/match/swipe",
            headers=_auth_headers(u2),
            json={"target_user_id": str(u1.id), "action": "LIKE"}
        )
        assert res2.status_code == 200
        assert res2.get_json()["data"]["is_match"] is True
        match_id = res2.get_json()["data"]["match_id"]

        # Ahora u1 consulta /my-matches y debe ver el nuevo match
        res_matches = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
        assert res_matches.status_code == 200
        items = res_matches.get_json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["id"] == match_id
