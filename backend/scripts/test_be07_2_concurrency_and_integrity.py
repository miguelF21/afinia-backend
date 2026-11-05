"""
Suite exhaustiva de pruebas de concurrencia e integridad (BE-07.2) contra PostgreSQL QA.
Verifica:
1. Dos PUT simultáneos para el mismo usuario y pregunta (cero duplicados, atomicidad).
2. Dos PUT simultáneos para usuarios diferentes (aislamiento e independencia).
3. Actualización de respuesta existente (UPSERT modifica valor).
4. Reintento de una solicitud idéntica (idempotencia perfecta).
5. Solicitud que contiene una pregunta duplicada en payload (rechazo 422).
6. Error de validación sin persistencia parcial (rollback transaccional completo).
7. Imposibilidad de insertar duplicados mediante SQL directo (violación de UNIQUE).
8. Acceso restringido a respuestas del usuario autenticado (aislamiento de lectura).
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import threading
import uuid
from app import create_app, db
from app.models.user import User
from app.models.analytics import AnalyticQuestionnaireAnswer
from app.utils.security import create_access_token
from sqlalchemy.exc import IntegrityError

def run_tests():
    app = create_app()
    with app.app_context():
        print("=" * 80)
        print("INICIANDO SUITE DE CONCURRENCIA E INTEGRIDAD POSTGRESQL QA (BE-07.2)")
        print("=" * 80)

        # Helpers
        def make_user(label):
            u_id = str(uuid.uuid4())
            u_email = f"qa_{label}_{uuid.uuid4().hex[:6]}@afinia.test"
            user = User(id=u_id, email=u_email, password_hash="fake", is_active=True)
            db.session.add(user)
            db.session.commit()
            token = create_access_token(u_id, u_email, "user", app.config['SECRET_KEY'])
            return {"id": u_id, "email": u_email, "token": token}

        created_users = []

        try:
            client = app.test_client()

            # -----------------------------------------------------------------
            # 1. Dos PUT simultáneos para el mismo usuario y pregunta
            # -----------------------------------------------------------------
            print("\n[TEST 1] Dos PUT simultáneos para el mismo usuario y pregunta...")
            u1 = make_user("concurrent_same")
            created_users.append(u1["id"])
            h1 = {"Authorization": f"Bearer {u1['token']}"}

            barrier = threading.Barrier(2)
            results1 = []

            def worker1(val, worker_id):
                barrier.wait()
                res = client.put("/api/v1/questionnaire/answers", headers=h1, json={
                    "version": "draft-1",
                    "answers": [
                        {"question_id": "importance_fidelity", "value": val},
                        {"question_id": "importance_honesty", "value": 5}
                    ]
                })
                results1.append((worker_id, res.status_code))

            t1a = threading.Thread(target=worker1, args=(3, "W1"))
            t1b = threading.Thread(target=worker1, args=(5, "W2"))
            t1a.start(); t1b.start()
            t1a.join(); t1b.join()

            assert all(code == 200 for _, code in results1), f"Fallaron peticiones: {results1}"
            u1_rows = AnalyticQuestionnaireAnswer.query.filter_by(user_id=u1["id"]).all()
            assert len(u1_rows) == 2, f"Se esperaban 2 filas, encontradas {len(u1_rows)}"
            assert len({r.variable_name for r in u1_rows}) == 2, "Duplicados detectados!"
            print(f"   -> [PASS] Ambas peticiones concluyeron con 200 OK. Total filas: {len(u1_rows)} (CERO duplicados).")

            # -----------------------------------------------------------------
            # 2. Dos PUT simultáneos para usuarios diferentes
            # -----------------------------------------------------------------
            print("\n[TEST 2] Dos PUT simultáneos para usuarios diferentes...")
            u2a = make_user("diff_a")
            u2b = make_user("diff_b")
            created_users.extend([u2a["id"], u2b["id"]])

            barrier2 = threading.Barrier(2)
            results2 = []

            def worker2(user_data, val):
                barrier2.wait()
                headers = {"Authorization": f"Bearer {user_data['token']}"}
                res = client.put("/api/v1/questionnaire/answers", headers=headers, json={
                    "version": "draft-1",
                    "answers": [{"question_id": "importance_fidelity", "value": val}]
                })
                results2.append((user_data["id"], res.status_code))

            t2a = threading.Thread(target=worker2, args=(u2a, 4))
            t2b = threading.Thread(target=worker2, args=(u2b, 5))
            t2a.start(); t2b.start()
            t2a.join(); t2b.join()

            assert all(code == 200 for _, code in results2)
            r2a = AnalyticQuestionnaireAnswer.query.filter_by(user_id=u2a["id"]).all()
            r2b = AnalyticQuestionnaireAnswer.query.filter_by(user_id=u2b["id"]).all()
            assert len(r2a) == 1 and r2a[0].value_numeric == 4
            assert len(r2b) == 1 and r2b[0].value_numeric == 5
            print("   -> [PASS] Ambos usuarios persistieron sus respuestas aisladamente (200 OK).")

            # -----------------------------------------------------------------
            # 3. Actualización de respuesta existente (UPSERT modifica valor)
            # -----------------------------------------------------------------
            print("\n[TEST 3] Actualización de respuesta existente (UPSERT modifica valor)...")
            res_upd = client.put("/api/v1/questionnaire/answers", headers=h1, json={
                "version": "draft-1",
                "answers": [{"question_id": "importance_fidelity", "value": 2}]
            })
            assert res_upd.status_code == 200
            val_check = AnalyticQuestionnaireAnswer.query.filter_by(user_id=u1["id"], variable_name="importance_fidelity").first()
            assert val_check.value_numeric == 2, f"Esperado 2, obtenido {val_check.value_numeric}"
            print("   -> [PASS] Valor actualizado correctamente de forma atómica a 2.")

            # -----------------------------------------------------------------
            # 4. Reintento de una solicitud idéntica (Idempotencia)
            # -----------------------------------------------------------------
            print("\n[TEST 4] Reintento de una solicitud idéntica (Idempotencia)...")
            res_retry = client.put("/api/v1/questionnaire/answers", headers=h1, json={
                "version": "draft-1",
                "answers": [{"question_id": "importance_fidelity", "value": 2}]
            })
            assert res_retry.status_code == 200
            u1_rows_after = AnalyticQuestionnaireAnswer.query.filter_by(user_id=u1["id"]).all()
            assert len(u1_rows_after) == 2, "La reejecución idéntica no debe crear filas adicionales."
            print("   -> [PASS] Idempotencia verificada: el estado de la BD no se altera.")

            # -----------------------------------------------------------------
            # 5. Pregunta duplicada dentro de una misma solicitud (Rechazo 422)
            # -----------------------------------------------------------------
            print("\n[TEST 5] Pregunta duplicada en el payload...")
            res_dup_payload = client.put("/api/v1/questionnaire/answers", headers=h1, json={
                "version": "draft-1",
                "answers": [
                    {"question_id": "importance_fidelity", "value": 5},
                    {"question_id": "importance_fidelity", "value": 3}
                ]
            })
            assert res_dup_payload.status_code == 422
            assert res_dup_payload.get_json()["error"]["code"] == "VALIDATION_ERROR"
            print("   -> [PASS] Rechazado con 422 VALIDATION_ERROR.")

            # -----------------------------------------------------------------
            # 6. Error de validación sin persistencia parcial
            # -----------------------------------------------------------------
            print("\n[TEST 6] Error de validación sin persistencia parcial (Rollback)...")
            u6 = make_user("rollback_test")
            created_users.append(u6["id"])
            h6 = {"Authorization": f"Bearer {u6['token']}"}

            # Enviar 1 válida y 1 inválida (value = 99)
            res_partial = client.put("/api/v1/questionnaire/answers", headers=h6, json={
                "version": "draft-1",
                "answers": [
                    {"question_id": "importance_fidelity", "value": 5},
                    {"question_id": "importance_honesty", "value": 99}
                ]
            })
            assert res_partial.status_code == 422
            u6_rows = AnalyticQuestionnaireAnswer.query.filter_by(user_id=u6["id"]).all()
            assert len(u6_rows) == 0, f"Persistencia parcial detectada! {len(u6_rows)} filas guardadas."
            print("   -> [PASS] Cero persistencia parcial; base de datos intacta tras error de validación.")

            # -----------------------------------------------------------------
            # 7. Imposibilidad de insertar duplicados mediante SQL directo
            # -----------------------------------------------------------------
            print("\n[TEST 7] Imposibilidad de insertar duplicados mediante SQL directo...")
            try:
                # Intentar insertar exactamente la misma clave primaria compuesta vía SQL raw
                db.session.execute(db.text("""
                    INSERT INTO analytic_questionnaire_answers (id, user_id, variable_name, value_numeric)
                    VALUES (:id1, :uid, 'importance_fidelity', 5)
                """), {"id1": str(uuid.uuid4()), "uid": u1["id"]})
                db.session.commit()
                raise AssertionError("FALLO: PostgreSQL permitió insertar duplicado físico!")
            except IntegrityError as e:
                db.session.rollback()
                assert "uq_analytic_questionnaire_user_variable" in str(e).lower() or "unique" in str(e).lower()
                print("   -> [PASS] PostgreSQL rechazó la inserción directa violando uq_analytic_questionnaire_user_variable.")

            # -----------------------------------------------------------------
            # 8. Acceso restringido a respuestas del usuario autenticado
            # -----------------------------------------------------------------
            print("\n[TEST 8] Aislamiento de lectura en GET /api/v1/questionnaire/answers...")
            res_get_u1 = client.get("/api/v1/questionnaire/answers", headers=h1)
            assert res_get_u1.status_code == 200
            ans_u1 = res_get_u1.get_json()["data"]["answers"]
            assert len(ans_u1) == 2

            res_get_u6 = client.get("/api/v1/questionnaire/answers", headers=h6)
            assert res_get_u6.status_code == 200
            ans_u6 = res_get_u6.get_json()["data"]["answers"]
            assert len(ans_u6) == 0, "Usuario u6 no debe ver las respuestas de u1!"
            print("   -> [PASS] Aislamiento estricto de lectura verificado.")

            print("\n" + "=" * 80)
            print("TODAS LAS 8 PRUEBAS DE CONCURRENCIA E INTEGRIDAD PASARON CON ÉXITO ROTUNDO")
            print("=" * 80)

        finally:
            # Limpieza limpia y aislada de los fixtures de prueba
            if created_users:
                AnalyticQuestionnaireAnswer.query.filter(AnalyticQuestionnaireAnswer.user_id.in_(created_users)).delete(synchronize_session=False)
                User.query.filter(User.id.in_(created_users)).delete(synchronize_session=False)
                db.session.commit()
                print("\n[LIMPIEZA COMPLETADA] Fixtures de prueba eliminadas de la base de datos.")

if __name__ == "__main__":
    run_tests()
