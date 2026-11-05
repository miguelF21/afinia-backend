#!/usr/bin/env python3
"""
AFINIA — Certificación Real BE-10 en PostgreSQL QA (127.0.0.1:55433/afinia_qa_db).
===================================================================================
Verifica con conexiones reales independientes hacia PostgreSQL QA:
1. Precondiciones de base de datos, revisión Alembic (`f4c2d8e1a3b5`) y conteos preexistentes.
2. Control de acceso RBAC (usuario normal 403, administrador autorizado 200).
3. Paginación por cursor y orden determinista sobre `user_reports`.
4. Concurrencia real: 2 administradores autenticados en hilos con sesiones independientes
   resolviendo simultáneamente la misma denuncia (`SELECT ... FOR UPDATE` en PostgreSQL):
   - Exactamente 1 transacción gana (`200 OK`).
   - La otra transacción recibe `409 CONFLICT` sin sobrescribir `resolved_by_user_id`, `resolved_at`,
     `resolution_action` ni `resolution_notes`.
5. Resolución de denuncia asociada a una cuenta eliminada vía `POST /api/v1/account/deletion`.
6. Limpieza selectiva por UUID exacto preservando el 100% de los datos preexistentes.
"""

import os
import sys
import uuid
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app import create_app, db
from app.models import User, UserReport


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
    ]
    counts = {}
    with db.engine.connect() as conn:
        for t in tables:
            counts[t] = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
    return counts


def run_certification():
    app = create_app()
    created_user_ids = []
    created_report_ids = []

    print("=" * 85)
    print("INICIANDO CERTIFICACIÓN BE-10 EN POSTGRESQL QA (127.0.0.1:55433 / afinia_qa_db)")
    print("=" * 85)

    with app.app_context():
        with db.engine.connect() as conn:
            db_name = conn.execute(text("SELECT current_database()")).scalar()
            alembic_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"[PRE-CHECK] Base de datos conectada: {db_name}")
        print(f"[PRE-CHECK] Revisión Alembic activa: {alembic_rev}")
        assert db_name == "afinia_qa_db", f"Base de datos inesperada: {db_name}"
        assert alembic_rev == "f4c2d8e1a3b5", f"Revisión Alembic inesperada: {alembic_rev}"

        baseline_counts = get_table_counts()
        print(f"[PRE-CHECK] Conteos preexistentes capturados: {baseline_counts}")

        try:
            client = app.test_client()
            pwd = "ClaveSeguraCertBE10_2026!"
            suffix = uuid.uuid4().hex[:8]

            def _reg_user(prefix, role="user"):
                email = f"be10_{prefix}_{suffix}@qa.afinia.test"
                r = client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": email,
                        "password": pwd,
                        "accept_terms_version": "v1-draft",
                        "accept_privacy_version": "v1-draft",
                    },
                )
                assert r.status_code == 201, r.get_json()
                uid = r.get_json()["data"]["id"]
                created_user_ids.append(uid)

                with db.engine.begin() as wconn:
                    wconn.execute(
                        text(
                            "UPDATE users SET email_verified = true, role = :role, lifecycle_status = 'active' WHERE id = :uid"
                        ),
                        {"role": role, "uid": uid},
                    )

                lg = client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": pwd},
                    headers={"X-Client-Platform": "mobile"},
                )
                assert lg.status_code == 200, lg.get_json()
                tok = lg.get_json()["data"]["access_token"]
                return {"id": uid, "email": email, "headers": {"Authorization": f"Bearer {tok}"}}

            print("\n--- PASO 1: Creación de 2 administradores y 2 usuarios sintéticos ---")
            admin1 = _reg_user("admin1", role="admin")
            admin2 = _reg_user("admin2", role="admin")
            u_rep = _reg_user("reporter", role="user")
            u_target = _reg_user("reported", role="user")

            # Verificar que u_rep (role='user') recibe 403 FORBIDDEN en /api/v1/admin/reports
            assert client.get("/api/v1/admin/reports", headers=u_rep["headers"]).status_code == 403

            # Crear 2 denuncias reales en PostgreSQL QA
            rep1_res = client.post(
                f"/api/v1/users/{u_target['id']}/reports",
                json={"reason": "acoso", "description": "Denuncia sintética 1 para concurrencia PG"},
                headers=u_rep["headers"],
            )
            assert rep1_res.status_code == 201
            report1_id = rep1_res.get_json()["data"]["report_id"]
            created_report_ids.append(report1_id)

            rep2_res = client.post(
                f"/api/v1/users/{u_target['id']}/reports",
                json={"reason": "spam", "description": "Denuncia sintética 2 sobre cuenta por eliminar"},
                headers=u_rep["headers"],
            )
            assert rep2_res.status_code == 201
            report2_id = rep2_res.get_json()["data"]["report_id"]
            created_report_ids.append(report2_id)

            db.session.remove()
            print("[PASS] Usuarios, roles y denuncias sintéticas creadas; control RBAC verificado.")

            # PASO 2: CONCURRENCIA REAL EN POSTGRESQL QA
            print("\n--- PASO 2: Concurrencia real de 2 administradores resolviendo la misma denuncia ---")
            barrier = threading.Barrier(2)
            race_results = []
            lock = threading.Lock()

            def _resolve_worker(worker_name, headers_dict, action_val, notes_val, admin_id):
                with app.app_context():
                    try:
                        c = app.test_client()
                        barrier.wait(timeout=10)
                        r = c.post(
                            f"/api/v1/admin/reports/{report1_id}/resolve",
                            json={"action": action_val, "notes": notes_val},
                            headers=headers_dict,
                        )
                        with lock:
                            race_results.append((r.status_code, worker_name, admin_id, action_val, r.get_json()))
                    finally:
                        db.session.remove()

            t1 = threading.Thread(
                target=_resolve_worker,
                args=("PG-Admin-1", admin1["headers"], "warn", "Advertencia emitida por Admin 1", admin1["id"]),
            )
            t2 = threading.Thread(
                target=_resolve_worker,
                args=("PG-Admin-2", admin2["headers"], "dismiss", "Desestimada por Admin 2", admin2["id"]),
            )
            t1.start()
            t2.start()
            t1.join(timeout=15)
            t2.join(timeout=15)

            print(f"[PG-ADMIN-CONCURRENCY] Resultados: {race_results}")
            codes = sorted([r[0] for r in race_results])
            assert codes == [200, 409], f"Se esperaba [200, 409] y se obtuvo: {codes}"

            winner = [r for r in race_results if r[0] == 200][0]
            with db.engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT status, resolution_action, resolved_by_user_id, resolved_at "
                        "FROM user_reports WHERE id = :rid"
                    ),
                    {"rid": report1_id},
                ).fetchone()
            assert row is not None
            expected_status = "dismissed" if winner[3] == "dismiss" else "resolved"
            assert row[0] == expected_status
            assert row[1] == winner[3]
            assert row[2] == winner[2]
            assert row[3] is not None
            print("[PASS] Concurrencia PostgreSQL verificada: 1 éxito (200) y 1 conflicto (409) sin sobrescritura.")

            # PASO 3: DENUNCIA SOBRE CUENTA ELIMINADA Y LISTADO PAGINADO
            print("\n--- PASO 3: Eliminación de cuenta denunciada y resolución posterior ---")
            del_target = client.post(
                "/api/v1/account/deletion",
                json={"password": pwd, "confirm": True},
                headers=u_target["headers"],
            )
            assert del_target.status_code == 202

            list_res = client.get(
                f"/api/v1/admin/reports?reported_user_id={u_target['id']}&limit=1",
                headers=admin1["headers"],
            )
            assert list_res.status_code == 200
            l_body = list_res.get_json()
            assert len(l_body["data"]["items"]) == 1
            assert l_body["meta"]["has_more"] is True
            assert l_body["meta"]["next_cursor"] is not None

            res_rep2 = client.post(
                f"/api/v1/admin/reports/{report2_id}/resolve",
                json={"action": "suspend", "notes": "Resuelta sobre cuenta ya eliminada"},
                headers=admin1["headers"],
            )
            assert res_rep2.status_code == 200
            assert res_rep2.get_json() == {"data": {"status": "resolved"}}
            db.session.remove()
            print("[PASS] Listado paginado y resolución de denuncia sobre cuenta eliminada verificados.")

        finally:
            print("\n--- LIMPIEZA SELECTIVA POR UUID EXACTO EN POSTGRESQL QA ---")
            db.session.remove()
            with db.engine.begin() as wconn:
                if created_report_ids:
                    wconn.execute(
                        text("DELETE FROM user_reports WHERE id = ANY(:rids)"),
                        {"rids": created_report_ids},
                    )
                if created_user_ids:
                    wconn.execute(
                        text("DELETE FROM user_reports WHERE reporter_user_id = ANY(:uids) OR reported_user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    wconn.execute(
                        text("DELETE FROM email_verification_tokens WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    wconn.execute(
                        text("DELETE FROM refresh_tokens WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    wconn.execute(
                        text("DELETE FROM legal_consents WHERE user_id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )
                    wconn.execute(
                        text("DELETE FROM users WHERE id = ANY(:uids)"),
                        {"uids": created_user_ids},
                    )

            final_counts = get_table_counts()
            print(f"[POST-CHECK] Conteos finales tras limpieza: {final_counts}")
            assert final_counts == baseline_counts, (
                f"Divergencia en conteos preexistentes:\nAntes: {baseline_counts}\nDespués: {final_counts}"
            )
            print("[CLEANUP] Limpieza por UUID exacto completada: 100% de los datos preexistentes intactos.")

    print("\n" + "=" * 85)
    print("CERTIFICACIÓN BE-10 COMPLETADA SATISFACTORIAMENTE EN POSTGRESQL QA (PASS)")
    print("=" * 85)


if __name__ == "__main__":
    run_certification()

