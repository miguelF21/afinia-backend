import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'super-secret-key-for-afinia'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://afinia_user:afinia_password@localhost:5432/afinia_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
