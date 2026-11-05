import os
import sys
import json
from dotenv import load_dotenv
load_dotenv('.env')

from sqlalchemy import create_engine, text, inspect

def check_preconditions():
    print("[1/5] Verificando variables de entorno y conexión...")
    db_url = os.environ.get('DATABASE_URL', '')
    if '55433' not in db_url or 'afinia_qa_db' not in db_url:
        print(f"ABORTADO: DATABASE_URL no apunta al puerto QA 55433 / afinia_qa_db: {db_url}")
        sys.exit(1)

    engine = create_engine(db_url)
    with engine.connect() as conn:
        db_name = conn.execute(text("SELECT current_database();")).scalar()
        db_user = conn.execute(text("SELECT current_user;")).scalar()
        print(f" -> Conexión exitosa a DB={db_name}, Usuario={db_user}")

        print("[2/5] Verificando revisión Alembic actual...")
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        print(f" -> Revisión activa en DB: {rev}")
        if rev != 'e3a1f8b2c5d4':
            print(f"ABORTADO: La revisión debe ser e3a1f8b2c5d4, pero se encontró {rev}")
            sys.exit(1)

        print("[3/5] Inspeccionando archivo de migración pendiente...")
        pending_file = os.path.join('migrations', 'pending_versions', 'f4c2d8e1a3b5_password_reset_tokens.py')
        if not os.path.exists(pending_file):
            print(f"ABORTADO: No se encontró el archivo {pending_file}")
            sys.exit(1)

        with open(pending_file, 'r', encoding='utf-8') as f:
            content = f.read()

        if "revision = 'f4c2d8e1a3b5'" not in content:
            print("ABORTADO: revision ID inválido en el archivo")
            sys.exit(1)
        if "down_revision = 'e3a1f8b2c5d4'" not in content:
            print("ABORTADO: down_revision debe ser e3a1f8b2c5d4")
            sys.exit(1)
        if "op.create_table(\n        'password_reset_tokens'" not in content and "create_table('password_reset_tokens'" not in content and "'password_reset_tokens'" not in content:
            print("ABORTADO: La migración no define la tabla password_reset_tokens")
            sys.exit(1)
        print(" -> Archivo de migración pendiente verificado correctamente.")

        print("[4/5] Comprobando que no existe ya la tabla password_reset_tokens en QA...")
        insp = inspect(engine)
        if 'password_reset_tokens' in insp.get_table_names():
            print("ABORTADO: La tabla password_reset_tokens ya existe en la base de datos.")
            sys.exit(1)
        print(" -> Confirmado: password_reset_tokens aún no existe.")

        print("[5/5] Generando respaldo preventivo de estado de base de datos...")
        os.makedirs('backups', exist_ok=True)
        backup_path = os.path.join('backups', 'backup_pre_f4c2d8e1a3b5.json')
        
        # Guardar conteo de tablas y versión alembic
        tables = insp.get_table_names()
        table_counts = {}
        for t in tables:
            c = conn.execute(text(f"SELECT COUNT(*) FROM {t};")).scalar()
            table_counts[t] = c

        backup_data = {
            'alembic_version': rev,
            'tables': table_counts,
            'timestamp': str(os.path.getmtime(pending_file))
        }
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2)
        print(f" -> Respaldo generado en {backup_path}")
        print(" -> Tablas respaldadas:", table_counts)

    print("\nPRECONDICIONES VERIFICADAS EXITOSAMENTE: LISTO PARA APLICAR MIGRACIÓN.")

if __name__ == '__main__':
    check_preconditions()
