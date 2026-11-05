import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app, db

def audit_duplicates():
    app = create_app()
    with app.app_context():
        # 1. Total rows
        total_rows = db.session.execute(db.text("SELECT count(*) FROM analytic_questionnaire_answers")).scalar()
        
        # 2. Distinct users
        distinct_users = db.session.execute(db.text("SELECT count(DISTINCT user_id) FROM analytic_questionnaire_answers")).scalar()
        
        # 3. Duplicate check
        dup_query = db.text("""
            SELECT user_id, variable_name, count(*) as qty
            FROM analytic_questionnaire_answers
            GROUP BY user_id, variable_name
            HAVING count(*) > 1
            ORDER BY count(*) DESC
        """)
        duplicates = db.session.execute(dup_query).fetchall()
        
        print(f"Total registros en analytic_questionnaire_answers: {total_rows}")
        print(f"Usuarios distintos con respuestas: {distinct_users}")
        print(f"Grupos (user_id, variable_name) duplicados: {len(duplicates)}")
        if duplicates:
            print("Duplicados encontrados:")
            for d in duplicates[:10]:
                print(f"  User: {d[0]}, Variable: {d[1]}, Conteo: {d[2]}")
        else:
            print("[OK] No existen duplicados actualmente en la base de datos.")

if __name__ == "__main__":
    audit_duplicates()
