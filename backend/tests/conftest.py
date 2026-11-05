import os
import tempfile
import shutil
import sqlite3
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
from config import Config
from app import create_app, db


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'test-key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Configura cada conexión SQLite de pruebas:
    - PRAGMA foreign_keys=ON: integridad referencial física en SQLite.
    - PRAGMA journal_mode=WAL y busy_timeout=30000: permite conexiones independientes
      por hilo sin compartir una única conexión DBAPI (evita rollbacks cruzados de StaticPool).
    - PRAGMA synchronous=OFF: velocidad en memoria sin fsync a disco en pruebas.
    NOTA: Las restricciones nativas y bloqueos SELECT FOR UPDATE de PostgreSQL se verifican en QA.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


@pytest.fixture
def app():
    test_dir = tempfile.mkdtemp(prefix='afinia_test_env_')
    upload_dir = os.path.join(test_dir, 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    db_path = os.path.join(test_dir, 'test.db')

    class IsolatedTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
        SQLALCHEMY_ENGINE_OPTIONS = {
            'poolclass': NullPool,
            'connect_args': {'timeout': 30, 'check_same_thread': False}
        }
        UPLOAD_FOLDER = upload_dir

    app = create_app(IsolatedTestConfig)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()

    if os.path.exists(test_dir) and 'afinia_test_env_' in test_dir:
        shutil.rmtree(test_dir, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()
