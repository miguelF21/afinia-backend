"""
AFINIA — API de Cuestionario Analítico (BE-06 / BE-07).
======================================================
Implementa las operaciones contractuales de cuestionario conforme a OpenAPI v1
y el catálogo canónico de 16 preguntas de escala 1-5 derivado de Afinia.csv:
- Las 13 características valoradas de la Pregunta 8.
- Las 3 escalas de compatibilidad de las Preguntas 11, 12 y 14.
- GET /api/v1/questionnaire
- PUT /api/v1/questionnaire/answers
- GET /api/v1/questionnaire/answers
"""

import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, current_app
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.auth.middleware import token_required
from app.utils.errors import api_response, api_error
from app.models.analytics import AnalyticQuestionnaireAnswer
from app import db

bp = Blueprint('questionnaire', __name__)
QUESTIONNAIRE_VERSION = "draft-1"

# Catálogo canónico de 16 preguntas derivado textualmente de Afinia.csv (Pregunta 8 + 11, 12, 14).
# Todas de tipo scale_1_5 (rango 1 a 5), perfectamente compatibles con OpenAPI v1 y el modelo físico.
CONTRACT_QUESTIONS = [
    # --- Pregunta 8: Las 13 características al considerar una posible pareja ---
    {
        "id": "importance_physical_attractiveness",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Atractivo físico]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_personality",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Personalidad]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_sense_of_humor",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Sentido del humor]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_intelligence",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Inteligencia]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_communication",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Comunicación]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_values",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Valores similares]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_shared_interests",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Intereses compartidos]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_emotional_stability",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Estabilidad emocional]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_economic_stability",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Estabilidad económica]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_life_goals",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Metas de vida]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_responsibility",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Responsabilidad]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_honesty",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Honestidad]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_fidelity",
        "label": "8. ¿Qué nivel de importancia tiene para ti cada una de las siguientes características al considerar a una posible pareja? [Fidelidad]",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    # --- Preguntas complementarias de afinidad en escala 1 a 5 ---
    {
        "id": "pref_similarity_interests",
        "label": "11. ¿Qué tanto prefieres que una posible pareja tenga gustos e intereses similares a los tuyos?",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "pref_similarity_values",
        "label": "12. ¿Qué tanto prefieres que una posible pareja comparta valores y principios similares a los tuyos?",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    },
    {
        "id": "importance_compatible_life_goals",
        "label": "14. ¿Qué importancia tiene para ti que una posible pareja tenga metas de vida compatibles con las tuyas?",
        "type": "scale_1_5",
        "required": True,
        "min": 1,
        "max": 5
    }
]

VALID_QUESTION_IDS = {q["id"] for q in CONTRACT_QUESTIONS}


@bp.route('', methods=['GET'])
@bp.route('/', methods=['GET'])
@token_required
def get_questionnaire(current_user):
    """
    GET /api/v1/questionnaire
    Consultar preguntas de preferencias/cuestionario.
    """
    return api_response({
        "version": QUESTIONNAIRE_VERSION,
        "questions": CONTRACT_QUESTIONS
    }, 200)


@bp.route('/answers', methods=['PUT'])
@token_required
def put_questionnaire_answers(current_user):
    """
    PUT /api/v1/questionnaire/answers
    Guardar o actualizar respuestas de preferencias (upsert idempotente).
    """
    data = request.get_json(silent=True)
    if not data or not isinstance(data, dict):
        return api_error('VALIDATION_ERROR', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 422)

    version = data.get('version')
    if not version or not isinstance(version, str) or not version.strip():
        return api_error('VALIDATION_ERROR', "El campo 'version' es obligatorio y debe ser una cadena no vacía.", 422)

    answers = data.get('answers')
    if answers is None or not isinstance(answers, list) or len(answers) == 0:
        return api_error('VALIDATION_ERROR', "El campo 'answers' es obligatorio y debe contener al menos una respuesta.", 422)

    validated_answers = []
    seen_questions = set()
    for idx, item in enumerate(answers):
        if not isinstance(item, dict):
            return api_error('VALIDATION_ERROR', f"El elemento en el índice {idx} debe ser un objeto.", 422)
        
        q_id = item.get('question_id')
        if not q_id or not isinstance(q_id, str) or not q_id.strip():
            return api_error('VALIDATION_ERROR', f"El campo 'question_id' en el índice {idx} es obligatorio.", 422)
        
        q_id = q_id.strip()
        val = item.get('value')
        
        if isinstance(val, bool) or not isinstance(val, int):
            return api_error('VALIDATION_ERROR', f"El campo 'value' en el índice {idx} debe ser un número entero entre 1 y 5.", 422)
            
        if val < 1 or val > 5:
            return api_error('VALIDATION_ERROR', f"El campo 'value' en el índice {idx} debe estar entre 1 y 5.", 422)

        if q_id in seen_questions:
            return api_error('VALIDATION_ERROR', f"Pregunta duplicada '{q_id}' en el conjunto de respuestas.", 422)
        seen_questions.add(q_id)

        validated_answers.append((q_id, val))

    # Persistencia con semántica PUT (Upsert idempotente y atómico por user_id + variable_name)
    try:
        bind = db.session.get_bind()
        saved_count = len(validated_answers)

        if bind.dialect.name == "postgresql":
            # Operación atómica nativa PostgreSQL: INSERT ... ON CONFLICT (user_id, variable_name) DO UPDATE
            for q_id, val in validated_answers:
                stmt = pg_insert(AnalyticQuestionnaireAnswer).values(
                    id=str(uuid.uuid4()),
                    user_id=current_user.id,
                    variable_name=q_id,
                    value_numeric=val
                )
                stmt = stmt.on_conflict_do_update(
                    constraint='uq_analytic_questionnaire_user_variable',
                    set_={'value_numeric': val}
                )
                db.session.execute(stmt)
        else:
            # Fallback compatible con SQLite para suite Pytest en memoria
            q_ids = [q_id for q_id, _ in validated_answers]
            existing_answers = AnalyticQuestionnaireAnswer.query.filter(
                AnalyticQuestionnaireAnswer.user_id == current_user.id,
                AnalyticQuestionnaireAnswer.variable_name.in_(q_ids)
            ).all()
            existing_map = {ans.variable_name: ans for ans in existing_answers}
            for q_id, val in validated_answers:
                if q_id in existing_map:
                    existing_map[q_id].value_numeric = val
                else:
                    new_ans = AnalyticQuestionnaireAnswer(
                        user_id=current_user.id,
                        variable_name=q_id,
                        value_numeric=val
                    )
                    db.session.add(new_ans)

        db.session.commit()

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return api_response({
            "version": version,
            "saved_count": saved_count,
            "updated_at": now_iso
        }, 200)

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error al guardar respuestas de cuestionario: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al persistir las respuestas.', 500)


@bp.route('/answers', methods=['GET'])
@token_required
def get_questionnaire_answers(current_user):
    """
    GET /api/v1/questionnaire/answers
    Consultar respuestas guardadas del usuario autenticado.
    Aislamiento estricto: solo el propio usuario.
    """
    try:
        answers = AnalyticQuestionnaireAnswer.query.filter_by(user_id=current_user.id).order_by(
            AnalyticQuestionnaireAnswer.variable_name.asc()
        ).all()

        answer_items = [
            {
                "question_id": ans.variable_name,
                "value": ans.value_numeric if ans.value_numeric is not None else 0
            }
            for ans in answers
        ]

        return api_response({
            "version": QUESTIONNAIRE_VERSION,
            "answers": answer_items
        }, 200)

    except Exception as e:
        current_app.logger.error(f"Error al consultar respuestas de cuestionario: {str(e)}")
        return api_error('INTERNAL_ERROR', 'Error interno al consultar las respuestas.', 500)
