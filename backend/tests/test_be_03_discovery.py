"""
AFINIA — Test Suite BE-03.1: Descubrimiento Real de Perfiles y Perfil Público.
=============================================================================
Pruebas exhaustivas para:
- GET /api/v1/match/potential
- GET /api/v1/users/{userId}
Verificando elegibilidad estricta, reciprocidad, bloqueos bidireccionales,
no exposición de datos privados, paginación estable por cursor y manejo de errores OpenAPI.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
import pytest
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
from flask import current_app
from app.utils.security import create_access_token


# -------------------------------------------------------------------------
# Fixtures y Helpers de creación de usuarios sintéticos
# -------------------------------------------------------------------------

def _create_synthetic_candidate(
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
        # Por defecto 25 años
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
    """Genera encabezados HTTP Authorization con JWT válido para el usuario."""
    token = create_access_token(
        user.id, user.email, user.role, current_app.config['SECRET_KEY']
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Client-Platform": "mobile",
    }


# =========================================================================
# PRUEBAS BE-03.1
# =========================================================================

class TestDiscoveryAuthenticationAndEligibility:
    """Pruebas de autenticación y estado del usuario solicitante."""

    def test_01_discovery_valid_between_active_users(self, client):
        """1. Descubrimiento válido entre usuarios activos retorna lista con items y metadatos."""
        viewer = _create_synthetic_candidate(
            first_name="Carlos",
            gender="masculino",
            interested_in_genders=["femenino"],
            min_age=20,
            max_age=30,
            target_relationship_type="seria",
        )
        candidate = _create_synthetic_candidate(
            first_name="Diana",
            gender="femenino",
            interested_in_genders=["masculino"],
            min_age=20,
            max_age=35,
            target_relationship_type="seria",
        )

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        body = res.get_json()
        assert "data" in body and "items" in body["data"]
        assert "meta" in body and "has_more" in body["meta"]
        items = body["data"]["items"]
        assert len(items) == 1
        assert items[0]["user_id"] == candidate.id
        assert items[0]["first_name"] == "Diana"
        assert items[0]["relationship_goal"] == "seria"

    def test_02_discovery_without_session_returns_401(self, client):
        """2. Usuario sin sesión responde 401 UNAUTHORIZED."""
        res = client.get("/api/v1/match/potential")
        assert res.status_code == 401
        assert res.get_json()["error"]["code"] == "UNAUTHORIZED"

    def test_03_discovery_user_pending_profile_returns_403(self, client):
        """3. Usuario con status 'pending_profile' responde 403 FORBIDDEN."""
        pending_user = _create_synthetic_candidate(lifecycle_status="pending_profile")
        res = client.get("/api/v1/match/potential", headers=_auth_headers(pending_user))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    def test_04_discovery_user_suspended_returns_403(self, client):
        """4. Cuenta suspendida responde 403 FORBIDDEN."""
        suspended = _create_synthetic_candidate(lifecycle_status="suspended")
        res = client.get("/api/v1/match/potential", headers=_auth_headers(suspended))
        assert res.status_code == 403
        assert res.get_json()["error"]["code"] == "FORBIDDEN"

    def test_05_discovery_user_deactivated_returns_403_or_401(self, client):
        """5. Cuenta desactivada es rechazada (401 UNAUTHORIZED por token_required o 403 FORBIDDEN)."""
        deactivated = _create_synthetic_candidate(lifecycle_status="deactivated")
        res = client.get("/api/v1/match/potential", headers=_auth_headers(deactivated))
        assert res.status_code in (401, 403)
        assert res.get_json()["error"]["code"] in ("UNAUTHORIZED", "FORBIDDEN")

    def test_06_exclusion_of_candidate_without_ready_photo(self, client):
        """6. Exclusión de candidatos sin fotografía en estado 'ready'."""
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        # Candidata con foto en estado 'pending'
        _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"], photo_status="pending")
        # Candidata con foto en estado 'rejected'
        _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"], photo_status="rejected")
        # Candidata sin ninguna foto
        _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"], with_ready_primary_photo=False)

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        assert len(res.get_json()["data"]["items"]) == 0

    def test_07_exclusion_of_candidate_without_email_verified(self, client):
        """7. Exclusión de candidatos que no tienen email verificado."""
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"], email_verified=False)

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        assert len(res.get_json()["data"]["items"]) == 0

    def test_08_exclusion_of_own_account(self, client):
        """8. Exclusión de la propia cuenta (el solicitante nunca se ve a sí mismo)."""
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["masculino"])

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert all(it["user_id"] != viewer.id for it in items)


class TestBlocksAndInteractions:
    """Pruebas de bloqueos bidireccionales y conservación de likes entrantes."""

    def test_09_exclusion_when_viewer_blocks_candidate(self, client):
        """9. Bloqueo de A hacia B: B no aparece en candidatos de A."""
        viewer_a = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        candidate_b = _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])

        # A bloquea a B
        block = UserBlock(blocker_user_id=viewer_a.id, blocked_user_id=candidate_b.id)
        db.session.add(block)
        db.session.commit()

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer_a))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert all(it["user_id"] != candidate_b.id for it in items)

    def test_10_exclusion_when_candidate_blocks_viewer(self, client):
        """10. Bloqueo de B hacia A: A no ve a B en candidatos."""
        viewer_a = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        candidate_b = _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])

        # B bloquea a A
        block = UserBlock(blocker_user_id=candidate_b.id, blocked_user_id=viewer_a.id)
        db.session.add(block)
        db.session.commit()

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer_a))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert all(it["user_id"] != candidate_b.id for it in items)

    def test_15_exclusion_of_already_seen_profiles(self, client):
        """15. Exclusión de candidatos que el solicitante ya vio (LIKE o PASS emitido por A)."""
        viewer_a = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        cand_like = _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])
        cand_pass = _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])

        # A ya dio LIKE a cand_like y PASS a cand_pass
        db.session.add(ProfileInteraction(viewer_user_id=viewer_a.id, shown_user_id=cand_like.id, action="LIKE"))
        db.session.add(ProfileInteraction(viewer_user_id=viewer_a.id, shown_user_id=cand_pass.id, action="PASS"))
        db.session.commit()

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer_a))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        seen_ids = [it["user_id"] for it in items]
        assert cand_like.id not in seen_ids
        assert cand_pass.id not in seen_ids

    def test_16_preservation_of_incoming_likes(self, client):
        """16. Conservación de likes entrantes: si B dio LIKE a A, B SÍ debe aparecer como candidato de A."""
        viewer_a = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        candidate_b = _create_synthetic_candidate(first_name="Beatriz", gender="femenino", interested_in_genders=["masculino"])

        # B vio a A y le dio LIKE. A aún NO ha interactuado con B.
        db.session.add(ProfileInteraction(viewer_user_id=candidate_b.id, shown_user_id=viewer_a.id, action="LIKE"))
        db.session.commit()

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer_a))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        candidate_ids = [it["user_id"] for it in items]
        assert candidate_b.id in candidate_ids


class TestPreferencesAndReciprocity:
    """Pruebas de filtrado por edades, géneros y reciprocidad."""

    def test_11_filtering_by_age_range(self, client):
        """11. Filtrado por edades: candidatos fuera del rango solicitado son excluidos."""
        today = datetime.now(timezone.utc).date()
        viewer = _create_synthetic_candidate(
            gender="masculino",
            interested_in_genders=["femenino"],
            min_age=25,
            max_age=30,
        )
        # Candidata de 22 años (demasiado joven)
        _create_synthetic_candidate(
            gender="femenino",
            birth_date=date(today.year - 22, today.month, today.day),
            interested_in_genders=["masculino"],
            min_age=18,
            max_age=40,
        )
        # Candidata de 35 años (demasiado mayor)
        _create_synthetic_candidate(
            gender="femenino",
            birth_date=date(today.year - 35, today.month, today.day),
            interested_in_genders=["masculino"],
            min_age=18,
            max_age=40,
        )
        # Candidata de 27 años (dentro de rango)
        cand_in_range = _create_synthetic_candidate(
            gender="femenino",
            birth_date=date(today.year - 27, today.month, today.day),
            interested_in_genders=["masculino"],
            min_age=18,
            max_age=40,
        )

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["user_id"] == cand_in_range.id

    def test_12_filtering_by_interested_genders(self, client):
        """12. Filtrado por géneros de interés."""
        viewer = _create_synthetic_candidate(
            gender="masculino",
            interested_in_genders=["femenino"],
        )
        # Candidato masculino (no solicitado por viewer)
        _create_synthetic_candidate(gender="masculino", interested_in_genders=["masculino"])
        # Candidato no_binario (no solicitado por viewer)
        _create_synthetic_candidate(gender="no_binario", interested_in_genders=["masculino"])
        # Candidata femenina
        cand_fem = _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["user_id"] == cand_fem.id

    def test_13_reciprocity_enforcement(self, client):
        """13. Reciprocidad: el solicitante también debe cumplir las preferencias del candidato."""
        today = datetime.now(timezone.utc).date()
        # Viewer tiene 25 años y es masculino
        viewer = _create_synthetic_candidate(
            gender="masculino",
            birth_date=date(today.year - 25, today.month, today.day),
            interested_in_genders=["femenino"],
            min_age=20,
            max_age=30,
        )
        # Candidata A: solo busca mujeres (incompatible recíproco con viewer masculino)
        _create_synthetic_candidate(
            gender="femenino",
            interested_in_genders=["femenino"],
            min_age=20,
            max_age=30,
        )
        # Candidata B: busca hombres pero de 30 a 40 años (viewer tiene 25, incompatible)
        _create_synthetic_candidate(
            gender="femenino",
            interested_in_genders=["masculino"],
            min_age=30,
            max_age=40,
        )
        # Candidata C: busca hombres de 20 a 30 años (compatible recíprocamente)
        cand_c = _create_synthetic_candidate(
            gender="femenino",
            interested_in_genders=["masculino"],
            min_age=20,
            max_age=30,
        )

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["user_id"] == cand_c.id

    def test_14_relationship_goal_determinism(self, client):
        """14. Tratamiento determinista del objetivo relacional."""
        # Viewer busca 'seria'
        viewer = _create_synthetic_candidate(
            gender="masculino",
            interested_in_genders=["femenino"],
            target_relationship_type="seria",
        )
        # Candidata busca 'casual' (incompatible)
        _create_synthetic_candidate(
            gender="femenino",
            interested_in_genders=["masculino"],
            target_relationship_type="casual",
        )
        # Candidata busca 'seria' (compatible exacta)
        cand_seria = _create_synthetic_candidate(
            first_name="Laura",
            gender="femenino",
            interested_in_genders=["masculino"],
            target_relationship_type="seria",
        )
        # Candidata tiene 'sin_definir' (abierta, compatible)
        cand_sin_def = _create_synthetic_candidate(
            first_name="Sofia",
            gender="femenino",
            interested_in_genders=["masculino"],
            target_relationship_type="sin_definir",
        )

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 2
        returned_names = {it["first_name"] for it in items}
        assert returned_names == {"Laura", "Sofia"}


class TestPublicProfileEndpoint:
    """Pruebas para GET /api/v1/users/{userId}."""

    def test_17_get_valid_public_profile_returns_200(self, client):
        """17. Consulta de perfil público válido retorna 200 con esquema PublicProfile."""
        viewer = _create_synthetic_candidate()
        target = _create_synthetic_candidate(
            first_name="Valentina",
            gender="femenino",
            city="Medellín",
            bio="Apasionada por la música",
            target_relationship_type="seria",
        )

        res = client.get(f"/api/v1/users/{target.id}", headers=_auth_headers(viewer))
        assert res.status_code == 200
        data = res.get_json()["data"]

        assert data["user_id"] == target.id
        assert data["first_name"] == "Valentina"
        assert data["gender"] == "femenino"
        assert data["city"] == "Medellín"
        assert data["bio"] == "Apasionada por la música"
        assert data["relationship_goal"] == "seria"
        assert isinstance(data["photos"], list)
        assert len(data["photos"]) >= 1
        assert data["photos"][0]["is_primary"] is True

    def test_18_get_public_profile_blocked_or_ineligible_returns_404(self, client):
        """18. Rechazo con 404 NOT_FOUND si hay bloqueo o el usuario no existe/no es elegible."""
        viewer = _create_synthetic_candidate()
        target = _create_synthetic_candidate()

        # Bloqueo mutuo
        db.session.add(UserBlock(blocker_user_id=target.id, blocked_user_id=viewer.id))
        db.session.commit()

        res_blocked = client.get(f"/api/v1/users/{target.id}", headers=_auth_headers(viewer))
        assert res_blocked.status_code == 404
        assert res_blocked.get_json()["error"]["code"] == "NOT_FOUND"

        # UUID inexistente
        random_uuid = str(uuid.uuid4())
        res_nonexistent = client.get(f"/api/v1/users/{random_uuid}", headers=_auth_headers(viewer))
        assert res_nonexistent.status_code == 404

    def test_19_no_private_data_leakage_in_public_profile(self, client):
        """19. Privacidad estricta: NO exposición de email, birth_date, password_hash ni role."""
        viewer = _create_synthetic_candidate()
        target = _create_synthetic_candidate(email="privado.secreto@afinia.test")

        res = client.get(f"/api/v1/users/{target.id}", headers=_auth_headers(viewer))
        assert res.status_code == 200
        data = res.get_json()["data"]

        forbidden_keys = ["email", "birth_date", "password_hash", "role", "tokens", "storage_key", "answers"]
        for key in forbidden_keys:
            assert key not in data, f"Fuga de privacidad: '{key}' no debe exponerse en PublicProfile."

    def test_20_public_photos_ready_only(self, client):
        """20. Las fotografías devueltas deben estar exclusivamente en estado 'ready'."""
        viewer = _create_synthetic_candidate()
        target = _create_synthetic_candidate()

        # Agregar una foto 'pending' y una foto 'rejected'
        db.session.add(ProfilePhoto(
            profile_id=target.profile.id,
            storage_key=f"photos/{target.id}/pending.webp",
            position=1,
            is_primary=False,
            status="pending",
        ))
        db.session.add(ProfilePhoto(
            profile_id=target.profile.id,
            storage_key=f"photos/{target.id}/rejected.webp",
            position=2,
            is_primary=False,
            status="rejected",
        ))
        # Agregar una segunda foto 'ready'
        db.session.add(ProfilePhoto(
            profile_id=target.profile.id,
            storage_key=f"photos/{target.id}/ready2.webp",
            position=3,
            is_primary=False,
            status="ready",
        ))
        db.session.commit()

        res = client.get(f"/api/v1/users/{target.id}", headers=_auth_headers(viewer))
        assert res.status_code == 200
        photos = res.get_json()["data"]["photos"]
        # Debe haber exactamente 2 fotos (la primaria ready + la segunda ready)
        assert len(photos) == 2


class TestPaginationAndCursor:
    """Pruebas de paginación estable, cursores y límites."""

    def test_21_stable_cursor_pagination(self, client):
        """21. Paginación estable: límite efectivo y cursor determinista sin duplicados."""
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        candidates = []
        for i in range(5):
            c = _create_synthetic_candidate(
                first_name=f"Candidata_{i}",
                gender="femenino",
                interested_in_genders=["masculino"],
            )
            candidates.append(c)

        # Página 1 con limit=2
        res1 = client.get("/api/v1/match/potential?limit=2", headers=_auth_headers(viewer))
        assert res1.status_code == 200
        b1 = res1.get_json()
        assert len(b1["data"]["items"]) == 2
        assert b1["meta"]["has_more"] is True
        assert b1["meta"]["next_cursor"] is not None

        # Página 2 con cursor
        cursor = b1["meta"]["next_cursor"]
        res2 = client.get(f"/api/v1/match/potential?limit=2&cursor={cursor}", headers=_auth_headers(viewer))
        assert res2.status_code == 200
        b2 = res2.get_json()
        assert len(b2["data"]["items"]) == 2

        # Comprobar disyunción de páginas (cero duplicados)
        ids_p1 = {it["user_id"] for it in b1["data"]["items"]}
        ids_p2 = {it["user_id"] for it in b2["data"]["items"]}
        assert len(ids_p1.intersection(ids_p2)) == 0

    def test_22_invalid_cursor_returns_422(self, client):
        """22. Cursores inválidos o manipulados responden 422 VALIDATION_ERROR."""
        viewer = _create_synthetic_candidate()
        res = client.get("/api/v1/match/potential?cursor=cursor_corrupto_no_base64", headers=_auth_headers(viewer))
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_23_empty_page_response(self, client):
        """23. Página vacía responde con items: [], next_cursor: null, has_more: false."""
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        # Sin candidatas en BD

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        b = res.get_json()
        assert b["data"]["items"] == []
        assert b["meta"]["next_cursor"] is None
        assert b["meta"]["has_more"] is False

    def test_24_exact_json_envelope_openapi_compliance(self, client):
        """24. Compatibilidad exacta de respuesta JSON con el contrato OpenAPI v1."""
        viewer = _create_synthetic_candidate()
        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res.status_code == 200
        body = res.get_json()

        assert "data" in body and isinstance(body["data"], dict)
        assert "items" in body["data"] and isinstance(body["data"]["items"], list)
        assert "meta" in body and isinstance(body["meta"], dict)
        assert "next_cursor" in body["meta"]
        assert "has_more" in body["meta"] and isinstance(body["meta"]["has_more"], bool)

    def test_25_invalid_limit_query_param_returns_422(self, client):
        """25. Límite fuera de rango (0, 51 o no entero) responde 422 VALIDATION_ERROR."""
        viewer = _create_synthetic_candidate()
        # limit < 1
        res_zero = client.get("/api/v1/match/potential?limit=0", headers=_auth_headers(viewer))
        assert res_zero.status_code == 422
        assert res_zero.get_json()["error"]["code"] == "VALIDATION_ERROR"

        # limit > 50
        res_overflow = client.get("/api/v1/match/potential?limit=51", headers=_auth_headers(viewer))
        assert res_overflow.status_code == 422
        assert res_overflow.get_json()["error"]["code"] == "VALIDATION_ERROR"

        # limit no numérico
        res_nan = client.get("/api/v1/match/potential?limit=diez", headers=_auth_headers(viewer))
        assert res_nan.status_code == 422
        assert res_nan.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_26_hmac_tampered_cursor_returns_422(self, client):
        """26. Cursor alterado conservando Base64 válido es rechazado con 422 VALIDATION_ERROR."""
        import base64
        import json
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])
        _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])

        res = client.get("/api/v1/match/potential?limit=1", headers=_auth_headers(viewer))
        assert res.status_code == 200
        valid_cursor = res.get_json()["meta"]["next_cursor"]
        assert valid_cursor is not None

        # Alterar el payload conservando base64url válido
        raw_bytes = base64.urlsafe_b64decode(valid_cursor.encode('ascii'))
        payload = json.loads(raw_bytes.decode('utf-8'))
        # Cambiar el user_id objetivo sin recalcular la firma HMAC
        payload["u"] = str(uuid.uuid4())
        tampered_bytes = json.dumps(payload).encode('utf-8')
        tampered_cursor = base64.urlsafe_b64encode(tampered_bytes).decode('ascii')

        res_tampered = client.get(f"/api/v1/match/potential?cursor={tampered_cursor}", headers=_auth_headers(viewer))
        assert res_tampered.status_code == 422
        assert res_tampered.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_27_cursor_cross_user_reuse_rejected(self, client):
        """27. Cursor emitido para un usuario utilizado por otro usuario es rechazado con 422."""
        viewer_1 = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        viewer_2 = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])
        _create_synthetic_candidate(gender="femenino", interested_in_genders=["masculino"])

        res1 = client.get("/api/v1/match/potential?limit=1", headers=_auth_headers(viewer_1))
        assert res1.status_code == 200
        cursor_v1 = res1.get_json()["meta"]["next_cursor"]
        assert cursor_v1 is not None

        # viewer_2 intenta usar el cursor emitido para viewer_1
        res2 = client.get(f"/api/v1/match/potential?cursor={cursor_v1}", headers=_auth_headers(viewer_2))
        assert res2.status_code == 422
        assert res2.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_28_pagination_more_than_three_pages(self, client):
        """28. Paginación de más de 3 páginas recorre todos los candidatos sin duplicados ni omisiones."""
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        for i in range(7):
            _create_synthetic_candidate(
                first_name=f"CandMulti_{i}",
                gender="femenino",
                interested_in_genders=["masculino"]
            )

        collected_ids = []
        cursor = None
        pages_count = 0

        while True:
            url = "/api/v1/match/potential?limit=2"
            if cursor:
                url += f"&cursor={cursor}"
            res = client.get(url, headers=_auth_headers(viewer))
            assert res.status_code == 200
            body = res.get_json()
            items = body["data"]["items"]
            pages_count += 1

            for it in items:
                collected_ids.append(it["user_id"])

            if not body["meta"]["has_more"]:
                assert body["meta"]["next_cursor"] is None
                break
            cursor = body["meta"]["next_cursor"]

        assert pages_count == 4  # 2 + 2 + 2 + 1 = 7 elementos en 4 páginas
        assert len(collected_ids) == 7
        assert len(set(collected_ids)) == 7  # Cero duplicados

    def test_29_pagination_same_created_at_tie_breaking(self, client):
        """29. Desempate por user_id ASC cuando varios perfiles tienen exactamente el mismo created_at."""
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        fixed_timestamp = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        candidates = []
        for i in range(4):
            c = _create_synthetic_candidate(
                first_name=f"CandTie_{i}",
                gender="femenino",
                interested_in_genders=["masculino"]
            )
            # Forzar exactamente el mismo created_at
            c.profile.created_at = fixed_timestamp
            candidates.append(c)
        db.session.commit()

        # Recorrer con limit=2
        res1 = client.get("/api/v1/match/potential?limit=2", headers=_auth_headers(viewer))
        assert res1.status_code == 200
        b1 = res1.get_json()
        assert len(b1["data"]["items"]) == 2
        assert b1["meta"]["has_more"] is True

        cursor1 = b1["meta"]["next_cursor"]
        res2 = client.get(f"/api/v1/match/potential?limit=2&cursor={cursor1}", headers=_auth_headers(viewer))
        assert res2.status_code == 200
        b2 = res2.get_json()
        assert len(b2["data"]["items"]) == 2
        assert b2["meta"]["has_more"] is False

        # Verificar que no se repitan y que los 4 candidatos hayan aparecido
        all_ids = [it["user_id"] for it in b1["data"]["items"]] + [it["user_id"] for it in b2["data"]["items"]]
        assert len(all_ids) == 4
        assert len(set(all_ids)) == 4

    def test_30_jsonb_non_binary_and_undisclosed_gender(self, client):
        """30. Filtrado JSONB con categorías no_binario y prefiero_no_indicar."""
        viewer_nb = _create_synthetic_candidate(
            gender="no_binario",
            interested_in_genders=["femenino", "no_binario"]
        )
        cand_accepts_nb = _create_synthetic_candidate(
            first_name="AceptaNB",
            gender="femenino",
            interested_in_genders=["no_binario"]
        )
        cand_rejects_nb = _create_synthetic_candidate(
            first_name="RechazaNB",
            gender="femenino",
            interested_in_genders=["masculino"]
        )

        res = client.get("/api/v1/match/potential", headers=_auth_headers(viewer_nb))
        assert res.status_code == 200
        items = res.get_json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["user_id"] == cand_accepts_nb.id

    def test_31_photo_url_is_functional_and_downloads_binary(self, client):
        """31. photo.url devuelta en potential y users/{id} es funcional y descarga binario real."""
        viewer = _create_synthetic_candidate(gender="masculino", interested_in_genders=["femenino"])
        candidate = _create_synthetic_candidate(
            first_name="CamilaFoto",
            gender="femenino",
            interested_in_genders=["masculino"]
        )

        # Crear archivo físico de imagen de prueba con storage_adapter
        from app.services.storage_service import storage_adapter
        test_bytes = b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x02\x00\x34\x25"
        real_key = storage_adapter.save_file(test_bytes, "webp")
        candidate.profile.photos[0].storage_key = real_key
        db.session.commit()

        # A. Desde /potential
        res_pot = client.get("/api/v1/match/potential", headers=_auth_headers(viewer))
        assert res_pot.status_code == 200
        photo_pot = res_pot.get_json()["data"]["items"][0]["photos"][0]
        pot_photo_url = photo_pot["url"]
        assert "/api/v1/profile/photos/media/" in pot_photo_url

        # Descargar con GET usando ruta extraída literalmente
        pot_path = "/" + pot_photo_url.split("/", 3)[-1] if pot_photo_url.startswith("http") else pot_photo_url

        res_media_pot = client.get(pot_path, headers=_auth_headers(viewer))
        assert res_media_pot.status_code == 200
        assert res_media_pot.content_type.startswith("image/")
        assert len(res_media_pot.data) > 0

        # B. Repetir desde GET /api/v1/users/{userId}
        res_user = client.get(f"/api/v1/users/{candidate.id}", headers=_auth_headers(viewer))
        assert res_user.status_code == 200
        user_photo = res_user.get_json()["data"]["photos"][0]
        user_photo_url = user_photo["url"]
        assert "/api/v1/profile/photos/media/" in user_photo_url

        user_photo_path = "/" + user_photo_url.split("/", 3)[-1] if user_photo_url.startswith("http") else user_photo_url
        res_media_user = client.get(user_photo_path, headers=_auth_headers(viewer))
        assert res_media_user.status_code == 200
        assert res_media_user.content_type.startswith("image/")
        assert len(res_media_user.data) > 0

        # C. Sin JWT -> 401
        res_no_auth = client.get(pot_path)
        assert res_no_auth.status_code == 401

        # D. Con bloqueo mutuo -> 403
        db.session.add(UserBlock(blocker_user_id=candidate.id, blocked_user_id=viewer.id))
        db.session.commit()
        res_blocked = client.get(pot_path, headers=_auth_headers(viewer))
        assert res_blocked.status_code == 403

