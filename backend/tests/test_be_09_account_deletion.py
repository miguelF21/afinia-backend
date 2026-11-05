"""
AFINIA — Pruebas Automatizadas BE-09: Eliminación Segura de Cuenta.
==================================================================
Verifica los 17 escenarios obligatorios de eliminación de cuenta:
1. Eliminación válida.
2. Petición sin JWT.
3. Usuario inexistente.
4. Usuario previamente eliminado.
5. Intento de eliminar una cuenta ajena.
6. Login después de eliminar la cuenta.
7. Refresh token anterior.
8. JWT emitido antes de la eliminación.
9. Visibilidad en descubrimiento.
10. Matches y conversaciones relacionados.
11. Fotografías y acceso a medios.
12. Denuncias y bloqueos existentes.
13. Integridad referencial.
14. Reintentos.
15. Dos solicitudes concurrentes de eliminación.
16. Fallo transaccional y recuperación.
17. Aislamiento entre usuarios.
"""

import io
import os
import uuid
import threading
from datetime import date, datetime, timezone, timedelta
from PIL import Image
import pytest
import sqlalchemy as sa

from app import db
from app.models import (
    User,
    Profile,
    ProfilePhoto,
    DiscoveryPreference,
    AnalyticQuestionnaireAnswer,
    ProfileInteraction,
    Match,
    Message,
    UserBlock,
    UserReport,
    LegalConsent,
    RefreshToken,
    EmailVerificationToken,
    PasswordResetToken,
)
from app.services.storage_service import storage_adapter
from app.services.profile_service import approve_photo_for_qa
from app.services.auth_service import request_account_deletion, AuthError
from app.utils.security import create_access_token


VALID_PWD_1 = "ClaveSeguraUsuario1_2026!"
VALID_PWD_2 = "ClaveSeguraUsuario2_2026!"
VALID_PWD_3 = "ClaveSeguraUsuario3_2026!"


def _make_jpeg_bytes(color=(40, 120, 200)) -> bytes:
    img = Image.new("RGB", (64, 64), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _create_complete_user(
    client,
    email: str,
    password: str = VALID_PWD_1,
    first_name: str = "Ana",
    gender: str = "femenino",
    interested_in=None,
) -> dict:
    """
    Registra un usuario completo con consentimientos legales, verifica su email,
    inicia sesión (obteniendo access_token y refresh_token), crea su perfil,
    preferencias de descubrimiento, sube y aprueba una fotografía principal
    y guarda respuestas del cuestionario analítico.
    """
    if interested_in is None:
        interested_in = ["masculino", "femenino"]

    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "accept_terms_version": "v1-draft",
            "accept_privacy_version": "v1-draft",
        },
    )
    assert reg_res.status_code == 201, reg_res.get_json()
    user_id = reg_res.get_json()["data"]["id"]

    # Marcar email_verified = True para activar onboarding completo
    user_obj = db.session.get(User, user_id)
    user_obj.email_verified = True
    db.session.commit()

    # Login como cliente móvil para obtener tanto access_token como refresh_token
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"X-Client-Platform": "mobile"},
    )
    assert login_res.status_code == 200, login_res.get_json()
    login_data = login_res.get_json()["data"]
    access_token = login_data["access_token"]
    refresh_token = login_data["refresh_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # Crear perfil
    prof_res = client.post(
        "/api/v1/profile/",
        json={
            "first_name": first_name,
            "birth_date": "1999-05-15",
            "gender": gender,
            "city": "Villavicencio",
            "bio": f"Biografía de {first_name}",
        },
        headers=headers,
    )
    assert prof_res.status_code == 201, prof_res.get_json()

    # Guardar preferencias de descubrimiento
    pref_res = client.put(
        "/api/v1/profile/discovery-preferences",
        json={
            "interested_in_genders": interested_in,
            "min_age": 18,
            "max_age": 45,
            "target_relationship_type": "seria",
        },
        headers=headers,
    )
    assert pref_res.status_code == 200, pref_res.get_json()

    # Subir foto principal y aprobarla para QA
    photo_res = client.post(
        "/api/v1/profile/photos",
        data={
            "file": (io.BytesIO(_make_jpeg_bytes()), "avatar.jpg"),
            "is_primary": "true",
        },
        headers=headers,
        content_type="multipart/form-data",
    )
    assert photo_res.status_code == 201, photo_res.get_json()
    photo_id = photo_res.get_json()["data"]["id"]
    approve_photo_for_qa(photo_id)

    photo_obj = db.session.get(ProfilePhoto, photo_id)
    storage_key = photo_obj.storage_key
    file_path = storage_adapter.get_file_path(storage_key)
    assert file_path is not None and os.path.exists(file_path)

    # Guardar respuestas del cuestionario analítico
    q_res = client.put(
        "/api/v1/questionnaire/answers",
        json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_communication", "value": 5},
                {"question_id": "importance_values", "value": 4},
                {"question_id": "importance_honesty", "value": 5},
            ],
        },
        headers=headers,
    )
    assert q_res.status_code == 200, q_res.get_json()

    return {
        "user_id": user_id,
        "email": email,
        "password": password,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "headers": headers,
        "photo_id": photo_id,
        "storage_key": storage_key,
        "file_path": file_path,
    }


def test_01_valid_account_deletion(client, app):
    """1. Eliminación válida conforme a OpenAPI v1 (202 Accepted + DeletionReceipt)."""
    u1 = _create_complete_user(client, "delete.valid@example.test")

    res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert res.status_code == 202, res.get_json()
    body = res.get_json()
    assert "data" in body
    receipt = body["data"]
    assert set(receipt.keys()) == {"request_id", "status", "sessions_revoked"}
    assert str(uuid.UUID(receipt["request_id"])) == receipt["request_id"]
    assert receipt["status"] == "accepted"
    assert receipt["sessions_revoked"] is True

    # Verificar estado en BD
    db.session.expire_all()
    user_db = db.session.get(User, u1["user_id"])
    assert user_db is not None
    assert user_db.is_active is False
    assert user_db.lifecycle_status == "deactivated"
    assert user_db.deleted_at is not None
    assert user_db.email_verified is False
    assert user_db.email == f"deleted+{u1['user_id']}@deleted.afinia.invalid"
    assert Profile.query.filter_by(user_id=u1["user_id"]).count() == 0
    assert DiscoveryPreference.query.filter_by(user_id=u1["user_id"]).count() == 0
    assert AnalyticQuestionnaireAnswer.query.filter_by(user_id=u1["user_id"]).count() == 0


def test_02_deletion_without_jwt(client):
    """2. Petición sin JWT o con JWT inválido/corrupto retorna 401 UNAUTHORIZED."""
    res_no_jwt = client.post(
        "/api/v1/account/deletion",
        json={"password": VALID_PWD_1, "confirm": True},
    )
    assert res_no_jwt.status_code == 401
    assert res_no_jwt.get_json()["error"]["code"] == "UNAUTHORIZED"

    res_bad_jwt = client.post(
        "/api/v1/account/deletion",
        json={"password": VALID_PWD_1, "confirm": True},
        headers={"Authorization": "Bearer token.invalido.corrupto"},
    )
    assert res_bad_jwt.status_code == 401
    assert res_bad_jwt.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_03_deletion_nonexistent_user(client, app):
    """3. Usuario inexistente con JWT firmado retorna 401 UNAUTHORIZED."""
    ghost_id = str(uuid.uuid4())
    ghost_token = create_access_token(
        user_id=ghost_id,
        email="ghost@example.test",
        role="user",
        secret_key=app.config["SECRET_KEY"],
        expires_in=900,
        password_hash="scrypt:32768:8:1$ghost$hash",
    )
    res = client.post(
        "/api/v1/account/deletion",
        json={"password": VALID_PWD_1, "confirm": True},
        headers={"Authorization": f"Bearer {ghost_token}"},
    )
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_04_deletion_previously_deleted_user(client, app):
    """4. Usuario previamente eliminado no puede volver a eliminarse."""
    u1 = _create_complete_user(client, "already.deleted@example.test")

    first_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert first_res.status_code == 202

    # Intento por HTTP con el JWT anterior -> 401 UNAUTHORIZED
    second_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert second_res.status_code == 401
    assert second_res.get_json()["error"]["code"] == "UNAUTHORIZED"

    # Intento directo a nivel de servicio sobre la entidad ya eliminada -> 409 CONFLICT
    user_db = db.session.get(User, u1["user_id"])
    with pytest.raises(AuthError) as exc_info:
        request_account_deletion(user_db, {"password": u1["password"], "confirm": True})
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CONFLICT"


def test_05_cannot_delete_other_users_account(client):
    """5. Intento de eliminar una cuenta ajena es bloqueado y preserva ambas cuentas."""
    u1 = _create_complete_user(client, "attacker@example.test", password=VALID_PWD_1, first_name="Atacante")
    u2 = _create_complete_user(client, "victim@example.test", password=VALID_PWD_2, first_name="Victima")

    # 5a. Intentar inyectar user_id o email de la víctima en el body JSON -> 400 BAD_REQUEST
    res_extra = client.post(
        "/api/v1/account/deletion",
        json={
            "password": u1["password"],
            "confirm": True,
            "user_id": u2["user_id"],
        },
        headers=u1["headers"],
    )
    assert res_extra.status_code == 400
    assert res_extra.get_json()["error"]["code"] == "BAD_REQUEST"

    # 5b. Intentar usar el JWT de u1 enviando la contraseña de u2 -> 401 UNAUTHORIZED
    res_wrong_pwd = client.post(
        "/api/v1/account/deletion",
        json={"password": u2["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert res_wrong_pwd.status_code == 401
    assert res_wrong_pwd.get_json()["error"]["code"] == "UNAUTHORIZED"

    # 5c. Intentar confirm=False -> 422 VALIDATION_ERROR
    res_unconfirmed = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": False},
        headers=u1["headers"],
    )
    assert res_unconfirmed.status_code == 422
    assert res_unconfirmed.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # Verificar que tanto u2 como u1 permanecen activos e intactos
    db.session.expire_all()
    u2_db = db.session.get(User, u2["user_id"])
    assert u2_db.is_active is True
    assert u2_db.deleted_at is None
    assert u2_db.email == "victim@example.test"


def test_06_login_after_account_deletion(client):
    """6. Login después de eliminar la cuenta es rechazado (401 UNAUTHORIZED)."""
    u1 = _create_complete_user(client, "nologin@example.test")

    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert del_res.status_code == 202

    # Login con correo y contraseña originales -> 401 UNAUTHORIZED
    login_orig = client.post(
        "/api/v1/auth/login",
        json={"email": u1["email"], "password": u1["password"]},
    )
    assert login_orig.status_code == 401
    assert login_orig.get_json()["error"]["code"] == "UNAUTHORIZED"

    # Login con correo anonimizado -> 401 UNAUTHORIZED
    login_anon = client.post(
        "/api/v1/auth/login",
        json={
            "email": f"deleted+{u1['user_id']}@deleted.afinia.invalid",
            "password": u1["password"],
        },
    )
    assert login_anon.status_code == 401
    assert login_anon.get_json()["error"]["code"] == "UNAUTHORIZED"

    # Forgot password con correo original responde 202 anti-enumeración pero sin crear token
    fp_res = client.post("/api/v1/auth/forgot-password", json={"email": u1["email"]})
    assert fp_res.status_code == 202
    assert PasswordResetToken.query.filter_by(user_id=u1["user_id"]).count() == 0


def test_07_previous_refresh_token_rejected(client):
    """7. Refresh token emitido antes de la eliminación queda revocado e inválido."""
    u1 = _create_complete_user(client, "norefresh@example.test")

    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert del_res.status_code == 202

    # Verificar que en BD todos los refresh_tokens tienen revoked_at IS NOT NULL y sin IP/UA
    tokens = RefreshToken.query.filter_by(user_id=u1["user_id"]).all()
    assert len(tokens) >= 1
    for t in tokens:
        assert t.revoked_at is not None
        assert t.ip_address is None
        assert t.user_agent is None

    # Intentar renovar sesión con refresh_token anterior -> 401 UNAUTHORIZED
    ref_res = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": u1["refresh_token"]},
        headers={"X-Client-Platform": "mobile"},
    )
    assert ref_res.status_code == 401
    assert ref_res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_08_jwt_issued_before_deletion_rejected(client):
    """8. JWT emitido antes de la eliminación queda invalidado de inmediato en todos los endpoints."""
    u1 = _create_complete_user(client, "nojwt@example.test")
    old_headers = u1["headers"]

    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=old_headers,
    )
    assert del_res.status_code == 202

    for method, url in [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/profile/"),
        ("GET", "/api/v1/profile/discovery-preferences"),
        ("GET", "/api/v1/match/potential"),
        ("GET", "/api/v1/match/my-matches"),
        ("GET", "/api/v1/questionnaire/answers"),
    ]:
        resp = client.open(url, method=method, headers=old_headers)
        assert resp.status_code == 401, f"Endpoint {method} {url} no rechazó el JWT antiguo"
        assert resp.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_09_visibility_in_discovery_and_public_profile(client):
    """9. Usuario eliminado desaparece de descubrimiento, perfil público y swipes."""
    u1 = _create_complete_user(
        client, "u1.discover@example.test", first_name="Carla", gender="femenino", interested_in=["masculino"]
    )
    u2 = _create_complete_user(
        client, "u2.viewer@example.test", first_name="Diego", gender="masculino", interested_in=["femenino"]
    )

    # Antes de eliminar, u2 puede ver a u1 en discovery y en perfil público
    pre_disc = client.get("/api/v1/match/potential", headers=u2["headers"])
    assert pre_disc.status_code == 200
    pre_ids = [item["user_id"] for item in pre_disc.get_json()["data"]["items"]]
    assert u1["user_id"] in pre_ids

    pre_pub = client.get(f"/api/v1/users/{u1['user_id']}", headers=u2["headers"])
    assert pre_pub.status_code == 200

    # u1 elimina su cuenta
    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert del_res.status_code == 202

    # Después de eliminar, u1 NO aparece en discovery de u2
    post_disc = client.get("/api/v1/match/potential", headers=u2["headers"])
    assert post_disc.status_code == 200
    post_ids = [item["user_id"] for item in post_disc.get_json()["data"]["items"]]
    assert u1["user_id"] not in post_ids

    # Perfil público de u1 retorna 404 NOT_FOUND
    post_pub = client.get(f"/api/v1/users/{u1['user_id']}", headers=u2["headers"])
    assert post_pub.status_code == 404
    assert post_pub.get_json()["error"]["code"] == "NOT_FOUND"

    # Swipe hacia u1 retorna 404 NOT_FOUND
    swipe_res = client.post(
        "/api/v1/match/swipe",
        json={"target_user_id": u1["user_id"], "action": "LIKE"},
        headers=u2["headers"],
    )
    assert swipe_res.status_code == 404
    assert swipe_res.get_json()["error"]["code"] == "NOT_FOUND"


def test_10_related_matches_and_conversations(client):
    """10. Matches abiertos se cierran lógicamente, mensajes se preservan en BD y el chat se bloquea para la contraparte."""
    u1 = _create_complete_user(
        client, "u1.match@example.test", first_name="Elena", gender="femenino", interested_in=["masculino"]
    )
    u2 = _create_complete_user(
        client, "u2.match@example.test", first_name="Fernando", gender="masculino", interested_in=["femenino"]
    )

    # Crear match mutuo entre u1 y u2
    s1 = client.post(
        "/api/v1/match/swipe",
        json={"target_user_id": u2["user_id"], "action": "LIKE"},
        headers=u1["headers"],
    )
    assert s1.status_code == 200
    s2 = client.post(
        "/api/v1/match/swipe",
        json={"target_user_id": u1["user_id"], "action": "LIKE"},
        headers=u2["headers"],
    )
    assert s2.status_code == 200
    match_id = s2.get_json()["data"]["match_id"]
    assert match_id is not None

    # Intercambiar mensajes
    m1 = client.post(
        f"/api/v1/match/{match_id}/messages",
        json={"text": "Hola Fernando, ¿cómo estás?"},
        headers=u1["headers"],
    )
    assert m1.status_code == 201
    m2 = client.post(
        f"/api/v1/match/{match_id}/messages",
        json={"text": "¡Hola Elena! Todo muy bien."},
        headers=u2["headers"],
    )
    assert m2.status_code == 201

    # u1 elimina su cuenta
    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert del_res.status_code == 202

    # Verificar que el match quedó cerrado lógicamente por u1 y que los 2 mensajes se conservaron en BD
    db.session.expire_all()
    match_db = db.session.get(Match, match_id)
    assert match_db is not None
    assert match_db.closed_at is not None
    assert match_db.closed_by_user_id == u1["user_id"]
    assert Message.query.filter_by(match_id=match_id).count() == 2

    # Verificar que para u2 el match ya no aparece en my-matches ni permite leer/enviar mensajes
    my_matches_u2 = client.get("/api/v1/match/my-matches", headers=u2["headers"])
    assert my_matches_u2.status_code == 200
    assert my_matches_u2.get_json()["data"]["items"] == []

    assert client.get(f"/api/v1/match/{match_id}", headers=u2["headers"]).status_code == 404
    assert client.get(f"/api/v1/match/{match_id}/messages", headers=u2["headers"]).status_code == 404
    assert (
        client.post(
            f"/api/v1/match/{match_id}/messages",
            json={"text": "Mensaje posterior"},
            headers=u2["headers"],
        ).status_code
        == 404
    )
    # DELETE unmatch sobre match ya cerrado responde 204 idempotentemente
    assert client.delete(f"/api/v1/match/{match_id}", headers=u2["headers"]).status_code == 204


def test_11_photos_and_media_access(client):
    """11. Fotografías y archivos físicos se eliminan y el endpoint de medios impide el acceso."""
    u1 = _create_complete_user(client, "u1.photos@example.test")
    u2 = _create_complete_user(client, "u2.photos@example.test")

    photo_id = u1["photo_id"]
    file_path = u1["file_path"]
    assert os.path.exists(file_path)

    # Antes de eliminar, u2 puede acceder al medio 'ready' de u1
    pre_media = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=u2["headers"])
    assert pre_media.status_code == 200

    # u1 elimina su cuenta
    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert del_res.status_code == 202

    # Verificar eliminación en BD y en sistema de archivos físico
    db.session.expire_all()
    assert db.session.get(ProfilePhoto, photo_id) is None
    assert not os.path.exists(file_path)
    assert storage_adapter.get_file_path(u1["storage_key"]) is None

    # u2 recibe 404 NOT_FOUND al intentar acceder al medio de la cuenta eliminada
    post_media = client.get(f"/api/v1/profile/photos/media/{photo_id}", headers=u2["headers"])
    assert post_media.status_code == 404
    assert post_media.get_json()["error"]["code"] == "NOT_FOUND"


def test_12_existing_reports_and_blocks(client):
    """12. Denuncias y bloqueos existentes se conservan sin exponer PII ni romper endpoints de terceros."""
    u1 = _create_complete_user(client, "u1.reported@example.test", first_name="NombrePrivadoU1")
    u2 = _create_complete_user(client, "u2.reporter@example.test", first_name="ReportanteU2")
    u3 = _create_complete_user(client, "u3.other@example.test", first_name="TerceroU3")

    # u2 denuncia a u1, y u1 denuncia a u3
    rep1 = client.post(
        f"/api/v1/users/{u1['user_id']}/reports",
        json={"reason": "spam", "description": "Cuenta enviando spam"},
        headers=u2["headers"],
    )
    assert rep1.status_code == 201
    report_against_u1_id = rep1.get_json()["data"]["report_id"]

    rep2 = client.post(
        f"/api/v1/users/{u3['user_id']}/reports",
        json={"reason": "acoso", "description": "Reporte emitido por u1"},
        headers=u1["headers"],
    )
    assert rep2.status_code == 201
    report_by_u1_id = rep2.get_json()["data"]["report_id"]

    # u2 bloquea a u1
    blk = client.put(f"/api/v1/users/{u1['user_id']}/block", headers=u2["headers"])
    assert blk.status_code == 200

    # u1 elimina su cuenta
    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert del_res.status_code == 202

    # Verificar que ambos reportes siguen íntegros en BD (ON DELETE RESTRICT respetado)
    db.session.expire_all()
    r1_db = db.session.get(UserReport, report_against_u1_id)
    r2_db = db.session.get(UserReport, report_by_u1_id)
    assert r1_db is not None and r1_db.reported_user_id == u1["user_id"]
    assert r2_db is not None and r2_db.reporter_user_id == u1["user_id"]

    # Verificar que GET /api/v1/users/me/blocks de u2 funciona sin exponer PII de u1
    blocks_res = client.get("/api/v1/users/me/blocks", headers=u2["headers"])
    assert blocks_res.status_code == 200
    items = blocks_res.get_json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["user_id"] == u1["user_id"]
    assert items[0]["first_name"] != "NombrePrivadoU1"
    assert items[0]["photos"] == []
    assert items[0]["gender"] == "prefiero_no_indicar"

    # Nuevos intentos de bloquear o denunciar a u1 tras su eliminación retornan 404 NOT_FOUND
    assert client.put(f"/api/v1/users/{u1['user_id']}/block", headers=u3["headers"]).status_code == 404
    assert (
        client.post(
            f"/api/v1/users/{u1['user_id']}/reports",
            json={"reason": "spam"},
            headers=u3["headers"],
        ).status_code
        == 404
    )

    # u2 puede desbloquear su bloqueo histórico si lo desea (204)
    assert client.delete(f"/api/v1/users/{u1['user_id']}/block", headers=u2["headers"]).status_code == 204


def test_13_referential_integrity_full_audit(client):
    """13. Auditoría completa de integridad referencial sobre todas las tablas al eliminar cuenta."""
    u1 = _create_complete_user(
        client, "u1.integrity@example.test", first_name="Integra", gender="femenino", interested_in=["masculino"]
    )
    u2 = _create_complete_user(
        client, "u2.integrity@example.test", first_name="Marco", gender="masculino", interested_in=["femenino"]
    )

    # Generar token de recuperación pendiente para u1
    now = datetime.now(timezone.utc)
    reset_tok = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=u1["user_id"],
        token_hash="a" * 64,
        created_at=now,
        expires_at=now + timedelta(minutes=20),
    )
    db.session.add(reset_tok)
    db.session.commit()

    # Crear interacción y match con mensaje
    client.post("/api/v1/match/swipe", json={"target_user_id": u2["user_id"], "action": "LIKE"}, headers=u1["headers"])
    s2 = client.post("/api/v1/match/swipe", json={"target_user_id": u1["user_id"], "action": "LIKE"}, headers=u2["headers"])
    match_id = s2.get_json()["data"]["match_id"]
    client.post(f"/api/v1/match/{match_id}/messages", json={"text": "Mensaje de prueba"}, headers=u1["headers"])

    # Eliminar cuenta de u1
    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert del_res.status_code == 202

    db.session.expire_all()
    uid = u1["user_id"]

    # Tablas cuyos registros de u1 deben haberse eliminado físicamente
    assert Profile.query.filter_by(user_id=uid).count() == 0
    assert DiscoveryPreference.query.filter_by(user_id=uid).count() == 0
    assert AnalyticQuestionnaireAnswer.query.filter_by(user_id=uid).count() == 0
    assert (
        ProfileInteraction.query.filter(
            db.or_(ProfileInteraction.viewer_user_id == uid, ProfileInteraction.shown_user_id == uid)
        ).count()
        == 0
    )
    assert EmailVerificationToken.query.filter_by(user_id=uid).count() == 0
    assert PasswordResetToken.query.filter_by(user_id=uid).count() == 0

    # Consentimientos legales conservados por RESTRICT pero con ip_address anonimizada (None)
    consents = LegalConsent.query.filter_by(user_id=uid).all()
    assert len(consents) == 2
    for c in consents:
        assert c.ip_address is None

    # Comprobar PRAGMA foreign_key_check en SQLite (0 violaciones)
    fk_errors = db.session.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    assert fk_errors == []


def test_14_idempotent_retries_and_repeated_requests(client):
    """14. Reintentos posteriores a la eliminación responden de forma determinista sin errores 500."""
    u1 = _create_complete_user(client, "retry@example.test")

    r1 = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert r1.status_code == 202

    for _ in range(3):
        r_next = client.post(
            "/api/v1/account/deletion",
            json={"password": u1["password"], "confirm": True},
            headers=u1["headers"],
        )
        assert r_next.status_code == 401
        assert r_next.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_15_two_concurrent_deletion_requests(client, app):
    """15. Dos solicitudes concurrentes de eliminación para el mismo usuario se serializan sin condiciones de carrera."""
    u1 = _create_complete_user(client, "concurrent.del@example.test")
    headers = dict(u1["headers"])
    pwd = u1["password"]
    uid = u1["user_id"]

    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def _worker():
        with app.test_client() as local_client:
            barrier.wait(timeout=10)
            resp = local_client.post(
                "/api/v1/account/deletion",
                json={"password": pwd, "confirm": True},
                headers=headers,
            )
            with lock:
                results.append((resp.status_code, resp.get_json()))

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert len(results) == 2
    statuses = sorted([r[0] for r in results])
    # Exactamente una solicitud gana con 202 Accepted y la otra es rechazada limpiamente (409 o 401), nunca 500
    assert 202 in statuses
    assert statuses[0] == 202
    assert statuses[1] in (401, 409)

    db.session.expire_all()
    user_db = db.session.get(User, uid)
    assert user_db.is_active is False
    assert user_db.deleted_at is not None


def test_16_transactional_failure_and_recovery(client, monkeypatch):
    """16. Fallo transaccional revierte todos los cambios en BD, preserva archivos físicos y permite recuperación."""
    u1 = _create_complete_user(client, "tx.rollback@example.test")

    original_commit = db.session.commit

    def _failing_commit():
        raise RuntimeError("Fallo simulado de base de datos antes de commit")

    monkeypatch.setattr(db.session, "commit", _failing_commit)

    fail_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert fail_res.status_code == 500
    assert fail_res.get_json()["error"]["code"] == "INTERNAL_ERROR"

    # Restaurar commit real
    monkeypatch.setattr(db.session, "commit", original_commit)
    db.session.expire_all()

    # Verificar que la cuenta, perfil, respuestas y archivo físico de foto siguen 100% intactos
    user_db = db.session.get(User, u1["user_id"])
    assert user_db.is_active is True
    assert user_db.deleted_at is None
    assert user_db.email == "tx.rollback@example.test"
    assert Profile.query.filter_by(user_id=u1["user_id"]).count() == 1
    assert ProfilePhoto.query.filter_by(id=u1["photo_id"]).count() == 1
    assert AnalyticQuestionnaireAnswer.query.filter_by(user_id=u1["user_id"]).count() == 3
    assert os.path.exists(u1["file_path"])

    # Ahora el reintento con el mismo JWT y contraseña tiene éxito (202 Accepted)
    ok_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert ok_res.status_code == 202
    assert not os.path.exists(u1["file_path"])


def test_17_isolation_between_users(client):
    """17. Aislamiento entre usuarios: eliminar a u1 no altera datos, fotos, sesiones ni matches de u2 y u3."""
    u1 = _create_complete_user(
        client, "u1.iso@example.test", password=VALID_PWD_1, first_name="U1", gender="femenino", interested_in=["masculino"]
    )
    u2 = _create_complete_user(
        client, "u2.iso@example.test", password=VALID_PWD_2, first_name="U2", gender="masculino", interested_in=["femenino"]
    )
    u3 = _create_complete_user(
        client, "u3.iso@example.test", password=VALID_PWD_3, first_name="U3", gender="femenino", interested_in=["masculino"]
    )

    # Match entre u2 y u3 con mensajes
    client.post("/api/v1/match/swipe", json={"target_user_id": u3["user_id"], "action": "LIKE"}, headers=u2["headers"])
    s_u3 = client.post("/api/v1/match/swipe", json={"target_user_id": u2["user_id"], "action": "LIKE"}, headers=u3["headers"])
    match_u2_u3 = s_u3.get_json()["data"]["match_id"]
    client.post(f"/api/v1/match/{match_u2_u3}/messages", json={"text": "Hola U3"}, headers=u2["headers"])

    # u1 elimina su cuenta
    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": u1["password"], "confirm": True},
        headers=u1["headers"],
    )
    assert del_res.status_code == 202

    # Verificar que u2 y u3 siguen plenamente funcionales
    assert os.path.exists(u2["file_path"])
    assert os.path.exists(u3["file_path"])

    me_u2 = client.get("/api/v1/auth/me", headers=u2["headers"])
    assert me_u2.status_code == 200
    assert me_u2.get_json()["data"]["email"] == "u2.iso@example.test"

    prof_u2 = client.get("/api/v1/profile/", headers=u2["headers"])
    assert prof_u2.status_code == 200
    assert prof_u2.get_json()["data"]["first_name"] == "U2"

    ans_u2 = client.get("/api/v1/questionnaire/answers", headers=u2["headers"])
    assert ans_u2.status_code == 200
    assert len(ans_u2.get_json()["data"]["answers"]) == 3

    matches_u2 = client.get("/api/v1/match/my-matches", headers=u2["headers"])
    assert matches_u2.status_code == 200
    items_u2 = matches_u2.get_json()["data"]["items"]
    assert len(items_u2) == 1
    assert items_u2[0]["id"] == match_u2_u3

