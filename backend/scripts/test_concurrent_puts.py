import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import threading
import time
import uuid
from app import create_app, db
from app.models.user import User
from app.models.analytics import AnalyticQuestionnaireAnswer
from app.utils.security import create_access_token

def test_concurrent_puts():
    app = create_app()
    with app.app_context():
        # Crear usuario de prueba aislado
        u_id = str(uuid.uuid4())
        u_email = f"conc_test_{uuid.uuid4().hex[:6]}@qa.afinia.test"
        user = User(id=u_id, email=u_email, password_hash="fake", is_active=True)
        db.session.add(user)
        db.session.commit()
        token = create_access_token(u_id, u_email, "user", app.config['SECRET_KEY'])

    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    payload_1 = {
        "version": "draft-1",
        "answers": [
            {"question_id": "importance_fidelity", "value": 5},
            {"question_id": "importance_honesty", "value": 5}
        ]
    }
    payload_2 = {
        "version": "draft-1",
        "answers": [
            {"question_id": "importance_fidelity", "value": 4},
            {"question_id": "importance_honesty", "value": 4}
        ]
    }

    results = []
    barrier = threading.Barrier(2)

    def worker(payload, worker_id):
        # Sincronizar para que ambos disparen la petición exactamente en el mismo microsegundo
        barrier.wait()
        res = client.put("/api/v1/questionnaire/answers", headers=headers, json=payload)
        results.append((worker_id, res.status_code, res.get_json()))

    t1 = threading.Thread(target=worker, args=(payload_1, 1))
    t2 = threading.Thread(target=worker, args=(payload_2, 2))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print("Resultados de las dos peticiones PUT concurrentes:")
    for r in results:
        print(f"  Worker {r[0]}: HTTP {r[1]}, Body: {r[2]}")

    with app.app_context():
        rows = AnalyticQuestionnaireAnswer.query.filter_by(user_id=u_id).all()
        print(f"Total filas guardadas para el usuario: {len(rows)}")
        for row in rows:
            print(f"  Row: {row.variable_name} = {row.value_numeric}")

        # Limpieza
        AnalyticQuestionnaireAnswer.query.filter_by(user_id=u_id).delete()
        User.query.filter_by(id=u_id).delete()
        db.session.commit()

if __name__ == "__main__":
    test_concurrent_puts()
