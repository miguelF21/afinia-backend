import pytest
import sqlite3
from sqlalchemy import event
from sqlalchemy.engine import Engine
from config import Config
from app import create_app, db

import os
import tempfile
import shutil

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'test-key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = tempfile.mkdtemp(prefix='afinia_test_uploads_')

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Habilita la verificación de Foreign Keys en conexiones SQLite.
    Por defecto, SQLite tiene deshabilitada la integridad referencial física.
    NOTA: Esta configuración aplica exclusivamente a las pruebas unitarias en SQLite.
    Las pruebas físicas y restricciones nativas de PostgreSQL se verifican en QA.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

@pytest.fixture
def app():
    app = create_app(TestConfig)
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        upload_dir = app.config.get('UPLOAD_FOLDER')
        if upload_dir and os.path.exists(upload_dir) and 'afinia_test_uploads_' in upload_dir:
            shutil.rmtree(upload_dir, ignore_errors=True)

@pytest.fixture
def client(app):
    return app.test_client()
