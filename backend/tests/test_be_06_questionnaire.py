"""
AFINIA — Test Suite BE-06: Cuestionario Analítico y Respuestas.
==============================================================
Verifica:
1. Autenticación JWT obligatoria en GET /api/v1/questionnaire, PUT /answers, GET /answers.
2. Consulta de catálogo de preguntas y versión.
3. Validación estricta de esquemas y tipos de datos en PUT /answers (422).
4. Persistencia en DB y semántica PUT idempotente (actualización sin duplicación).
5. Consulta de respuestas del usuario autenticado.
6. Aislamiento y privacidad estricta entre diferentes usuarios.
"""

import pytest
import uuid
from app import db
from app.models.user import User
from app.models.analytics import AnalyticQuestionnaireAnswer
from app.utils.security import create_access_token


@pytest.fixture
def test_user(app):
    """Crea un usuario autenticado de prueba."""
    with app.app_context():
        user = User(
            id=str(uuid.uuid4()),
            email="test_questionnaire@afinia.test",
            password_hash="fakehash",
            is_active=True,
            email_verified=True,
            role="user",
            lifecycle_status="active"
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(user.id, user.email, user.role, app.config['SECRET_KEY'])
        return {"user": user, "token": token}


@pytest.fixture
def other_user(app):
    """Crea un segundo usuario para pruebas de aislamiento y privacidad."""
    with app.app_context():
        user = User(
            id=str(uuid.uuid4()),
            email="other_questionnaire@afinia.test",
            password_hash="fakehash",
            is_active=True,
            email_verified=True,
            role="user",
            lifecycle_status="active"
        )
        db.session.add(user)
        db.session.commit()
        token = create_access_token(user.id, user.email, user.role, app.config['SECRET_KEY'])
        return {"user": user, "token": token}


class TestQuestionnaireAuthentication:
    """Verifica que todos los endpoints del cuestionario exijan JWT válido."""

    def test_get_questionnaire_without_token_returns_401(self, client):
        res = client.get('/api/v1/questionnaire')
        assert res.status_code == 401
        data = res.get_json()
        assert 'error' in data
        assert data['error']['code'] == 'UNAUTHORIZED'

    def test_put_answers_without_token_returns_401(self, client):
        res = client.put('/api/v1/questionnaire/answers', json={
            "version": "draft-1",
            "answers": [{"question_id": "importance_communication", "value": 5}]
        })
        assert res.status_code == 401
        data = res.get_json()
        assert 'error' in data
        assert data['error']['code'] == 'UNAUTHORIZED'

    def test_get_answers_without_token_returns_401(self, client):
        res = client.get('/api/v1/questionnaire/answers')
        assert res.status_code == 401
        data = res.get_json()
        assert 'error' in data
        assert data['error']['code'] == 'UNAUTHORIZED'

    def test_get_questionnaire_with_invalid_token_returns_401(self, client):
        headers = {'Authorization': 'Bearer token-invalido-o-expirado'}
        res = client.get('/api/v1/questionnaire', headers=headers)
        assert res.status_code == 401


class TestGetQuestionnaireCatalog:
    """Verifica la consulta del catálogo de preguntas."""

    def test_get_questionnaire_success(self, client, test_user):
        headers = {'Authorization': f"Bearer {test_user['token']}"}
        res = client.get('/api/v1/questionnaire', headers=headers)
        assert res.status_code == 200
        body = res.get_json()
        assert 'data' in body
        data = body['data']
        assert data['version'] == 'draft-1'
        assert isinstance(data['questions'], list)
        assert len(data['questions']) >= 2

        # Validar estructura de cada pregunta
        q1 = data['questions'][0]
        assert 'id' in q1
        assert 'label' in q1
        assert q1['type'] == 'scale_1_5'
        assert q1['required'] is True
        assert q1['min'] == 1
        assert q1['max'] == 5


class TestPutQuestionnaireAnswersValidation:
    """Verifica la validación estricta de esquemas de entrada (422)."""

    def test_put_answers_missing_body(self, client, test_user):
        headers = {'Authorization': f"Bearer {test_user['token']}"}
        res = client.put('/api/v1/questionnaire/answers', headers=headers)
        assert res.status_code == 422
        assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

    def test_put_answers_missing_version(self, client, test_user):
        headers = {'Authorization': f"Bearer {test_user['token']}"}
        res = client.put('/api/v1/questionnaire/answers', headers=headers, json={
            "answers": [{"question_id": "importance_communication", "value": 5}]
        })
        assert res.status_code == 422
        assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

    def test_put_answers_empty_answers_list(self, client, test_user):
        headers = {'Authorization': f"Bearer {test_user['token']}"}
        res = client.put('/api/v1/questionnaire/answers', headers=headers, json={
            "version": "draft-1",
            "answers": []
        })
        assert res.status_code == 422
        assert res.get_json()['error']['code'] == 'VALIDATION_ERROR'

    def test_put_answers_invalid_value_range(self, client, test_user):
        headers = {'Authorization': f"Bearer {test_user['token']}"}
        # Valor 0 (fuera de 1-5)
        res = client.put('/api/v1/questionnaire/answers', headers=headers, json={
            "version": "draft-1",
            "answers": [{"question_id": "importance_communication", "value": 0}]
        })
        assert res.status_code == 422

        # Valor 6 (fuera de 1-5)
        res2 = client.put('/api/v1/questionnaire/answers', headers=headers, json={
            "version": "draft-1",
            "answers": [{"question_id": "importance_communication", "value": 6}]
        })
        assert res2.status_code == 422

    def test_put_answers_invalid_value_types(self, client, test_user):
        headers = {'Authorization': f"Bearer {test_user['token']}"}
        # Booleano True no debe permitirse como entero válido
        res_bool = client.put('/api/v1/questionnaire/answers', headers=headers, json={
            "version": "draft-1",
            "answers": [{"question_id": "importance_communication", "value": True}]
        })
        assert res_bool.status_code == 422

        # String en vez de int
        res_str = client.put('/api/v1/questionnaire/answers', headers=headers, json={
            "version": "draft-1",
            "answers": [{"question_id": "importance_communication", "value": "5"}]
        })
        assert res_str.status_code == 422

    def test_put_answers_duplicate_questions_in_payload(self, client, test_user):
        headers = {'Authorization': f"Bearer {test_user['token']}"}
        res = client.put('/api/v1/questionnaire/answers', headers=headers, json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_communication", "value": 5},
                {"question_id": "importance_communication", "value": 4}
            ]
        })
        assert res.status_code == 422
        assert "duplicada" in res.get_json()['error']['message']


class TestQuestionnairePersistenceAndIdempotency:
    """Verifica la persistencia real y la semántica PUT idempotente."""

    def test_put_and_get_answers_lifecycle(self, client, test_user, app):
        headers = {'Authorization': f"Bearer {test_user['token']}"}

        # 1. Al inicio, respuestas vacías
        get_res_initial = client.get('/api/v1/questionnaire/answers', headers=headers)
        assert get_res_initial.status_code == 200
        assert get_res_initial.get_json()['data']['answers'] == []

        # 2. Guardar respuestas
        payload_1 = {
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_communication", "value": 5},
                {"question_id": "importance_values", "value": 4}
            ]
        }
        put_res = client.put('/api/v1/questionnaire/answers', headers=headers, json=payload_1)
        assert put_res.status_code == 200
        put_data = put_res.get_json()['data']
        assert put_data['version'] == "draft-1"
        assert put_data['saved_count'] == 2
        assert 'updated_at' in put_data

        # Verificar persistencia en base de datos
        with app.app_context():
            rows = AnalyticQuestionnaireAnswer.query.filter_by(user_id=test_user['user'].id).all()
            assert len(rows) == 2

        # 3. Consultar respuestas guardadas
        get_res = client.get('/api/v1/questionnaire/answers', headers=headers)
        assert get_res.status_code == 200
        answers_saved = get_res.get_json()['data']['answers']
        assert len(answers_saved) == 2
        ans_dict = {a['question_id']: a['value'] for a in answers_saved}
        assert ans_dict['importance_communication'] == 5
        assert ans_dict['importance_values'] == 4

        # 4. Semántica PUT idempotente: actualizar valor existente
        payload_update = {
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_communication", "value": 2}
            ]
        }
        put_res_2 = client.put('/api/v1/questionnaire/answers', headers=headers, json=payload_update)
        assert put_res_2.status_code == 200
        assert put_res_2.get_json()['data']['saved_count'] == 1

        # Verificar que NO se crearon filas duplicadas
        with app.app_context():
            rows_after = AnalyticQuestionnaireAnswer.query.filter_by(user_id=test_user['user'].id).all()
            # 2 filas totales: communication actualizada a 2, values sigue en 4
            assert len(rows_after) == 2

        get_res_updated = client.get('/api/v1/questionnaire/answers', headers=headers)
        ans_dict_updated = {a['question_id']: a['value'] for a in get_res_updated.get_json()['data']['answers']}
        assert ans_dict_updated['importance_communication'] == 2
        assert ans_dict_updated['importance_values'] == 4


class TestQuestionnairePrivacyAndIsolation:
    """Verifica que ningún usuario pueda consultar ni modificar respuestas de terceros."""

    def test_user_answers_isolation(self, client, test_user, other_user):
        headers_a = {'Authorization': f"Bearer {test_user['token']}"}
        headers_b = {'Authorization': f"Bearer {other_user['token']}"}

        # Usuario A guarda respuestas
        client.put('/api/v1/questionnaire/answers', headers=headers_a, json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_communication", "value": 5}
            ]
        })

        # Usuario B consulta sus respuestas: debe estar vacío
        res_b = client.get('/api/v1/questionnaire/answers', headers=headers_b)
        assert res_b.status_code == 200
        assert res_b.get_json()['data']['answers'] == []

        # Usuario B guarda sus propias respuestas con valor diferente
        client.put('/api/v1/questionnaire/answers', headers=headers_b, json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_communication", "value": 1}
            ]
        })

        # Usuario A sigue viendo su valor 5
        res_a_final = client.get('/api/v1/questionnaire/answers', headers=headers_a)
        ans_a = res_a_final.get_json()['data']['answers']
        assert len(ans_a) == 1
        assert ans_a[0]['value'] == 5

        # Usuario B sigue viendo su valor 1
        res_b_final = client.get('/api/v1/questionnaire/answers', headers=headers_b)
        ans_b = res_b_final.get_json()['data']['answers']
        assert len(ans_b) == 1
        assert ans_b[0]['value'] == 1
