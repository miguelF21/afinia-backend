from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from app.models import User
from app import db
from flask import current_app

bp = Blueprint('auth', __name__)

@bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'message': 'Email y contraseña son requeridos'}), 400

    if User.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'El usuario ya existe'}), 409

    hashed_password = generate_password_hash(data['password'])
    new_user = User(email=data['email'], password_hash=hashed_password)
    
    db.session.add(new_user)
    db.session.commit()

    return jsonify({'message': 'Usuario registrado exitosamente', 'user_id': new_user.id}), 201

@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'message': 'Credenciales inválidas'}), 401

    user = User.query.filter_by(email=data['email']).first()

    if not user or not check_password_hash(user.password_hash, data['password']):
        return jsonify({'message': 'Credenciales inválidas'}), 401

    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, current_app.config['SECRET_KEY'], algorithm='HS256')

    return jsonify({'token': token})
