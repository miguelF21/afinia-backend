from flask import Blueprint, request, jsonify
from app.auth.middleware import token_required
import joblib
import pandas as pd
import os

bp = Blueprint('analytics', __name__)

# Cargar el modelo en memoria al iniciar (Singleton-like)
model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 
                          'analytics', 'models', 'afinia_model_v1.pkl')

model = None
try:
    if os.path.exists(model_path):
        model = joblib.load(model_path)
except Exception as e:
    print(f"Error cargando modelo ML: {e}")

@bp.route('/predict', methods=['POST'])
@token_required
def predict(current_user):
    if not model:
        return jsonify({'message': 'Modelo no disponible'}), 503
        
    data = request.get_json()
    if not data:
        return jsonify({'message': 'Se requieren datos para predecir'}), 400
        
    # Convertir JSON a DataFrame (asumiendo que viene 1 fila)
    try:
        df = pd.DataFrame([data])
        # Predicción
        pred = model.predict(df)
        prob = model.predict_proba(df)
        
        return jsonify({
            'prediction': int(pred[0]),
            'probability': prob[0].tolist()
        }), 200
    except Exception as e:
        return jsonify({'message': f'Error en predicción: {str(e)}'}), 500

@bp.route('/answers', methods=['POST'])
@token_required
def save_answers(current_user):
    from app.models.analytics import AnalyticQuestionnaireAnswer
    from app import db
    
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({'message': 'Se requiere un JSON con las respuestas'}), 400
        
    for key, value in data.items():
        try:
            val_num = float(value)
            answer = AnalyticQuestionnaireAnswer(user_id=current_user.id, variable_name=key, value_numeric=val_num)
        except (ValueError, TypeError):
            answer = AnalyticQuestionnaireAnswer(user_id=current_user.id, variable_name=key, value_text=str(value))
        db.session.add(answer)
        
    db.session.commit()
    return jsonify({'message': 'Respuestas guardadas exitosamente'}), 201
