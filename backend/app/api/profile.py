from flask import Blueprint, request, jsonify
from app.auth.middleware import token_required
from app.models import Profile
from app import db
import datetime

bp = Blueprint('profile', __name__)

@bp.route('/', methods=['GET'])
@token_required
def get_profile(current_user):
    profile = current_user.profile
    if not profile:
        return jsonify({'message': 'Perfil no encontrado'}), 404
        
    return jsonify({
        'id': profile.id,
        'first_name': profile.first_name,
        'birth_date': profile.birth_date.isoformat(),
        'gender': profile.gender,
        'city': profile.city,
        'bio': profile.bio
    })

@bp.route('/', methods=['POST', 'PUT'])
@token_required
def update_profile(current_user):
    data = request.get_json()
    
    if not data or not data.get('first_name') or not data.get('birth_date') or not data.get('gender'):
        return jsonify({'message': 'Faltan campos requeridos'}), 400

    try:
        birth_date = datetime.datetime.strptime(data['birth_date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'message': 'Formato de fecha inválido. Use YYYY-MM-DD'}), 400

    profile = current_user.profile
    
    if not profile:
        profile = Profile(user_id=current_user.id)
        db.session.add(profile)
        
    profile.first_name = data['first_name']
    profile.birth_date = birth_date
    profile.gender = data['gender']
    profile.city = data.get('city')
    profile.bio = data.get('bio')
    
    db.session.commit()
    
    return jsonify({'message': 'Perfil actualizado exitosamente'}), 200
