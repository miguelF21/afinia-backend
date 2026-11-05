"""
AFINIA — Pruebas de Integración BE-10: Moderación Administrativa de Denuncias.
==============================================================================
Cubre los 16 escenarios obligatorios especificados para BE-10:
1. Consulta administrativa autenticada.
2. Consulta sin autenticación.
3. Consulta con usuario normal (y verificación de no auto-escalación en registro/perfil/cuestionario).
4. Consulta con usuario suspendido, eliminado, JWT manipulado y JWT previo a cambio de credenciales.
5. Listado vacío.
6. Paginación por cursor, ordenamiento determinista y filtros.
7. Denuncia inexistente y validación de UUID.
8. Resolución válida (dismiss, warn, suspend) sin suspensión automática de la cuenta denunciada.
9. Resolución con payload inválido.
10. Resolución por usuario no autorizado.
11. Dos administradores resolviendo simultáneamente una denuncia.
12. Reintentos y estados previamente resueltos (inmutabilidad de resolución).
13. Denuncias asociadas con cuentas eliminadas.
14. Protección de información personal (exposición mínima contractual).
15. Conservación del historial de denuncias.
16. Integridad SQL y rollback ante fallos.
"""

import uuid
import threading
from datetime import datetime, timezone, timedelta
import jwt
import pytest
import sqlalchemy as sa

from app import db
from app.models import User, UserReport, Profile
from app.utils.security import create_access_token, hash_password


ADMIN_PWD = "ClaveAdminSegura_2026!"
USER_PWD = "ClaveUsuarioSegura_2026!"


def _create_user_with_role(
    client,
    email: str,
    password: str = USER_PWD,
    role: str = "user",
    lifecycle_status: str = "active",
    first_name: str = "Persona",
) -> dict:
    """
    Registra un usuario sintético, configura su rol en base de datos para pruebas QA
    y obtiene su token JWT firmado.
    """
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "accept_terms_version": "v1-draft",
            "accept_privacy_version": "v1-draft",
        },
    )
    assert reg.status_code == 201, reg.get_json()
    uid = reg.get_json()["data"]["id"]

    user_db = db.session.get(User, uid)
    user_db.email_verified = True
    user_db.role = role
    user_db.lifecycle_status = lifecycle_status
    db.session.commit()

    # Si está activo o pending_profile, iniciar sesión para obtener JWT real
    if lifecycle_status not in ("suspended", "deactivated"):
        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            headers={"X-Client-Platform": "mobile"},
        )
        assert login.status_code == 200, login.get_json()
        token = login.get_json()["data"]["access_token"]
    else:
        from flask import current_app
        token = create_access_token(
            user_id=uid,
            email=email,
            role=role,
            secret_key=current_app.config["SECRET_KEY"],
            password_hash=user_db.password_hash,
        )

    headers = {"Authorization": f"Bearer {token}"}

    if lifecycle_status == "active":
        client.post(
            "/api/v1/profile/",
            json={
                "first_name": first_name,
                "birth_date": "1998-04-12",
                "gender": "femenino",
                "city": "Villavicencio",
                "bio": f"Bio privada de {first_name}",
            },
            headers=headers,
        )
        # Asegurar lifecycle_status solicitado tras crear perfil
        u_refresh = db.session.get(User, uid)
        u_refresh.lifecycle_status = lifecycle_status
        db.session.commit()

    return {
        "user_id": uid,
        "email": email,
        "password": password,
        "role": role,
        "access_token": token,
        "headers": headers,
    }


def _file_report(client, reporter_headers: dict, reported_user_id: str, reason: str = "acoso", description: str = "Conducta inapropiada") -> str:
    res = client.post(
        f"/api/v1/users/{reported_user_id}/reports",
        json={"reason": reason, "description": description},
        headers=reporter_headers,
    )
    assert res.status_code == 201, res.get_json()
    return res.get_json()["data"]["report_id"]


def test_01_authenticated_admin_list_reports(client):
    """1. Consulta administrativa autenticada retorna 200 con estructura contractual ModerationReport."""
    admin = _create_user_with_role(client, "admin1@afinia.test", password=ADMIN_PWD, role="admin")
    u1 = _create_user_with_role(client, "rep1@afinia.test", role="user")
    u2 = _create_user_with_role(client, "target1@afinia.test", role="user")

    report_id = _file_report(client, u1["headers"], u2["user_id"], reason="spam", description="Envío masivo")

    res = client.get("/api/v1/admin/reports", headers=admin["headers"])
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert "data" in body and "meta" in body
    assert "items" in body["data"]
    assert set(body["meta"].keys()) == {"next_cursor", "has_more"}
    assert body["meta"]["has_more"] is False
    assert body["meta"]["next_cursor"] is None

    items = body["data"]["items"]
    assert len(items) == 1
    item = items[0]
    assert set(item.keys()) == {"id", "reporter_user_id", "reported_user_id", "reason", "status", "created_at"}
    assert item["id"] == report_id
    assert item["reporter_user_id"] == u1["user_id"]
    assert item["reported_user_id"] == u2["user_id"]
    assert item["reason"] == "spam"
    assert item["status"] == "pending"
    assert item["created_at"].endswith("Z")


def test_02_unauthenticated_access_rejected(client):
    """2. Consulta y resolución sin autenticación retornan 401 UNAUTHORIZED."""
    r_list = client.get("/api/v1/admin/reports")
    assert r_list.status_code == 401
    assert r_list.get_json()["error"]["code"] == "UNAUTHORIZED"

    r_bad_hdr = client.get("/api/v1/admin/reports", headers={"Authorization": "Basic abcdef"})
    assert r_bad_hdr.status_code == 401
    assert r_bad_hdr.get_json()["error"]["code"] == "UNAUTHORIZED"

    fake_id = str(uuid.uuid4())
    r_res = client.post(f"/api/v1/admin/reports/{fake_id}/resolve", json={"action": "dismiss"})
    assert r_res.status_code == 401
    assert r_res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_03_normal_user_and_privilege_escalation_blocked(client):
    """
    3. Usuario normal (role='user') y moderador no-admin (role='moderator') reciben 403 FORBIDDEN.
    Comprueba además que no es posible autoconcederse rol admin en registro, perfil ni cuestionario.
    """
    normal_user = _create_user_with_role(client, "normal@afinia.test", role="user")
    moderator_user = _create_user_with_role(client, "mod@afinia.test", role="moderator")

    for actor in (normal_user, moderator_user):
        res = client.get("/api/v1/admin/reports", headers=actor["headers"])
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    # Intento de autoconcederse 'role': 'admin' en registro -> rechazado (400/422)
    esc_reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "escalate@afinia.test",
            "password": USER_PWD,
            "accept_terms_version": "v1-draft",
            "accept_privacy_version": "v1-draft",
            "role": "admin",
        },
    )
    assert esc_reg.status_code in (400, 422)
    assert User.query.filter_by(email="escalate@afinia.test").count() == 0

    # Intento de inyectar 'role': 'admin' en PUT /api/v1/profile -> rechazado (400/422)
    esc_prof = client.put(
        "/api/v1/profile/",
        json={
            "first_name": "Intento",
            "birth_date": "1995-01-01",
            "gender": "masculino",
            "role": "admin",
        },
        headers=normal_user["headers"],
    )
    assert esc_prof.status_code in (400, 422)

    # Intento de inyectar 'role' en PUT /api/v1/questionnaire/answers nunca altera User.role
    esc_q_invalid = client.put(
        "/api/v1/questionnaire/answers",
        json={
            "version": "draft-1",
            "answers": [{"question_id": "role", "value": "admin"}],
        },
        headers=normal_user["headers"],
    )
    assert esc_q_invalid.status_code == 422

    esc_q_numeric = client.put(
        "/api/v1/questionnaire/answers",
        json={
            "version": "draft-1",
            "answers": [{"question_id": "role", "value": 5}],
            "role": "admin",
        },
        headers=normal_user["headers"],
    )
    assert esc_q_numeric.status_code in (200, 422)

    db.session.expire_all()
    assert db.session.get(User, normal_user["user_id"]).role == "user"
    assert client.get("/api/v1/admin/reports", headers=normal_user["headers"]).status_code == 403


def test_04_suspended_deleted_manipulated_jwt_and_credential_change(client, app):
    """
    4. Seguridad de sesiones y roles:
    - Usuario suspendido (incluso si tenía rol admin): 403 FORBIDDEN.
    - Usuario eliminado: 401 UNAUTHORIZED.
    - JWT manipulado (claim role='admin' falsificado o para usuario normal): rechazado (401 / 403).
    - JWT emitido antes de cambio de credenciales: 401 UNAUTHORIZED.
    """
    # 4a. Administrador suspendido -> 403 FORBIDDEN
    susp_admin = _create_user_with_role(
        client, "susp.admin@afinia.test", password=ADMIN_PWD, role="admin", lifecycle_status="suspended"
    )
    res_susp = client.get("/api/v1/admin/reports", headers=susp_admin["headers"])
    assert res_susp.status_code == 403
    assert res_susp.get_json()["error"]["code"] == "FORBIDDEN"

    # 4b. Administrador eliminado -> 401 UNAUTHORIZED
    del_admin = _create_user_with_role(client, "del.admin@afinia.test", password=ADMIN_PWD, role="admin")
    del_resp = client.post(
        "/api/v1/account/deletion",
        json={"password": ADMIN_PWD, "confirm": True},
        headers=del_admin["headers"],
    )
    assert del_resp.status_code == 202
    res_del = client.get("/api/v1/admin/reports", headers=del_admin["headers"])
    assert res_del.status_code == 401
    assert res_del.get_json()["error"]["code"] == "UNAUTHORIZED"

    # 4c. Usuario normal cuyo JWT fue firmado con claim role='admin' pero en BD tiene role='user' -> 403 FORBIDDEN
    normal_u = _create_user_with_role(client, "spoof@afinia.test", role="user")
    u_db = db.session.get(User, normal_u["user_id"])
    spoofed_jwt = create_access_token(
        user_id=u_db.id,
        email=u_db.email,
        role="admin",  # Claim manipulado que contradice u_db.role == 'user'
        secret_key=app.config["SECRET_KEY"],
        password_hash=u_db.password_hash,
    )
    res_spoof = client.get("/api/v1/admin/reports", headers={"Authorization": f"Bearer {spoofed_jwt}"})
    assert res_spoof.status_code == 403
    assert res_spoof.get_json()["error"]["code"] == "FORBIDDEN"

    # 4d. JWT firmado con clave secreta incorrecta -> 401 UNAUTHORIZED
    bad_sig_jwt = create_access_token(
        user_id=u_db.id,
        email=u_db.email,
        role="admin",
        secret_key="wrong-secret-key-attacker",
        password_hash=u_db.password_hash,
    )
    res_bad_sig = client.get("/api/v1/admin/reports", headers={"Authorization": f"Bearer {bad_sig_jwt}"})
    assert res_bad_sig.status_code == 401
    assert res_bad_sig.get_json()["error"]["code"] == "UNAUTHORIZED"

    # 4e. Administrador activo cuyo password_hash cambia después de emitir el JWT -> 401 UNAUTHORIZED
    active_admin = _create_user_with_role(client, "pwdchange.admin@afinia.test", password=ADMIN_PWD, role="admin")
    old_admin_headers = dict(active_admin["headers"])
    admin_db = db.session.get(User, active_admin["user_id"])
    admin_db.password_hash = hash_password("NuevaClaveAdminRotada_2026!")
    db.session.commit()

    res_old_jwt = client.get("/api/v1/admin/reports", headers=old_admin_headers)
    assert res_old_jwt.status_code == 401
    assert res_old_jwt.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_05_empty_reports_list(client):
    """5. Listado vacío retorna items=[], next_cursor=None, has_more=False."""
    admin = _create_user_with_role(client, "admin.empty@afinia.test", password=ADMIN_PWD, role="admin")
    res = client.get("/api/v1/admin/reports", headers=admin["headers"])
    assert res.status_code == 200
    body = res.get_json()
    assert body["data"]["items"] == []
    assert body["meta"] == {"next_cursor": None, "has_more": False}


def test_06_pagination_deterministic_order_and_filters(client):
    """6. Paginación por cursor, orden determinista (created_at DESC, id DESC), filtros y validación de parámetros."""
    admin = _create_user_with_role(client, "admin.page@afinia.test", password=ADMIN_PWD, role="admin")
    reporter = _create_user_with_role(client, "rep.page@afinia.test", role="user")

    base_time = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    created_ids = []

    reasons = ["acoso", "spam", "suplantacion", "contenido_inapropiado", "otro"]
    for idx in range(5):
        target = _create_user_with_role(client, f"target.page.{idx}@afinia.test", role="user")
        rep = UserReport(
            id=str(uuid.uuid4()),
            reporter_user_id=reporter["user_id"],
            reported_user_id=target["user_id"],
            reason=reasons[idx],
            description=f"Reporte #{idx}",
            status="pending",
            created_at=base_time + timedelta(minutes=idx),
        )
        db.session.add(rep)
        created_ids.append(rep.id)
    db.session.commit()

    # Orden esperado: del más reciente (idx=4) al más antiguo (idx=0)
    expected_order = list(reversed(created_ids))

    # Página 1 (limit=2)
    p1 = client.get("/api/v1/admin/reports?limit=2", headers=admin["headers"])
    assert p1.status_code == 200
    b1 = p1.get_json()
    assert [x["id"] for x in b1["data"]["items"]] == expected_order[0:2]
    assert b1["meta"]["has_more"] is True
    c1 = b1["meta"]["next_cursor"]
    assert c1 is not None

    # Página 2 (limit=2)
    p2 = client.get(f"/api/v1/admin/reports?limit=2&cursor={c1}", headers=admin["headers"])
    assert p2.status_code == 200
    b2 = p2.get_json()
    assert [x["id"] for x in b2["data"]["items"]] == expected_order[2:4]
    assert b2["meta"]["has_more"] is True
    c2 = b2["meta"]["next_cursor"]
    assert c2 is not None

    # Página 3 (limit=2) -> último elemento
    p3 = client.get(f"/api/v1/admin/reports?limit=2&cursor={c2}", headers=admin["headers"])
    assert p3.status_code == 200
    b3 = p3.get_json()
    assert [x["id"] for x in b3["data"]["items"]] == expected_order[4:5]
    assert b3["meta"]["has_more"] is False
    assert b3["meta"]["next_cursor"] is None

    # Filtro por reason=spam
    f_spam = client.get("/api/v1/admin/reports?reason=spam", headers=admin["headers"])
    assert f_spam.status_code == 200
    spam_items = f_spam.get_json()["data"]["items"]
    assert len(spam_items) == 1
    assert spam_items[0]["id"] == created_ids[1]

    # Parámetros inválidos -> 422 VALIDATION_ERROR
    for bad_query in [
        "limit=0",
        "limit=51",
        "limit=abc",
        "cursor=cursor_corrupto_invalido",
        "status=inexistente",
        "reason=motivo_falso",
        "unknown_param=1",
    ]:
        bad_res = client.get(f"/api/v1/admin/reports?{bad_query}", headers=admin["headers"])
        assert bad_res.status_code == 422, f"Query {bad_query} debió fallar con 422"
        assert bad_res.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_07_resolve_nonexistent_and_invalid_uuid_report(client):
    """7. Resolver denuncia inexistente retorna 404 NOT_FOUND y UUID malformado retorna 422 VALIDATION_ERROR."""
    admin = _create_user_with_role(client, "admin.404@afinia.test", password=ADMIN_PWD, role="admin")

    missing_id = str(uuid.uuid4())
    res_404 = client.post(
        f"/api/v1/admin/reports/{missing_id}/resolve",
        json={"action": "dismiss", "notes": "No existe"},
        headers=admin["headers"],
    )
    assert res_404.status_code == 404
    assert res_404.get_json()["error"]["code"] == "NOT_FOUND"

    res_422 = client.post(
        "/api/v1/admin/reports/not-a-valid-uuid/resolve",
        json={"action": "dismiss"},
        headers=admin["headers"],
    )
    assert res_422.status_code == 422
    assert res_422.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_08_valid_resolutions_and_no_automatic_account_suspension(client):
    """
    8. Resolución válida para las tres acciones contractuales (dismiss -> dismissed, warn -> resolved, suspend -> resolved).
    Verifica registro de resolved_by_user_id, resolved_at, resolution_action y resolution_notes,
    y comprueba que NO suspende, bloquea ni elimina automáticamente la cuenta denunciada.
    """
    admin = _create_user_with_role(client, "admin.resolve@afinia.test", password=ADMIN_PWD, role="admin")
    u_rep = _create_user_with_role(client, "rep.resolve@afinia.test", role="user")
    u_target = _create_user_with_role(client, "target.resolve@afinia.test", role="user")

    r_dismiss_id = _file_report(client, u_rep["headers"], u_target["user_id"], reason="spam")
    r_warn_id = _file_report(client, u_rep["headers"], u_target["user_id"], reason="acoso")
    r_suspend_id = _file_report(client, u_rep["headers"], u_target["user_id"], reason="suplantacion")

    # 8a. Acción 'dismiss' -> status 'dismissed'
    res1 = client.post(
        f"/api/v1/admin/reports/{r_dismiss_id}/resolve",
        json={"action": "dismiss", "notes": "Denuncia sin mérito tras revisión."},
        headers=admin["headers"],
    )
    assert res1.status_code == 200
    assert res1.get_json() == {"data": {"status": "dismissed"}}

    # 8b. Acción 'warn' -> status 'resolved'
    res2 = client.post(
        f"/api/v1/admin/reports/{r_warn_id}/resolve",
        json={"action": "warn", "notes": "Advertencia registrada en auditoría."},
        headers=admin["headers"],
    )
    assert res2.status_code == 200
    assert res2.get_json() == {"data": {"status": "resolved"}}

    # 8c. Acción 'suspend' -> status 'resolved'
    res3 = client.post(
        f"/api/v1/admin/reports/{r_suspend_id}/resolve",
        json={"action": "suspend", "notes": "Incumplimiento confirmado."},
        headers=admin["headers"],
    )
    assert res3.status_code == 200
    assert res3.get_json() == {"data": {"status": "resolved"}}

    # Verificar auditoría en BD y que la cuenta denunciada NO fue alterada automáticamente
    db.session.expire_all()
    rep3_db = db.session.get(UserReport, r_suspend_id)
    assert rep3_db.status == "resolved"
    assert rep3_db.resolution_action == "suspend"
    assert rep3_db.resolution_notes == "Incumplimiento confirmado."
    assert rep3_db.resolved_by_user_id == admin["user_id"]
    assert rep3_db.resolved_at is not None

    target_db = db.session.get(User, u_target["user_id"])
    assert target_db.is_active is True
    assert target_db.lifecycle_status == "active"
    assert target_db.deleted_at is None


def test_09_resolve_invalid_payloads_rejected(client):
    """9. Resolución con payload inválido es rechazada con 422 VALIDATION_ERROR sin alterar la denuncia."""
    admin = _create_user_with_role(client, "admin.invalid@afinia.test", password=ADMIN_PWD, role="admin")
    u1 = _create_user_with_role(client, "rep.invalid@afinia.test", role="user")
    u2 = _create_user_with_role(client, "target.invalid@afinia.test", role="user")
    report_id = _file_report(client, u1["headers"], u2["user_id"], reason="acoso")

    invalid_payloads = [
        {},  # Falta action
        {"action": None},
        {"action": "ban_forever"},  #Fuera del enum ('dismiss', 'warn', 'suspend')
        {"action": 123},
        {"action": "dismiss", "notes": "x" * 1001},  # Excede maxLength 1000
        {"action": "dismiss", "notes": ["no-string"]},
        {"action": "dismiss", "extra_field": "no-permitido"},  # additionalProperties: false
        {"action": "dismiss", "resolved_by_user_id": u1["user_id"]},
    ]

    for bad_body in invalid_payloads:
        res = client.post(
            f"/api/v1/admin/reports/{report_id}/resolve",
            json=bad_body,
            headers=admin["headers"],
        )
        assert res.status_code == 422, f"Payload {bad_body} debió retornar 422"
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    db.session.expire_all()
    rep_db = db.session.get(UserReport, report_id)
    assert rep_db.status == "pending"
    assert rep_db.resolved_at is None
    assert rep_db.resolved_by_user_id is None


def test_10_resolve_by_unauthorized_users_rejected(client):
    """10. Resolución por usuario no autorizado (normal, moderador o el propio denunciante/denunciado) retorna 403 FORBIDDEN."""
    u1 = _create_user_with_role(client, "rep.unauth@afinia.test", role="user")
    u2 = _create_user_with_role(client, "target.unauth@afinia.test", role="user")
    mod = _create_user_with_role(client, "mod.unauth@afinia.test", role="moderator")

    report_id = _file_report(client, u1["headers"], u2["user_id"], reason="spam")

    for actor in (u1, u2, mod):
        res = client.post(
            f"/api/v1/admin/reports/{report_id}/resolve",
            json={"action": "dismiss"},
            headers=actor["headers"],
        )
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    db.session.expire_all()
    assert db.session.get(UserReport, report_id).status == "pending"


def test_11_two_admins_resolving_simultaneously(client, app):
    """11. Dos administradores resolviendo simultáneamente la misma denuncia: 1 éxito (200) y 1 conflicto (409)."""
    admin1 = _create_user_with_role(client, "admin.race1@afinia.test", password=ADMIN_PWD, role="admin")
    admin2 = _create_user_with_role(client, "admin.race2@afinia.test", password=ADMIN_PWD, role="admin")
    u1 = _create_user_with_role(client, "rep.race@afinia.test", role="user")
    u2 = _create_user_with_role(client, "target.race@afinia.test", role="user")

    report_id = _file_report(client, u1["headers"], u2["user_id"], reason="acoso")

    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def _worker(headers_dict, action_val, notes_val, admin_id):
        with app.test_client() as local_client:
            barrier.wait(timeout=10)
            resp = local_client.post(
                f"/api/v1/admin/reports/{report_id}/resolve",
                json={"action": action_val, "notes": notes_val},
                headers=headers_dict,
            )
            with lock:
                results.append((resp.status_code, admin_id, action_val, resp.get_json()))

    t1 = threading.Thread(
        target=_worker,
        args=(dict(admin1["headers"]), "dismiss", "Resuelto por Admin 1", admin1["user_id"]),
    )
    t2 = threading.Thread(
        target=_worker,
        args=(dict(admin2["headers"]), "suspend", "Resuelto por Admin 2", admin2["user_id"]),
    )
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert len(results) == 2
    codes = sorted([r[0] for r in results])
    assert codes == [200, 409], f"Se esperaba [200, 409], se obtuvo {results}"

    winner = [r for r in results if r[0] == 200][0]
    winner_admin_id = winner[1]
    winner_action = winner[2]

    db.session.expire_all()
    rep_db = db.session.get(UserReport, report_id)
    assert rep_db.resolved_by_user_id == winner_admin_id
    assert rep_db.resolution_action == winner_action
    assert rep_db.status == ("dismissed" if winner_action == "dismiss" else "resolved")


def test_12_retries_and_already_resolved_states_immutable(client):
    """12. Reintentos sobre denuncias ya resueltas retornan 409 CONFLICT y nunca sobrescriben la resolución previa."""
    admin1 = _create_user_with_role(client, "admin.imm1@afinia.test", password=ADMIN_PWD, role="admin")
    admin2 = _create_user_with_role(client, "admin.imm2@afinia.test", password=ADMIN_PWD, role="admin")
    u1 = _create_user_with_role(client, "rep.imm@afinia.test", role="user")
    u2 = _create_user_with_role(client, "target.imm@afinia.test", role="user")

    report_id = _file_report(client, u1["headers"], u2["user_id"], reason="spam")

    first = client.post(
        f"/api/v1/admin/reports/{report_id}/resolve",
        json={"action": "warn", "notes": "Decisión original"},
        headers=admin1["headers"],
    )
    assert first.status_code == 200
    assert first.get_json()["data"]["status"] == "resolved"

    db.session.expire_all()
    orig_resolved_at = db.session.get(UserReport, report_id).resolved_at

    # Reintento con la misma acción por el mismo admin -> 409 CONFLICT
    retry_same = client.post(
        f"/api/v1/admin/reports/{report_id}/resolve",
        json={"action": "warn", "notes": "Intento de re-escribir"},
        headers=admin1["headers"],
    )
    assert retry_same.status_code == 409
    assert retry_same.get_json()["error"]["code"] == "CONFLICT"

    # Reintento con otra acción por un segundo admin -> 409 CONFLICT
    retry_diff = client.post(
        f"/api/v1/admin/reports/{report_id}/resolve",
        json={"action": "dismiss", "notes": "Intento de revocar"},
        headers=admin2["headers"],
    )
    assert retry_diff.status_code == 409
    assert retry_diff.get_json()["error"]["code"] == "CONFLICT"

    # Comprobar que la resolución original permanece intacta
    db.session.expire_all()
    rep_after = db.session.get(UserReport, report_id)
    assert rep_after.status == "resolved"
    assert rep_after.resolution_action == "warn"
    assert rep_after.resolution_notes == "Decisión original"
    assert rep_after.resolved_by_user_id == admin1["user_id"]
    assert rep_after.resolved_at == orig_resolved_at


def test_13_reports_associated_with_deleted_accounts(client):
    """13. Denuncias donde el denunciante y/o el denunciado eliminaron su cuenta se listan y resuelven de forma segura."""
    admin = _create_user_with_role(client, "admin.delacc@afinia.test", password=ADMIN_PWD, role="admin")
    u_reporter = _create_user_with_role(client, "rep.delacc@afinia.test", password=USER_PWD, role="user")
    u_reported = _create_user_with_role(client, "target.delacc@afinia.test", password=USER_PWD, role="user")

    report_id = _file_report(client, u_reporter["headers"], u_reported["user_id"], reason="acoso")

    # Tanto el denunciante como el denunciado eliminan su cuenta (BE-09)
    assert (
        client.post(
            "/api/v1/account/deletion",
            json={"password": USER_PWD, "confirm": True},
            headers=u_reporter["headers"],
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/api/v1/account/deletion",
            json={"password": USER_PWD, "confirm": True},
            headers=u_reported["headers"],
        ).status_code
        == 202
    )

    # El administrador puede listar la denuncia sin error y sin exponer emails anonimizados
    list_res = client.get("/api/v1/admin/reports", headers=admin["headers"])
    assert list_res.status_code == 200
    items = list_res.get_json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == report_id
    assert items[0]["reporter_user_id"] == u_reporter["user_id"]
    assert items[0]["reported_user_id"] == u_reported["user_id"]

    # El administrador puede resolver la denuncia sobre las cuentas ya eliminadas
    res_resolve = client.post(
        f"/api/v1/admin/reports/{report_id}/resolve",
        json={"action": "suspend", "notes": "Cuentas ya habían sido eliminadas, se cierra caso."},
        headers=admin["headers"],
    )
    assert res_resolve.status_code == 200
    assert res_resolve.get_json()["data"]["status"] == "resolved"


def test_14_personal_information_protection_minimal_exposure(client):
    """14. Protección de información personal: GET /api/v1/admin/reports expone solo los campos de ModerationReport."""
    admin = _create_user_with_role(client, "admin.pii@afinia.test", password=ADMIN_PWD, role="admin")
    u1 = _create_user_with_role(client, "secret.email.1@afinia.test", role="user", first_name="NombreSecretoUno")
    u2 = _create_user_with_role(client, "secret.email.2@afinia.test", role="user", first_name="NombreSecretoDos")

    _file_report(client, u1["headers"], u2["user_id"], reason="suplantacion", description="Descripción confidencial")

    res = client.get("/api/v1/admin/reports", headers=admin["headers"])
    assert res.status_code == 200
    raw_text = res.get_data(as_text=True)

    # Ningún dato personal ajeno al esquema ModerationReport debe aparecer en el payload
    for forbidden_leak in [
        "secret.email.1@afinia.test",
        "secret.email.2@afinia.test",
        "NombreSecretoUno",
        "NombreSecretoDos",
        "1998-04-12",
        "password_hash",
        "scrypt:",
    ]:
        assert forbidden_leak not in raw_text

    item = res.get_json()["data"]["items"][0]
    assert set(item.keys()) == {"id", "reporter_user_id", "reported_user_id", "reason", "status", "created_at"}


def test_15_conservation_of_report_history(client):
    """15. Conservación del historial: las denuncias resueltas y desestimadas permanecen en BD y son consultables."""
    admin = _create_user_with_role(client, "admin.hist@afinia.test", password=ADMIN_PWD, role="admin")
    u1 = _create_user_with_role(client, "rep.hist@afinia.test", role="user")
    u2 = _create_user_with_role(client, "target.hist@afinia.test", role="user")

    r1 = _file_report(client, u1["headers"], u2["user_id"], reason="spam")
    r2 = _file_report(client, u1["headers"], u2["user_id"], reason="acoso")
    r3 = _file_report(client, u1["headers"], u2["user_id"], reason="otro")

    client.post(f"/api/v1/admin/reports/{r1}/resolve", json={"action": "dismiss"}, headers=admin["headers"])
    client.post(f"/api/v1/admin/reports/{r2}/resolve", json={"action": "warn"}, headers=admin["headers"])

    # Las 3 denuncias siguen en la tabla física y en el listado general
    all_res = client.get("/api/v1/admin/reports", headers=admin["headers"])
    assert all_res.status_code == 200
    assert len(all_res.get_json()["data"]["items"]) == 3

    # Filtro por cada estado devuelve exactamente su subconjunto histórico
    assert len(client.get("/api/v1/admin/reports?status=dismissed", headers=admin["headers"]).get_json()["data"]["items"]) == 1
    assert len(client.get("/api/v1/admin/reports?status=resolved", headers=admin["headers"]).get_json()["data"]["items"]) == 1
    assert len(client.get("/api/v1/admin/reports?status=pending", headers=admin["headers"]).get_json()["data"]["items"]) == 1


def test_16_sql_integrity_and_rollback_on_failure(client, monkeypatch):
    """16. Integridad SQL y rollback ante fallo durante commit de resolución."""
    admin = _create_user_with_role(client, "admin.tx@afinia.test", password=ADMIN_PWD, role="admin")
    u1 = _create_user_with_role(client, "rep.tx@afinia.test", role="user")
    u2 = _create_user_with_role(client, "target.tx@afinia.test", role="user")

    report_id = _file_report(client, u1["headers"], u2["user_id"], reason="acoso")

    original_commit = db.session.commit

    def _failing_commit():
        raise RuntimeError("Simulated DB commit failure during report resolution")

    monkeypatch.setattr(db.session, "commit", _failing_commit)

    fail_res = client.post(
        f"/api/v1/admin/reports/{report_id}/resolve",
        json={"action": "suspend", "notes": "Intento fallido"},
        headers=admin["headers"],
    )
    assert fail_res.status_code == 500
    assert fail_res.get_json()["error"]["code"] == "INTERNAL_ERROR"

    monkeypatch.setattr(db.session, "commit", original_commit)
    db.session.expire_all()

    rep_db = db.session.get(UserReport, report_id)
    assert rep_db.status == "pending"
    assert rep_db.resolved_at is None
    assert rep_db.resolved_by_user_id is None
    assert rep_db.resolution_action is None

    # Una vez restaurado el commit, la denuncia puede resolverse normalmente
    ok_res = client.post(
        f"/api/v1/admin/reports/{report_id}/resolve",
        json={"action": "suspend", "notes": "Resolución exitosa tras recuperación"},
        headers=admin["headers"],
    )
    assert ok_res.status_code == 200
    assert ok_res.get_json()["data"]["status"] == "resolved"

    fk_errors = db.session.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    assert fk_errors == []

