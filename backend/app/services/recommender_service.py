"""
AFINIA — Servicio de Recomendación Determinista basado en Preferencias Declaradas (BE-07).
========================================================================================
Implementa el algoritmo determinista de congruencia de preferencias de cuestionario
para el ordenamiento de candidatos en el feed de descubrimiento (/api/v1/match/potential).

Mecanismo Matemático:
- Cada usuario que responde el cuestionario posee un vector de preferencias R_u en escala 1-5.
- La congruencia entre el solicitante u y un candidato v se define como la similitud
  normalizada de Manhattan inversa sobre el conjunto de preguntas respondidas en común Q_uv:
    Congruencia(u, v) = 1.0 - ( sum_{q in Q_uv} |R_{u,q} - R_{v,q}| ) / ( 4.0 * |Q_uv| )
- Si |Q_uv| < MIN_COMMON_QUESTIONS (por defecto 2), se asigna None y se recurre
  al ordenamiento por defecto del sistema (created_at DESC, user_id ASC).
- Esta métrica refleja exclusivamente congruencia de expectativas declaradas,
  sin fingir probabilidades predictivas de éxito romántico.
"""

from typing import Dict, List, Optional, Tuple
from app import db
from app.models import Profile
from app.models.analytics import AnalyticQuestionnaireAnswer

MIN_COMMON_QUESTIONS = 2


def get_user_answers_vector(user_id: str) -> Dict[str, int]:
    """Obtiene el vector de respuestas numéricas del cuestionario para un usuario."""
    answers = AnalyticQuestionnaireAnswer.query.filter(
        AnalyticQuestionnaireAnswer.user_id == user_id,
        AnalyticQuestionnaireAnswer.value_numeric.isnot(None)
    ).all()
    return {ans.variable_name: ans.value_numeric for ans in answers}


def compute_preference_congruence(
    vector_a: Dict[str, int],
    vector_b: Dict[str, int],
    min_common: int = MIN_COMMON_QUESTIONS
) -> Optional[float]:
    """
    Calcula la congruencia normalizada en el intervalo [0.0, 1.0] entre dos vectores de preferencias.
    Retorna None si no comparten al menos min_common preguntas.
    """
    if not vector_a or not vector_b:
        return None

    common_keys = set(vector_a.keys()) & set(vector_b.keys())
    if len(common_keys) < min_common:
        return None

    # Escala 1 a 5 -> máxima diferencia por ítem es |5 - 1| = 4
    total_diff = sum(abs(vector_a[k] - vector_b[k]) for k in common_keys)
    max_possible_diff = 4.0 * len(common_keys)

    congruence = 1.0 - (total_diff / max_possible_diff)
    return round(float(congruence), 4)


def rank_candidates_by_preference_congruence(
    viewer_id: str,
    candidate_profiles: List[Profile]
) -> List[Profile]:
    """
    Ordena una lista de perfiles candidatos elegibles según su congruencia de preferencias
    declaradas respecto al usuario solicitante (viewer_id).

    Reglas de ordenamiento estable:
    1. Perfiles con congruencia calculable (>= MIN_COMMON_QUESTIONS) van antes que perfiles sin respuestas.
    2. Perfiles con mayor congruencia van primero (orden descendente).
    3. Criterio de desempate determinista: Profile.created_at DESC, Profile.user_id ASC.
    """
    if not candidate_profiles:
        return []

    # 1. Obtener vector de respuestas del solicitante
    viewer_vector = get_user_answers_vector(viewer_id)
    if not viewer_vector:
        # Solicitante no ha respondido el cuestionario: mantener ordenamiento original intacto
        return candidate_profiles

    # 2. Consultar en lote las respuestas de todos los candidatos para máxima eficiencia
    candidate_user_ids = [p.user_id for p in candidate_profiles]
    candidate_answers = AnalyticQuestionnaireAnswer.query.filter(
        AnalyticQuestionnaireAnswer.user_id.in_(candidate_user_ids),
        AnalyticQuestionnaireAnswer.value_numeric.isnot(None)
    ).all()

    # Mapear respuestas por candidate_user_id
    answers_by_user: Dict[str, Dict[str, int]] = {}
    for ans in candidate_answers:
        if ans.user_id not in answers_by_user:
            answers_by_user[ans.user_id] = {}
        answers_by_user[ans.user_id][ans.variable_name] = ans.value_numeric

    # 3. Calcular congruencia para cada candidato
    scored_profiles: List[Tuple[Profile, Optional[float]]] = []
    for profile in candidate_profiles:
        cand_vector = answers_by_user.get(profile.user_id, {})
        score = compute_preference_congruence(viewer_vector, cand_vector, MIN_COMMON_QUESTIONS)
        scored_profiles.append((profile, score))

    # 4. Ordenación determinista estricta en una sola pasada:
    # - has_score DESC (candidatos con cuestionario primero)
    # - score DESC (mayor congruencia primero)
    # - created_at DESC (más recientes primero ante empate de score)
    # - user_id ASC (desempate lexicográfico estricto)
    def single_sort_key(item: Tuple[Profile, Optional[float]]):
        profile, score = item
        has_score = 1 if score is not None else 0
        score_val = score if score is not None else -1.0
        created_ts = profile.created_at.timestamp() if (profile.created_at and hasattr(profile.created_at, 'timestamp')) else 0.0
        return (-has_score, -score_val, -created_ts, str(profile.user_id))

    scored_profiles.sort(key=single_sort_key)
    return [p for p, _ in scored_profiles]
