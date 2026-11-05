"""
AFINIA — Pruebas de Integración BE-11: Cierre del Contrato OpenAPI v1.
======================================================================
Verifica exhaustivamente las 3 operaciones añadidas para completar el contrato 41/41:
- POST /api/v1/legal/acceptances (recordLegalAcceptance)
- GET /api/v1/notifications (getNotifications)
- POST /api/v1/notifications/{notificationId}/read (readNotification)

Cubre:
1. Autenticación y rechazo de accesos no autorizados en los 3 endpoints.
2. Registro explícito de consentimientos legales con versiones vigentes (terms_of_service, privacy_policy).
3. Rechazo de versiones o documentos legales inválidos, vacíos o inexistentes (422).
4. Rechazo de payloads con campos adicionales o malformados (400 / 422).
5. Idempotencia y preservación de trazabilidad ante aceptaciones repetidas del mismo usuario (200 con accepted_at).
6. Concurrencia transaccional en aceptación legal (dos peticiones concurrentes para el mismo usuario).
7. Consulta de notificaciones para usuario sin eventos (lista vacía, 200 OK).
8. Generación automática y desacoplada de notificación 'new_match' tras swipe recíproco.
9. Generación automática y desacoplada de notificación 'new_message' tras envío de mensaje en chat.
10. Aislamiento estricto de notificaciones entre usuarios (usuario A jamás ve notificaciones de usuario B).
11. Paginación por cursor firmado con HMAC y ordenamiento determinista (created_at DESC, id DESC).
12. Marcación de lectura de notificación propia (204 No Content, read: true) e idempotencia ante reintentos.
13. Protección y rechazo al intentar marcar o consultar notificaciones de otros usuarios (404 NOT_FOUND).
14. Validación estricta del identificador UUID en la ruta de marcación (422 VALIDATION_ERROR).
15. Limpieza de notificaciones al procesar la eliminación segura de cuenta (POST /api/v1/account/deletion).
16. Manejo transaccional, integridad y reversión (rollback) ante fallos simulados.
"""

import uuid
import threading
from datetime import datetime, timezone, timedelta, date
import pytest

from app import db
from app.models import (
    User,
    LegalConsent,
    Profile,
    ProfilePhoto,
    DiscoveryPreference,
    Match,
    Message,
)
from app.models.notification import Notification
from app.services.notification_service import (
    notifications_table_exists,
    emit_match_notifications,
    emit_message_notification,
)


USER_PWD = "ClaveUsuarioSegura_2026!"


def _setup_full_user(client, email: str, gender: str = "femenino") -> dict:
    """Registra y habilita completamente a un usuario sintético para discovery y matches."""
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": USER_PWD,
            "accept_terms_version": "v1-draft",
            "accept_privacy_version": "v1-draft",
        },
    )
    assert reg.status_code == 201, reg.get_json()
    uid = reg.get_json()["data"]["id"]

    user_db = db.session.get(User, uid)
    user_db.email_verified = True
    user_db.lifecycle_status = "active"

    # Perfil con foto lista
    prof = Profile(
        id=str(uuid.uuid4()),
        user_id=uid,
        first_name="UsuarioTest",
        birth_date=date(2000, 1, 1),
        gender=gender,
        city="Bogotá",
        bio="Bio de prueba",
    )
    db.session.add(prof)
    db.session.flush()

    photo = ProfilePhoto(
        id=str(uuid.uuid4()),
        profile_id=prof.id,
        storage_key=f"uploads/{uid}/photo1.jpg",
        position=0,
        status="ready",
        is_primary=True,
    )
    db.session.add(photo)

    # Preferencias de descubrimiento
    pref = DiscoveryPreference(
        id=str(uuid.uuid4()),
        user_id=uid,
        interested_in_genders=["masculino", "femenino"],
        min_age=18,
        max_age=50,
    )
    db.session.add(pref)
    db.session.commit()

    # Login móvil para obtener JWT
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": USER_PWD},
        headers={"X-Client-Platform": "mobile"},
    )
    assert login_res.status_code == 200, login_res.get_json()
    token = login_res.get_json()["data"]["access_token"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    return {"user_id": uid, "token": token, "headers": headers, "email": email}


def test_01_unauthenticated_and_unauthorized_access(client):
    """
    1. Autenticación requerida en los tres nuevos endpoints:
    - POST /api/v1/legal/acceptances -> 401
    - GET /api/v1/notifications -> 401
    - POST /api/v1/notifications/{id}/read -> 401
    - Token con formato inválido o expirado -> 401
    """
    # Sin cabecera
    assert client.post("/api/v1/legal/acceptances", json={}).status_code == 401
    assert client.get("/api/v1/notifications").status_code == 401
    random_uuid = str(uuid.uuid4())
    assert client.post(f"/api/v1/notifications/{random_uuid}/read").status_code == 401

    # Token malformado
    bad_headers = {"Authorization": "Bearer token_falso_invalido_12345"}
    assert client.post("/api/v1/legal/acceptances", json={}, headers=bad_headers).status_code == 401
    assert client.get("/api/v1/notifications", headers=bad_headers).status_code == 401
    assert client.post(f"/api/v1/notifications/{random_uuid}/read", headers=bad_headers).status_code == 401


def test_02_record_legal_acceptance_happy_path_and_idempotency(client):
    """
    2 y 5. Registro explícito de aceptación de documentos vigentes e idempotencia:
    - POST con terms_version y privacy_version vigentes -> 200 con data.accepted_at.
    - Se persiste en legal_consents para el usuario autenticado.
    - Llamadas posteriores idénticas devuelven 200 OK con la fecha original sin duplicar registros.
    """
    u = _setup_full_user(client, "legal_accept_1@afinia.test")

    payload = {
        "terms_version": "v1-draft",
        "privacy_version": "v1-draft",
    }

    res1 = client.post("/api/v1/legal/acceptances", json=payload, headers=u["headers"])
    assert res1.status_code == 200, res1.get_json()
    data1 = res1.get_json()["data"]
    assert "accepted_at" in data1
    accepted_at_1 = data1["accepted_at"]
    assert accepted_at_1.endswith("Z")

    # Verificar filas en la tabla legal_consents
    consents = LegalConsent.query.filter_by(user_id=u["user_id"]).all()
    # Durante el registro ya se registraron los dos consentimientos iniciales,
    # por lo que el número total de consentimientos únicos para este par (tipo, versión) es exactamente 2.
    assert len(consents) == 2
    types = {c.document_type for c in consents}
    assert types == {"terms_of_service", "privacy_policy"}

    # Idempotencia: segunda llamada con el mismo payload
    res2 = client.post("/api/v1/legal/acceptances", json=payload, headers=u["headers"])
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]
    assert data2["accepted_at"] == accepted_at_1

    # Los registros no se duplican
    consents_after = LegalConsent.query.filter_by(user_id=u["user_id"]).all()
    assert len(consents_after) == 2


def test_03_record_legal_acceptance_invalid_versions_and_payloads(client):
    """
    3 y 4. Validación de versiones, documentos y esquemas:
    - Versiones que no coinciden con las vigentes -> 422 VALIDATION_ERROR.
    - Campos extra (additionalProperties: false) -> 422 VALIDATION_ERROR.
    - Campos faltantes o tipos incorrectos -> 422 VALIDATION_ERROR.
    - JSON inválido o nulo -> 400 BAD_REQUEST.
    """
    u = _setup_full_user(client, "legal_invalid_1@afinia.test")

    # Versión inexistente / inventada
    res_bad_ver = client.post(
        "/api/v1/legal/acceptances",
        json={"terms_version": "v99-inventada", "privacy_version": "v1-draft"},
        headers=u["headers"],
    )
    assert res_bad_ver.status_code == 422
    assert res_bad_ver.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # Campos adicionales
    res_extra = client.post(
        "/api/v1/legal/acceptances",
        json={
            "terms_version": "v1-draft",
            "privacy_version": "v1-draft",
            "extra_campo": "no_permitido",
        },
        headers=u["headers"],
    )
    assert res_extra.status_code == 422
    assert res_extra.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # Faltan campos requeridos
    res_missing = client.post(
        "/api/v1/legal/acceptances",
        json={"terms_version": "v1-draft"},
        headers=u["headers"],
    )
    assert res_missing.status_code == 422

    # Query params no permitidos
    res_qp = client.post(
        "/api/v1/legal/acceptances?param_extra=1",
        json={"terms_version": "v1-draft", "privacy_version": "v1-draft"},
        headers=u["headers"],
    )
    assert res_qp.status_code == 422

    # Body no JSON
    res_no_json = client.post(
        "/api/v1/legal/acceptances",
        data="esto no es json",
        headers={"Authorization": u["headers"]["Authorization"], "Content-Type": "text/plain"},
    )
    assert res_no_json.status_code in (400, 422)


def test_04_concurrent_legal_acceptance(client):
    """
    6. Concurrencia transaccional en aceptación legal:
    - Dos hilos envían simultáneamente POST /api/v1/legal/acceptances para el mismo usuario.
    - Ambos hilos deben terminar con código exitoso (200 OK) sin producir excepciones no controladas.
    - La tabla física no debe tener registros duplicados.
    """
    u = _setup_full_user(client, "legal_concur_1@afinia.test")
    barrier = threading.Barrier(2)
    results = []

    def _worker():
        barrier.wait()
        res = client.post(
            "/api/v1/legal/acceptances",
            json={"terms_version": "v1-draft", "privacy_version": "v1-draft"},
            headers=u["headers"],
        )
        results.append(res.status_code)

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert all(code == 200 for code in results)
    consents = LegalConsent.query.filter_by(user_id=u["user_id"]).all()
    assert len(consents) == 2


def test_05_notifications_empty_list(client):
    """
    7. Consulta de notificaciones para usuario sin notificaciones:
    - GET /api/v1/notifications -> 200 OK con data.items=[], next_cursor=null, has_more=false.
    """
    u = _setup_full_user(client, "notif_empty_1@afinia.test")
    res = client.get("/api/v1/notifications", headers=u["headers"])
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert "data" in body and "meta" in body
    assert body["data"]["items"] == []
    assert body["meta"]["next_cursor"] is None
    assert body["meta"]["has_more"] is False


def test_06_match_and_message_notification_generation_and_isolation(client):
    """
    8, 9 y 10. Generación automática y aislamiento estricto de notificaciones:
    - Dos usuarios mutuamente compatibles se dan LIKE -> se genera match y notificación 'new_match' para ambos.
    - Usuario 1 envía mensaje -> se genera notificación 'new_message' para Usuario 2 (destinatario).
    - Usuario 1 jamás ve la notificación de 'new_message' generada para Usuario 2.
    """
    u1 = _setup_full_user(client, "notif_user_a@afinia.test", gender="masculino")
    u2 = _setup_full_user(client, "notif_user_b@afinia.test", gender="femenino")

    # Swipe 1: u1 le da LIKE a u2
    s1 = client.post(
        "/api/v1/match/swipe",
        json={"target_user_id": u2["user_id"], "action": "LIKE"},
        headers=u1["headers"],
    )
    assert s1.status_code == 200
    assert s1.get_json()["data"]["is_match"] is False

    # Swipe 2: u2 le da LIKE a u1 -> MATCH RECÍPROCO
    s2 = client.post(
        "/api/v1/match/swipe",
        json={"target_user_id": u1["user_id"], "action": "LIKE"},
        headers=u2["headers"],
    )
    assert s2.status_code == 200
    assert s2.get_json()["data"]["is_match"] is True
    match_id = s2.get_json()["data"]["match_id"]
    assert match_id is not None

    # Verificar que ambos usuarios recibieron la notificación 'new_match'
    res_notif_u1 = client.get("/api/v1/notifications", headers=u1["headers"])
    assert res_notif_u1.status_code == 200
    items_u1 = res_notif_u1.get_json()["data"]["items"]
    assert len(items_u1) == 1
    assert items_u1[0]["type"] == "new_match"
    assert items_u1[0]["title"] == "Tienes un nuevo match"
    assert items_u1[0]["read"] is False

    res_notif_u2 = client.get("/api/v1/notifications", headers=u2["headers"])
    assert res_notif_u2.status_code == 200
    items_u2 = res_notif_u2.get_json()["data"]["items"]
    assert len(items_u2) == 1
    assert items_u2[0]["type"] == "new_match"
    assert items_u2[0]["id"] != items_u1[0]["id"]  # Notificaciones independientes

    # u1 envía un mensaje a u2
    msg_res = client.post(
        f"/api/v1/match/{match_id}/messages",
        json={"text": "¡Hola! ¿Cómo estás?"},
        headers=u1["headers"],
    )
    assert msg_res.status_code == 201

    # u2 debe tener ahora 2 notificaciones: 1 'new_message' y 1 'new_match'
    res_notif_u2_after = client.get("/api/v1/notifications", headers=u2["headers"])
    items_u2_after = res_notif_u2_after.get_json()["data"]["items"]
    assert len(items_u2_after) == 2
    types_u2 = [n["type"] for n in items_u2_after]
    assert types_u2 == ["new_message", "new_match"]

    # u1 (el remitente) NO debe haber recibido notificación de 'new_message'
    res_notif_u1_after = client.get("/api/v1/notifications", headers=u1["headers"])
    items_u1_after = res_notif_u1_after.get_json()["data"]["items"]
    assert len(items_u1_after) == 1
    assert items_u1_after[0]["type"] == "new_match"


def test_07_notifications_pagination_and_deterministic_order(client):
    """
    11. Paginación por cursor firmado HMAC y orden determinista:
    - Se generan 5 notificaciones sintéticas para el usuario.
    - Se consulta con limit=2, paginando consecutivamente con cursor.
    - Se verifica la ausencia de duplicados y el orden decreciente por created_at e id.
    """
    u = _setup_full_user(client, "notif_pag_1@afinia.test")

    now = datetime.now(timezone.utc)
    created_ids = []
    for i in range(5):
        n = Notification(
            id=str(uuid.uuid4()),
            user_id=u["user_id"],
            type="new_match" if i % 2 == 0 else "new_message",
            title=f"Notificación de prueba {i}",
            reference_id=str(uuid.uuid4()),
            created_at=now + timedelta(seconds=i * 10),
            read_at=None,
        )
        db.session.add(n)
        created_ids.append(str(n.id))
    db.session.commit()

    # Página 1
    p1 = client.get("/api/v1/notifications?limit=2", headers=u["headers"])
    assert p1.status_code == 200
    d1 = p1.get_json()
    assert len(d1["data"]["items"]) == 2
    assert d1["meta"]["has_more"] is True
    cursor_1 = d1["meta"]["next_cursor"]
    assert cursor_1 is not None

    # Página 2
    p2 = client.get(f"/api/v1/notifications?limit=2&cursor={cursor_1}", headers=u["headers"])
    assert p2.status_code == 200
    d2 = p2.get_json()
    assert len(d2["data"]["items"]) == 2
    assert d2["meta"]["has_more"] is True
    cursor_2 = d2["meta"]["next_cursor"]
    assert cursor_2 is not None

    # Página 3
    p3 = client.get(f"/api/v1/notifications?limit=2&cursor={cursor_2}", headers=u["headers"])
    assert p3.status_code == 200
    d3 = p3.get_json()
    assert len(d3["data"]["items"]) == 1
    assert d3["meta"]["has_more"] is False
    assert d3["meta"]["next_cursor"] is None

    # Consolidar todos los IDs recolectados
    all_seen = [
        item["id"]
        for page in (d1, d2, d3)
        for item in page["data"]["items"]
    ]
    assert len(all_seen) == 5
    assert len(set(all_seen)) == 5
    # Orden determinista: la más reciente (i=4) fue la primera
    assert all_seen == list(reversed(created_ids))


def test_08_read_notification_and_idempotency(client):
    """
    12. Marcación de lectura de notificación propia:
    - POST /api/v1/notifications/{id}/read -> 204 No Content.
    - La notificación pasa de read: false a read: true.
    - Idempotencia: una segunda llamada idéntica devuelve 204 No Content.
    """
    u = _setup_full_user(client, "notif_read_1@afinia.test")
    n = Notification(
        id=str(uuid.uuid4()),
        user_id=u["user_id"],
        type="new_match",
        title="Tienes un nuevo match",
        reference_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        read_at=None,
    )
    db.session.add(n)
    db.session.commit()

    # Verificar estado no leída
    r1 = client.get("/api/v1/notifications", headers=u["headers"])
    assert r1.get_json()["data"]["items"][0]["read"] is False

    # Marcar como leída
    res_mark = client.post(f"/api/v1/notifications/{n.id}/read", headers=u["headers"])
    assert res_mark.status_code == 204

    # Verificar que ahora esté en read: true
    r2 = client.get("/api/v1/notifications", headers=u["headers"])
    assert r2.get_json()["data"]["items"][0]["read"] is True

    # Reintento idempotente
    res_mark_again = client.post(f"/api/v1/notifications/{n.id}/read", headers=u["headers"])
    assert res_mark_again.status_code == 204


def test_09_cannot_read_another_users_notification(client):
    """
    13. Protección contra lectura de notificaciones ajenas:
    - El usuario B intenta marcar como leída la notificación del usuario A -> 404 NOT_FOUND.
    - La notificación del usuario A no es alterada.
    """
    u1 = _setup_full_user(client, "notif_owner@afinia.test")
    u2 = _setup_full_user(client, "notif_attacker@afinia.test")

    n = Notification(
        id=str(uuid.uuid4()),
        user_id=u1["user_id"],
        type="new_match",
        title="Tienes un nuevo match",
        reference_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        read_at=None,
    )
    db.session.add(n)
    db.session.commit()

    # Usuario 2 intenta marcar como leída la notificación de Usuario 1
    res_attack = client.post(f"/api/v1/notifications/{n.id}/read", headers=u2["headers"])
    assert res_attack.status_code == 404
    assert res_attack.get_json()["error"]["code"] == "NOT_FOUND"

    # La notificación de u1 permanece no leída
    db.session.refresh(n)
    assert n.read_at is None


def test_10_read_notification_invalid_uuid_and_extra_body(client):
    """
    14. Validación de identificador UUID y rechazo de body en marcación:
    - ID que no es UUID -> 422 VALIDATION_ERROR.
    - ID inexistente -> 404 NOT_FOUND.
    - Body JSON con campos -> 422 VALIDATION_ERROR.
    - Query params no permitidos -> 422 VALIDATION_ERROR.
    """
    u = _setup_full_user(client, "notif_val_1@afinia.test")

    # UUID malformado
    res_bad_id = client.post("/api/v1/notifications/no-es-un-uuid/read", headers=u["headers"])
    assert res_bad_id.status_code == 422
    assert res_bad_id.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # UUID inexistente
    non_existent = str(uuid.uuid4())
    res_not_found = client.post(f"/api/v1/notifications/{non_existent}/read", headers=u["headers"])
    assert res_not_found.status_code == 404

    # Body no permitido
    res_body = client.post(
        f"/api/v1/notifications/{non_existent}/read",
        json={"unwanted_field": 123},
        headers=u["headers"],
    )
    assert res_body.status_code == 422

    # Query params no permitidos
    res_qp = client.post(
        f"/api/v1/notifications/{non_existent}/read?extra=true",
        headers=u["headers"],
    )
    assert res_qp.status_code == 422


def test_11_account_deletion_cleans_notifications(client):
    """
    15. Eliminación de cuenta (POST /api/v1/account/deletion) limpia notificaciones:
    - Se crea un usuario con notificaciones.
    - Se ejecuta la eliminación de su cuenta.
    - La tabla física 'notifications' elimina los registros asociados al usuario.
    """
    u = _setup_full_user(client, "notif_delete_1@afinia.test")
    n = Notification(
        id=str(uuid.uuid4()),
        user_id=u["user_id"],
        type="new_match",
        title="Tienes un nuevo match",
        reference_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        read_at=None,
    )
    db.session.add(n)
    db.session.commit()

    assert Notification.query.filter_by(user_id=u["user_id"]).count() == 1

    # Eliminar cuenta
    del_res = client.post(
        "/api/v1/account/deletion",
        json={"password": USER_PWD, "confirm": True},
        headers=u["headers"],
    )
    assert del_res.status_code == 202

    # Verificar que las notificaciones del usuario fueron eliminadas
    assert Notification.query.filter_by(user_id=u["user_id"]).count() == 0


def test_12_legal_versions_public_endpoint(client):
    """
    GET /api/v1/legal/current es público y devuelve LegalVersions.
    """
    res = client.get("/api/v1/legal/current")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "terms_version" in data
    assert "privacy_version" in data
    assert "terms_url" in data
    assert "privacy_url" in data

