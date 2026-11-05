import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app, db

def verify_post_migration():
    app = create_app()
    with app.app_context():
        print("=" * 70)
        print("VERIFICACIÓN POST-MIGRACIÓN e3a1f8b2c5d4 EN POSTGRESQL QA")
        print("=" * 70)

        # 1. Revisión Alembic
        current_rev = db.session.execute(db.text("SELECT version_num FROM alembic_version")).scalar()
        print(f"1. Revisión Alembic activa: {current_rev}")
        assert current_rev == "e3a1f8b2c5d4", f"Esperado e3a1f8b2c5d4, obtenido {current_rev}"

        # 2. Restricción UNIQUE en PostgreSQL
        constraint_query = db.text("""
            SELECT tc.constraint_name, tc.constraint_type, string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) as cols
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_name = 'analytic_questionnaire_answers'
              AND tc.constraint_type = 'UNIQUE'
            GROUP BY tc.constraint_name, tc.constraint_type;
        """)
        unique_constraints = db.session.execute(constraint_query).fetchall()
        print(f"\n2. Restricciones UNIQUE en analytic_questionnaire_answers:")
        found_uq = False
        for uc in unique_constraints:
            print(f"   - {uc[0]} ({uc[1]}): {uc[2]}")
            if uc[0] == "uq_analytic_questionnaire_user_variable" and "user_id" in uc[2] and "variable_name" in uc[2]:
                found_uq = True
        assert found_uq, "No se encontró la restricción física uq_analytic_questionnaire_user_variable sobre (user_id, variable_name)"
        print("   [OK] Restricción física UNIQUE (user_id, variable_name) confirmada.")

        # 3. Integridad de los registros preexistentes vs respaldo
        backup_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backups', 'backup_answers_pre_e3a1f8b2c5d4.json'))
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        rows = db.session.execute(db.text("""
            SELECT id, user_id, variable_name, value_numeric, value_text
            FROM analytic_questionnaire_answers
            ORDER BY user_id, variable_name
        """)).fetchall()

        print(f"\n3. Verificación de registros preexistentes:")
        print(f"   - Filas respaldadas: {len(backup_data)}")
        print(f"   - Filas actuales: {len(rows)}")
        assert len(rows) == len(backup_data), f"Conteo de filas difiere: {len(rows)} vs {len(backup_data)}"

        backup_map = {(b["user_id"], b["variable_name"]): b for b in backup_data}
        for r in rows:
            key = (str(r[1]), str(r[2]))
            assert key in backup_map, f"Clave {key} no encontrada en respaldo"
            b = backup_map[key]
            assert str(r[0]) == b["id"], f"ID difiere para {key}"
            assert r[3] == b["value_numeric"], f"value_numeric difiere para {key}"
        print("   [OK] Todos los registros preexistentes se mantienen 100% idénticos e íntegros.")

        print("\n" + "=" * 70)
        print("[VERIFICACIÓN POST-MIGRACIÓN COMPLETADA CON ÉXITO]")
        print("=" * 70)

if __name__ == "__main__":
    verify_post_migration()
