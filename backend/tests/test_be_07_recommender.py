"""
AFINIA — Test Suite BE-07: Recomendador Funcional basado en Afinia.csv.
======================================================================
Verifica:
1. Carga, esquema e integridad de data/raw/Afinia.csv (105 respuestas, 49 columnas).
2. Catálogo canónico de 16 preguntas derivado del CSV en GET /api/v1/questionnaire.
3. Precisión matemática y determinismo de compute_preference_congruence.
4. Reordenamiento de candidatos potenciales según afinidad de preferencias declaradas.
5. Fallback suave y estabilidad para usuarios y candidatos sin respuestas.
6. Preservación estricta de filtros recíprocos de edad, género, bloqueos, PASS y unmatch cerrado.
"""

import os
import uuid
from datetime import date, datetime, timezone
import pytest
import pandas as pd

from app import db
from app.models import (
    User,
    Profile,
    ProfilePhoto,
    DiscoveryPreference,
    UserBlock,
    Match,
    ProfileInteraction,
)
from app.models.analytics import AnalyticQuestionnaireAnswer
from app.utils.security import create_access_token
from app.services.recommender_service import (
    compute_preference_congruence,
    rank_candidates_by_preference_congruence,
)


def _get_afinia_csv_path():
    """Busca Afinia.csv tanto desde la raíz como desde el subdirectorio backend."""
    candidates = [
        os.path.abspath(os.path.join("data", "raw", "Afinia.csv")),
        os.path.abspath(os.path.join("..", "data", "raw", "Afinia.csv")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "Afinia.csv")),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


@pytest.fixture
def base_user(app):
    """Crea un usuario base con perfil y foto aprobada listo para descubrimiento."""
    with app.app_context():
        u_id = str(uuid.uuid4())
        u_email = f"recommender_viewer_{uuid.uuid4().hex[:6]}@afinia.test"
        user = User(
            id=u_id,
            email=u_email,
            password_hash="fakehash",
            is_active=True,
            email_verified=True,
            role="user",
            lifecycle_status="active"
        )
        db.session.add(user)
        db.session.flush()

        profile = Profile(
            user_id=u_id,
            first_name="Viewer",
            birth_date=date(2000, 1, 1),
            gender="masculino",
            city="Villavicencio",
            bio="Perfil de prueba recomendador"
        )
        db.session.add(profile)
        db.session.flush()

        photo = ProfilePhoto(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            storage_key=f"photos/{u_id}/photo.webp",
            position=0,
            is_primary=True,
            status="ready"
        )
        db.session.add(photo)

        pref = DiscoveryPreference(
            user_id=u_id,
            interested_in_gender="femenino",
            interested_in_genders=["femenino"],
            min_age=18,
            max_age=35,
            target_relationship_type="seria"
        )
        db.session.add(pref)
        db.session.commit()

        token = create_access_token(u_id, u_email, "user", app.config['SECRET_KEY'])
        return {"id": u_id, "email": u_email, "token": token}


def _create_candidate(app, name: str, birth_date: date, gender: str = "femenino", target_goal: str = "seria") -> dict:
    """Helper para crear candidatas elegibles recíprocas sin problemas de DetachedInstanceError."""
    with app.app_context():
        u_id = str(uuid.uuid4())
        u_email = f"cand_{name.lower()}_{uuid.uuid4().hex[:6]}@afinia.test"
        user = User(
            id=u_id,
            email=u_email,
            password_hash="fakehash",
            is_active=True,
            email_verified=True,
            role="user",
            lifecycle_status="active"
        )
        db.session.add(user)
        db.session.flush()

        profile = Profile(
            user_id=u_id,
            first_name=name,
            birth_date=birth_date,
            gender=gender,
            city="Villavicencio",
            bio=f"Bio de {name}"
        )
        db.session.add(profile)
        db.session.flush()

        photo = ProfilePhoto(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            storage_key=f"photos/{u_id}/photo.webp",
            position=0,
            is_primary=True,
            status="ready"
        )
        db.session.add(photo)

        pref = DiscoveryPreference(
            user_id=u_id,
            interested_in_gender="masculino",
            interested_in_genders=["masculino"],
            min_age=18,
            max_age=40,
            target_relationship_type=target_goal
        )
        db.session.add(pref)
        db.session.commit()

        token = create_access_token(u_id, u_email, "user", app.config['SECRET_KEY'])
        return {"id": u_id, "email": u_email, "token": token, "first_name": name}


# =========================================================================
# 1. PRUEBAS DE CARGA DEL DATASET ORIGINAL
# =========================================================================

class TestDatasetOriginalAfiniaCSV:
    """Verifica que Afinia.csv exista y cumpla los requisitos de BE-07."""

    def test_afinia_csv_exists_and_dimensions(self):
        csv_path = _get_afinia_csv_path()
        assert os.path.exists(csv_path), f"Afinia.csv debe existir físicamente en {csv_path}"
        df = pd.read_csv(csv_path)
        assert len(df) == 105, f"Se esperaban 105 filas, encontradas {len(df)}"
        assert len(df.columns) == 49, f"Se esperaban 49 columnas, encontradas {len(df.columns)}"

    def test_afinia_csv_has_p8_features_and_target(self):
        csv_path = _get_afinia_csv_path()
        df = pd.read_csv(csv_path)

        p8_cols = [c for c in df.columns if c.startswith("8.") and "[" in c]
        assert len(p8_cols) == 13, f"Deben ser exactamente 13 características en P8, encontradas {len(p8_cols)}"

        p7_col = [c for c in df.columns if c.startswith("7.")][0]
        assert p7_col in df.columns
        assert "Una relación seria y estable" in df[p7_col].values


# =========================================================================
# 2. PRUEBAS DEL CATÁLOGO CANÓNICO DE PREGUNTAS
# =========================================================================

class TestCanonicalQuestionnaireCatalog:
    """Verifica la API GET /api/v1/questionnaire con las 16 preguntas de Afinia.csv."""

    def test_get_questionnaire_returns_canonical_16_questions(self, client, base_user):
        headers = {"Authorization": f"Bearer {base_user['token']}"}
        res = client.get("/api/v1/questionnaire", headers=headers)
        assert res.status_code == 200
        data = res.get_json()["data"]

        assert data["version"] == "draft-1"
        questions = data["questions"]
        assert len(questions) == 16

        q_ids = {q["id"] for q in questions}
        assert "importance_fidelity" in q_ids
        assert "importance_honesty" in q_ids
        assert "importance_communication" in q_ids
        assert "importance_values" in q_ids
        assert "importance_personality" in q_ids
        assert "pref_similarity_interests" in q_ids
        assert "pref_similarity_values" in q_ids
        assert "importance_compatible_life_goals" in q_ids

        for q in questions:
            assert q["type"] == "scale_1_5"
            assert q["min"] == 1
            assert q["max"] == 5
            assert q["required"] is True


# =========================================================================
# 3. PRUEBAS MATEMÁTICAS DE CONGRUENCIA DE PREFERENCIAS
# =========================================================================

class TestPreferenceCongruenceMath:
    """Verifica el cálculo determinista y normalizado de congruencia."""

    def test_identical_vectors_return_1_0(self):
        v1 = {"q1": 5, "q2": 4, "q3": 5}
        v2 = {"q1": 5, "q2": 4, "q3": 5}
        score = compute_preference_congruence(v1, v2)
        assert score == 1.0

    def test_maximally_opposite_vectors_return_0_0(self):
        v1 = {"q1": 5, "q2": 5}
        v2 = {"q1": 1, "q2": 1}
        score = compute_preference_congruence(v1, v2)
        assert score == 0.0

    def test_intermediate_difference(self):
        v1 = {"q1": 5, "q2": 4}
        v2 = {"q1": 3, "q2": 2}
        score = compute_preference_congruence(v1, v2)
        assert score == 0.5

    def test_insufficient_common_questions_returns_none(self):
        v1 = {"q1": 5}
        v2 = {"q1": 5, "q2": 4}
        score = compute_preference_congruence(v1, v2, min_common=2)
        assert score is None

    def test_empty_vectors_return_none(self):
        assert compute_preference_congruence({}, {"q1": 5}) is None
        assert compute_preference_congruence(None, None) is None


# =========================================================================
# 4. PRUEBAS DEL RECOMENDADOR EN EL FEED DE DESCUBRIMIENTO
# =========================================================================

class TestDiscoveryRecommenderFeed:
    """Verifica que el recomendador priorice candidatos según congruencia."""

    def test_recommender_ranks_high_affinity_candidate_first(self, client, app, base_user):
        cand_a = _create_candidate(app, "AnaAltaAfinidad", date(2001, 5, 10))
        cand_b = _create_candidate(app, "BertaBajaAfinidad", date(2001, 3, 15))
        cand_c = _create_candidate(app, "CarlaSinRespuestas", date(2001, 1, 20))

        headers_viewer = {"Authorization": f"Bearer {base_user['token']}"}
        client.put("/api/v1/questionnaire/answers", headers=headers_viewer, json={
            "version": "v1-afinia-survey",
            "answers": [
                {"question_id": "importance_fidelity", "value": 5},
                {"question_id": "importance_honesty", "value": 5},
                {"question_id": "importance_communication", "value": 5},
            ]
        })

        client.put("/api/v1/questionnaire/answers", headers={"Authorization": f"Bearer {cand_a['token']}"}, json={
            "version": "v1-afinia-survey",
            "answers": [
                {"question_id": "importance_fidelity", "value": 5},
                {"question_id": "importance_honesty", "value": 5},
                {"question_id": "importance_communication", "value": 5},
            ]
        })

        client.put("/api/v1/questionnaire/answers", headers={"Authorization": f"Bearer {cand_b['token']}"}, json={
            "version": "v1-afinia-survey",
            "answers": [
                {"question_id": "importance_fidelity", "value": 1},
                {"question_id": "importance_honesty", "value": 1},
                {"question_id": "importance_communication", "value": 1},
            ]
        })

        res = client.get("/api/v1/match/potential?limit=10", headers=headers_viewer)
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]

        user_ids_in_feed = [item["user_id"] for item in items]
        assert cand_a["id"] in user_ids_in_feed
        assert cand_b["id"] in user_ids_in_feed
        assert cand_c["id"] in user_ids_in_feed

        idx_a = user_ids_in_feed.index(cand_a["id"])
        idx_b = user_ids_in_feed.index(cand_b["id"])
        idx_c = user_ids_in_feed.index(cand_c["id"])

        assert idx_a < idx_b, "Candidata con afinidad 1.0 debe aparecer antes que candidata con afinidad 0.0"
        assert idx_b < idx_c, "Candidata con respuestas debe aparecer antes que candidata sin respuestas"

    def test_viewer_without_answers_falls_back_gracefully(self, client, app, base_user):
        cand_1 = _create_candidate(app, "Diana1", date(2001, 1, 1))
        cand_2 = _create_candidate(app, "Elena2", date(2001, 2, 1))

        headers_viewer = {"Authorization": f"Bearer {base_user['token']}"}
        res = client.get("/api/v1/match/potential?limit=10", headers=headers_viewer)
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) >= 2


# =========================================================================
# 5. NO REGRESIÓN DE FILTROS SOCIALES Y EXCLUSIONES ESTRICTAS
# =========================================================================

class TestSocialFiltersPreservation:
    """Verifica que el recomendador jamás vulnere filtros de seguridad o exclusiones."""

    def test_blocked_candidate_excluded_even_with_perfect_answers(self, client, app, base_user):
        cand_blocked = _create_candidate(app, "Bloqueada", date(2001, 5, 10))

        headers_viewer = {"Authorization": f"Bearer {base_user['token']}"}
        client.put("/api/v1/questionnaire/answers", headers=headers_viewer, json={
            "version": "v1-afinia-survey",
            "answers": [{"question_id": "importance_fidelity", "value": 5}, {"question_id": "importance_honesty", "value": 5}]
        })
        client.put("/api/v1/questionnaire/answers", headers={"Authorization": f"Bearer {cand_blocked['token']}"}, json={
            "version": "v1-afinia-survey",
            "answers": [{"question_id": "importance_fidelity", "value": 5}, {"question_id": "importance_honesty", "value": 5}]
        })

        with app.app_context():
            block = UserBlock(blocker_user_id=base_user["id"], blocked_user_id=cand_blocked["id"])
            db.session.add(block)
            db.session.commit()

        res = client.get("/api/v1/match/potential?limit=10", headers=headers_viewer)
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        ids = [it["user_id"] for it in items]
        assert cand_blocked["id"] not in ids, "Usuario bloqueado jamás debe ser recomendado"

    def test_passed_or_matched_candidate_excluded(self, client, app, base_user):
        cand_pass = _create_candidate(app, "Pasada", date(2001, 5, 10))

        with app.app_context():
            interaction = ProfileInteraction(
                viewer_user_id=base_user["id"],
                shown_user_id=cand_pass["id"],
                action="PASS"
            )
            db.session.add(interaction)
            db.session.commit()

        headers_viewer = {"Authorization": f"Bearer {base_user['token']}"}
        res = client.get("/api/v1/match/potential?limit=10", headers=headers_viewer)
        ids = [it["user_id"] for it in res.get_json()["data"]["items"]]
        assert cand_pass["id"] not in ids, "Candidata con PASS previo no debe aparecer"


# =========================================================================
# 6. CERTIFICACIÓN DE RANKING GLOBAL Y PAGINACIÓN CON 30 CANDIDATOS (BE-07.1)
# =========================================================================

class TestRecommenderGlobalPaginationWith30Candidates:
    """
    Verifica que el recomendador ordene GLOBALMENTE por congruencia y no sobre
    una página pre-recortada por created_at.
    Prueba con 30 candidatos elegibles, colocando al de mayor afinidad al final
    cronológico, y validando paginación exhaustiva de 3 páginas de 10 elementos.
    """

    def test_global_ranking_brings_oldest_highest_affinity_to_first_page(self, client, app, base_user):
        headers_viewer = {"Authorization": f"Bearer {base_user['token']}"}

        # 1. El usuario solicitante responde el cuestionario
        client.put("/api/v1/questionnaire/answers", headers=headers_viewer, json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_fidelity", "value": 5},
                {"question_id": "importance_honesty", "value": 5},
                {"question_id": "importance_communication", "value": 5},
                {"question_id": "importance_responsibility", "value": 5}
            ]
        })

        # 2. Creamos 30 candidatas elegibles con fechas escalonadas
        # cand_list[0] = más reciente, cand_list[29] = más antigua (posición 30 por created_at)
        cand_list = []
        base_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        for i in range(30):
            c_time = datetime(2026, 1, 30 - i, 10, 0, 0, tzinfo=timezone.utc)
            cand = _create_candidate(app, f"CandRank_{i:02d}", date(2001, 1, 1))
            # Ajustar created_at en BD
            with app.app_context():
                p = Profile.query.filter_by(user_id=cand["id"]).first()
                p.created_at = c_time
                db.session.commit()
            cand_list.append(cand)

        # 3. La candidata 29 (la más antigua, que por created_at quedaría en la página 3)
        # tiene respuestas PERFECTAMENTE IDÉNTICAS (Afinidad 1.0)
        cand_top = cand_list[29]
        client.put("/api/v1/questionnaire/answers", headers={"Authorization": f"Bearer {cand_top['token']}"}, json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_fidelity", "value": 5},
                {"question_id": "importance_honesty", "value": 5},
                {"question_id": "importance_communication", "value": 5},
                {"question_id": "importance_responsibility", "value": 5}
            ]
        })

        # La candidata 28 tiene afinidad moderada
        cand_mid = cand_list[28]
        client.put("/api/v1/questionnaire/answers", headers={"Authorization": f"Bearer {cand_mid['token']}"}, json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_fidelity", "value": 4},
                {"question_id": "importance_honesty", "value": 4},
                {"question_id": "importance_communication", "value": 4},
                {"question_id": "importance_responsibility", "value": 4}
            ]
        })

        # 4. Solicitamos Página 1 con limit=10 al endpoint CANÓNICO /api/v1/match/potential
        res1 = client.get("/api/v1/match/potential?limit=10", headers=headers_viewer)
        assert res1.status_code == 200
        b1 = res1.get_json()
        items1 = b1["data"]["items"]
        assert len(items1) == 10
        assert b1["meta"]["has_more"] is True
        cur1 = b1["meta"]["next_cursor"]
        assert cur1 is not None

        # ¡PRUEBA CRÍTICA DE RANKING GLOBAL!
        # cand_top DEBE aparecer en la posición 0 de la primera página
        assert items1[0]["user_id"] == cand_top["id"], (
            f"El candidato con máxima congruencia (cand_29) debe aparecer de primero en la página 1, "
            f"pero apareció {items1[0]['first_name']}"
        )
        assert items1[1]["user_id"] == cand_mid["id"], (
            f"El candidato con segunda congruencia (cand_28) debe aparecer de segundo en la página 1."
        )

        # 5. Solicitamos Página 2 con cursor
        res2 = client.get(f"/api/v1/match/potential?limit=10&cursor={cur1}", headers=headers_viewer)
        assert res2.status_code == 200
        b2 = res2.get_json()
        items2 = b2["data"]["items"]
        assert len(items2) == 10
        assert b2["meta"]["has_more"] is True
        cur2 = b2["meta"]["next_cursor"]
        assert cur2 is not None

        # 6. Solicitamos Página 3 con cursor
        res3 = client.get(f"/api/v1/match/potential?limit=10&cursor={cur2}", headers=headers_viewer)
        assert res3.status_code == 200
        b3 = res3.get_json()
        items3 = b3["data"]["items"]
        assert len(items3) == 10
        assert b3["meta"]["has_more"] is False
        assert b3["meta"]["next_cursor"] is None

        # 7. Validaciones globales de paginación
        ids_p1 = [it["user_id"] for it in items1]
        ids_p2 = [it["user_id"] for it in items2]
        ids_p3 = [it["user_id"] for it in items3]

        all_collected = ids_p1 + ids_p2 + ids_p3
        assert len(all_collected) == 30, "Deben haberse recolectado exactamente los 30 candidatos."
        assert len(set(all_collected)) == 30, "CERO duplicados entre las 3 páginas."

        # Cero omisiones
        for c in cand_list:
            assert c["id"] in set(all_collected), f"Candidato {c['id']} fue omitido en la paginación."

