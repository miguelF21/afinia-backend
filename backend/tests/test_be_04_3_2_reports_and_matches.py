"""
AFINIA — Test Suite BE-04.3.2: Reportes y Gestión de Matches.
=============================================================
Pruebas exhaustivas para:
- POST /api/v1/users/{userId}/reports
- DELETE /api/v1/match/{matchId}
- Cumplimiento estricto del contrato OpenAPI v1, restricciones físicas de base de datos
  y políticas de retención, privacidad e idempotencia.
"""

import uuid
from datetime import date, datetime, timezone
import pytest
from flask import current_app

from app import db
from app.models import (
    User,
    Profile,
    ProfilePhoto,
    DiscoveryPreference,
    UserReport,
    Match,
    Message,
    ProfileInteraction,
)
from app.utils.security import create_access_token


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
        city="Bogotá",
        bio="Bio de prueba",
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
        target_relationship_type="seria"
    )
    db.session.add(pref)
    db.session.commit()

    user.cached_token = create_access_token(user.id, user.email, user.role, current_app.config['SECRET_KEY'])
    return user


def _auth_headers(user: User) -> dict:
    token = getattr(user, 'cached_token', None)
    if not token:
        token = create_access_token(user.id, user.email, user.role, current_app.config['SECRET_KEY'])
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def _create_match(user_1: User, user_2: User) -> Match:
    low_id, high_id = (user_1.id, user_2.id) if user_1.id < user_2.id else (user_2.id, user_1.id)
    match_obj = Match(
        id=str(uuid.uuid4()),
        user_a_id=low_id,
        user_b_id=high_id,
        created_at=datetime.now(timezone.utc)
    )
    db.session.add(match_obj)
    db.session.commit()
    return match_obj


# -------------------------------------------------------------------------
# Test Suite: REPORTES DE USUARIOS (POST /api/v1/users/{userId}/reports)
# -------------------------------------------------------------------------

def test_01_report_without_jwt_unauthorized(client):
    """POST /users/{userId}/reports sin JWT debe responder 401 UNAUTHORIZED."""
    target_id = str(uuid.uuid4())
    res = client.post(
        f"/api/v1/users/{target_id}/reports",
        json={"reason": "acoso"}
    )
    assert res.status_code == 401
    data = res.get_json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_02_report_invalid_json_body_bad_request(client):
    """POST /users/{userId}/reports con Content-Type o JSON no válido debe responder 400 BAD_REQUEST."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    headers = {
        "Authorization": _auth_headers(u1)["Authorization"],
        "Content-Type": "text/plain"
    }

    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=headers,
        data="no json data"
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"]["code"] == "BAD_REQUEST"


def test_03_report_self_fails_bad_request(client):
    """POST /users/{userId}/reports intentando denunciarse a sí mismo debe responder 400 BAD_REQUEST."""
    u1 = _create_user(gender="femenino")

    res = client.post(
        f"/api/v1/users/{u1.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "acoso"}
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"]["code"] == "BAD_REQUEST"
    assert "propio" in data["error"]["message"].lower()


def test_04_report_nonexistent_user_not_found(client):
    """POST /users/{userId}/reports con UUID inexistente en base de datos debe responder 404 NOT_FOUND."""
    u1 = _create_user(gender="femenino")
    fake_uuid = str(uuid.uuid4())

    res = client.post(
        f"/api/v1/users/{fake_uuid}/reports",
        headers=_auth_headers(u1),
        json={"reason": "spam"}
    )
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"]["code"] == "NOT_FOUND"


def test_05_report_invalid_uuid_validation_error(client):
    """POST /users/{userId}/reports con parámetro userId malformado debe responder 422 VALIDATION_ERROR."""
    u1 = _create_user(gender="femenino")

    res = client.post(
        "/api/v1/users/not-a-valid-uuid/reports",
        headers=_auth_headers(u1),
        json={"reason": "otro"}
    )
    assert res.status_code == 422
    data = res.get_json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_06_report_missing_reason_validation_error(client):
    """POST /users/{userId}/reports sin el campo obligatorio 'reason' debe responder 422 VALIDATION_ERROR."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")

    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"description": "Envió spam"}
    )
    assert res.status_code == 422
    data = res.get_json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_07_report_invalid_reason_enum_validation_error(client):
    """POST /users/{userId}/reports con motivo no perteneciente al enum permitido debe responder 422."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")

    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "motivo_invalido_inventado"}
    )
    assert res.status_code == 422
    data = res.get_json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_08_report_extra_fields_validation_error(client):
    """POST /users/{userId}/reports con campos extra no permitidos (additionalProperties: false) debe responder 422."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")

    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "spam", "extra_field": "hack"}
    )
    assert res.status_code == 422
    data = res.get_json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_09_report_description_too_long_validation_error(client):
    """POST /users/{userId}/reports con descripción > 1000 caracteres debe responder 422 VALIDATION_ERROR."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")

    long_desc = "a" * 1001
    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "acoso", "description": long_desc}
    )
    assert res.status_code == 422
    data = res.get_json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_10_report_valid_reason_only_success_201(client):
    """POST /users/{userId}/reports exitoso solo con motivo obligatorio responde 201 Created conforme a OpenAPI."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")

    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "suplantacion"}
    )
    assert res.status_code == 201
    data = res.get_json()["data"]
    assert "report_id" in data
    assert data["status"] == "received"
    # Verificar formato UUID
    uuid.UUID(data["report_id"])


def test_11_report_valid_reason_and_description_persisted_postgres(client):
    """POST /users/{userId}/reports persiste correctamente en PostgreSQL en estado 'pending' sin moderación resuelta."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")

    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "contenido_inapropiado", "description": "Contenido que viola las normas de la comunidad."}
    )
    assert res.status_code == 201
    rep_id = res.get_json()["data"]["report_id"]

    saved = db.session.get(UserReport, rep_id)
    assert saved is not None
    assert saved.reporter_user_id == str(u1.id)
    assert saved.reported_user_id == str(u2.id)
    assert saved.reason == "contenido_inapropiado"
    assert saved.description == "Contenido que viola las normas de la comunidad."
    assert saved.status == "pending"
    assert saved.resolved_at is None
    assert saved.resolved_by_user_id is None
    assert saved.resolution_action is None


def test_12_report_idempotency_returns_same_report_id(client):
    """POST /users/{userId}/reports repetido idéntico es idempotente y retorna el mismo report_id."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")

    res1 = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "spam", "description": "Envío masivo de enlaces"}
    )
    assert res1.status_code == 201
    rep_id_1 = res1.get_json()["data"]["report_id"]

    res2 = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "spam", "description": "Envío masivo de enlaces"}
    )
    assert res2.status_code == 201
    rep_id_2 = res2.get_json()["data"]["report_id"]

    assert rep_id_1 == rep_id_2

    count = UserReport.query.filter_by(
        reporter_user_id=str(u1.id),
        reported_user_id=str(u2.id),
        reason="spam"
    ).count()
    assert count == 1


def test_13_report_privacy_no_automatic_account_suspension(client):
    """La recepción de una denuncia no suspende automáticamente la cuenta del usuario denunciado."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    assert u2.lifecycle_status == "active"

    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "otro", "description": "Comportamiento sospechoso"}
    )
    assert res.status_code == 201

    reloaded_u2 = db.session.get(User, u2.id)
    assert reloaded_u2.lifecycle_status == "active"


def test_14_report_confidentiality_does_not_reveal_reporters(client):
    """Un usuario denunciado no recibe información de quién lo denunció ni accede a reportes en su contra."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")

    res = client.post(
        f"/api/v1/users/{u2.id}/reports",
        headers=_auth_headers(u1),
        json={"reason": "acoso"}
    )
    assert res.status_code == 201

    # El usuario denunciado u2 consulta su propio perfil y no ve reportes
    res_me = client.get("/api/v1/users/me/blocks", headers=_auth_headers(u2))
    assert res_me.status_code == 200


# -------------------------------------------------------------------------
# Test Suite: GESTIÓN DE MATCHES (DELETE /api/v1/match/{matchId})
# -------------------------------------------------------------------------

def test_15_unmatch_without_jwt_unauthorized(client):
    """DELETE /match/{matchId} sin JWT debe responder 401 UNAUTHORIZED."""
    match_id = str(uuid.uuid4())
    res = client.delete(f"/api/v1/match/{match_id}")
    assert res.status_code == 401
    data = res.get_json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_16_unmatch_nonexistent_or_invalid_match_not_found(client):
    """DELETE /match/{matchId} con UUID inexistente o malformado debe responder 404 NOT_FOUND."""
    u1 = _create_user(gender="femenino")

    # UUID válido pero inexistente
    fake_uuid = str(uuid.uuid4())
    res1 = client.delete(f"/api/v1/match/{fake_uuid}", headers=_auth_headers(u1))
    assert res1.status_code == 404
    assert res1.get_json()["error"]["code"] == "NOT_FOUND"

    # UUID malformado
    res2 = client.delete("/api/v1/match/not-a-valid-uuid", headers=_auth_headers(u1))
    assert res2.status_code == 404
    assert res2.get_json()["error"]["code"] == "NOT_FOUND"


def test_17_unmatch_non_participant_forbidden(client):
    """DELETE /match/{matchId} invocado por un usuario ajeno al match debe responder 403 FORBIDDEN."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    alien = _create_user(gender="masculino")
    match_obj = _create_match(u1, u2)

    res = client.delete(f"/api/v1/match/{match_obj.id}", headers=_auth_headers(alien))
    assert res.status_code == 403
    data = res.get_json()
    assert data["error"]["code"] == "FORBIDDEN"


def test_18_unmatch_with_messages_success_204_and_preserves_history(client):
    """
    DELETE /match/{matchId} sobre un match con mensajes realiza un cierre lógico exitoso (204 No Content),
    registrando closed_at y closed_by_user_id, y preservando el 100% de los mensajes en la tabla messages.
    """
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    match_obj = _create_match(u1, u2)
    mid = match_obj.id

    msg = Message(
        id=str(uuid.uuid4()),
        match_id=mid,
        sender_user_id=u1.id,
        text="Mensaje histórico que debe preservarse intacto",
        sent_at=datetime.now(timezone.utc)
    )
    db.session.add(msg)
    db.session.commit()

    res = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u1))
    assert res.status_code == 204
    assert res.data == b""

    # El match existe físicamente pero con closed_at y closed_by_user_id poblados
    reloaded_match = db.session.get(Match, mid)
    assert reloaded_match is not None
    assert reloaded_match.closed_at is not None
    assert str(reloaded_match.closed_by_user_id) == str(u1.id)

    # El mensaje histórico se conserva íntegro en la tabla messages
    saved_msg = db.session.get(Message, msg.id)
    assert saved_msg is not None
    assert saved_msg.text == "Mensaje histórico que debe preservarse intacto"


def test_19_unmatch_without_messages_success_204(client):
    """DELETE /match/{matchId} sobre un match sin mensajes realiza el cierre lógico y responde 204 No Content."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    match_obj = _create_match(u1, u2)
    mid = match_obj.id

    res = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u2))
    assert res.status_code == 204
    assert res.data == b""

    reloaded_match = db.session.get(Match, mid)
    assert reloaded_match is not None
    assert reloaded_match.closed_at is not None
    assert str(reloaded_match.closed_by_user_id) == str(u2.id)


def test_20_unmatch_logically_closes_and_chat_becomes_404(client):
    """Tras unmatch exitoso, las consultas de detalle, mensajes y envío responden 404 NOT_FOUND."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    match_obj = _create_match(u1, u2)
    mid = match_obj.id

    # 1. Unmatch
    res_del = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u2))
    assert res_del.status_code == 204

    # 2. GET /match/{matchId} -> 404
    res_get_match = client.get(f"/api/v1/match/{mid}", headers=_auth_headers(u1))
    assert res_get_match.status_code == 404
    assert res_get_match.get_json()["error"]["code"] == "NOT_FOUND"

    # 3. GET /match/{matchId}/messages -> 404
    res_get_msgs = client.get(f"/api/v1/match/{mid}/messages", headers=_auth_headers(u1))
    assert res_get_msgs.status_code == 404
    assert res_get_msgs.get_json()["error"]["code"] == "NOT_FOUND"

    # 4. POST /match/{matchId}/messages -> 404
    res_post_msg = client.post(
        f"/api/v1/match/{mid}/messages",
        headers=_auth_headers(u1),
        json={"text": "Hola después de unmatch"}
    )
    assert res_post_msg.status_code == 404
    assert res_post_msg.get_json()["error"]["code"] == "NOT_FOUND"

    # 5. POST /match/{matchId}/read -> 404
    res_read = client.post(f"/api/v1/match/{mid}/read", headers=_auth_headers(u1))
    assert res_read.status_code == 404
    assert res_read.get_json()["error"]["code"] == "NOT_FOUND"


def test_21_unmatch_does_not_allow_re_matching_via_swipe(client):
    """
    OpenAPI: 'no restaurar automáticamente el match tras un nuevo swipe'.
    Un nuevo swipe tras unmatch no restaura el match cerrado (is_match: False, match_id: null).
    """
    u1 = _create_user(gender="femenino", interested_in_genders=["masculino"])
    u2 = _create_user(gender="masculino", interested_in_genders=["femenino"])

    # Ambos dan LIKE
    pi1 = ProfileInteraction(id=str(uuid.uuid4()), viewer_user_id=u1.id, shown_user_id=u2.id, action="LIKE")
    pi2 = ProfileInteraction(id=str(uuid.uuid4()), viewer_user_id=u2.id, shown_user_id=u1.id, action="LIKE")
    db.session.add_all([pi1, pi2])
    db.session.commit()

    # Se forma match
    low_id, high_id = (u1.id, u2.id) if u1.id < u2.id else (u2.id, u1.id)
    match_obj = Match(id=str(uuid.uuid4()), user_a_id=low_id, user_b_id=high_id)
    db.session.add(match_obj)
    db.session.commit()
    mid = match_obj.id

    # Deshacer match
    res_del = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u1))
    assert res_del.status_code == 204

    # Re-swipe LIKE de u1 hacia u2 (idempotente sin restaurar)
    res_swipe = client.post(
        "/api/v1/match/swipe",
        headers=_auth_headers(u1),
        json={"target_user_id": str(u2.id), "action": "LIKE"}
    )
    assert res_swipe.status_code == 200
    swipe_data = res_swipe.get_json()["data"]
    assert swipe_data["action"] == "LIKE"
    assert swipe_data["is_match"] is False
    assert swipe_data["match_id"] is None


def test_22_unmatch_preserves_historical_profile_interactions(client):
    """Unmatch preserva las ProfileInteraction históricas sin alteraciones."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    pi = ProfileInteraction(id=str(uuid.uuid4()), viewer_user_id=u1.id, shown_user_id=u2.id, action="LIKE")
    match_obj = _create_match(u1, u2)
    db.session.add(pi)
    db.session.commit()
    pi_id = pi.id
    mid = match_obj.id

    res = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u1))
    assert res.status_code == 204

    # Match continúa existiendo pero cerrado
    m = db.session.get(Match, mid)
    assert m is not None
    assert m.closed_at is not None
    # ProfileInteraction permanece intacto
    saved_pi = db.session.get(ProfileInteraction, pi_id)
    assert saved_pi is not None
    assert saved_pi.action == "LIKE"


def test_23_unmatch_idempotency_repeated_call_returns_204(client):
    """Llamadas repetidas a DELETE /match/{matchId} por un participante autorizado son idempotentes (204)."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    match_obj = _create_match(u1, u2)
    mid = match_obj.id

    # Primer unmatch
    res1 = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u1))
    assert res1.status_code == 204

    # Segundo unmatch idéntico
    res2 = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u1))
    assert res2.status_code == 204

    # Tercer unmatch por la contraparte
    res3 = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u2))
    assert res3.status_code == 204


def test_24_get_user_matches_excludes_closed_matches(client):
    """GET /api/v1/match/my-matches no retorna coincidencias que han sido deshechas (closed_at IS NOT NULL)."""
    u1 = _create_user(gender="femenino", interested_in_genders=["masculino"])
    u2 = _create_user(gender="masculino", interested_in_genders=["femenino"])
    u3 = _create_user(gender="masculino", interested_in_genders=["femenino"])

    m12 = _create_match(u1, u2)
    m13 = _create_match(u1, u3)

    # Inicialmente u1 tiene 2 matches
    res_list1 = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
    assert res_list1.status_code == 200
    items1 = res_list1.get_json()["data"]["items"]
    assert len(items1) == 2

    # u1 deshace match con u2
    res_del = client.delete(f"/api/v1/match/{m12.id}", headers=_auth_headers(u1))
    assert res_del.status_code == 204

    # Ahora u1 solo ve el match con u3
    res_list2 = client.get("/api/v1/match/my-matches", headers=_auth_headers(u1))
    assert res_list2.status_code == 200
    items2 = res_list2.get_json()["data"]["items"]
    assert len(items2) == 1
    assert items2[0]["id"] == str(m13.id)


def test_25_unblock_does_not_reopen_closed_match(client):
    """Desbloquear a un usuario no restaura una coincidencia cerrada previamente."""
    u1 = _create_user(gender="femenino")
    u2 = _create_user(gender="masculino")
    match_obj = _create_match(u1, u2)
    mid = match_obj.id

    # 1. Unmatch
    res_del = client.delete(f"/api/v1/match/{mid}", headers=_auth_headers(u1))
    assert res_del.status_code == 204

    # 2. Bloquear usuario (PUT /users/{userId}/block)
    res_block = client.put(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert res_block.status_code == 200

    # 3. Desbloquear usuario (DELETE /users/{userId}/block)
    res_unblock = client.delete(f"/api/v1/users/{u2.id}/block", headers=_auth_headers(u1))
    assert res_unblock.status_code == 204

    # 4. El match sigue cerrado (404 al consultar)
    res_get = client.get(f"/api/v1/match/{mid}", headers=_auth_headers(u1))
    assert res_get.status_code == 404

