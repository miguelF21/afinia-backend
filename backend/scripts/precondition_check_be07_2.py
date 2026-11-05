import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app, db

def check_preconditions():
    app = create_app()
    with app.app_context():
        # 1. Connection info
        engine = db.engine
        url = engine.url
        print("=" * 70)
        print("1. VERIFICACIÓN DE CONEXIÓN Y ENTORNO:")
        print(f"   - Dialect: {url.drivername}")
        print(f"   - Host: {url.host}")
        print(f"   - Port: {url.port}")
        print(f"   - Database: {url.database}")
        print(f"   - Username: {url.username}")

        # Comprobación de seguridad estricta
        if url.host not in ("127.0.0.1", "localhost") or url.port != 55433 or url.database != "afinia_qa_db":
            raise RuntimeError(f"ABORTADO: Conexión no autorizada ({url.host}:{url.port}/{url.database}). Debe ser 127.0.0.1:55433/afinia_qa_db")

        # 2. Revisión Alembic actual en DB
        current_rev = db.session.execute(db.text("SELECT version_num FROM alembic_version")).scalar()
        print(f"\n2. REVISIÓN ALEMBIC ACTUAL EN BD: {current_rev}")
        if current_rev != "ab128894ff73":
            raise RuntimeError(f"ABORTADO: Revisión Alembic no coincide con ab128894ff73. Se encontró: {current_rev}")

        # 3. Consulta de duplicados
        dup_query = db.text("""
            SELECT user_id, variable_name, count(*) as qty
            FROM analytic_questionnaire_answers
            GROUP BY user_id, variable_name
            HAVING count(*) > 1
        """)
        duplicates = db.session.execute(dup_query).fetchall()
        print(f"\n3. VERIFICACIÓN DE DUPLICADOS (user_id, variable_name):")
        print(f"   - Duplicados encontrados: {len(duplicates)}")
        if duplicates:
            raise RuntimeError(f"ABORTADO: Existen duplicados preexistentes: {duplicates}")

        # 4. Conteo e integridad de respuestas preexistentes
        rows = db.session.execute(db.text("""
            SELECT id, user_id, variable_name, value_numeric, value_text
            FROM analytic_questionnaire_answers
            ORDER BY user_id, variable_name
        """)).fetchall()
        print(f"\n4. INTEGRIDAD DE RESPUESTAS PREEXISTENTES:")
        print(f"   - Total filas actuales: {len(rows)}")
        backup_data = []
        for r in rows:
            print(f"     * ID={r[0]}, User={r[1]}, Var={r[2]}, Val={r[3]}")
            backup_data.append({
                "id": str(r[0]),
                "user_id": str(r[1]),
                "variable_name": str(r[2]),
                "value_numeric": r[3],
                "value_text": r[4]
            })

        # 5. Guardar respaldo verificable
        backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backups'))
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"backup_answers_pre_e3a1f8b2c5d4.json")
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2)
        print(f"\n5. RESPALDO PRE-MIGRACIÓN CREADO:")
        print(f"   - Archivo: {backup_path}")
        print(f"   - Registros respaldados: {len(backup_data)}")

        # 6. Comprobar que no hay transacciones o escrituras bloqueantes
        locks = db.session.execute(db.text("""
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = 'afinia_qa_db'
              AND state = 'active'
              AND pid != pg_backend_pid();
        """)).scalar()
        print(f"\n6. SESIONES ACTIVAS EXTERNAS EN afinia_qa_db: {locks}")

        print("\n" + "=" * 70)
        print("[PRECONDICIONES COMPLETAMENTE APROBADAS]")
        print("=" * 70)

if __name__ == "__main__":
    check_preconditions()
