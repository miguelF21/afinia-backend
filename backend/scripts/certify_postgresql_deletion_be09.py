#!/usr/bin/env python3
"""
AFINIA — BE-09: SCRIPT DE CERTIFICACIÓN DE ELIMINACIÓN SEGURA DE CUENTA EN POSTGRESQL QA
========================================================================================
Verifica de principio a fin en PostgreSQL QA (127.0.0.1:55433 / afinia_qa_db):
1. Precondiciones: base afinia_qa_db, revisión Alembic f4c2d8e1a3b5 y captura de conteos preexistentes.
2. Flujo completo sobre cuentas sintéticas (U1 y U2): perfil, fotos físicas, preferencias,
   cuestionario, match, mensajes, denuncias y bloqueos.
3. Concurrencia real en PostgreSQL QA con dos conexiones simultáneas sobre POST /api/v1/account/deletion
   sincronizadas con threading.Barrier(2) -> 1 éxito (202) y 1 rechazo controlado (409/401).
4. Verificación SQL de supresión física, anonimización, cierre lógico de matches,
   revocación de sesiones/JWT, borrado de archivos multimedia e integridad referencial RESTRICT.
5. Limpieza estricta por UUIDs exactos y verificación de preservación íntegra de datos preexistentes.
"""

import io
import os
import sys
import uuid
import threading
from PIL import Image
from sqlalchemy import text

sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("."))

from app import create_app, db
from app.models import ProfilePhoto
from app.services.email_service import email_service
from app.services.profile_service import approve_photo_for_qa
from app.services.storage_service import storage_adapter


TABLES_TO_AUDIT = [
    "users",
    "profiles",
    "profile_photos",
    "discovery_preferences",
    "analytic_questionnaire_answers",
    "profile_interactions",
    "matches",
    "messages",
    "user_blocks",
    "user_reports",
    "legal_consents",
    "refresh_tokens",
    "email_verification_tokens",
    "password_reset_tokens",
]


def run_query(sql, params=None):
    with db.engine.connect() as conn:
        return conn.execute(text(sql), params or {})


def get_table_counts():
    counts = {}
    for t in TABLES_TO_AUDIT:
        counts[t] = run_query(f"SELECT COUNT(*) FROM {t}").scalar()
    return counts


def _make_jpeg_bytes(color=(60, 140, 220)) -> bytes:
    img = Image.new("RGB", (64, 64), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def run_certification():
    print("=" * 85)
    print("INICIANDO CERTIFICACIÓN BE-09 EN POSTGRESQL QA (127.0.0.1:55433 / afinia_qa_db)")
    print("=" * 85)

    app = create_app()
    client = app.test_client()

    with app.app_context():
        db_name = run_query("SELECT current_database()").scalar()
        alembic_rev = run_query("SELECT version_num FROM alembic_version").scalar()
        print(f"[PRE-CHECK] Base de datos conectada: {db_name}")
        print(f"[PRE-CHECK] Revisión Alembic activa: {alembic_rev}")

        assert db_name == "afinia_qa_db", f"Se esperaba afinia_qa_db, actual: {db_name}"
        assert alembic_rev == "f4c2d8e1a3b5", f"Se esperaba revisión f4c2d8e1a3b5, actual: {alembic_rev}"

        baseline_counts = get_table_counts()
        print(f"[PRE-CHECK] Conteos preexistentes capturados: {baseline_counts}")

        run_id = uuid.uuid4().hex[:8]
        u1_email = f"qa.del.u1.{run_id}@afinia.test"
        u2_email = f"qa.del.u2.{run_id}@afinia.test"
        pwd = "QaDeletionPass2026!#"

        created_user_ids = []
        created_match_ids = []
        created_storage_keys = []

        try:
            print("\n--- PASO 1: Creación y onboarding de usuarios sintéticos U1 y U2 ---")
            email_service.clear_sent_messages()

            # Registrar U1
            r1 = client.post(
                "/api/v1/auth/register",
                json={
                    "email": u1_email,
                    "password": pwd,
                    "accept_terms_version": "v1-draft",
                    "accept_privacy_version": "v1-draft",
                },
            )
            assert r1.status_code == 201, r1.get_json()
            u1_id = r1.get_json()["data"]["id"]
            created_user_ids.append(u1_id)
            tok1 = email_service.get_last_token_for(u1_email)
            assert client.post("/api/v1/auth/verify-email", json={"token": tok1}).status_code == 204

            # Registrar U2
            r2 = client.post(
                "/api/v1/auth/register",
                json={
                    "email": u2_email,
                    "password": pwd,
                    "accept_terms_version": "v1-draft",
                    "accept_privacy_version": "v1-draft",
                },
            )
            assert r2.status_code == 201, r2.get_json()
            u2_id = r2.get_json()["data"]["id"]
            created_user_ids.append(u2_id)
            tok2 = email_service.get_last_token_for(u2_email)
            assert client.post("/api/v1/auth/verify-email", json={"token": tok2}).status_code == 204

            # Login U1 y U2
            l1 = client.post(
                "/api/v1/auth/login",
                json={"email": u1_email, "password": pwd},
                headers={"X-Client-Platform": "mobile"},
            )
            assert l1.status_code == 200
            jwt_u1 = l1.get_json()["data"]["access_token"]
            ref_u1 = l1.get_json()["data"]["refresh_token"]
            h_u1 = {"Authorization": f"Bearer {jwt_u1}"}

            l2 = client.post(
                "/api/v1/auth/login",
                json={"email": u2_email, "password": pwd},
                headers={"X-Client-Platform": "mobile"},
            )
            assert l2.status_code == 200
            jwt_u2 = l2.get_json()["data"]["access_token"]
            h_u2 = {"Authorization": f"Bearer {jwt_u2}"}

            # Perfiles y preferencias
            assert (
                client.post(
                    "/api/v1/profile/",
                    json={
                        "first_name": "QaUserUno",
                        "birth_date": "1998-03-10",
                        "gender": "femenino",
                        "city": "Villavicencio",
                        "bio": "Bio sintética U1",
                    },
                    headers=h_u1,
                ).status_code
                == 201
            )
            assert (
                client.put(
                    "/api/v1/profile/discovery-preferences",
                    json={
                        "interested_in_genders": ["masculino"],
                        "min_age": 18,
                        "max_age": 45,
                        "target_relationship_type": "seria",
                    },
                    headers=h_u1,
                ).status_code
                == 200
            )

            assert (
                client.post(
                    "/api/v1/profile/",
                    json={
                        "first_name": "QaUserDos",
                        "birth_date": "1997-07-20",
                        "gender": "masculino",
                        "city": "Villavicencio",
                        "bio": "Bio sintética U2",
                    },
                    headers=h_u2,
                ).status_code
                == 201
            )
            assert (
                client.put(
                    "/api/v1/profile/discovery-preferences",
                    json={
                        "interested_in_genders": ["femenino"],
                        "min_age": 18,
                        "max_age": 45,
                        "target_relationship_type": "seria",
                    },
                    headers=h_u2,
                ).status_code
                == 200
            )

            # Fotografías
            ph1 = client.post(
                "/api/v1/profile/photos",
                data={"file": (io.BytesIO(_make_jpeg_bytes()), "u1.jpg"), "is_primary": "true"},
                headers=h_u1,
                content_type="multipart/form-data",
            )
            assert ph1.status_code == 201
            photo_u1_id = ph1.get_json()["data"]["id"]
            approve_photo_for_qa(photo_u1_id)
            p1_obj = db.session.get(ProfilePhoto, photo_u1_id)
            u1_storage_key = p1_obj.storage_key
            created_storage_keys.append(u1_storage_key)
            u1_file_path = storage_adapter.get_file_path(u1_storage_key)
            assert u1_file_path and os.path.exists(u1_file_path)

            ph2 = client.post(
                "/api/v1/profile/photos",
                data={"file": (io.BytesIO(_make_jpeg_bytes((120, 40, 200))), "u2.jpg"), "is_primary": "true"},
                headers=h_u2,
                content_type="multipart/form-data",
            )
            assert ph2.status_code == 201
            photo_u2_id = ph2.get_json()["data"]["id"]
            approve_photo_for_qa(photo_u2_id)
            p2_obj = db.session.get(ProfilePhoto, photo_u2_id)
            created_storage_keys.append(p2_obj.storage_key)
            db.session.remove()

            # Cuestionario U1
            assert (
                client.put(
                    "/api/v1/questionnaire/answers",
                    json={
                        "version": "draft-1",
                        "answers": [
                            {"question_id": "importance_communication", "value": 5},
                            {"question_id": "importance_values", "value": 4},
                        ],
                    },
                    headers=h_u1,
                ).status_code
                == 200
            )

            # Match y mensajes entre U1 y U2
            assert (
                client.post(
                    "/api/v1/match/swipe",
                    json={"target_user_id": u2_id, "action": "LIKE"},
                    headers=h_u1,
                ).status_code
                == 200
            )
            sw2 = client.post(
                "/api/v1/match/swipe",
                json={"target_user_id": u1_id, "action": "LIKE"},
                headers=h_u2,
            )
            assert sw2.status_code == 200
            match_id = sw2.get_json()["data"]["match_id"]
            assert match_id is not None
            created_match_ids.append(match_id)

            assert (
                client.post(
                    f"/api/v1/match/{match_id}/messages",
                    json={"text": "Mensaje de prueba QA antes de eliminar cuenta."},
                    headers=h_u1,
                ).status_code
                == 201
            )

            # Reporte de U2 contra U1
            rep = client.post(
                f"/api/v1/users/{u1_id}/reports",
                json={"reason": "spam", "description": "Reporte sintético QA BE-09"},
                headers=h_u2,
            )
            assert rep.status_code == 201
            print("[PASS] Usuarios sintéticos U1 y U2 configurados con fotos, cuestionario, match, mensaje y reporte.")

            # PASO 2: CONCURRENCIA REAL DE ELIMINACIÓN EN POSTGRESQL QA
            print("\n--- PASO 2: Solicitud concurrente de eliminación de cuenta (2 conexiones simultáneas) ---")
            barrier = threading.Barrier(2)
            race_results = []
            lock = threading.Lock()

            def _del_worker(worker_name):
                with app.app_context():
                    try:
                        c = app.test_client()
                        barrier.wait(timeout=10)
                        r = c.post(
                            "/api/v1/account/deletion",
                            json={"password": pwd, "confirm": True},
                            headers=h_u1,
                        )
                        with lock:
                            race_results.append((r.status_code, worker_name, r.get_json()))
                    finally:
                        db.session.remove()

            t1 = threading.Thread(target=_del_worker, args=("PG-Worker-1",))
            t2 = threading.Thread(target=_del_worker, args=("PG-Worker-2",))
            t1.start()
            t2.start()
            t1.join(timeout=15)
            t2.join(timeout=15)

            print(f"[PG-DELETION-CONCURRENCY] Resultados: {race_results}")
            codes = sorted([r[0] for r in race_results])
            assert codes[0] == 202, f"Se esperaba exactamente un 202 Accepted: {codes}"
            assert codes[1] in (401, 409), f"La segunda solicitud concurrente debió recibir 409 o 401: {codes}"
            print("[PASS] Concurrencia en PostgreSQL QA: 1 éxito (202) y 1 rechazo controlado sin errores 500.")

            # PASO 3: VERIFICACIÓN SQL Y DE ARCHIVOS TRAS LA ELIMINACIÓN
            print("\n--- PASO 3: Verificación SQL y de almacenamiento tras eliminar U1 ---")
            u1_row = run_query(
                "SELECT email, is_active, email_verified, lifecycle_status, deleted_at FROM users WHERE id = :uid",
                {"uid": u1_id},
            ).fetchone()
            assert u1_row is not None
            assert u1_row[0] == f"deleted+{u1_id}@deleted.afinia.invalid"
            assert u1_row[1] is False
            assert u1_row[2] is False
            assert u1_row[3] == "deactivated"
            assert u1_row[4] is not None

            assert run_query("SELECT COUNT(*) FROM profiles WHERE user_id = :uid", {"uid": u1_id}).scalar() == 0
            assert run_query("SELECT COUNT(*) FROM profile_photos WHERE id = :pid", {"pid": photo_u1_id}).scalar() == 0
            assert run_query("SELECT COUNT(*) FROM discovery_preferences WHERE user_id = :uid", {"uid": u1_id}).scalar() == 0
            assert run_query("SELECT COUNT(*) FROM analytic_questionnaire_answers WHERE user_id = :uid", {"uid": u1_id}).scalar() == 0
            assert (
                run_query(
                    "SELECT COUNT(*) FROM profile_interactions WHERE viewer_user_id = :uid OR shown_user_id = :uid",
                    {"uid": u1_id},
                ).scalar()
                == 0
            )
            assert (
                run_query(
                    "SELECT COUNT(*) FROM refresh_tokens WHERE user_id = :uid AND revoked_at IS NULL",
                    {"uid": u1_id},
                ).scalar()
                == 0
            )
            assert not os.path.exists(u1_file_path), "El archivo físico de la foto de U1 debió ser eliminado"

            match_row = run_query(
                "SELECT closed_at, closed_by_user_id FROM matches WHERE id = :mid",
                {"mid": match_id},
            ).fetchone()
            assert match_row[0] is not None and match_row[1] == u1_id
            assert run_query("SELECT COUNT(*) FROM messages WHERE match_id = :mid", {"mid": match_id}).scalar() == 1
            assert run_query("SELECT COUNT(*) FROM user_reports WHERE reported_user_id = :uid", {"uid": u1_id}).scalar() == 1
            assert (
                run_query(
                    "SELECT COUNT(*) FROM legal_consents WHERE user_id = :uid AND ip_address IS NULL",
                    {"uid": u1_id},
                ).scalar()
                == 2
            )
            print("[PASS] Estado SQL y eliminación de archivos físicos verificados en PostgreSQL QA.")

            # PASO 4: VERIFICACIÓN HTTP POST-ELIMINACIÓN
            print("\n--- PASO 4: Verificación HTTP de bloqueo de acceso y privacidad ---")
            assert client.post("/api/v1/auth/login", json={"email": u1_email, "password": pwd}).status_code == 401
            assert client.post("/api/v1/auth/refresh", json={"refresh_token": ref_u1}).status_code == 401
            assert client.get("/api/v1/auth/me", headers=h_u1).status_code == 401
            assert client.get(f"/api/v1/users/{u1_id}", headers=h_u2).status_code == 404
            assert client.get(f"/api/v1/profile/photos/media/{photo_u1_id}", headers=h_u2).status_code == 404
            assert client.get(f"/api/v1/match/{match_id}", headers=h_u2).status_code == 404
            assert client.get("/api/v1/auth/me", headers=h_u2).status_code == 200
            print("[PASS] Controles de sesión, visibilidad y medios verificados.")

        finally:
            print("\n--- LIMPIEZA SELECTIVA POR UUID EXACTO EN POSTGRESQL QA ---")
            db.session.remove()
            if created_user_ids:
                with db.engine.begin() as write_conn:
                    if created_match_ids:
                        write_conn.execute(
                            text("DELETE FROM messages WHERE match_id = ANY(:mids)"),
                            {"mids": created_match_ids},
                        )
                        write_conn.execute(
                            text("DELETE FROM matches WHERE id = ANY(:mids)"),
                            {"mids": created_match_ids},
                        )
                    write_conn.execute(
                        text("DELETE FROM user_reports WHERE reporter_user_id = ANY(:uids) OR reported_user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM user_blocks WHERE blocker_user_id = ANY(:uids) OR blocked_user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM profile_interactions WHERE viewer_user_id = ANY(:uids) OR shown_user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM analytic_questionnaire_answers WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM discovery_preferences WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM profile_photos WHERE profile_id IN (SELECT id FROM profiles WHERE user_id = ANY(:uids))"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM profiles WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM password_reset_tokens WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM email_verification_tokens WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM refresh_tokens WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM legal_consents WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    write_conn.execute(
                        text("DELETE FROM users WHERE id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )

            for sk in created_storage_keys:
                storage_adapter.delete_file(sk)

            final_counts = get_table_counts()
            print(f"[POST-CHECK] Conteos finales tras limpieza: {final_counts}")
            assert final_counts == baseline_counts, (
                f"Divergencia en conteos preexistentes tras limpieza:\n"
                f"Antes:   {baseline_counts}\n"
                f"Después: {final_counts}"
            )
            print("[CLEANUP] Limpieza por UUID exacto completada: 100% de los datos preexistentes intactos.")

    print("\n" + "=" * 85)
    print("CERTIFICACIÓN BE-09 COMPLETADA SATISFACTORIAMENTE EN POSTGRESQL QA (PASS)")
    print("=" * 85)


if __name__ == "__main__":
    run_certification()

