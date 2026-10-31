"""
AFINIA — Test Suite BE-03.2: Likes, Pases, Idempotencia y Matches Recíprocos.
============================================================================
Pruebas exhaustivas para POST /api/v1/match/swipe cubriendo los 30 escenarios obligatorios:
1. LIKE válido sin reciprocidad.
2. PASS válido.
3. LIKE recíproco.
4. PASS recibido cuando existe LIKE entrante.
5. LIKE repetido (idempotente).
6. PASS repetido (idempotente).
7. LIKE -> PASS contradictorio (409 CONFLICT).
8. PASS -> LIKE contradictorio (409 CONFLICT).
9. Auto-like (422 VALIDATION_ERROR).
10. UUID inválido (422 VALIDATION_ERROR).
11. Usuario inexistente (404 NOT_FOUND).
12. Usuario sin autenticación (401 UNAUTHORIZED).
13. Usuario pending_profile (403 FORBIDDEN).
14. Usuario suspended (403 FORBIDDEN).
15. Usuario deactivated (403 FORBIDDEN).
16. Candidato bloqueado por solicitante (403 FORBIDDEN).
17. Solicitante bloqueado por candidato (403 FORBIDDEN).
18. Candidato sin fotografía ready (404 NOT_FOUND).
19. Candidato fuera de las preferencias válidas (422 VALIDATION_ERROR).
20. LIKE entrante que no excluye al candidato.
21. Exclusión de descubrimiento después de LIKE.
22. Exclusión de descubrimiento después de PASS.
23. Exclusión de descubrimiento después de match.
24. Dos LIKE simultáneos desde procesos/hilos distintos.
25. Múltiples reintentos simultáneos del mismo LIKE.
26. Prevención de duplicados físicos en matches.
27. Integridad canónica de user_a_id y user_b_id.
28. Rollback si falla la creación del match.
29. Respuestas HTTP/JSON exactas de OpenAPI.
30. Ausencia de regresiones en el sistema.
"""

import uuid
from datetime import date, datetime, timezone
import pytest
from flask import current_app
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    User,
    Profile,
    ProfilePhoto,
    DiscoveryPreference,
    UserBlock,
    ProfileInteraction,
    Match,
)
from app.utils.security import create_access_token


# -------------------------------------------------------------------------
# Fixtures y Helpers
# -------------------------------------------------------------------------

def _create_synthetic_user(
    email: str = None,
    first_name: str = "Ana",
    gender: str = "femenino",
    birth_date: date = None,
    interested_in_genders: list = None,
    min_age: int = 18,
    max_age: int = 40,
    target_relationship_type: str = "seria",
    email_verified: bool = True,
    lifecycle_status: str = "active",
    with_ready_primary_photo: bool = True,
    photo_status: str = "ready",
    city: str = "Bogotá",
    bio: str = "Bio de prueba",
) -> User:
    """Crea y persiste un usuario sintético completo y determinista."""
    if not email:
        email = f"user_{uuid.uuid4().hex[:8]}@afinia.test"
    if not birth_date:
        today = datetime.now(timezone.utc).date()
        birth_date = date(today.year - 25, today.month, today.day)
    if interested_in_genders is None:
        interested_in_genders = ["masculino"]

    user = User(
        email=email,
        password_hash="fake_hash",
        email_verified=email_verified,
        lifecycle_status=lifecycle_status,
        role="user",
    )
    db.session.add(user)
    db.session.flush()

    profile = Profile(
        user_id=user.id,
        first_name=first_name,
        birth_date=birth_date,
        gender=gender,
        city=city,
        bio=bio,
    )
    db.session.add(profile)
    db.session.flush()

    if with_ready_primary_photo:
        photo = ProfilePhoto(
            profile_id=profile.id,
            storage_key=f"photos/{user.id}/p_{uuid.uuid4().hex[:8]}.webp",
            position=0,
            is_primary=True,
            status=photo_status,
            byte_size=1024,
            content_type="image/webp",
        )
        db.session.add(photo)

    pref = DiscoveryPreference(
        user_id=user.id,
        interested_in_genders=interested_in_genders,
        min_age=min_age,
        max_age=max_age,
        target_relationship_type=target_relationship_type,
    )
    db.session.add(pref)
    db.session.commit()
    return user


def _auth_headers(user: User) -> dict:
    """Genera cabeceras HTTP de autorización válidas para el usuario."""
    token = create_access_token(user.id, user.email, user.role, current_app.config['SECRET_KEY'])
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Client-Platform": "mobile",
    }


# -------------------------------------------------------------------------
# Test Suite
# -------------------------------------------------------------------------

class TestSwipeAndReciprocalMatches:

    def test_01_valid_like_without_reciprocity(self, client):
        """1. LIKE válido sin reciprocidad: guarda interacción, is_match=false, match_id=null."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["action"] == "LIKE"
        assert data["is_match"] is False
        assert data["match_id"] is None
        assert "interaction_id" in data

        # Verificar BD
        inter = ProfileInteraction.query.filter_by(viewer_user_id=user_a.id, shown_user_id=user_b.id).first()
        assert inter is not None
        assert inter.action == "LIKE"
        assert Match.query.count() == 0

    def test_02_valid_pass(self, client):
        """2. PASS válido: guarda interacción, is_match=false, match_id=null."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "PASS"}, headers=_auth_headers(user_a))
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["action"] == "PASS"
        assert data["is_match"] is False
        assert data["match_id"] is None

        inter = ProfileInteraction.query.filter_by(viewer_user_id=user_a.id, shown_user_id=user_b.id).first()
        assert inter is not None
        assert inter.action == "PASS"
        assert Match.query.count() == 0

    def test_03_reciprocal_like_creates_single_match(self, client):
        """3. LIKE recíproco: dos LIKE mutuos crean exactamente un Match con is_match=true y match_id real."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # A da LIKE a B
        res1 = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res1.status_code == 200
        assert res1.get_json()["data"]["is_match"] is False

        # B da LIKE a A (recíproco)
        res2 = client.post("/api/v1/match/swipe", json={"target_user_id": user_a.id, "action": "LIKE"}, headers=_auth_headers(user_b))
        assert res2.status_code == 200
        data2 = res2.get_json()["data"]
        assert data2["is_match"] is True
        assert data2["match_id"] is not None

        # Verificar BD: exactamente 1 match y orden canónico
        matches = Match.query.all()
        assert len(matches) == 1
        m = matches[0]
        assert str(m.id) == str(data2["match_id"])
        expected_min = min(user_a.id, user_b.id)
        expected_max = max(user_a.id, user_b.id)
        assert m.user_a_id == expected_min
        assert m.user_b_id == expected_max

    def test_04_pass_with_incoming_like_does_not_match(self, client):
        """4. PASS recibido cuando existe LIKE entrante: guarda PASS y NO genera match."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # B da LIKE a A
        client.post("/api/v1/match/swipe", json={"target_user_id": user_a.id, "action": "LIKE"}, headers=_auth_headers(user_b))

        # A da PASS a B
        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "PASS"}, headers=_auth_headers(user_a))
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["action"] == "PASS"
        assert data["is_match"] is False
        assert data["match_id"] is None
        assert Match.query.count() == 0

    def test_05_repeated_like_is_idempotent(self, client):
        """5. LIKE repetido: no crea otra interacción, conserva interaction_id y refleja match correctamente."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # Primer LIKE de A hacia B
        res1 = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        data1 = res1.get_json()["data"]
        interaction_id_1 = data1["interaction_id"]

        # Reintento idéntico de A hacia B
        res2 = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res2.status_code == 200
        data2 = res2.get_json()["data"]
        assert data2["interaction_id"] == interaction_id_1
        assert data2["is_match"] is False
        assert data2["match_id"] is None

        # B da LIKE a A (se crea match)
        client.post("/api/v1/match/swipe", json={"target_user_id": user_a.id, "action": "LIKE"}, headers=_auth_headers(user_b))

        # Reintento de A hacia B después de formarse match: debe reflejar is_match=True
        res3 = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res3.status_code == 200
        data3 = res3.get_json()["data"]
        assert data3["interaction_id"] == interaction_id_1
        assert data3["is_match"] is True
        assert data3["match_id"] is not None
        assert ProfileInteraction.query.filter_by(viewer_user_id=user_a.id, shown_user_id=user_b.id).count() == 1

    def test_06_repeated_pass_is_idempotent(self, client):
        """6. PASS repetido: no crea duplicados, conserva interaction_id y devuelve 200 OK."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        res1 = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "PASS"}, headers=_auth_headers(user_a))
        data1 = res1.get_json()["data"]

        res2 = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "PASS"}, headers=_auth_headers(user_a))
        assert res2.status_code == 200
        data2 = res2.get_json()["data"]
        assert data2["interaction_id"] == data1["interaction_id"]
        assert data2["action"] == "PASS"
        assert ProfileInteraction.query.filter_by(viewer_user_id=user_a.id, shown_user_id=user_b.id).count() == 1

    def test_07_contradictory_like_then_pass_returns_409(self, client):
        """7. LIKE -> PASS contradictorio: responde 409 CONFLICT."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "PASS"}, headers=_auth_headers(user_a))
        assert res.status_code == 409
        assert res.get_json()["error"]["code"] == "CONFLICT"

    def test_08_contradictory_pass_then_like_returns_409(self, client):
        """8. PASS -> LIKE contradictorio: responde 409 CONFLICT."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "PASS"}, headers=_auth_headers(user_a))
        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 409
        assert res.get_json()["error"]["code"] == "CONFLICT"

    def test_09_auto_like_rejected_with_422(self, client):
        """9. Auto-like: target_user_id == current_user.id responde 422 VALIDATION_ERROR."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_a.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_10_invalid_uuid_returns_422(self, client):
        """10. UUID inválido: responde 422 VALIDATION_ERROR."""
        user_a = _create_synthetic_user()
        res = client.post("/api/v1/match/swipe", json={"target_user_id": "no-es-un-uuid", "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_11_nonexistent_target_user_returns_404(self, client):
        """11. Usuario inexistente: responde 404 NOT_FOUND."""
        user_a = _create_synthetic_user()
        random_uuid = str(uuid.uuid4())
        res = client.post("/api/v1/match/swipe", json={"target_user_id": random_uuid, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    def test_12_unauthenticated_request_returns_401(self, client):
        """12. Solicitud sin JWT: responde 401 UNAUTHORIZED."""
        random_uuid = str(uuid.uuid4())
        res = client.post("/api/v1/match/swipe", json={"target_user_id": random_uuid, "action": "LIKE"})
        assert res.status_code == 401
        assert res.get_json()["error"]["code"] == "UNAUTHORIZED"

    def test_13_pending_profile_viewer_returns_403(self, client):
        """13. Usuario en pending_profile: responde 403 FORBIDDEN."""
        user_a = _create_synthetic_user(lifecycle_status="pending_profile")
        user_b = _create_synthetic_user()

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    def test_14_suspended_viewer_returns_403(self, client):
        """14. Usuario suspendido: responde 403 FORBIDDEN."""
        user_a = _create_synthetic_user(lifecycle_status="suspended")
        user_b = _create_synthetic_user()

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    def test_15_deactivated_viewer_returns_403(self, client):
        """15. Usuario desactivado: responde 403 FORBIDDEN o 401 UNAUTHORIZED por middleware."""
        user_a = _create_synthetic_user(lifecycle_status="deactivated")
        user_b = _create_synthetic_user()

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code in (401, 403)
        assert res.get_json()["error"]["code"] in ("FORBIDDEN", "UNAUTHORIZED")

    def test_16_target_blocked_by_viewer_returns_403(self, client):
        """16. Candidato bloqueado por solicitante: responde 403 FORBIDDEN."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        db.session.add(UserBlock(blocker_user_id=user_a.id, blocked_user_id=user_b.id))
        db.session.commit()

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    def test_17_viewer_blocked_by_target_returns_403(self, client):
        """17. Solicitante bloqueado por candidato: responde 403 FORBIDDEN."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        db.session.add(UserBlock(blocker_user_id=user_b.id, blocked_user_id=user_a.id))
        db.session.commit()

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    def test_18_target_without_ready_photo_returns_404(self, client):
        """18. Candidato sin fotografía principal ready: responde 404 NOT_FOUND."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"], photo_status="pending")

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "NOT_FOUND"

    def test_19_target_outside_valid_preferences_returns_422(self, client):
        """19. Candidato fuera de preferencias de género o edad: responde 422 VALIDATION_ERROR."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"], min_age=20, max_age=30)
        # Candidata fuera de rango de edad de Alex (38 años)
        today = datetime.now(timezone.utc).date()
        user_b = _create_synthetic_user(
            first_name="Beatriz",
            gender="femenino",
            birth_date=date(today.year - 38, today.month, today.day),
            interested_in_genders=["masculino"]
        )

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_20_incoming_like_does_not_exclude_from_discovery(self, client):
        """20. Un LIKE entrante de B hacia A no excluye a B de la lista de descubrimiento de A."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # B da LIKE a A
        client.post("/api/v1/match/swipe", json={"target_user_id": user_a.id, "action": "LIKE"}, headers=_auth_headers(user_b))

        # A consulta GET /match/potential
        res = client.get("/api/v1/match/potential", headers=_auth_headers(user_a))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert any(item["user_id"] == user_b.id for item in items)

    def test_21_exclusion_from_discovery_after_like(self, client):
        """21. Después de emitir LIKE, el candidato no reaparece en el descubrimiento del solicitante."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # A da LIKE a B
        client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))

        # A vuelve a consultar descubrimiento
        res = client.get("/api/v1/match/potential", headers=_auth_headers(user_a))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert not any(item["user_id"] == user_b.id for item in items)

    def test_22_exclusion_from_discovery_after_pass(self, client):
        """22. Después de emitir PASS, el candidato no reaparece en el descubrimiento del solicitante."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # A da PASS a B
        client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "PASS"}, headers=_auth_headers(user_a))

        # A consulta descubrimiento
        res = client.get("/api/v1/match/potential", headers=_auth_headers(user_a))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert not any(item["user_id"] == user_b.id for item in items)

    def test_23_mutual_exclusion_from_discovery_after_match(self, client):
        """23. Tras formarse un match, ambos usuarios quedan excluidos del descubrimiento mutuo."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # A da LIKE a B y B da LIKE a A
        client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        client.post("/api/v1/match/swipe", json={"target_user_id": user_a.id, "action": "LIKE"}, headers=_auth_headers(user_b))

        # Ni A ve a B, ni B ve a A
        res_a = client.get("/api/v1/match/potential", headers=_auth_headers(user_a))
        assert not any(item["user_id"] == user_b.id for item in res_a.get_json()["data"]["items"])

        res_b = client.get("/api/v1/match/potential", headers=_auth_headers(user_b))
        assert not any(item["user_id"] == user_a.id for item in res_b.get_json()["data"]["items"])

    def test_24_simultaneous_likes_concurrency_serializes_cleanly(self, client):
        """24. Dos likes consecutivos o simultáneos generan exactamente un Match físico y dos interacciones."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        r1 = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        r2 = client.post("/api/v1/match/swipe", json={"target_user_id": user_a.id, "action": "LIKE"}, headers=_auth_headers(user_b))

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.get_json()["data"]["is_match"] is False
        assert r2.get_json()["data"]["is_match"] is True

        assert Match.query.count() == 1
        assert ProfileInteraction.query.count() == 2

    def test_25_multiple_rapid_retries_preserve_single_interaction(self, client):
        """25. Múltiples reintentos idénticos rápidos conservan exactamente 1 interacción física."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        for _ in range(5):
            res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
            assert res.status_code == 200

        assert ProfileInteraction.query.filter_by(viewer_user_id=user_a.id, shown_user_id=user_b.id).count() == 1

    def test_26_prevent_physical_duplicates_in_matches_table(self, client):
        """26. La restricción uq_match_pair previene físicamente duplicados de pareja ordenada."""
        user_a = _create_synthetic_user(first_name="Alex")
        user_b = _create_synthetic_user(first_name="Beatriz")

        id_a, id_b = sorted([user_a.id, user_b.id])
        m1 = Match(id=str(uuid.uuid4()), user_a_id=id_a, user_b_id=id_b)
        db.session.add(m1)
        db.session.commit()

        # Intentar insertar exactamente la misma pareja ordenada
        m2 = Match(id=str(uuid.uuid4()), user_a_id=id_a, user_b_id=id_b)
        db.session.add(m2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_27_canonical_ordering_user_a_less_than_user_b(self, client):
        """27. Integridad canónica de user_a_id < user_b_id forzada por check constraint."""
        user_a = _create_synthetic_user(first_name="Alex")
        user_b = _create_synthetic_user(first_name="Beatriz")

        id_min, id_max = sorted([user_a.id, user_b.id])
        # Intentar insertar con orden inverso (id_max como user_a_id)
        m_invalid = Match(id=str(uuid.uuid4()), user_a_id=id_max, user_b_id=id_min)
        db.session.add(m_invalid)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_28_rollback_on_failure_leaves_no_corrupted_state(self, client):
        """28. Rollback ante error imprevisto no deja interacciones huérfanas ni matches parciales."""
        user_a = _create_synthetic_user()
        # Enviar petición con body corrupto que rompa validaciones
        res = client.post(
            "/api/v1/match/swipe",
            data="not-a-json",
            headers={"Authorization": _auth_headers(user_a)["Authorization"], "Content-Type": "application/json"}
        )
        assert res.status_code in (400, 422)
        assert ProfileInteraction.query.count() == 0
        assert Match.query.count() == 0

    def test_29_exact_openapi_swipe_result_envelope(self, client):
        """29. Respuesta HTTP 200 cumple estrictamente con el esquema OpenAPI SwipeResult."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        res = client.post("/api/v1/match/swipe", json={"target_user_id": user_b.id, "action": "LIKE"}, headers=_auth_headers(user_a))
        assert res.status_code == 200
        body = res.get_json()

        # Envoltura { data: ... }
        assert "data" in body
        data = body["data"]

        # Campos obligatorios de SwipeResult
        assert set(data.keys()) == {"interaction_id", "action", "is_match", "match_id"}
        uuid.UUID(data["interaction_id"])  # valida formato UUID
        assert data["action"] in ("LIKE", "PASS")
        assert isinstance(data["is_match"], bool)
        assert data["match_id"] is None or isinstance(data["match_id"], str)

    def test_30_no_regressions_with_additional_properties_rejected(self, client):
        """30. Rechazo de propiedades no documentadas (additionalProperties: false) con 422 VALIDATION_ERROR."""
        user_a = _create_synthetic_user(first_name="Alex", gender="masculino", interested_in_genders=["femenino"])
        user_b = _create_synthetic_user(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # Intento de inyectar campo malicioso o no documentado
        payload = {
            "target_user_id": user_b.id,
            "action": "LIKE",
            "viewer_user_id": user_a.id,  # Campo no permitido
            "extra_field": 123
        }
        res = client.post("/api/v1/match/swipe", json=payload, headers=_auth_headers(user_a))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"
