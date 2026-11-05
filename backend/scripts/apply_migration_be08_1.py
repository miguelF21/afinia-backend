import os
import sys
import shutil
import subprocess
from dotenv import load_dotenv
load_dotenv('.env')

from sqlalchemy import create_engine, text, inspect

def apply_and_verify():
    pending_src = os.path.join('migrations', 'pending_versions', 'f4c2d8e1a3b5_password_reset_tokens.py')
    versions_dst = os.path.join('migrations', 'versions', 'f4c2d8e1a3b5_password_reset_tokens.py')

    print("[1/4] Promoviendo archivo de migración a migrations/versions/...")
    shutil.copy2(pending_src, versions_dst)
    print(f" -> Copiado a {versions_dst}")

    print("[2/4] Ejecutando flask db upgrade en PostgreSQL QA...")
    cmd = [sys.executable, "-m", "flask", "db", "upgrade"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)
    if res.returncode != 0:
        print(f"ERROR: Falló flask db upgrade con código {res.returncode}")
        sys.exit(1)

    print("[3/4] Verificando revisión Alembic resultante en DB...")
    engine = create_engine(os.environ['DATABASE_URL'])
    with engine.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        print(f" -> Nueva revisión activa: {rev}")
        if rev != 'f4c2d8e1a3b5':
            print(f"ERROR: La revisión debe ser f4c2d8e1a3b5, pero es {rev}")
            sys.exit(1)

        print("[4/4] Verificando físicamente la estructura en catálogos PostgreSQL...")
        insp = inspect(engine)
        if 'password_reset_tokens' not in insp.get_table_names():
            print("ERROR: La tabla password_reset_tokens no se encuentra en el catálogo")
            sys.exit(1)

        cols = insp.get_columns('password_reset_tokens')
        col_names = {c['name']: c for c in cols}
        print(" -> Columnas detectadas:", list(col_names.keys()))

        expected_cols = {'id', 'user_id', 'token_hash', 'created_at', 'expires_at', 'consumed_at', 'revoked_at'}
        if set(col_names.keys()) != expected_cols:
            print(f"ERROR: Discrepancia en columnas. Esperadas: {expected_cols}, Encontradas: {set(col_names.keys())}")
            sys.exit(1)

        # Verificar índices
        indexes = insp.get_indexes('password_reset_tokens')
        index_names = {idx['name']: idx for idx in indexes}
        print(" -> Índices detectados:", list(index_names.keys()))

        if 'ix_password_reset_tokens_token_hash' not in index_names:
            print("ERROR: Falta el índice ix_password_reset_tokens_token_hash")
            sys.exit(1)
        if not index_names['ix_password_reset_tokens_token_hash'].get('unique'):
            print("ERROR: ix_password_reset_tokens_token_hash debe ser UNIQUE")
            sys.exit(1)

        # Verificar Foreign Keys
        fks = insp.get_foreign_keys('password_reset_tokens')
        print(" -> Foreign Keys detectadas:", fks)
        fk_valid = any(
            fk.get('referred_table') == 'users' and 
            fk.get('referred_columns') == ['id'] and 
            fk.get('constrained_columns') == ['user_id']
            for fk in fks
        )
        if not fk_valid:
            print("ERROR: FK hacia users.id no encontrada o inválida")
            sys.exit(1)

    print("\n¡MIGRACIÓN f4c2d8e1a3b5 APLICADA Y CERTIFICADA EXITOSAMENTE EN POSTGRESQL QA!")

if __name__ == '__main__':
    apply_and_verify()
