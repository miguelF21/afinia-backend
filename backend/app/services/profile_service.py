import uuid
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any, Tuple
from flask import current_app
from app import db
from app.models import User, Profile, ProfilePhoto, DiscoveryPreference
from app.services.storage_service import (
    StorageError,
    storage_adapter,
    validate_and_sanitize_image,
    build_photo_url
)

ALLOWED_GENDERS = ('masculino', 'femenino', 'no_binario', 'otro', 'prefiero_no_indicar')
ALLOWED_RELATIONSHIP_TYPES = ('seria', 'casual', 'amistad', 'sin_definir')

class ProfileError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

def calculate_age(birth_date: date, reference_date: Optional[date] = None) -> int:
    """
    Calcula la edad exacta en años cumplidos considerando año, mes y día de calendario.
    Si reference_date no se provee, utiliza la fecha actual en UTC explícitamente.
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc).date()
    
    if birth_date > reference_date:
        raise ProfileError('VALIDATION_ERROR', 'La fecha de nacimiento no puede ser futura.', 422)
    
    age = reference_date.year - birth_date.year - (
        (reference_date.month, reference_date.day) < (birth_date.month, birth_date.day)
    )
    
    if age < 18:
        raise ProfileError('VALIDATION_ERROR', 'Afinia es una plataforma exclusiva para personas mayores de 18 años.', 422)
    
    if age > 120:
        raise ProfileError('VALIDATION_ERROR', 'La fecha de nacimiento excede el límite permitido (120 años).', 422)
    
    return age

def is_onboarding_complete(user: User) -> bool:
    """
    Regla centralizada de completitud de onboarding basada en datos verificables.
    
    Condiciones requeridas:
    A. Perfil básico válido: first_name, birth_date con edad >= 18 y gender permitido.
    B. Preferencias de descubrimiento válidas y persistidas.
    C. Fotografía principal aprobada y disponible (is_primary is True y status == 'ready').
    D. Correo electrónico verificado (user.email_verified is True).
    E. Cuentas suspendidas o desactivadas nunca completan onboarding.
    """
    if not user or user.lifecycle_status in ('suspended', 'deactivated'):
        return False
    
    # A. Verificación de perfil básico
    profile = user.profile
    if not profile or not profile.first_name or not profile.birth_date or not profile.gender:
        return False
    
    if profile.gender not in ALLOWED_GENDERS:
        return False
    
    try:
        age = calculate_age(profile.birth_date)
        if age < 18:
            return False
    except Exception:
        return False

    # B. Verificación de preferencias de descubrimiento persistidas
    pref = user.discovery_preference
    if not pref or pref.interested_in_genders is None:
        return False
    
    canonical_genders = pref.canonical_interested_in_genders
    if not canonical_genders or len(canonical_genders) < 1:
        return False
    
    for g in canonical_genders:
        if g not in ALLOWED_GENDERS:
            return False
            
    min_age = pref.min_age if pref.min_age is not None else 18
    max_age = pref.max_age if pref.max_age is not None else 99
    if min_age < 18 or max_age > 120 or min_age > max_age:
        return False

    # C. Verificación de fotografía principal aprobada (status='ready')
    has_ready_primary_photo = any(
        photo.is_primary and photo.status == 'ready'
        for photo in profile.photos
    )
    if not has_ready_primary_photo:
        return False

    # D. Verificación de correo electrónico
    if not user.email_verified:
        return False

    return True

def sync_user_lifecycle_status(user: User) -> str:
    """
    Sincroniza atómicamente el estado de ciclo de vida (lifecycle_status) del usuario con sus requisitos de onboarding.
    
    Reglas estrictas de negocio:
    1. Cuentas suspendidas ('suspended') o desactivadas ('deactivated'):
       NUNCA se modifican automáticamente. Se preserva la sanción o desactivación administrativa.
    2. Cuentas en 'pending_profile':
       Si is_onboarding_complete(user) es True (Perfil creado + Mayoría de edad comprobada + Preferencias persistidas + Foto principal 'ready' + Correo verificado),
       transiciona a 'active'.
    3. Cuentas en 'active':
       Si posteriormente pierde la completitud del onboarding (ej. elimina su foto principal ready, o se eliminan preferencias),
       vuelve de forma controlada a 'pending_profile' para impedir el descubrimiento prematuro.
    4. Los roles ('user', 'moderator', 'admin') y privilegios jamás se alteran en esta sincronización.
    """
    if not user or user.lifecycle_status in ('suspended', 'deactivated'):
        return user.lifecycle_status if user else 'pending_profile'

    eligible = is_onboarding_complete(user)

    if eligible and user.lifecycle_status == 'pending_profile':
        user.lifecycle_status = 'active'
    elif not eligible and user.lifecycle_status == 'active':
        user.lifecycle_status = 'pending_profile'

    return user.lifecycle_status

def serialize_photo(photo: ProfilePhoto) -> dict:
    """Serializa un objeto ProfilePhoto al esquema OpenAPI Photo."""
    return {
        'id': str(photo.id),
        'url': build_photo_url(photo.id),
        'is_primary': photo.is_primary
    }

def serialize_own_profile(profile: Profile, user: User) -> dict:
    """
    Serializa el perfil del usuario autenticado conforme al esquema OpenAPI OwnProfile.
    Garantiza que no se expongan hashes de contraseñas, roles, tokens ni datos sensibles.
    """
    formatted_photos = [
        serialize_photo(p)
        for p in sorted(profile.photos, key=lambda p: p.position)
    ]

    return {
        'user_id': str(profile.user_id),
        'first_name': profile.first_name,
        'birth_date': profile.birth_date.isoformat(),
        'age': calculate_age(profile.birth_date),
        'gender': profile.gender,
        'city': profile.city,
        'bio': profile.bio,
        'photos': formatted_photos,
        'onboarding_complete': is_onboarding_complete(user)
    }

def create_profile(user: User, data: dict) -> dict:
    """
    POST /api/v1/profile/
    Crea el perfil del usuario autenticado a partir de ProfileWrite.
    Rechaza mass assignment, valida mayoría de edad exacta y evita perfiles duplicados (409 CONFLICT).
    """
    if not isinstance(data, dict):
        raise ProfileError('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    allowed_keys = {'first_name', 'birth_date', 'gender', 'city', 'bio'}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        raise ProfileError(
            'VALIDATION_ERROR',
            f'Campos adicionales no permitidos: {", ".join(sorted(extra_keys))}.',
            422
        )

    if user.profile is not None:
        raise ProfileError('CONFLICT', 'El usuario ya cuenta con un perfil creado.', 409)

    for field in ('first_name', 'birth_date', 'gender'):
        if field not in data or data[field] is None:
            raise ProfileError('VALIDATION_ERROR', f'El campo {field} es obligatorio.', 422)

    first_name = str(data['first_name']).strip()
    if not (1 <= len(first_name) <= 50):
        raise ProfileError('VALIDATION_ERROR', 'El nombre debe tener entre 1 y 50 caracteres.', 422)

    gender = str(data['gender']).strip()
    if gender not in ALLOWED_GENDERS:
        raise ProfileError(
            'VALIDATION_ERROR',
            f"Género inválido: '{gender}'. Valores admitidos: {', '.join(ALLOWED_GENDERS)}.",
            422
        )

    raw_birth_date = str(data['birth_date']).strip()
    try:
        birth_date = datetime.strptime(raw_birth_date, '%Y-%m-%d').date()
    except ValueError:
        raise ProfileError('VALIDATION_ERROR', 'Formato de fecha de nacimiento inválido. Debe ser YYYY-MM-DD.', 422)

    calculate_age(birth_date)

    city = data.get('city')
    if city is not None:
        city = str(city).strip()
        if len(city) > 100:
            raise ProfileError('VALIDATION_ERROR', 'La ciudad no puede exceder 100 caracteres.', 422)

    bio = data.get('bio')
    if bio is not None:
        bio = str(bio).strip()
        if len(bio) > 1000:
            raise ProfileError('VALIDATION_ERROR', 'La biografía no puede exceder 1000 caracteres.', 422)

    try:
        new_profile = Profile(
            user_id=user.id,
            first_name=first_name,
            birth_date=birth_date,
            gender=gender,
            city=city,
            bio=bio
        )
        db.session.add(new_profile)
        sync_user_lifecycle_status(user)
        db.session.commit()
        return serialize_own_profile(new_profile, user)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error al persistir perfil para user {user.id}: {str(e)}")
        raise ProfileError('INTERNAL_ERROR', 'Error interno al registrar el perfil.', 500)

def get_own_profile(user: User) -> dict:
    """
    GET /api/v1/profile/
    Retorna el perfil del usuario autenticado (OwnProfile).
    Si el usuario no tiene perfil aún, responde 404 NOT_FOUND.
    """
    if not user.profile:
        raise ProfileError('NOT_FOUND', 'Perfil no encontrado.', 404)
    
    return serialize_own_profile(user.profile, user)

def update_profile(user: User, data: dict) -> dict:
    """
    PUT /api/v1/profile/
    Actualiza completamente el perfil del usuario autenticado a partir de ProfileWrite.
    """
    if not user.profile:
        raise ProfileError('NOT_FOUND', 'Perfil no encontrado.', 404)

    if not isinstance(data, dict):
        raise ProfileError('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    allowed_keys = {'first_name', 'birth_date', 'gender', 'city', 'bio'}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        raise ProfileError(
            'VALIDATION_ERROR',
            f'Campos adicionales no permitidos: {", ".join(sorted(extra_keys))}.',
            422
        )

    for field in ('first_name', 'birth_date', 'gender'):
        if field not in data or data[field] is None:
            raise ProfileError('VALIDATION_ERROR', f'El campo {field} es obligatorio.', 422)

    first_name = str(data['first_name']).strip()
    if not (1 <= len(first_name) <= 50):
        raise ProfileError('VALIDATION_ERROR', 'El nombre debe tener entre 1 y 50 caracteres.', 422)

    gender = str(data['gender']).strip()
    if gender not in ALLOWED_GENDERS:
        raise ProfileError(
            'VALIDATION_ERROR',
            f"Género inválido: '{gender}'. Valores admitidos: {', '.join(ALLOWED_GENDERS)}.",
            422
        )

    raw_birth_date = str(data['birth_date']).strip()
    try:
        birth_date = datetime.strptime(raw_birth_date, '%Y-%m-%d').date()
    except ValueError:
        raise ProfileError('VALIDATION_ERROR', 'Formato de fecha de nacimiento inválido. Debe ser YYYY-MM-DD.', 422)

    calculate_age(birth_date)

    city = data.get('city')
    if city is not None:
        city = str(city).strip()
        if len(city) > 100:
            raise ProfileError('VALIDATION_ERROR', 'La ciudad no puede exceder 100 caracteres.', 422)

    bio = data.get('bio')
    if bio is not None:
        bio = str(bio).strip()
        if len(bio) > 1000:
            raise ProfileError('VALIDATION_ERROR', 'La biografía no puede exceder 1000 caracteres.', 422)

    try:
        profile = user.profile
        profile.first_name = first_name
        profile.birth_date = birth_date
        profile.gender = gender
        profile.city = city
        profile.bio = bio
        sync_user_lifecycle_status(user)
        db.session.commit()
        return serialize_own_profile(profile, user)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error al actualizar perfil para user {user.id}: {str(e)}")
        raise ProfileError('INTERNAL_ERROR', 'Error interno al actualizar el perfil.', 500)

def serialize_preferences(pref: DiscoveryPreference) -> dict:
    """Serializa las preferencias al esquema OpenAPI Preferences."""
    return {
        'interested_in_genders': pref.canonical_interested_in_genders or ['masculino', 'femenino'],
        'min_age': pref.min_age if pref.min_age is not None else 18,
        'max_age': pref.max_age if pref.max_age is not None else 99,
        'target_relationship_type': pref.target_relationship_type
    }

def get_discovery_preferences(user: User) -> dict:
    """
    GET /api/v1/profile/discovery-preferences
    Retorna las preferencias de búsqueda del usuario autenticado.
    """
    pref = user.discovery_preference
    if not pref or pref.interested_in_genders is None:
        return {
            'interested_in_genders': ['masculino', 'femenino'],
            'min_age': 18,
            'max_age': 99,
            'target_relationship_type': None
        }
    return serialize_preferences(pref)

def save_discovery_preferences(user: User, data: dict) -> dict:
    """
    PUT /api/v1/profile/discovery-preferences
    Guarda o actualiza las preferencias de búsqueda del usuario autenticado.
    """
    if not isinstance(data, dict):
        raise ProfileError('BAD_REQUEST', 'El cuerpo de la solicitud debe ser un objeto JSON válido.', 400)

    allowed_keys = {'interested_in_genders', 'min_age', 'max_age', 'target_relationship_type'}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        raise ProfileError(
            'VALIDATION_ERROR',
            f'Campos adicionales no permitidos: {", ".join(sorted(extra_keys))}.',
            422
        )

    for field in ('interested_in_genders', 'min_age', 'max_age'):
        if field not in data or data[field] is None:
            raise ProfileError('VALIDATION_ERROR', f'El campo {field} es obligatorio.', 422)

    genders = data['interested_in_genders']
    if not isinstance(genders, list):
        raise ProfileError('VALIDATION_ERROR', 'interested_in_genders debe ser una lista de géneros.', 422)

    if len(genders) < 1:
        raise ProfileError('VALIDATION_ERROR', 'interested_in_genders debe contener al menos un género.', 422)

    if len(genders) != len(set(genders)):
        raise ProfileError('VALIDATION_ERROR', 'interested_in_genders no debe contener géneros duplicados.', 422)

    for g in genders:
        if not isinstance(g, str) or g not in ALLOWED_GENDERS:
            raise ProfileError(
                'VALIDATION_ERROR',
                f"Género de interés inválido: '{g}'. Valores admitidos: {', '.join(ALLOWED_GENDERS)}.",
                422
            )

    try:
        min_age = int(data['min_age'])
        max_age = int(data['max_age'])
    except (ValueError, TypeError):
        raise ProfileError('VALIDATION_ERROR', 'min_age y max_age deben ser números enteros válidos.', 422)

    if min_age < 18 or min_age > 120:
        raise ProfileError('VALIDATION_ERROR', 'min_age debe estar comprendido entre 18 y 120 años.', 422)

    if max_age < 18 or max_age > 120:
        raise ProfileError('VALIDATION_ERROR', 'max_age debe estar comprendido entre 18 y 120 años.', 422)

    if min_age > max_age:
        raise ProfileError('VALIDATION_ERROR', 'min_age no puede ser mayor que max_age.', 422)

    rel_type = data.get('target_relationship_type')
    if rel_type is not None:
        rel_type = str(rel_type).strip()
        if rel_type not in ALLOWED_RELATIONSHIP_TYPES:
            raise ProfileError(
                'VALIDATION_ERROR',
                f"target_relationship_type inválido: '{rel_type}'. Valores admitidos: {', '.join(ALLOWED_RELATIONSHIP_TYPES)}.",
                422
            )

    try:
        pref = user.discovery_preference
        if not pref:
            pref = DiscoveryPreference(
                user_id=user.id,
                interested_in_genders=list(genders),
                min_age=min_age,
                max_age=max_age,
                target_relationship_type=rel_type
            )
            db.session.add(pref)
        else:
            pref.interested_in_genders = list(genders)
            pref.min_age = min_age
            pref.max_age = max_age
            pref.target_relationship_type = rel_type

        sync_user_lifecycle_status(user)
        db.session.commit()
        return serialize_preferences(pref)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error al guardar preferencias para user {user.id}: {str(e)}")
        raise ProfileError('INTERNAL_ERROR', 'Error interno al guardar las preferencias de búsqueda.', 500)

# =========================================================================
# GESTIÓN DE FOTOGRAFÍAS DE PERFIL (BE-02.2)
# =========================================================================

def upload_profile_photo(user: User, file_storage, is_primary_requested: bool = False) -> dict:
    """
    POST /api/v1/profile/photos
    Valida y sube una fotografía para el perfil del usuario autenticado.
    Aplica límite máximo de 6 fotos, asigna posición libre y maneja unicidad de foto principal.
    """
    if not user.profile:
        raise ProfileError('VALIDATION_ERROR', 'Debe crear su perfil antes de subir fotografías.', 422)

    profile = user.profile
    current_photos = profile.photos

    if len(current_photos) >= 6:
        raise ProfileError('VALIDATION_ERROR', 'Se ha alcanzado el límite máximo de 6 fotografías por perfil.', 422)

    # 1. Validación técnica de la imagen (tamaño, tipo, sanitización EXIF/GPS)
    try:
        clean_bytes, ext, mime = validate_and_sanitize_image(file_storage)
    except StorageError as e:
        raise ProfileError(e.code, e.message, e.status_code, e.details)

    # 2. Asignar la menor posición libre disponible entre 0 y 5
    occupied_positions = {p.position for p in current_photos}
    available_positions = sorted(list(set(range(6)) - occupied_positions))
    if not available_positions:
        raise ProfileError('VALIDATION_ERROR', 'No hay posiciones libres para nuevas fotografías.', 422)
    next_position = available_positions[0]

    # 3. Determinar foto principal
    # Si es la primera foto o se solicitó explícitamente is_primary
    should_be_primary = is_primary_requested or len(current_photos) == 0

    # 4. Guardar archivo en almacenamiento local
    storage_key = storage_adapter.save_file(clean_bytes, ext)

    # 5. Persistencia transaccional en PostgreSQL
    try:
        if should_be_primary:
            # Desmarcar atómicamente fotos principales previas
            ProfilePhoto.query.filter_by(profile_id=profile.id, is_primary=True).update({'is_primary': False})

        new_photo = ProfilePhoto(
            profile_id=profile.id,
            storage_key=storage_key,
            position=next_position,
            is_primary=should_be_primary,
            status='pending',
            file_name=getattr(file_storage, 'filename', f'photo.{ext}'),
            content_type=mime,
            byte_size=len(clean_bytes)
        )
        db.session.add(new_photo)
        db.session.commit()
        return serialize_photo(new_photo)
    except Exception as e:
        db.session.rollback()
        # Limpieza de archivo huérfano ante error en base de datos
        storage_adapter.delete_file(storage_key)
        current_app.logger.error(f"Error al registrar fotografía en BD para user {user.id}: {str(e)}")
        raise ProfileError('INTERNAL_ERROR', 'Error interno al registrar la fotografía.', 500)

def set_primary_photo(user: User, photo_id: str) -> dict:
    """
    PUT /api/v1/profile/photos/{photoId}/primary
    Establece la fotografía indicada como principal garantizando unicidad transaccional.
    """
    photo = db.session.get(ProfilePhoto, photo_id)
    if not photo:
        raise ProfileError('NOT_FOUND', 'Fotografía no encontrada.', 404)

    if not user.profile or photo.profile_id != user.profile.id:
        raise ProfileError('FORBIDDEN', 'Acceso denegado. La fotografía no pertenece a tu perfil.', 403)

    if photo.is_primary:
        return serialize_photo(photo)

    try:
        # Desmarcar cualquier otra foto principal previa del perfil
        ProfilePhoto.query.filter(
            ProfilePhoto.profile_id == user.profile.id,
            ProfilePhoto.id != photo.id,
            ProfilePhoto.is_primary == True
        ).update({'is_primary': False})

        photo.is_primary = True
        sync_user_lifecycle_status(user)
        db.session.commit()
        return serialize_photo(photo)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error al establecer foto principal {photo_id}: {str(e)}")
        raise ProfileError('INTERNAL_ERROR', 'Error interno al actualizar la fotografía principal.', 500)

def delete_profile_photo(user: User, photo_id: str) -> None:
    """
    DELETE /api/v1/profile/photos/{photoId}
    Elimina la fotografía especificada y su archivo en almacenamiento.
    Si era la principal, promueve deterministamente la siguiente disponible.
    """
    photo = db.session.get(ProfilePhoto, photo_id)
    if not photo:
        raise ProfileError('NOT_FOUND', 'Fotografía no encontrada.', 404)

    if not user.profile or photo.profile_id != user.profile.id:
        raise ProfileError('FORBIDDEN', 'Acceso denegado. La fotografía no pertenece a tu perfil.', 403)

    storage_key_to_delete = photo.storage_key
    was_primary = photo.is_primary
    profile_id = photo.profile_id

    try:
        db.session.delete(photo)

        if was_primary:
            # Buscar otra foto disponible para promover a principal
            remaining_photos = ProfilePhoto.query.filter(
                ProfilePhoto.profile_id == profile_id,
                ProfilePhoto.id != photo.id
            ).order_by(ProfilePhoto.position.asc()).all()

            if remaining_photos:
                new_primary = remaining_photos[0]
                new_primary.is_primary = True

        sync_user_lifecycle_status(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error al eliminar fotografía {photo_id} en BD: {str(e)}")
        raise ProfileError('INTERNAL_ERROR', 'Error interno al eliminar la fotografía.', 500)

    # Eliminar archivo físico una vez confirmado el commit en PostgreSQL
    try:
        storage_adapter.delete_file(storage_key_to_delete)
    except Exception as e:
        current_app.logger.warning(f"Error al eliminar archivo físico {storage_key_to_delete} tras commit: {e}")

def get_photo_media(user: Optional[User], photo_id: str) -> Tuple[str, str, str]:
    """
    Obtiene la ruta física segura, el tipo MIME y el status de una fotografía para el endpoint de medios de QA.
    Aplica política integral de privacidad y autorización:
    - Todas las fotografías requieren autenticación (user no nulo).
    - Fotos 'ready': Accesibles para cualquier usuario autenticado salvo que exista un bloqueo mutuo con el propietario.
    - Fotos 'pending', 'processing', 'rejected': Requieren pertenecer al perfil del usuario autenticado (propietario).
    - Bloqueos: Si el solicitante y el propietario se han bloqueado mutuamente (en cualquier dirección), se deniega (403).
    """
    if not user:
        raise ProfileError('UNAUTHORIZED', 'Autenticación requerida para acceder a los archivos multimedia.', 401)

    photo = db.session.get(ProfilePhoto, photo_id)
    if not photo:
        raise ProfileError('NOT_FOUND', 'Fotografía no encontrada.', 404)

    owner_profile = photo.profile
    owner_user_id = owner_profile.user_id if owner_profile else None

    # 1. Validación para estados en moderación o no públicos ('pending', 'processing', 'rejected')
    if photo.status != 'ready':
        if not user.profile or photo.profile_id != user.profile.id:
            raise ProfileError('FORBIDDEN', 'Acceso denegado. Fotografía en moderación o no autorizada.', 403)
        # El propietario autenticado sí puede visualizar sus fotos pending/processing/rejected para previsualización

    # 2. Validación para fotos 'ready': control estricto de bloqueos mutuos
    else:
        if owner_user_id and user.id != owner_user_id:
            from app.models.block import UserBlock
            block_exists = UserBlock.query.filter(
                db.or_(
                    db.and_(UserBlock.blocker_user_id == user.id, UserBlock.blocked_user_id == owner_user_id),
                    db.and_(UserBlock.blocker_user_id == owner_user_id, UserBlock.blocked_user_id == user.id)
                )
            ).first()
            if block_exists:
                raise ProfileError('FORBIDDEN', 'Acceso denegado por restricciones de privacidad o bloqueo.', 403)

    file_path = storage_adapter.get_file_path(photo.storage_key)
    if not file_path:
        raise ProfileError('NOT_FOUND', 'Archivo físico de la fotografía no encontrado en el servidor.', 404)

    return file_path, photo.content_type or 'image/jpeg', photo.status

def approve_photo_for_qa(photo_id: str) -> None:
    """
    Procedimiento controlado para QA y pruebas: aprueba una fotografía transicionando su status al canónico 'ready'.
    No es un endpoint público del usuario.
    """
    photo = db.session.get(ProfilePhoto, photo_id)
    if not photo:
        raise ProfileError('NOT_FOUND', 'Fotografía no encontrada.', 404)
    photo.status = 'ready'
    if photo.profile and photo.profile.user:
        sync_user_lifecycle_status(photo.profile.user)
    db.session.commit()

