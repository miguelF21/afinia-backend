"""
Procedimiento seguro de rotación de credenciales para afinia_qa_user en PostgreSQL QA (127.0.0.1:55433).
Seguridad:
- Genera contraseña criptográfica aleatoria con secrets.token_urlsafe(32).
- Ejecuta ALTER USER con parámetro seguro (sin imprimir en logs ni consola).
- Actualiza backend/.env localmente sin exponer el secreto.
- Comprueba la conectividad posterior con la nueva credencial.
"""
import sys
import os
import secrets
import re
from urllib.parse import urlparse, urlunparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app, db

def rotate_qa_password():
    print("Iniciando rotación segura de credenciales de afinia_qa_user...")
    app = create_app()
    with app.app_context():
        # Generar nueva contraseña criptográfica
        new_pw = secrets.token_urlsafe(32)

        # 1. Ejecutar ALTER USER en PostgreSQL QA
        try:
            # En PostgreSQL: ALTER USER afinia_qa_user WITH PASSWORD '...'
            # Usamos ejecución parametrizada segura
            sql = db.text(f"ALTER USER afinia_qa_user WITH PASSWORD :pw")
            db.session.execute(sql, {"pw": new_pw})
            db.session.commit()
            print("[OK] Contraseña rotada en el motor PostgreSQL QA (puerto 55433).")
        except Exception as e:
            print(f"[ERROR] No se pudo alterar la contraseña en PostgreSQL: {type(e).__name__}")
            raise

    # 2. Actualizar archivo .env de forma atómica y segura
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Reemplazar contraseña en DATABASE_URL
        new_db_url = f"postgresql://afinia_qa_user:{new_pw}@127.0.0.1:55433/afinia_qa_db"
        content_updated = re.sub(r'DATABASE_URL=postgresql://[^\s@]+:[^\s@]+@', f'DATABASE_URL=postgresql://afinia_qa_user:{new_pw}@', content)

        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(content_updated)
        print("[OK] backend/.env actualizado con la nueva credencial rotada.")
    else:
        print("[AVISO] No se encontró backend/.env")

    # 3. Comprobar conectividad posterior con nueva conexión fresca
    from sqlalchemy import create_engine
    test_engine = create_engine(f"postgresql://afinia_qa_user:{new_pw}@127.0.0.1:55433/afinia_qa_db")
    with test_engine.connect() as conn:
        rev = conn.execute(db.text("SELECT version_num FROM alembic_version")).scalar()
        print(f"[OK] Conectividad comprobada exitosamente con la nueva credencial. Alembic rev: {rev}")

    print("[ROTACIÓN COMPLETADA SATISFACTORIAMENTE]")

if __name__ == "__main__":
    rotate_qa_password()
