from flask import Blueprint, jsonify, request
from app.auth.middleware import token_required
from app.models import Profile, Match
from app import db
import random

bp = Blueprint('match', __name__)

@bp.route('/potential', methods=['GET'])
@token_required
def get_potential_matches(current_user):
    all_profiles = Profile.query.filter(Profile.user_id != current_user.id).all()
    if not all_profiles:
        return jsonify([])
        
    random.shuffle(all_profiles)
    candidates = all_profiles[:10]
    
    results = []
    for cand in candidates:
        results.append({
            'id': cand.id,
            'user_id': cand.user_id,
            'first_name': cand.first_name,
            'bio': cand.bio,
            'compatibility_score': round(random.uniform(50, 99), 1)
        })
    return jsonify(results)

@bp.route('/swipe', methods=['POST'])
@token_required
def swipe(current_user):
    data = request.get_json()
    if not data or 'target_user_id' not in data or 'action' not in data:
        return jsonify({'message': 'Faltan datos'}), 400
    return jsonify({'message': 'Swipe registrado', 'match': random.choice([True, False])})
