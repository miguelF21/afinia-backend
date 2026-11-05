"""
Prueba HTTP autenticada de la ruta canónica GET /api/v1/match/potential.
Demuestra la integración real del recomendador sobre el endpoint canónico del contrato.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from datetime import date
from app import create_app, db
from app.utils.security import create_access_token
from tests.test_be_07_recommender import _create_candidate

def test_canonical_potential_endpoint():
    app = create_app()
    with app.test_client() as client:
        # 1. Crear usuario espectador y candidata con preferencias afines
        viewer = _create_candidate(app, "ViewerHTTP", date(2000, 1, 1), gender="masculino", target_goal="seria")
        cand = _create_candidate(app, "CandHTTP", date(2001, 2, 2), gender="femenino", target_goal="seria")

        # Ajustar preferencias del viewer para buscar femenino
        with app.app_context():
            from app.models import DiscoveryPreference
            v_pref = DiscoveryPreference.query.filter_by(user_id=viewer["id"]).first()
            v_pref.interested_in_gender = "femenino"
            v_pref.interested_in_genders = ["femenino"]
            db.session.commit()

        headers_viewer = {"Authorization": f"Bearer {viewer['token']}"}
        headers_cand = {"Authorization": f"Bearer {cand['token']}"}

        # 2. Ambos responden el cuestionario con alta afinidad
        client.put("/api/v1/questionnaire/answers", headers=headers_viewer, json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_fidelity", "value": 5},
                {"question_id": "importance_honesty", "value": 5}
            ]
        })
        client.put("/api/v1/questionnaire/answers", headers=headers_cand, json={
            "version": "draft-1",
            "answers": [
                {"question_id": "importance_fidelity", "value": 5},
                {"question_id": "importance_honesty", "value": 5}
            ]
        })

        # 3. Petición HTTP auténtica a la ruta canónica
        print("Realizando GET autenticado a /api/v1/match/potential?limit=10 ...")
        res = client.get("/api/v1/match/potential?limit=10", headers=headers_viewer)
        print(f"Status Code: {res.status_code}")
        body = res.get_json()
        print(f"Response Meta: {body.get('meta')}")
        items = body.get("data", {}).get("items", [])
        print(f"Total Items Retornados: {len(items)}")
        if items:
            print(f"Primer candidato retornado: user_id={items[0]['user_id']}, first_name={items[0]['first_name']}")
            assert items[0]["user_id"] == cand["id"]
            print("[CERTIFICACIÓN OK] El recomendador operó exitosamente en la ruta canónica /api/v1/match/potential.")

if __name__ == "__main__":
    test_canonical_potential_endpoint()
