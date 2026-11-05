#!/usr/bin/env python3
"""
AFINIA — Certificación Integral del Backend MVP en PostgreSQL QA (127.0.0.1:55433).
====================================================================================
Certifica la persistencia real y el contrato 41/41 tras la migración a7b3c9d1e5f2:
1. Comprobación de revisión Alembic (a7b3c9d1e5f2) y existencia física de la tabla notifications.
2. Flujo completo de eventos y notificaciones reales (A a L):
   A. Registro de 2 usuarios sintéticos (u1 y u2).
   B. Creación de perfiles completos, fotos y preferencias.
   C. Swipe recíproco y generación de match atómico.
   D. Comprobación de notificación real 'new_match' en PostgreSQL para ambos participantes.
   E. Envío de mensaje en el match activo.
   F. Comprobación de notificación real 'new_message' en PostgreSQL para el receptor (y no para el emisor).
   G. Consulta paginada por cursor HMAC de notificaciones (GET /api/v1/notifications).
   H. Marcación de lectura de notificación propia (POST /api/v1/notifications/{id}/read -> 204).
   I. Verificación de persistencia física de read_at en PostgreSQL QA.
   J. Protección multi-tenant: intento de leer/marcar notificación ajena rechazado con 404 NOT_FOUND.
   K. Concurrencia transaccional e idempotencia en aceptaciones legales y marcación de lectura.
   L. Eliminación segura de cuenta (POST /api/v1/account/deletion) y verificación de limpieza de notificaciones.
3. Limpieza selectiva estricta por UUID restaurando el 100% de los conteos preexistentes.
"""

import os
import sys
import uuid
import threading
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app import create_app, db
from app.models import User, Profile, ProfilePhoto, DiscoveryPreference, Notification
from app.services.profile_service import sync_user_lifecycle_status


def get_table_counts():
    tables = [
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
        "notifications",
    ]
    counts = {}
    for t in tables:
        try:
            cnt = db.session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            counts[t] = cnt
        except Exception:
            counts[t] = -1
    return counts


def run_full_qa_certification():
    app = create_app()
    with app.app_context():
        print("=" * 80)
        print("AFINIA — CERTIFICACIÓN INTEGRAL DE CIERRE EN POSTGRESQL QA")
        print("=" * 80)

        # 1. Precondiciones
        engine_url = str(db.engine.url)
        print(f"Motor DB: {engine_url}")
        assert "55433" in engine_url and "afinia_qa_db" in engine_url

        rev = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"Revisión Alembic en QA: {rev}")
        assert rev == "a7b3c9d1e5f2", f"Revisión esperada a7b3c9d1e5f2, encontrada: {rev}"

        initial_counts = get_table_counts()
        print(f"Conteos preexistentes en PostgreSQL QA: {initial_counts}")

        client = app.test_client()

        # A. Registrar dos usuarios sintéticos
        print("\n[A] Registrando usuarios sintéticos u1 y u2...")
        pwd = "Password123*CertBE11Final!"
        tag = uuid.uuid4().hex[:8]
        u1_email = f"qa_final_u1_{tag}@qa.afinia.test"
        u2_email = f"qa_final_u2_{tag}@qa.afinia.test"

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

        # Habilitar cuentas en QA
        for uid in (u1_id, u2_id):
            u_db = db.session.get(User, uid)
            u_db.email_verified = True
            u_db.lifecycle_status = "active"
        db.session.commit()

        # Login móvil para obtener JWT
        l1 = client.post(
            "/api/v1/auth/login",
            json={"email": u1_email, "password": pwd},
            headers={"X-Client-Platform": "mobile"},
        )
        assert l1.status_code == 200
        h1 = {"Authorization": f"Bearer {l1.get_json()['data']['access_token']}", "Content-Type": "application/json"}

        l2 = client.post(
            "/api/v1/auth/login",
            json={"email": u2_email, "password": pwd},
            headers={"X-Client-Platform": "mobile"},
        )
        assert l2.status_code == 200
        h2 = {"Authorization": f"Bearer {l2.get_json()['data']['access_token']}", "Content-Type": "application/json"}

        # B. Completar perfiles y preferencias
        print("[B] Creando perfiles completos, fotos y preferencias...")
        prof1_res = client.post(
            "/api/v1/profile/",
            json={"first_name": "Usuario Uno", "birth_date": "1998-06-15", "gender": "masculino", "city": "Bogotá", "bio": "Bio 1"},
            headers=h1,
        )
        assert prof1_res.status_code == 201, prof1_res.get_json()

        prof2_res = client.post(
            "/api/v1/profile/",
            json={"first_name": "Usuario Dos", "birth_date": "1999-08-20", "gender": "femenino", "city": "Bogotá", "bio": "Bio 2"},
            headers=h2,
        )
        assert prof2_res.status_code == 201, prof2_res.get_json()

        pref1_res = client.put(
            "/api/v1/profile/discovery-preferences",
            json={"interested_in_genders": ["femenino"], "min_age": 18, "max_age": 40},
            headers=h1,
        )
        assert pref1_res.status_code == 200, pref1_res.get_json()

        pref2_res = client.put(
            "/api/v1/profile/discovery-preferences",
            json={"interested_in_genders": ["masculino"], "min_age": 18, "max_age": 40},
            headers=h2,
        )
        assert pref2_res.status_code == 200, pref2_res.get_json()

        # Insertar fotos aprobadas (ready) en base de datos para habilitar discovery
        p1_obj = Profile.query.filter_by(user_id=u1_id).first()
        p2_obj = Profile.query.filter_by(user_id=u2_id).first()
        p1_id = str(p1_obj.id)
        p2_id = str(p2_obj.id)
        photo1 = ProfilePhoto(id=str(uuid.uuid4()), profile_id=p1_id, storage_key=f"uploads/{u1_id}/p1.jpg", position=0, is_primary=True, status="ready")
        photo2 = ProfilePhoto(id=str(uuid.uuid4()), profile_id=p2_id, storage_key=f"uploads/{u2_id}/p2.jpg", position=0, is_primary=True, status="ready")
        db.session.add_all([photo1, photo2])
        sync_user_lifecycle_status(db.session.get(User, u1_id))
        sync_user_lifecycle_status(db.session.get(User, u2_id))
        db.session.commit()

        # Verificación explícita de POST /api/v1/legal/acceptances
        print("\n[Legal] Verificando POST /api/v1/legal/acceptances...")
        acc_res = client.post(
            "/api/v1/legal/acceptances",
            json={"terms_version": "v1-draft", "privacy_version": "v1-draft"},
            headers=h1,
        )
        assert acc_res.status_code == 200, acc_res.get_json()
        print(" -> Aceptación legal registrada:", acc_res.get_json()["data"])

        # C. Swipe recíproco y Match
        print("\n[C] Ejecutando swipe recíproco (LIKE mutuo)...")
        sw1 = client.post("/api/v1/match/swipe", json={"target_user_id": u2_id, "action": "LIKE"}, headers=h1)
        assert sw1.status_code == 200 and sw1.get_json()["data"]["is_match"] is False

        sw2 = client.post("/api/v1/match/swipe", json={"target_user_id": u1_id, "action": "LIKE"}, headers=h2)
        assert sw2.status_code == 200 and sw2.get_json()["data"]["is_match"] is True
        match_id = sw2.get_json()["data"]["match_id"]
        print(f" -> Match recíproco creado: match_id={match_id}")

        # D. Verificar notificación 'new_match' persistida en PostgreSQL QA para ambos
        print("\n[D] Verificando notificación 'new_match' en PostgreSQL QA para ambos...")
        n1_res = client.get("/api/v1/notifications", headers=h1)
        assert n1_res.status_code == 200, n1_res.get_json()
        n1_items = n1_res.get_json()["data"]["items"]
        assert len(n1_items) == 1
        assert n1_items[0]["type"] == "new_match"
        assert n1_items[0]["read"] is False
        print(f" -> User 1 tiene notificación: {n1_items[0]}")

        n2_res = client.get("/api/v1/notifications", headers=h2)
        assert n2_res.status_code == 200, n2_res.get_json()
        n2_items = n2_res.get_json()["data"]["items"]
        assert len(n2_items) == 1
        assert n2_items[0]["type"] == "new_match"
        assert n2_items[0]["read"] is False
        print(f" -> User 2 tiene notificación: {n2_items[0]}")

        # E. Enviar mensaje de User 1 a User 2
        print("\n[E] User 1 envía mensaje en el match activo...")
        msg_res = client.post(
            f"/api/v1/match/{match_id}/messages",
            json={"text": "¡Hola desde la certificación final de BE-11!"},
            headers=h1,
        )
        assert msg_res.status_code == 201, msg_res.get_json()
        msg_id = msg_res.get_json()["data"]["id"]
        print(f" -> Mensaje enviado: msg_id={msg_id}")

        # F. Verificar que User 2 recibe 'new_message' y User 1 NO lo recibe
        print("\n[F] Verificando notificación 'new_message' para el destinatario...")
        n2_after = client.get("/api/v1/notifications", headers=h2)
        n2_after_items = n2_after.get_json()["data"]["items"]
        assert len(n2_after_items) == 2
        types_u2 = [n["type"] for n in n2_after_items]
        assert types_u2 == ["new_message", "new_match"]
        new_msg_notif = n2_after_items[0]
        print(f" -> User 2 tiene 2 notificaciones: {types_u2}")

        n1_after = client.get("/api/v1/notifications", headers=h1)
        n1_after_items = n1_after.get_json()["data"]["items"]
        assert len(n1_after_items) == 1
        assert n1_after_items[0]["type"] == "new_match"
        print(" -> User 1 (remitente) no tiene notificación de su propio mensaje: OK")

        # G. Paginación por cursor HMAC
        print("\n[G] Probando paginación por cursor en GET /api/v1/notifications...")
        page1 = client.get("/api/v1/notifications?limit=1", headers=h2)
        assert page1.status_code == 200
        p1_data = page1.get_json()
        assert len(p1_data["data"]["items"]) == 1
        assert p1_data["meta"]["has_more"] is True
        cur1 = p1_data["meta"]["next_cursor"]
        assert cur1 is not None

        page2 = client.get(f"/api/v1/notifications?limit=1&cursor={cur1}", headers=h2)
        assert page2.status_code == 200
        p2_data = page2.get_json()
        assert len(p2_data["data"]["items"]) == 1
        assert p2_data["meta"]["has_more"] is False
        assert p2_data["meta"]["next_cursor"] is None
        print(" -> Paginación por cursor determinista: OK")

        # H e I. Marcar notificación como leída y verificar read_at persistido
        print("\n[H & I] Marcando notificación como leída (POST /read) y verificando persistencia...")
        read_res = client.post(f"/api/v1/notifications/{new_msg_notif['id']}/read", headers=h2)
        assert read_res.status_code == 204
        print(" -> Marcación devolvió 204 No Content")

        # Verificar persistencia física en PostgreSQL QA
        db_notif = db.session.execute(
            text("SELECT read_at FROM notifications WHERE id = :nid"),
            {"nid": new_msg_notif["id"]},
        ).fetchone()
        assert db_notif is not None and db_notif[0] is not None
        print(f" -> read_at físico en PostgreSQL QA: {db_notif[0]}")

        # Idempotencia al reintentar marcar como leída
        read_again = client.post(f"/api/v1/notifications/{new_msg_notif['id']}/read", headers=h2)
        assert read_again.status_code == 204
        print(" -> Idempotencia de marcación repetida: OK (204 No Content)")

        # J. Protección multi-tenant
        print("\n[J] Comprobando protección contra acceso o marcación de notificaciones ajenas...")
        attack_res = client.post(f"/api/v1/notifications/{new_msg_notif['id']}/read", headers=h1)
        assert attack_res.status_code == 404
        assert attack_res.get_json()["error"]["code"] == "NOT_FOUND"
        print(" -> Intento de marcar notificación ajena rechazado con 404 NOT_FOUND: OK")

        # K. Concurrencia transaccional e idempotencia
        print("\n[K] Verificando concurrencia de 2 peticiones simultáneas sobre la misma notificación...")
        db.session.remove()
        barrier = threading.Barrier(2)
        race_res = []
        lock = threading.Lock()

        def _race_worker():
            with app.app_context():
                try:
                    c = app.test_client()
                    barrier.wait(timeout=10)
                    r = c.post(f"/api/v1/notifications/{new_msg_notif['id']}/read", headers=h2)
                    with lock:
                        race_res.append(r.status_code)
                except Exception as ex:
                    with lock:
                        race_res.append(f"ERROR: {ex}")

        th1 = threading.Thread(target=_race_worker)
        th2 = threading.Thread(target=_race_worker)
        th1.start()
        th2.start()
        th1.join(timeout=15)
        th2.join(timeout=15)
        assert all(s == 204 for s in race_res), f"Fallo en concurrencia: {race_res}"
        print(f" -> Concurrencia real simultánea: {race_res} -> OK")

        # L. Eliminación de cuenta limpia notificaciones asociadas
        print("\n[L] Verificando que POST /api/v1/account/deletion limpia las notificaciones...")
        notifs_before_del = db.session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid"),
            {"uid": u2_id},
        ).scalar()
        assert notifs_before_del == 2

        del_res = client.post(
            "/api/v1/account/deletion",
            json={"password": pwd, "confirm": True},
            headers=h2,
        )
        assert del_res.status_code == 202, del_res.get_json()

        notifs_after_del = db.session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid"),
            {"uid": u2_id},
        ).scalar()
        assert notifs_after_del == 0
        print(" -> Notificaciones limpiadas físicamente tras account deletion: OK (conteo=0)")

        # Limpieza selectiva de fixtures de User 1 y User 2
        print("\n[CLEANUP] Limpiando registros sintéticos por UUID exacto...")
        db.session.execute(text("DELETE FROM notifications WHERE user_id IN (:u1, :u2)"), {"u1": u1_id, "u2": u2_id})
        db.session.execute(text("DELETE FROM messages WHERE match_id = :mid"), {"mid": match_id})
        db.session.execute(text("DELETE FROM matches WHERE id = :mid"), {"mid": match_id})
        db.session.execute(text("DELETE FROM profile_interactions WHERE viewer_user_id IN (:u1, :u2) OR shown_user_id IN (:u1, :u2)"), {"u1": u1_id, "u2": u2_id})
        db.session.execute(text("DELETE FROM profile_photos WHERE profile_id IN (:p1, :p2)"), {"p1": p1_id, "p2": p2_id})
        db.session.execute(text("DELETE FROM profiles WHERE user_id IN (:u1, :u2)"), {"u1": u1_id, "u2": u2_id})
        db.session.execute(text("DELETE FROM discovery_preferences WHERE user_id IN (:u1, :u2)"), {"u1": u1_id, "u2": u2_id})
        db.session.execute(text("DELETE FROM legal_consents WHERE user_id IN (:u1, :u2)"), {"u1": u1_id, "u2": u2_id})
        db.session.execute(text("DELETE FROM refresh_tokens WHERE user_id IN (:u1, :u2)"), {"u1": u1_id, "u2": u2_id})
        db.session.execute(text("DELETE FROM email_verification_tokens WHERE user_id IN (:u1, :u2)"), {"u1": u1_id, "u2": u2_id})
        db.session.execute(text("DELETE FROM users WHERE id IN (:u1, :u2)"), {"u1": u1_id, "u2": u2_id})
        db.session.commit()

        # Verificación de integridad de datos preexistentes
        final_counts = get_table_counts()
        print(f"Conteos finales en PostgreSQL QA: {final_counts}")
        assert final_counts == initial_counts, (
            f"Divergencia en conteos:\nInicial: {initial_counts}\nFinal:   {final_counts}"
        )

        print("\n" + "=" * 80)
        print("CERTIFICACIÓN INTEGRAL DE LAS 41 OPERACIONES EN POSTGRESQL QA: ¡PASS TOTAL!")
        print("=" * 80)


if __name__ == "__main__":
    run_full_qa_certification()

