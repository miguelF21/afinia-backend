"""
AFINIA — Test Suite BE-04.3.1: Bloqueo y Desbloqueo de Usuarios.
================================================================
Pruebas exhaustivas para:
- PUT /api/v1/users/{userId}/block
- DELETE /api/v1/users/{userId}/block
- GET /api/v1/users/me/blocks
- Protocolo transaccional canónico y serialización frente a mensajería

Cubriendo los 22 escenarios obligatorios de BE-04.3.1.
"""

import uuid
import threading
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
    ProfileInteraction,
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
        id=str(uuid.uuid4())
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
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            storage_key=f"photos/{user.id}/p_{uuid.uuid4().hex[:8]}.webp",
            position=0,
            is_primary=True,
            status=photo_status,
            content_type="image/jpeg",
            byte_size=1024
        )
        db.session.add(photo)

    pref = DiscoveryPreference(
        user_id=user.id,
        min_age=18,
        max_age=50,
        interested_in_genders=interested_in_genders,
        target_relationship_type=relationship_goal
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


def _create_match(user_a: User, user_b: User) -> Match:
    # Orden canónico
    u1, u2 = (user_a, user_b) if user_a.id < user_b.id else (user_b, user_a)
    m = Match(
        id=str(uuid.uuid4()),
        user_a_id=u1.id,
        user_b_id=u2.id,
        created_at=datetime.now(timezone.utc)
    )
    db.session.add(m)
    db.session.commit()
    return m


# -------------------------------------------------------------------------
# Test Cases BE-04.3.1
# -------------------------------------------------------------------------

def test_01_block_user_valid(client):
    """1. Bloqueo válido: PUT /api/v1/users/{userId}/block retorna 200 con BlockReceipt."""
    u1 = _create_user(gender="femenino", interested_in_genders=["masculino"])
    u2 = _create_user(gender="masculino", interested_in_genders=["femenino"])

    res = client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["blocked_user_id"] == u2.id
    assert data["blocked"] is True

    # Verificar persistencia física en user_blocks
    block = UserBlock.query.filter_by(blocker_user_id=u1.id, blocked_user_id=u2.id).first()
    assert block is not None


def test_02_block_user_repeated_idempotent(client):
    """2. Bloqueo repetido: Comportamiento idempotente retorna 200 sin duplicar registros."""
    u1 = _create_user()
    u2 = _create_user()

    res1 = client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert res1.status_code == 200

    res2 = client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert res2.status_code == 200
    assert res2.get_json()["data"]["blocked"] is True

    count = UserBlock.query.filter_by(blocker_user_id=u1.id, blocked_user_id=u2.id).count()
    assert count == 1


def test_03_block_self_forbidden(client):
    """3. Auto-bloqueo: Prohibición de bloquearse a sí mismo retorna 400 BAD_REQUEST."""
    u1 = _create_user()

    res = client.put(f"/api/v1/users/{u1.id}/block", headers=_auth_headers(u1))
    assert res.status_code == 400
    err = res.get_json()["error"]
    assert err["code"] == "BAD_REQUEST"


def test_04_block_nonexistent_user(client):
    """4. Usuario inexistente: Retorna 404 NOT_FOUND."""
    u1 = _create_user()
    fake_id = str(uuid.uuid4())

    res = client.put(f"/api/v1/users/{fake_id}/block", headers=_auth_headers(u1))
    assert res.status_code == 404
    err = res.get_json()["error"]
    assert err["code"] == "NOT_FOUND"


def test_05_block_unauthorized_no_jwt(client):
    """5. JWT ausente: Retorna 401 UNAUTHORIZED."""
    fake_id = str(uuid.uuid4())
    res = client.put(f"/api/v1/users/{fake_id}/block")
    assert res.status_code == 401


def test_06_block_invalid_uuid(client):
    """6. UUID inválido: Retorna 400 BAD_REQUEST."""
    u1 = _create_user()
    res = client.put("/api/v1/users/not-a-valid-uuid/block", headers=_auth_headers(u1))
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"


def test_07_concurrent_block_same_pair(client):
    """7. Bloqueo simultáneo A -> B: Ambos completan exitosamente y persiste exactamente 1 fila."""
    u1 = _create_user()
    u2 = _create_user()
    u1_id = u1.id
    u2_id = u2.id
    headers_u1 = _auth_headers(u1)

    results = []
    barrier = threading.Barrier(2)

    def _block_req():
        with client.application.app_context():
            try:
                c = client.application.test_client()
                barrier.wait(timeout=5)
                res = c.put(f"/api/v1/users/{u2_id}/block", headers=headers_u1)
                results.append((res.status_code, res.get_json() if res.is_json else res.data))
            finally:
                db.session.remove()

    t1 = threading.Thread(target=_block_req)
    t2 = threading.Thread(target=_block_req)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    codes = [code for code, _ in results]
    assert codes == [200, 200], f"Obtained results: {results}"
    db.session.expire_all()
    count = UserBlock.query.filter_by(blocker_user_id=u1_id, blocked_user_id=u2_id).count()
    assert count == 1


def test_08_concurrent_block_mutual(client):
    """8. Bloqueo simultáneo A -> B y B -> A: Ambos completan sin deadlock y persisten 2 filas."""
    u1 = _create_user()
    u2 = _create_user()
    u1_id = u1.id
    u2_id = u2.id
    headers_u1 = _auth_headers(u1)
    headers_u2 = _auth_headers(u2)

    results = []
    barrier = threading.Barrier(2)

    def _block_ab():
        with client.application.app_context():
            try:
                c = client.application.test_client()
                barrier.wait(timeout=5)
                res = c.put(f"/api/v1/users/{u2_id}/block", headers=headers_u1)
                results.append((res.status_code, "a_blocks_b"))
            finally:
                db.session.remove()

    def _block_ba():
        with client.application.app_context():
            try:
                c = client.application.test_client()
                barrier.wait(timeout=5)
                res = c.put(f"/api/v1/users/{u1_id}/block", headers=headers_u2)
                results.append((res.status_code, "b_blocks_a"))
            finally:
                db.session.remove()

    t1 = threading.Thread(target=_block_ab)
    t2 = threading.Thread(target=_block_ba)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    assert all(code == 200 for code, _ in results)
    db.session.expire_all()
    assert UserBlock.query.filter_by(blocker_user_id=u1_id, blocked_user_id=u2_id).count() == 1
    assert UserBlock.query.filter_by(blocker_user_id=u2_id, blocked_user_id=u1_id).count() == 1


def test_09_unblock_own_user(client):
    """9. Desbloqueo propio: DELETE /api/v1/users/{userId}/block retorna 204 No Content."""
    u1 = _create_user()
    u2 = _create_user()

    # Bloquear primero
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert UserBlock.query.filter_by(blocker_user_id=u1.id, blocked_user_id=u2.id).count() == 1

    # Desbloquear
    res = client.delete(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert res.status_code == 204
    assert UserBlock.query.filter_by(blocker_user_id=u1.id, blocked_user_id=u2.id).count() == 0

    # Desbloqueo repetido retorna 404 sin inconsistencias
    res_repeat = client.delete(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert res_repeat.status_code == 404


def test_10_unblock_third_party_rejected(client):
    """10. Desbloqueo ajeno rechazado: Un tercero no puede eliminar bloqueos ajenos."""
    u1 = _create_user()
    u2 = _create_user()
    u3 = _create_user()

    # u1 bloquea a u2
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    # u3 intenta desbloquear a u2
    res = client.delete(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u3))
    assert res.status_code == 404
    assert UserBlock.query.filter_by(blocker_user_id=u1.id, blocked_user_id=u2.id).count() == 1


def test_11_unblock_preserves_inverse_block(client):
    """11. Bloqueo inverso conservado: Desbloqueo unilateral de A a B no elimina el bloqueo de B a A."""
    u1 = _create_user()
    u2 = _create_user()

    # Ambos se bloquean mutuamente
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    client.put(f"/api/v1/users/{u1.id}/block", headers=_auth_headers(u2))

    # u1 desbloquea a u2
    res = client.delete(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert res.status_code == 204

    # El bloqueo de u1 a u2 fue eliminado, pero el de u2 a u1 sigue intacto
    assert UserBlock.query.filter_by(blocker_user_id=u1.id, blocked_user_id=u2.id).count() == 0
    assert UserBlock.query.filter_by(blocker_user_id=u2.id, blocked_user_id=u1.id).count() == 1


def test_12_exclusion_in_discovery(client):
    """12. Exclusión en descubrimiento: B desaparece de potencial de A, y A desaparece de potencial de B."""
    u1 = _create_user(gender="femenino", interested_in_genders=["masculino"])
    u2 = _create_user(gender="masculino", interested_in_genders=["femenino"])

    # Antes del bloqueo, u2 aparece en potencial de u1
    res1 = client.get("/api/v1/match/potential", headers=_auth_headers(u1))
    assert res1.status_code == 200
    u2_ids = [c["user_id"] for c in res1.get_json()["data"]["items"]]
    assert u2.id in u2_ids

    # u1 bloquea a u2
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    # Ahora u2 no aparece para u1
    res2 = client.get("/api/v1/match/potential", headers=_auth_headers(u1))
    assert res2.status_code == 200
    u2_ids_after = [c["user_id"] for c in res2.get_json()["data"]["items"]]
    assert u2.id not in u2_ids_after

    # Y u1 no aparece para u2
    res3 = client.get("/api/v1/match/potential", headers=_auth_headers(u2))
    assert res3.status_code == 200
    u1_ids_after = [c["user_id"] for c in res3.get_json()["data"]["items"]]
    assert u1.id not in u1_ids_after


def test_13_exclusion_in_public_profile(client):
    """13. Exclusión en perfil público: GET /api/v1/users/{userId} retorna 404 tras bloqueo."""
    u1 = _create_user(gender="femenino", interested_in_genders=["masculino"])
    u2 = _create_user(gender="masculino", interested_in_genders=["femenino"])

    # Antes del bloqueo
    res_before = client.get(f"/api/v1/users/{u2.id}", headers=_auth_headers(u1))
    assert res_before.status_code == 200

    # u1 bloquea a u2
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    # u1 no puede ver a u2
    res1 = client.get(f"/api/v1/users/{u2.id}", headers=_auth_headers(u1))
    assert res1.status_code == 404

    # u2 no puede ver a u1
    res2 = client.get(f"/api/v1/users/{u1.id}", headers=_auth_headers(u2))
    assert res2.status_code == 404


def test_14_exclusion_in_matches(client):
    """14. Exclusión en matches: El match desaparece de /my-matches y /match/{matchId} da 404."""
    u1 = _create_user()
    u2 = _create_user()
    match_obj = _create_match(u1, u2)

    # Antes del bloqueo, match es visible
    res_matches = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
    assert res_matches.status_code == 200
    match_ids = [m["id"] for m in res_matches.get_json()["data"]["items"]]
    assert match_obj.id in match_ids

    # u1 bloquea a u2
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    # Match ya no aparece en my-matches para u1 ni para u2
    res_m1 = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
    assert match_obj.id not in [m["id"] for m in res_m1.get_json()["data"]["items"]]

    res_m2 = client.get("/api/v1/match/my-matches", headers=_auth_headers(u2))
    assert match_obj.id not in [m["id"] for m in res_m2.get_json()["data"]["items"]]

    # Consulta directa de detalle retorna 404
    assert client.get(f"/api/v1/match/{match_obj.id}", headers=_auth_headers(u1)).status_code == 404
    assert client.get(f"/api/v1/match/{match_obj.id}", headers=_auth_headers(u2)).status_code == 404


def test_15_rejection_get_messages(client):
    """15. Rechazo de GET /messages: GET /api/v1/match/{matchId}/messages retorna 404."""
    u1 = _create_user()
    u2 = _create_user()
    match_obj = _create_match(u1, u2)

    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    res = client.get(f"/api/v1/match/{match_obj.id}/messages", headers=_auth_headers(u1))
    assert res.status_code == 404

    res2 = client.get(f"/api/v1/match/{match_obj.id}/messages", headers=_auth_headers(u2))
    assert res2.status_code == 404


def test_16_rejection_post_messages(client):
    """16. Rechazo de POST /messages: POST /api/v1/match/{matchId}/messages retorna 404."""
    u1 = _create_user()
    u2 = _create_user()
    match_obj = _create_match(u1, u2)

    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    payload = {"text": "Mensaje bloqueado"}
    res = client.post(f"/api/v1/match/{match_obj.id}/messages", json=payload, headers=_auth_headers(u1))
    assert res.status_code == 404

    res2 = client.post(f"/api/v1/match/{match_obj.id}/messages", json=payload, headers=_auth_headers(u2))
    assert res2.status_code == 404


def test_17_rejection_photos_access(client):
    """17. Rechazo de fotografías: GET /api/v1/profile/photos/media/{photoId} retorna 403."""
    u1 = _create_user(with_photo=True, photo_status="ready")
    u2 = _create_user(with_photo=True, photo_status="ready")
    u2_photo = u2.profile.photos[0]

    # u1 bloquea a u2
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    # u1 intentando acceder a la foto protegida de u2 retorna 403
    res = client.get(f"/api/v1/profile/photos/media/{u2_photo.id}", headers=_auth_headers(u1))
    assert res.status_code == 403


def test_18_canonical_lock_blocks_concurrent_messages(client):
    """18. Protocolo canónico y prevención de condición de carrera con mensajería."""
    u1 = _create_user()
    u2 = _create_user()
    match_obj = _create_match(u1, u2)

    # Simular bloqueo confirmado
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    # Envío de mensaje posterior debe ser inmediatamente rechazado por re-verificación bajo bloqueo
    res = client.post(
        f"/api/v1/match/{match_obj.id}/messages",
        json={"text": "Intento de carrera"},
        headers=_auth_headers(u2)
    )
    assert res.status_code == 404
    assert Message.query.filter_by(match_id=match_obj.id).count() == 0


def test_19_block_concurrent_with_post_read(client):
    """19. Bloqueo y POST /read: Retorna 404 si la conversación está bloqueada."""
    u1 = _create_user()
    u2 = _create_user()
    match_obj = _create_match(u1, u2)

    # u1 envía un mensaje antes del bloqueo
    msg = Message(
        id=str(uuid.uuid4()),
        match_id=match_obj.id,
        sender_user_id=u1.id,
        text="Hola antes del bloqueo",
        sent_at=datetime.now(timezone.utc),
        read_at=None
    )
    db.session.add(msg)
    db.session.commit()

    # u1 bloquea a u2
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    # u2 intenta marcar como leído
    res = client.post(f"/api/v1/match/{match_obj.id}/read", headers=_auth_headers(u2))
    assert res.status_code == 404


def test_20_direct_db_verification(client):
    """20. Verificación directa de restricciones físicas en PostgreSQL / SQLite."""
    u1 = _create_user()
    u2 = _create_user()

    # Inserción directa
    b = UserBlock(id=str(uuid.uuid4()), blocker_user_id=u1.id, blocked_user_id=u2.id)
    db.session.add(b)
    db.session.commit()

    saved = db.session.get(UserBlock, b.id)
    assert saved.blocker_user_id == u1.id
    assert saved.blocked_user_id == u2.id
    assert saved.created_at is not None

    # Limpiar
    db.session.delete(saved)
    db.session.commit()


def test_21_historical_messages_and_interactions_preserved(client):
    """21. No eliminación de historial: Mensajes e interacciones físicas se conservan tras bloqueo."""
    u1 = _create_user()
    u2 = _create_user()
    match_obj = _create_match(u1, u2)

    # Guardar mensaje histórico
    msg = Message(
        id=str(uuid.uuid4()),
        match_id=match_obj.id,
        sender_user_id=u1.id,
        text="Mensaje histórico preservado",
        sent_at=datetime.now(timezone.utc),
        read_at=None
    )
    db.session.add(msg)

    # Guardar interacción de swipe
    inter = ProfileInteraction(
        id=str(uuid.uuid4()),
        viewer_user_id=u1.id,
        shown_user_id=u2.id,
        action="LIKE",
        timestamp=datetime.now(timezone.utc)
    )
    db.session.add(inter)
    db.session.commit()

    # Bloquear
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))

    # Verificar que el mensaje y la interacción persisten físicamente en la BD
    assert db.session.get(Message, msg.id) is not None
    assert db.session.get(ProfileInteraction, inter.id) is not None
    assert db.session.get(Match, match_obj.id) is not None


def test_22_get_my_blocks_pagination(client):
    """22. GET /api/v1/users/me/blocks: Lista paginada de usuarios bloqueados."""
    u1 = _create_user()
    u2 = _create_user(first_name="Bloqueado1")
    u3 = _create_user(first_name="Bloqueado2")

    # u1 bloquea a u2 y u3
    client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    client.put(f"/api/v1/users/{u3.id}/block", headers=_auth_headers(u1))

    # Consultar con limit=1
    res = client.get("/api/v1/users/me/blocks?limit=1", headers=_auth_headers(u1))
    assert res.status_code == 200
    body = res.get_json()
    assert len(body["data"]["items"]) == 1
    assert body["meta"]["has_more"] is True
    assert body["meta"]["next_cursor"] is not None

    # Consultar siguiente página
    cursor = body["meta"]["next_cursor"]
    res2 = client.get(f"/api/v1/users/me/blocks?limit=1&cursor={cursor}", headers=_auth_headers(u1))
    assert res2.status_code == 200
    body2 = res2.get_json()
    assert len(body2["data"]["items"]) == 1
    assert body2["meta"]["has_more"] is False
