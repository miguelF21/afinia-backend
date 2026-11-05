#!/usr/bin/env python3
"""
AFINIA — BE-05: PRUEBA SMOKE HTTP E2E (15 PASOS)
Verificación de extremo a extremo del flujo de API con datos sintéticos y limpieza selectiva.
Sin TRUNCATE global, preservando la integridad de PostgreSQL QA.
"""
import os
import sys
import io
import uuid
from datetime import datetime, timezone
from PIL import Image

# Configurar path para importar la aplicación Flask
sys.path.insert(0, os.path.abspath('backend'))
sys.path.insert(0, os.path.abspath('.'))

from app import create_app, db
from app.services.email_service import email_service
from app.services.storage_service import storage_adapter
from app.services.profile_service import sync_user_lifecycle_status
from app.models.user import User
from app.models.profile import Profile, ProfilePhoto
from app.models.discovery import DiscoveryPreference
from app.models.match import Match
from app.models.message import Message
from app.models.interaction import ProfileInteraction
from app.models.block import UserBlock
from app.models.report import UserReport
from app.models.auth import RefreshToken, EmailVerificationToken
from app.models.legal import LegalConsent

def run_smoke_test():
    print("=" * 80)
    print("INICIANDO PRUEBA SMOKE HTTP E2E — AFINIA (15 PASOS CANÓNICOS)")
    print("=" * 80)
    
    app = create_app()
    client = app.test_client()
    
    with app.app_context():
        # Verificación previa de conexión QA
        conn = db.session.connection()
        from sqlalchemy import text
        db_name = conn.execute(text("SELECT current_database()")).scalar()
        alembic_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"[PRE-CHECK] DB: {db_name}, Alembic: {alembic_rev}")
        assert db_name == "afinia_qa_db", "Debe ejecutarse contra afinia_qa_db"
        assert alembic_rev == "f4c2d8e1a3b5", "Debe tener revisión f4c2d8e1a3b5"
        
        # Generar datos sintéticos únicos
        run_id = uuid.uuid4().hex[:8]
        u1_email = f"smoke_u1_{run_id}@qa.afinia.test"
        u2_email = f"smoke_u2_{run_id}@qa.afinia.test"
        password = "Password123*Secure!"
        
        created_user_ids = []
        created_match_id = None
        
        try:
            # -------------------------------------------------------------
            # PASO 1: REGISTRO (POST /api/v1/auth/register)
            # -------------------------------------------------------------
            print("\n[PASO 1] Registro de dos usuarios sintéticos...")
            res1 = client.post('/api/v1/auth/register', json={
                'email': u1_email,
                'password': password,
                'accept_terms_version': 'v1-draft',
                'accept_privacy_version': 'v1-draft'
            })
            assert res1.status_code == 201, f"Fallo registro User 1: {res1.get_json()}"
            u1_id = res1.get_json()['data']['id']
            created_user_ids.append(u1_id)
            print(f" -> User 1 registrado: ID={u1_id}, Email={u1_email} [HTTP 201]")
            
            res2 = client.post('/api/v1/auth/register', json={
                'email': u2_email,
                'password': password,
                'accept_terms_version': 'v1-draft',
                'accept_privacy_version': 'v1-draft'
            })
            assert res2.status_code == 201, f"Fallo registro User 2: {res2.get_json()}"
            u2_id = res2.get_json()['data']['id']
            created_user_ids.append(u2_id)
            print(f" -> User 2 registrado: ID={u2_id}, Email={u2_email} [HTTP 201]")

            # -------------------------------------------------------------
            # PASO 2: VERIFICACIÓN DE CORREO (POST /api/v1/auth/verify-email)
            # -------------------------------------------------------------
            print("\n[PASO 2] Verificación de correo vía token QA...")
            t1 = email_service.get_last_token_for(u1_email)
            t2 = email_service.get_last_token_for(u2_email)
            assert t1 and t2, "Tokens de verificación no encontrados en email_service"
            
            v_res1 = client.post('/api/v1/auth/verify-email', json={'token': t1})
            assert v_res1.status_code == 204, f"Fallo verificación User 1: código {v_res1.status_code}"
            print(" -> User 1 verificado [HTTP 204]")
            
            v_res2 = client.post('/api/v1/auth/verify-email', json={'token': t2})
            assert v_res2.status_code == 204, f"Fallo verificación User 2: código {v_res2.status_code}"
            print(" -> User 2 verificado [HTTP 204]")

            # -------------------------------------------------------------
            # PASO 3: LOGIN (POST /api/v1/auth/login con X-Client-Platform: mobile)
            # -------------------------------------------------------------
            print("\n[PASO 3] Login de ambos usuarios con cabecera móvil...")
            l1 = client.post('/api/v1/auth/login', 
                             headers={'X-Client-Platform': 'mobile'},
                             json={'email': u1_email, 'password': password})
            assert l1.status_code == 200, f"Fallo login User 1: {l1.get_json()}"
            token1 = l1.get_json()['data']['access_token']
            h1 = {'Authorization': f'Bearer {token1}', 'X-Client-Platform': 'mobile'}
            print(" -> User 1 autenticado exitosamente [HTTP 200]")
            
            l2 = client.post('/api/v1/auth/login',
                             headers={'X-Client-Platform': 'mobile'},
                             json={'email': u2_email, 'password': password})
            assert l2.status_code == 200, f"Fallo login User 2: {l2.get_json()}"
            token2 = l2.get_json()['data']['access_token']
            h2 = {'Authorization': f'Bearer {token2}', 'X-Client-Platform': 'mobile'}
            print(" -> User 2 autenticado exitosamente [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 4: CREACIÓN DE PERFIL (POST /api/v1/profile)
            # -------------------------------------------------------------
            print("\n[PASO 4] Creación de perfiles completos...")
            p1 = client.post('/api/v1/profile', headers=h1, json={
                'first_name': 'Carlos',
                'birth_date': '1998-05-15',
                'gender': 'masculino',
                'bio': 'Ingeniero de software en prueba smoke.',
                'city': 'Barranquilla'
            })
            assert p1.status_code == 201, f"Fallo perfil User 1: {p1.get_json()}"
            prof1_user_id = p1.get_json()['data']['user_id']
            print(f" -> Perfil User 1 creado: UserID={prof1_user_id} [HTTP 201]")
            
            p2 = client.post('/api/v1/profile', headers=h2, json={
                'first_name': 'Valeria',
                'birth_date': '1999-08-20',
                'gender': 'femenino',
                'bio': 'Diseñadora UX en prueba smoke.',
                'city': 'Barranquilla'
            })
            assert p2.status_code == 201, f"Fallo perfil User 2: {p2.get_json()}"
            prof2_user_id = p2.get_json()['data']['user_id']
            print(f" -> Perfil User 2 creado: UserID={prof2_user_id} [HTTP 201]")

            # -------------------------------------------------------------
            # PASO 5: CONFIGURACIÓN DE PREFERENCIAS (PUT /api/v1/profile/discovery-preferences)
            # -------------------------------------------------------------
            print("\n[PASO 5] Configuración de preferencias de descubrimiento...")
            pref1 = client.put('/api/v1/profile/discovery-preferences', headers=h1, json={
                'min_age': 18,
                'max_age': 35,
                'interested_in_genders': ['femenino', 'masculino'],
                'target_relationship_type': 'amistad'
            })
            assert pref1.status_code == 200, f"Fallo preferencias User 1: {pref1.get_json()}"
            print(" -> Preferencias User 1 configuradas [HTTP 200]")
            
            pref2 = client.put('/api/v1/profile/discovery-preferences', headers=h2, json={
                'min_age': 18,
                'max_age': 35,
                'interested_in_genders': ['masculino', 'femenino'],
                'target_relationship_type': 'amistad'
            })
            assert pref2.status_code == 200, f"Fallo preferencias User 2: {pref2.get_json()}"
            print(" -> Preferencias User 2 configuradas [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 6: FOTOGRAFÍAS (POST /api/v1/profile/photos)
            # -------------------------------------------------------------
            print("\n[PASO 6] Carga y verificación de fotografías...")
            img = Image.new('RGB', (200, 200), color=(74, 144, 226))
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG')
            img_bytes = img_byte_arr.getvalue()
            
            # Subir foto User 1
            data1 = {'file': (io.BytesIO(img_bytes), 'photo1.jpg', 'image/jpeg')}
            ph1 = client.post('/api/v1/profile/photos', headers=h1, data=data1, content_type='multipart/form-data')
            assert ph1.status_code == 201, f"Fallo subida foto User 1: {ph1.get_json()}"
            photo1_id = ph1.get_json()['data']['id']
            print(f" -> Foto User 1 subida: ID={photo1_id} [HTTP 201]")
            
            # Subir foto User 2
            data2 = {'file': (io.BytesIO(img_bytes), 'photo2.jpg', 'image/jpeg')}
            ph2 = client.post('/api/v1/profile/photos', headers=h2, data=data2, content_type='multipart/form-data')
            assert ph2.status_code == 201, f"Fallo subida foto User 2: {ph2.get_json()}"
            photo2_id = ph2.get_json()['data']['id']
            print(f" -> Foto User 2 subida: ID={photo2_id} [HTTP 201]")
            
            # Aprobación controlada de fotos (status='ready') y sincronización a lifecycle 'active'
            db_p1 = db.session.get(ProfilePhoto, photo1_id)
            db_p1.status = 'ready'
            user1_obj = db.session.get(User, u1_id)
            sync_user_lifecycle_status(user1_obj)

            db_p2 = db.session.get(ProfilePhoto, photo2_id)
            db_p2.status = 'ready'
            user2_obj = db.session.get(User, u2_id)
            sync_user_lifecycle_status(user2_obj)
            db.session.commit()
            print(" -> Fotografías aprobadas a 'ready' y lifecycle sincronizado a 'active'.")

            # Verificar visualización de fotografía autenticada
            media_res = client.get(f'/api/v1/profile/photos/media/{photo1_id}', headers=h2)
            assert media_res.status_code == 200, f"Fallo descarga foto User 1 por User 2: {media_res.status_code}"
            assert media_res.mimetype == 'image/jpeg'
            assert 'private' in media_res.headers.get('Cache-Control', '')
            print(" -> Descarga autenticada de imagen con Cache-Control privado validada [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 7: DESCUBRIMIENTO (GET /api/v1/match/potential)
            # -------------------------------------------------------------
            print("\n[PASO 7] Consulta de candidatos potenciales de descubrimiento...")
            pot1 = client.get('/api/v1/match/potential', headers=h1)
            assert pot1.status_code == 200, f"Fallo descubrimiento: {pot1.get_json()}"
            candidates = pot1.get_json()['data']['items']
            candidate_ids = [c['user_id'] for c in candidates]
            assert u2_id in candidate_ids, f"User 2 ({u2_id}) debe aparecer en candidatos de User 1. Candidatos: {candidate_ids}"
            print(f" -> User 2 encontrado en candidatos potenciales de User 1 ({len(candidates)} candidatos) [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 8: LIKE RECÍPROCO (POST /api/v1/match/swipe)
            # -------------------------------------------------------------
            print("\n[PASO 8] LIKE recíproco...")
            sw1 = client.post('/api/v1/match/swipe', headers=h1, json={
                'target_user_id': u2_id,
                'action': 'LIKE'
            })
            assert sw1.status_code == 200, f"Fallo swipe 1: {sw1.get_json()}"
            assert sw1.get_json()['data']['is_match'] is False, "Primer swipe no debe ser match aún"
            print(" -> Swipe 1 (User 1 -> LIKE User 2) registrado. is_match=False [HTTP 200]")
            
            sw2 = client.post('/api/v1/match/swipe', headers=h2, json={
                'target_user_id': u1_id,
                'action': 'LIKE'
            })
            assert sw2.status_code == 200, f"Fallo swipe 2: {sw2.get_json()}"
            sw2_data = sw2.get_json()['data']
            assert sw2_data['is_match'] is True, "Segundo swipe recíproco DEBE generar match"
            created_match_id = sw2_data['match_id']
            print(f" -> Swipe 2 (User 2 -> LIKE User 1) registrado. is_match=True, Match ID={created_match_id} [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 9: LISTADO Y DETALLE DE MATCH (GET /api/v1/match/my-matches)
            # -------------------------------------------------------------
            print("\n[PASO 9] Consulta de listado y detalle del Match...")
            m_list = client.get('/api/v1/match/my-matches', headers=h1)
            assert m_list.status_code == 200, f"Fallo listado matches: {m_list.get_json()}"
            matches = m_list.get_json()['data']['items']
            assert any(m['id'] == created_match_id for m in matches), "Match creado debe aparecer en lista"
            print(f" -> Match confirmado en listado de User 1 ({len(matches)} matches activos) [HTTP 200]")
            
            m_det = client.get(f'/api/v1/match/{created_match_id}', headers=h1)
            assert m_det.status_code == 200, f"Fallo detalle match: {m_det.get_json()}"
            print(" -> Detalle de match obtenido exitosamente [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 10: MENSAJERÍA (POST y GET /api/v1/match/{matchId}/messages)
            # -------------------------------------------------------------
            print("\n[PASO 10] Envío y consulta de mensajes...")
            sm1 = client.post(f'/api/v1/match/{created_match_id}/messages', headers=h1, json={
                'text': '¡Hola Valeria! Qué coincidencia encontrarte aquí en Afinia.'
            })
            assert sm1.status_code == 201, f"Fallo envío mensaje: {sm1.get_json()}"
            msg1_id = sm1.get_json()['data']['id']
            print(f" -> Mensaje 1 enviado por User 1: ID={msg1_id} [HTTP 201]")
            
            sm2 = client.post(f'/api/v1/match/{created_match_id}/messages', headers=h2, json={
                'text': '¡Hola Carlos! Totalmente, me encanta tu perfil.'
            })
            assert sm2.status_code == 201, f"Fallo envío mensaje 2: {sm2.get_json()}"
            msg2_id = sm2.get_json()['data']['id']
            print(f" -> Mensaje 2 enviado por User 2: ID={msg2_id} [HTTP 201]")
            
            m_hist = client.get(f'/api/v1/match/{created_match_id}/messages', headers=h1)
            assert m_hist.status_code == 200, f"Fallo historial mensajes: {m_hist.get_json()}"
            messages = m_hist.get_json()['data']['items']
            assert len(messages) == 2, f"Se esperaban 2 mensajes, se obtuvieron {len(messages)}"
            print(f" -> Historial de mensajes verificado ({len(messages)} mensajes) [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 11: MARCADO DE LECTURA (POST /api/v1/match/{matchId}/read)
            # -------------------------------------------------------------
            print("\n[PASO 11] Marcado de lectura de mensajes recibidos...")
            rd = client.post(f'/api/v1/match/{created_match_id}/read', headers=h1)
            assert rd.status_code == 200, f"Fallo marcado lectura: {rd.get_json()}"
            rd_data = rd.get_json()['data']
            assert rd_data['unread_count'] == 0
            print(f" -> Mensajes marcados como leídos por User 1: unread_count={rd_data['unread_count']} [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 12: BLOQUEO Y DESBLOQUEO (PUT/GET/DELETE /api/v1/users/{userId}/block)
            # -------------------------------------------------------------
            print("\n[PASO 12] Bloqueo y desbloqueo de usuarios...")
            blk = client.put(f'/api/v1/users/{u2_id}/block', headers=h1)
            assert blk.status_code == 200, f"Fallo bloqueo: {blk.get_json()}"
            print(" -> User 1 bloqueó a User 2 [HTTP 200]")
            
            blks = client.get('/api/v1/users/me/blocks', headers=h1)
            assert blks.status_code == 200, f"Fallo listado bloqueos: {blks.get_json()}"
            assert any(b['user_id'] == u2_id for b in blks.get_json()['data']['items']), "User 2 debe estar en lista de bloqueados"
            print(" -> User 2 confirmado en /api/v1/users/me/blocks [HTTP 200]")
            
            unblk = client.delete(f'/api/v1/users/{u2_id}/block', headers=h1)
            assert unblk.status_code == 204, f"Fallo desbloqueo: {unblk.status_code}"
            print(" -> User 1 desbloqueó a User 2 [HTTP 204]")

            # -------------------------------------------------------------
            # PASO 13: REPORTE DE USUARIO (POST /api/v1/users/{userId}/reports)
            # -------------------------------------------------------------
            print("\n[PASO 13] Reporte de usuario por conducta sospechosa...")
            rep = client.post(f'/api/v1/users/{u2_id}/reports', headers=h1, json={
                'reason': 'spam',
                'description': 'Comportamiento sospechoso verificado en prueba smoke automatizada.'
            })
            assert rep.status_code == 201, f"Fallo reporte: {rep.get_json()}"
            rep_id = rep.get_json()['data']['report_id']
            print(f" -> Reporte registrado exitosamente: ID={rep_id} [HTTP 201]")

            # -------------------------------------------------------------
            # PASO 14: UNMATCH CON HISTORIAL (DELETE /api/v1/match/{matchId})
            # -------------------------------------------------------------
            print("\n[PASO 14] Cierre lógico de match (Unmatch con mensajes existentes)...")
            unm = client.delete(f'/api/v1/match/{created_match_id}', headers=h1)
            assert unm.status_code == 204, f"Fallo unmatch: {unm.status_code}"
            print(f" -> Match {created_match_id} cerrado lógicamente por User 1 [HTTP 204]")
            
            m_list_after = client.get('/api/v1/match/my-matches', headers=h1)
            matches_after = m_list_after.get_json()['data']['items']
            assert not any(m['id'] == created_match_id for m in matches_after), "Match cerrado no debe aparecer en activos"
            print(" -> Match cerrado verificado ausente de /match/my-matches [HTTP 200]")

            # -------------------------------------------------------------
            # PASO 15: COMPROBACIÓN DE QUE EL CHAT CERRADO NO PUEDE UTILIZARSE
            # -------------------------------------------------------------
            print("\n[PASO 15] Comprobación de inaccesibilidad del chat cerrado...")
            send_closed = client.post(f'/api/v1/match/{created_match_id}/messages', headers=h1, json={
                'text': 'Este mensaje no debería permitirse en chat cerrado.'
            })
            assert send_closed.status_code == 404, f"Se esperaba 404 en chat cerrado, se obtuvo {send_closed.status_code}"
            assert send_closed.get_json()['error']['code'] == 'NOT_FOUND'
            print(" -> Intento de envío en match cerrado rechazado estrictamente con 404 NOT_FOUND [HTTP 404]")
            
            get_closed = client.get(f'/api/v1/match/{created_match_id}/messages', headers=h1)
            assert get_closed.status_code == 404, f"Se esperaba 404 en consulta de chat cerrado, se obtuvo {get_closed.status_code}"
            assert get_closed.get_json()['error']['code'] == 'NOT_FOUND'
            print(" -> Intento de consulta en match cerrado rechazado estrictamente con 404 NOT_FOUND [HTTP 404]")

            print("\n" + "=" * 80)
            print("¡LOS 15 PASOS DE LA PRUEBA SMOKE HTTP E2E CONCLUYERON CON ÉXITO ROTUNDO!")
            print("=" * 80)

        finally:
            # LIMPIEZA SELECTIVA ESTRICTA (Únicamente registros de esta prueba)
            print("\n[CLEANUP] Ejecutando limpieza selectiva de registros sintéticos...")
            if created_user_ids:
                profiles = Profile.query.filter(Profile.user_id.in_(created_user_ids)).all()
                profile_ids = [p.id for p in profiles]
                if profile_ids:
                    photos = ProfilePhoto.query.filter(ProfilePhoto.profile_id.in_(profile_ids)).all()
                    for photo in photos:
                        try:
                            storage_adapter.delete_file(photo.storage_key)
                        except Exception as e:
                            print(f"Aviso al borrar foto física: {e}")
                    ProfilePhoto.query.filter(ProfilePhoto.profile_id.in_(profile_ids)).delete(synchronize_session=False)

                Message.query.filter(Message.sender_user_id.in_(created_user_ids)).delete(synchronize_session=False)
                if created_match_id:
                    Message.query.filter(Message.match_id == created_match_id).delete(synchronize_session=False)
                    Match.query.filter(Match.id == created_match_id).delete(synchronize_session=False)
                Match.query.filter((Match.user_a_id.in_(created_user_ids)) | (Match.user_b_id.in_(created_user_ids))).delete(synchronize_session=False)
                UserReport.query.filter((UserReport.reporter_user_id.in_(created_user_ids)) | (UserReport.reported_user_id.in_(created_user_ids))).delete(synchronize_session=False)
                UserBlock.query.filter((UserBlock.blocker_user_id.in_(created_user_ids)) | (UserBlock.blocked_user_id.in_(created_user_ids))).delete(synchronize_session=False)
                ProfileInteraction.query.filter((ProfileInteraction.viewer_user_id.in_(created_user_ids)) | (ProfileInteraction.shown_user_id.in_(created_user_ids))).delete(synchronize_session=False)
                DiscoveryPreference.query.filter(DiscoveryPreference.user_id.in_(created_user_ids)).delete(synchronize_session=False)
                Profile.query.filter(Profile.user_id.in_(created_user_ids)).delete(synchronize_session=False)
                LegalConsent.query.filter(LegalConsent.user_id.in_(created_user_ids)).delete(synchronize_session=False)
                RefreshToken.query.filter(RefreshToken.user_id.in_(created_user_ids)).delete(synchronize_session=False)
                EmailVerificationToken.query.filter(EmailVerificationToken.user_id.in_(created_user_ids)).delete(synchronize_session=False)
                User.query.filter(User.id.in_(created_user_ids)).delete(synchronize_session=False)
                db.session.commit()
                print(f"[CLEANUP OK] {len(created_user_ids)} usuarios sintéticos y todas sus entidades asociadas eliminados.")

if __name__ == '__main__':
    run_smoke_test()
