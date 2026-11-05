#!/usr/bin/env python3
"""
AFINIA — BE-08.1: SCRIPT DE CERTIFICACIÓN FINAL DE RECUPERACIÓN DE CONTRASEÑA EN POSTGRESQL QA
Verificación integral en PostgreSQL real (127.0.0.1:55433 / afinia_qa_db):
- Esquema físico y catálogos PostgreSQL (tabla, columnas, índices UNIQUE, FK CASCADE).
- Flujo completo de recuperación (202 / 204 / 422) con EmailService in_memory.
- Verificación de que PostgreSQL almacena únicamente el hash SHA-256.
- Revocación determinista de JWT y refresh tokens dentro del mismo segundo (sin sleeps).
- Concurrencia real de consumo con hilos/conexiones independientes (exactamente 1 éxito 204, 1 rechazo 422).
- Limpieza selectiva sin TRUNCATE global.
"""
import os
import sys
import uuid
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from sqlalchemy import text

# Configurar path
sys.path.insert(0, os.path.abspath('backend'))
sys.path.insert(0, os.path.abspath('.'))

from app import create_app, db
from app.models.user import User
from app.models.auth import RefreshToken, EmailVerificationToken, PasswordResetToken
from app.services.email_service import email_service
from app.utils.security import verify_password, hash_password

def run_query(sql, params=None):
    """Ejecuta una consulta de solo lectura contra PostgreSQL QA usando una conexión fresca."""
    with db.engine.connect() as connection:
        return connection.execute(text(sql), params or {})

def run_certification():
    print("=" * 80)
    print("INICIANDO CERTIFICACIÓN BE-08.1 EN POSTGRESQL QA (127.0.0.1:55433 / afinia_qa_db)")
    print("=" * 80)

    app = create_app()
    client = app.test_client()

    with app.app_context():
        # 1. PRECONDICIONES Y CATÁLOGOS POSTGRESQL
        db_name = run_query("SELECT current_database()").scalar()
        alembic_rev = run_query("SELECT version_num FROM alembic_version").scalar()
        print(f"[PRE-CHECK] Base de datos conectada: {db_name}")
        print(f"[PRE-CHECK] Revisión Alembic activa: {alembic_rev}")

        assert db_name == "afinia_qa_db", f"Debe ejecutarse contra afinia_qa_db, actual: {db_name}"
        assert alembic_rev == "f4c2d8e1a3b5", f"Revisión requerida f4c2d8e1a3b5, actual: {alembic_rev}"

        # Catálogo físico de la tabla password_reset_tokens
        table_exists = run_query("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'password_reset_tokens'
            );
        """).scalar()
        assert table_exists is True, "La tabla password_reset_tokens no existe en PostgreSQL"

        cols = run_query("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'password_reset_tokens'
            ORDER BY ordinal_position;
        """).fetchall()
        col_names = [c[0] for c in cols]
        expected_cols = ['id', 'user_id', 'token_hash', 'created_at', 'expires_at', 'consumed_at', 'revoked_at']
        print(f"[CATALOG] Columnas físicas: {col_names}")
        for ec in expected_cols:
            assert ec in col_names, f"Falta la columna requerida: {ec}"

        # Índices
        indexes = run_query("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'password_reset_tokens';
        """).fetchall()
        idx_names = [i[0] for i in indexes]
        print(f"[CATALOG] Índices físicos: {idx_names}")
        assert 'ix_password_reset_tokens_token_hash' in idx_names, "Falta índice UNIQUE en token_hash"
        assert 'ix_password_reset_tokens_user_id' in idx_names, "Falta índice en user_id"

        # Clave foránea
        fk = run_query("""
            SELECT tc.constraint_name, rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc 
              ON tc.constraint_name = rc.constraint_name
            WHERE tc.table_name = 'password_reset_tokens'
              AND tc.constraint_type = 'FOREIGN KEY';
        """).fetchall()
        print(f"[CATALOG] Claves foráneas: {fk}")
        assert any('CASCADE' in f[1].upper() for f in fk), "La FK debe tener ON DELETE CASCADE"

        print("[OK] Verificación física de catálogos PostgreSQL completada.")

        # Identificador único de ejecución sintética
        run_id = uuid.uuid4().hex[:8]
        test_email = f"qa.recover.{run_id}@afinia.test"
        initial_password = "InitialPassword2026!#"
        created_user_ids = []

        try:
            # 2. REGISTRO, VERIFICACIÓN DE CORREO Y LOGIN INICIAL
            print("\n--- PASO 1: Registro y activación de usuario sintético ---")
            email_service.clear_sent_messages()
            reg_res = client.post('/api/v1/auth/register', json={
                'email': test_email,
                'password': initial_password,
                'accept_terms_version': 'v1-draft',
                'accept_privacy_version': 'v1-draft'
            })
            assert reg_res.status_code == 201, f"Error registro: {reg_res.get_json()}"
            user_id = reg_res.get_json()['data']['id']
            created_user_ids.append(user_id)

            # Confirmar verificación de correo vía endpoint canónico POST /api/v1/auth/verify-email
            ver_token = email_service.get_last_token_for(test_email)
            assert ver_token is not None, "Token de verificación de correo no capturado por email_service"
            v_res = client.post('/api/v1/auth/verify-email', json={'token': ver_token})
            assert v_res.status_code == 204, f"Error verificación de correo: {v_res.status_code}"
            print("[PASS] Correo verificado con éxito vía POST /api/v1/auth/verify-email (HTTP 204).")

            # Login inicial
            login_1 = client.post('/api/v1/auth/login', json={
                'email': test_email,
                'password': initial_password
            }, headers={'X-Client-Platform': 'mobile'})
            assert login_1.status_code == 200
            jwt_1 = login_1.get_json()['data']['access_token']
            refresh_1 = login_1.get_json()['data']['refresh_token']
            print(f"[PASS] Usuario creado, verificado y autenticado. JWT 1 emitido.")

            # Comprobar acceso con JWT 1
            me_1 = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {jwt_1}'})
            assert me_1.status_code == 200
            print("[PASS] JWT 1 funcional en /api/v1/auth/me (HTTP 200).")

            # 3. SOLICITUD DE RECUPERACIÓN (FORGOT PASSWORD)
            print("\n--- PASO 2: Solicitud de recuperación de contraseña ---")
            email_service.clear_sent_messages()
            forgot_res = client.post('/api/v1/auth/forgot-password', json={'email': test_email})
            assert forgot_res.status_code == 202, f"Esperado 202, recibido {forgot_res.status_code}"
            assert forgot_res.get_json()['data']['status'] == 'accepted'
            print("[PASS] POST /forgot-password respondió HTTP 202 Accepted conforme a OpenAPI.")

            raw_reset_token = email_service.get_last_password_reset_token_for(test_email)
            assert raw_reset_token is not None, "EmailService no capturó el token en memoria"
            print(f"[PASS] Token leído mediante mecanismo QA autorizado (longitud {len(raw_reset_token)}).")

            # 4. COMPROBACIÓN FÍSICA EN POSTGRESQL: ALMACENAMIENTO EXCLUSIVO DE HASH SHA-256
            print("\n--- PASO 3: Verificación de persistencia segura (Solo Hash SHA-256) ---")
            expected_hash = hashlib.sha256(raw_reset_token.encode('utf-8')).hexdigest()
            row = run_query("""
                SELECT id, user_id, token_hash, consumed_at, revoked_at
                FROM password_reset_tokens
                WHERE user_id = :uid
            """, {'uid': user_id}).fetchone()

            assert row is not None, "El registro de reset token no se guardó en PostgreSQL"
            stored_hash = row[2]
            assert stored_hash == expected_hash, "El hash almacenado en PostgreSQL no coincide con SHA-256(raw_token)"
            assert raw_reset_token not in stored_hash, "El token en claro NUNCA debe estar en la BD"
            print(f"[PASS] Hash SHA-256 verificado en tabla PostgreSQL: {stored_hash[:16]}...")

            # 5. RESTABLECIMIENTO EXITOSO CON TOKEN VÁLIDO (204)
            print("\n--- PASO 4: Restablecimiento de contraseña con token válido ---")
            new_password = "BrandNewPassword2026!#"
            reset_res = client.post('/api/v1/auth/reset-password', json={
                'token': raw_reset_token,
                'new_password': new_password
            })
            assert reset_res.status_code == 204, f"Esperado 204, recibido {reset_res.status_code}"
            assert reset_res.data == b"", "HTTP 204 debe tener cuerpo vacío"
            print("[PASS] POST /reset-password respondió HTTP 204 No Content conforme a OpenAPI.")

            # Comprobar en PostgreSQL que el token se marcó como consumido
            row_consumed = run_query("""
                SELECT consumed_at FROM password_reset_tokens WHERE user_id = :uid
            """, {'uid': user_id}).scalar()
            assert row_consumed is not None, "El campo consumed_at debe ser no nulo en PostgreSQL"
            print(f"[PASS] Token marcado como consumido en PostgreSQL a las {row_consumed}.")

            # 6. RECHAZO DE REUSO DE TOKEN (422)
            print("\n--- PASO 5: Rechazo de reuso de token ya consumido ---")
            reused_res = client.post('/api/v1/auth/reset-password', json={
                'token': raw_reset_token,
                'new_password': 'AnotherPassword2026!#'
            })
            assert reused_res.status_code == 422, f"Esperado 422, recibido {reused_res.status_code}"
            assert reused_res.get_json()['error']['code'] == 'VALIDATION_ERROR'
            print("[PASS] Reuso de token consumido rechazado con HTTP 422 VALIDATION_ERROR conforme a OpenAPI.")

            # 7. COMPROBACIÓN DE LOGIN CON CREDENCIALES ANTIGUAS Y NUEVAS
            print("\n--- PASO 6: Verificación de login con clave antigua y nueva ---")
            login_old = client.post('/api/v1/auth/login', json={
                'email': test_email,
                'password': initial_password
            })
            assert login_old.status_code == 401, "El login con la contraseña antigua debió fallar con 401"
            print("[PASS] Login con contraseña antigua rechazado con HTTP 401 UNAUTHORIZED.")

            login_2 = client.post('/api/v1/auth/login', json={
                'email': test_email,
                'password': new_password
            }, headers={'X-Client-Platform': 'mobile'})
            assert login_2.status_code == 200, f"Error en login nuevo: {login_2.get_json()}"
            jwt_2 = login_2.get_json()['data']['access_token']
            refresh_2 = login_2.get_json()['data']['refresh_token']
            print("[PASS] Login con contraseña nueva aceptado con HTTP 200 OK. JWT 2 emitido.")

            # 8. REVOCACIÓN INMEDIATA DE SESIONES ANTERIORES
            print("\n--- PASO 7: Revocación inmediata de refresh token y JWT anteriores ---")
            # Refresh token anterior revocado
            ref_res = client.post('/api/v1/auth/refresh', json={'refresh_token': refresh_1})
            assert ref_res.status_code == 401, f"El refresh token anterior debió fallar: {ref_res.status_code}"
            print("[PASS] Refresh token anterior rechazado con HTTP 401 UNAUTHORIZED.")

            # JWT 1 (anterior) revocado inmediatamente
            me_old = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {jwt_1}'})
            assert me_old.status_code == 401, f"El JWT anterior debió ser rechazado: {me_old.status_code}"
            assert 'revocada' in me_old.get_json()['error']['message'].lower()
            print("[PASS] JWT 1 rechazado inmediatamente con HTTP 401 UNAUTHORIZED (Sesión revocada).")

            # JWT 2 (nuevo) aceptado inmediatamente
            me_new = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {jwt_2}'})
            assert me_new.status_code == 200
            print("[PASS] JWT 2 aceptado inmediatamente en /api/v1/auth/me (HTTP 200).")

            # 9. ESCENARIO TEMPORAL ESTRICTO: SUBSEGUNDO / MISMO SEGUNDO SIN SLEEPS (Sección 3)
            print("\n--- PASO 8: Escenario temporal subsegundo sin sleeps (5 ciclos) ---")
            app.config['PASSWORD_RESET_COOLDOWN_SECONDS'] = 0
            curr_pwd = new_password

            for iteration in range(1, 6):
                # A. Emitir JWT antiguo
                l_pre = client.post('/api/v1/auth/login', json={
                    'email': test_email,
                    'password': curr_pwd
                }, headers={'X-Client-Platform': 'web'})
                assert l_pre.status_code == 200
                jwt_old_iter = l_pre.get_json()['data']['access_token']
                assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {jwt_old_iter}'}).status_code == 200

                # B. Restablecer contraseña de inmediato (sin sleep)
                client.post('/api/v1/auth/forgot-password', json={'email': test_email})
                tok_iter = email_service.get_last_password_reset_token_for(test_email)
                next_pwd = f"SubsecondPwd_{iteration}_{run_id}!#"
                r_iter = client.post('/api/v1/auth/reset-password', json={
                    'token': tok_iter,
                    'new_password': next_pwd
                })
                assert r_iter.status_code == 204

                # C. Emitir JWT nuevo inmediatamente dentro del mismo segundo (cero sleep)
                l_post = client.post('/api/v1/auth/login', json={
                    'email': test_email,
                    'password': next_pwd
                }, headers={'X-Client-Platform': 'web'})
                assert l_post.status_code == 200
                jwt_new_iter = l_post.get_json()['data']['access_token']

                # D. JWT antiguo falla con 401 y JWT nuevo funciona con 200
                res_old_check = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {jwt_old_iter}'})
                res_new_check = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {jwt_new_iter}'})
                assert res_old_check.status_code == 401, f"Ciclo {iteration}: JWT antiguo debió ser 401"
                assert res_new_check.status_code == 200, f"Ciclo {iteration}: JWT nuevo debió ser 200"

                curr_pwd = next_pwd
            print("[PASS] Escenario temporal subsegundo superó 5 ciclos consecutivos sin sleeps.")

            # 10. CONCURRENCIA DE CONSUMO EN POSTGRESQL (Sección 6)
            print("\n--- PASO 9: Concurrencia de consumo con 2 conexiones simultáneas ---")
            client.post('/api/v1/auth/forgot-password', json={'email': test_email})
            concurrent_token = email_service.get_last_password_reset_token_for(test_email)
            assert concurrent_token is not None

            race_results = []
            def _race_worker(name, pwd_attempt):
                with app.app_context():
                    try:
                        c = app.test_client()
                        r = c.post('/api/v1/auth/reset-password', json={
                            'token': concurrent_token,
                            'new_password': pwd_attempt
                        })
                        race_results.append((r.status_code, name, r.get_json() if r.status_code != 204 else None))
                    finally:
                        db.session.remove()

            t1 = threading.Thread(target=_race_worker, args=('Worker-1', f'ConcRacePwd1_{run_id}!#'))
            t2 = threading.Thread(target=_race_worker, args=('Worker-2', f'ConcRacePwd2_{run_id}!#'))

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            status_list = [res[0] for res in race_results]
            print(f"[CONCURRENCY] Resultados de carrera: {race_results}")
            assert status_list.count(204) == 1, f"Exactamente 1 petición debió ganar (204): {status_list}"
            assert status_list.count(422) == 1, f"Exactamente 1 petición debió ser rechazada (422): {status_list}"
            print("[PASS] Carrera de concurrencia: exactamente un éxito (204) y un rechazo (422).")

            # 11. CONCURRENCIA DE BLOQUEO MUTUO EN POSTGRESQL QA (BE-08.2 Sección 2)
            print("\n--- PASO 10: Concurrencia real de bloqueo mutuo (A -> B y B -> A) en PostgreSQL QA ---")
            peer_email = f"qa.peer.{run_id}@afinia.test"
            peer_pwd = "PeerSecurePassword2026!#"
            reg_peer = client.post('/api/v1/auth/register', json={
                'email': peer_email,
                'password': peer_pwd,
                'accept_terms_version': 'v1-draft',
                'accept_privacy_version': 'v1-draft'
            })
            assert reg_peer.status_code == 201
            peer_id = reg_peer.get_json()['data']['id']
            created_user_ids.append(peer_id)

            peer_ver_tok = email_service.get_last_token_for(peer_email)
            assert client.post('/api/v1/auth/verify-email', json={'token': peer_ver_tok}).status_code == 204

            # Obtener tokens vigentes para ambos usuarios
            winning_pwd = [pwd for code, _, _ in race_results for pwd in (f'ConcRacePwd1_{run_id}!#', f'ConcRacePwd2_{run_id}!#') if code == 204]
            # Autenticar con la contraseña ganadora de la carrera anterior
            jwt_u1 = None
            for candidate_pwd in (f'ConcRacePwd1_{run_id}!#', f'ConcRacePwd2_{run_id}!#'):
                r_log = client.post('/api/v1/auth/login', json={'email': test_email, 'password': candidate_pwd})
                if r_log.status_code == 200:
                    jwt_u1 = r_log.get_json()['data']['access_token']
                    break
            assert jwt_u1 is not None, "No se pudo autenticar u1 tras carrera"

            r_log_peer = client.post('/api/v1/auth/login', json={'email': peer_email, 'password': peer_pwd})
            assert r_log_peer.status_code == 200
            jwt_u2 = r_log_peer.get_json()['data']['access_token']

            headers_u1 = {'Authorization': f'Bearer {jwt_u1}', 'Content-Type': 'application/json'}
            headers_u2 = {'Authorization': f'Bearer {jwt_u2}', 'Content-Type': 'application/json'}

            block_race_results = []
            block_barrier = threading.Barrier(2)

            def _pg_block_ab():
                with app.app_context():
                    try:
                        c = app.test_client()
                        block_barrier.wait(timeout=5)
                        r = c.put(f'/api/v1/users/{peer_id}/block', headers=headers_u1)
                        block_race_results.append((r.status_code, 'u1_blocks_u2'))
                    finally:
                        db.session.remove()

            def _pg_block_ba():
                with app.app_context():
                    try:
                        c = app.test_client()
                        block_barrier.wait(timeout=5)
                        r = c.put(f'/api/v1/users/{user_id}/block', headers=headers_u2)
                        block_race_results.append((r.status_code, 'u2_blocks_u1'))
                    finally:
                        db.session.remove()

            tb1 = threading.Thread(target=_pg_block_ab)
            tb2 = threading.Thread(target=_pg_block_ba)
            tb1.start()
            tb2.start()
            tb1.join()
            tb2.join()

            print(f"[PG-BLOCK-CONCURRENCY] Resultados: {block_race_results}")
            assert all(code == 200 for code, _ in block_race_results), f"Bloqueo mutuo falló: {block_race_results}"
            cnt_ab = run_query("SELECT COUNT(*) FROM user_blocks WHERE blocker_user_id = :u1 AND blocked_user_id = :u2", {'u1': user_id, 'u2': peer_id}).scalar()
            cnt_ba = run_query("SELECT COUNT(*) FROM user_blocks WHERE blocker_user_id = :u2 AND blocked_user_id = :u1", {'u1': user_id, 'u2': peer_id}).scalar()
            assert cnt_ab == 1 and cnt_ba == 1, f"Filas en user_blocks inconsistentes: ab={cnt_ab}, ba={cnt_ba}"
            print("[PASS] Bloqueo mutuo concurrente en PostgreSQL QA persistió exactamente 2 filas sin deadlocks.")

        finally:
            # 12. LIMPIEZA SELECTIVA POR UUID EXACTO EN POSTGRESQL
            print("\n--- LIMPIEZA SELECTIVA: Eliminando registros sintéticos por UUID exacto ---")
            if created_user_ids:
                with db.engine.begin() as write_conn:
                    write_conn.execute(text("DELETE FROM user_blocks WHERE blocker_user_id = ANY(:uids) OR blocked_user_id = ANY(:uids)"), {'uids': created_user_ids})
                    write_conn.execute(text("DELETE FROM password_reset_tokens WHERE user_id = ANY(:uids)"), {'uids': created_user_ids})
                    write_conn.execute(text("DELETE FROM refresh_tokens WHERE user_id = ANY(:uids)"), {'uids': created_user_ids})
                    write_conn.execute(text("DELETE FROM email_verification_tokens WHERE user_id = ANY(:uids)"), {'uids': created_user_ids})
                    write_conn.execute(text("DELETE FROM legal_consents WHERE user_id = ANY(:uids)"), {'uids': created_user_ids})
                    write_conn.execute(text("DELETE FROM users WHERE id = ANY(:uids)"), {'uids': created_user_ids})
                
                # Verificar ausencia de datos residuales
                remaining_blocks = run_query("SELECT COUNT(*) FROM user_blocks WHERE blocker_user_id = ANY(:uids) OR blocked_user_id = ANY(:uids)", {'uids': created_user_ids}).scalar()
                remaining_tokens = run_query("SELECT COUNT(*) FROM password_reset_tokens WHERE user_id = ANY(:uids)", {'uids': created_user_ids}).scalar()
                remaining_users = run_query("SELECT COUNT(*) FROM users WHERE id = ANY(:uids)", {'uids': created_user_ids}).scalar()
                assert remaining_blocks == 0 and remaining_tokens == 0 and remaining_users == 0, "No se completó la limpieza"
                print(f"[CLEANUP] Usuarios sintéticos ({created_user_ids}) y entidades asociadas purgados por UUID exacto sin datos residuales.")

    print("\n" + "=" * 80)
    print("CERTIFICACIÓN BE-08.1 COMPLETADA SATISFACTORIAMENTE EN POSTGRESQL QA (PASS)")
    print("=" * 80)

if __name__ == '__main__':
    run_certification()
