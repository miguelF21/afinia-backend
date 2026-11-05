import os
import io
import json
import uuid
import warnings
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any, List
from flask import current_app, request
from PIL import Image, ImageOps, UnidentifiedImageError

class StorageError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

class LocalStorageAdapter:
    """
    Adaptador de almacenamiento local seguro para QA y desarrollo.
    Almacena archivos fuera de carpetas públicas, previene directory traversal
    y gestiona una cola durable en disco (.pending_deletions.json) para registrar
    y reintentar eliminaciones físicas que fallen por errores de E/S post-commit.
    """
    PENDING_DELETIONS_FILENAME = ".pending_deletions.json"

    def __init__(self, base_folder: Optional[str] = None):
        self._base_folder = base_folder
        self._lock = threading.RLock()

    @property
    def base_folder(self) -> str:
        if self._base_folder:
            folder = os.path.abspath(self._base_folder)
            os.makedirs(folder, exist_ok=True)
            return folder
        try:
            configured = current_app.config.get('UPLOAD_FOLDER')
            if configured:
                folder = os.path.abspath(configured)
            else:
                folder = os.path.abspath(os.path.join(current_app.root_path, '..', '..', 'uploads', 'profile_photos'))
        except Exception:
            this_dir = os.path.dirname(os.path.abspath(__file__))
            folder = os.path.abspath(os.path.join(this_dir, '..', '..', '..', 'uploads', 'profile_photos'))

        os.makedirs(folder, exist_ok=True)
        return folder

    def _resolve_safe_target(self, storage_key: str) -> Optional[Tuple[str, str]]:
        """
        Normaliza y valida una storage_key contra directory traversal y nombres reservados.
        Retorna (canonical_key, target_path) o None si la clave no es válida.
        """
        if not storage_key or not isinstance(storage_key, str):
            return None

        normalized_raw = storage_key.strip().replace("\\", "/")
        if not normalized_raw:
            return None

        parts = [p for p in normalized_raw.split("/") if p]
        if not parts or any(p in (".", "..") for p in parts):
            return None

        filename = parts[-1]
        if not filename or filename.startswith(".") or filename == self.PENDING_DELETIONS_FILENAME:
            return None

        base = self.base_folder
        target_path = os.path.normpath(os.path.join(base, filename))
        try:
            if os.path.commonpath([base, target_path]) != base or target_path == base:
                return None
        except ValueError:
            return None

        canonical_key = f"photos/{filename}"
        return canonical_key, target_path

    def _pending_manifest_path(self) -> str:
        return os.path.join(self.base_folder, self.PENDING_DELETIONS_FILENAME)

    def _load_pending_deletions_unlocked(self) -> Dict[str, Dict[str, Any]]:
        manifest_path = self._pending_manifest_path()
        if not os.path.exists(manifest_path):
            return {}
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_pending_deletions_unlocked(self, data: Dict[str, Dict[str, Any]]) -> None:
        manifest_path = self._pending_manifest_path()
        if not data:
            if os.path.exists(manifest_path):
                try:
                    os.remove(manifest_path)
                except OSError:
                    pass
            return

        tmp_path = f"{manifest_path}.{uuid.uuid4().hex}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, manifest_path)

    def enqueue_pending_deletion(
        self,
        storage_key: str,
        reason: str = "account_deletion",
        context_id: Optional[str] = None,
    ) -> bool:
        """
        Registra de forma durable en disco una storage_key antes de ejecutar su borrado físico,
        garantizando que la referencia no se pierda si ocurre un fallo de E/S tras el commit en BD.
        """
        resolved = self._resolve_safe_target(storage_key)
        if not resolved:
            return False
        canonical_key, _ = resolved
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            pending = self._load_pending_deletions_unlocked()
            existing = pending.get(canonical_key)
            if existing:
                existing["reason"] = reason or existing.get("reason", "account_deletion")
                if context_id is not None:
                    existing["context_id"] = str(context_id)
            else:
                pending[canonical_key] = {
                    "storage_key": canonical_key,
                    "status": "pending_physical_deletion",
                    "reason": reason,
                    "context_id": str(context_id) if context_id is not None else None,
                    "queued_at": now_iso,
                    "last_attempt_at": None,
                    "attempts": 0,
                    "last_error": None,
                }
            self._save_pending_deletions_unlocked(pending)
        return True

    def mark_deletion_failed(
        self,
        storage_key: str,
        error: str,
        reason: str = "account_deletion",
        context_id: Optional[str] = None,
    ) -> bool:
        """
        Registra o actualiza un intento fallido de eliminación física en la cola persistente.
        """
        resolved = self._resolve_safe_target(storage_key)
        if not resolved:
            return False
        canonical_key, _ = resolved
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            pending = self._load_pending_deletions_unlocked()
            entry = pending.get(canonical_key) or {
                "storage_key": canonical_key,
                "status": "pending_physical_deletion",
                "reason": reason,
                "context_id": str(context_id) if context_id is not None else None,
                "queued_at": now_iso,
                "attempts": 0,
            }
            entry["status"] = "pending_physical_deletion"
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            entry["last_attempt_at"] = now_iso
            entry["last_error"] = str(error)
            if reason:
                entry["reason"] = reason
            if context_id is not None:
                entry["context_id"] = str(context_id)
            pending[canonical_key] = entry
            self._save_pending_deletions_unlocked(pending)
        return True

    def _clear_pending_deletion_unlocked(self, canonical_key: str) -> None:
        pending = self._load_pending_deletions_unlocked()
        if canonical_key in pending:
            del pending[canonical_key]
            self._save_pending_deletions_unlocked(pending)

    def get_pending_deletions(self) -> Dict[str, Dict[str, Any]]:
        """Retorna el diccionario de archivos físicos pendientes de eliminación."""
        with self._lock:
            return dict(self._load_pending_deletions_unlocked())

    def has_pending_deletion(self, storage_key: str) -> bool:
        """Indica si una storage_key se encuentra marcada como pendiente de eliminación física."""
        resolved = self._resolve_safe_target(storage_key)
        if not resolved:
            return False
        canonical_key, _ = resolved
        with self._lock:
            pending = self._load_pending_deletions_unlocked()
            return canonical_key in pending

    def _remove_physical_file(self, target_path: str) -> None:
        """Punto único de remoción física en el sistema de archivos."""
        os.remove(target_path)

    def save_file(self, clean_bytes: bytes, extension: str) -> str:
        """
        Guarda los bytes saneados bajo un identificador único seguro.
        Retorna la storage_key generada.
        """
        ext = extension.lstrip('.').lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        storage_key = f"photos/{unique_name}"
        
        target_path = os.path.normpath(os.path.join(self.base_folder, unique_name))
        # Protección contra directory traversal
        if not target_path.startswith(self.base_folder):
            raise StorageError('SECURITY_ERROR', 'Ruta de almacenamiento no permitida.', 403)
        
        with open(target_path, 'wb') as f:
            f.write(clean_bytes)
            
        return storage_key

    def delete_file(self, storage_key: str) -> bool:
        """
        Elimina físicamente de forma idempotente el archivo asociado a la storage_key:
        - Si la clave es inválida o insegura, retorna False sin alterar ningún archivo.
        - Si el archivo ya no existe físicamente en disco, limpia cualquier estado pendiente
          y retorna True (idempotente).
        - Si el archivo existe y se elimina exitosamente, limpia cualquier estado pendiente
          y retorna True.
        - Si ocurre un error de E/S al eliminar el archivo, lo registra/actualiza en la cola
          persistente de eliminaciones pendientes (.pending_deletions.json) y retorna False.
        """
        resolved = self._resolve_safe_target(storage_key)
        if not resolved:
            return False
        canonical_key, target_path = resolved

        with self._lock:
            if os.path.exists(target_path):
                try:
                    self._remove_physical_file(target_path)
                    self._clear_pending_deletion_unlocked(canonical_key)
                    return True
                except OSError as e:
                    self.mark_deletion_failed(canonical_key, error=f"{type(e).__name__}: {e}")
                    try:
                        current_app.logger.error(
                            f"Fallo de E/S al eliminar archivo físico {target_path}; "
                            f"registrado en cola de eliminaciones pendientes ({canonical_key}): {e}"
                        )
                    except RuntimeError:
                        pass
                    return False

            # Idempotencia: el archivo ya no existe en disco
            self._clear_pending_deletion_unlocked(canonical_key)
            return True

    def retry_pending_deletions(self, max_items: Optional[int] = None) -> Dict[str, Any]:
        """
        Reintenta las eliminaciones físicas pendientes registradas en .pending_deletions.json.
        Retorna un resumen con claves 'attempted', 'resolved' y 'still_pending'.
        """
        with self._lock:
            pending_snapshot = list(self._load_pending_deletions_unlocked().keys())

        if max_items is not None and max_items >= 0:
            pending_snapshot = pending_snapshot[:max_items]

        resolved_keys: List[str] = []
        still_pending_keys: List[str] = []

        for canonical_key in pending_snapshot:
            resolved_target = self._resolve_safe_target(canonical_key)
            if not resolved_target:
                with self._lock:
                    self._clear_pending_deletion_unlocked(canonical_key)
                continue

            _, target_path = resolved_target
            try:
                ok = self.delete_file(canonical_key)
                if ok and not os.path.exists(target_path):
                    with self._lock:
                        self._clear_pending_deletion_unlocked(canonical_key)
                    resolved_keys.append(canonical_key)
                else:
                    if not self.has_pending_deletion(canonical_key):
                        self.mark_deletion_failed(canonical_key, error="retry_pending_deletions: file still exists")
                    still_pending_keys.append(canonical_key)
            except Exception as exc:
                self.mark_deletion_failed(canonical_key, error=f"{type(exc).__name__}: {exc}")
                still_pending_keys.append(canonical_key)

        return {
            "attempted": len(pending_snapshot),
            "resolved": resolved_keys,
            "still_pending": still_pending_keys,
        }

    def get_file_path(self, storage_key: str) -> Optional[str]:
        """
        Retorna la ruta física segura del archivo si existe y NO está marcado como
        pendiente de eliminación física.
        """
        resolved = self._resolve_safe_target(storage_key)
        if not resolved:
            return None
        canonical_key, target_path = resolved
        if self.has_pending_deletion(canonical_key):
            return None
        if os.path.exists(target_path):
            return target_path
        return None

storage_adapter = LocalStorageAdapter()

# Límites de seguridad para procesamiento de imágenes
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_PIXELS = 50_000_000     # 50 Megapíxeles
MAX_DIMENSION = 8192              # Dimensión máxima por eje en píxeles

def validate_and_sanitize_image(file_storage) -> Tuple[bytes, str, str]:
    """
    Valida tamaño binario (máx 10 MB), decodifica la imagen con Pillow,
    limita dimensiones y píxeles contra ataques de descompresión (decompression bomb),
    controla DecompressionBombWarning y DecompressionBombError,
    respeta la orientación visual original (EXIF orientation) antes de descartar metadatos,
    elimina metadatos EXIF sensibles (GPS) y normaliza los bytes.
    Retorna: (clean_bytes, extension, mime_type)
    """
    if not file_storage:
        raise StorageError('BAD_REQUEST', 'No se ha proporcionado ningún archivo.', 400)

    # 1. Validación estricta de tamaño binario (10 MB = 10,485,760 bytes)
    file_storage.seek(0, os.SEEK_END)
    file_size = file_storage.tell()
    file_storage.seek(0)

    if file_size > MAX_FILE_SIZE:
        raise StorageError('PAYLOAD_TOO_LARGE', f'El archivo excede el tamaño máximo permitido de 10 MB ({file_size} bytes).', 413)

    if file_size == 0:
        raise StorageError('VALIDATION_ERROR', 'El archivo enviado está vacío.', 422)

    raw_bytes = file_storage.read()

    # 2. Configurar límite en Pillow y capturar warnings como errores
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            img = Image.open(io.BytesIO(raw_bytes))
            img_format = img.format
            if not img_format or img_format.upper() not in ('JPEG', 'PNG', 'WEBP'):
                raise StorageError(
                    'UNSUPPORTED_MEDIA_TYPE',
                    f"Formato no admitido ('{img_format}'). Afinia solo admite imágenes JPEG, PNG y WEBP.",
                    415
                )

            # Validación preventiva explícita de dimensiones y píxeles antes de load()
            width, height = img.size
            if width <= 0 or height <= 0:
                raise StorageError('VALIDATION_ERROR', 'Dimensiones de imagen inválidas.', 422)

            total_pixels = width * height
            if total_pixels > MAX_IMAGE_PIXELS or width > MAX_DIMENSION or height > MAX_DIMENSION:
                raise StorageError(
                    'VALIDATION_ERROR',
                    f'La imagen excede el límite máximo de resolución ({width}x{height} px = {total_pixels} píxeles). Máximo permitido: {MAX_IMAGE_PIXELS} px o dimensión {MAX_DIMENSION} px.',
                    422
                )

            # Carga completa de los datos crudos para detectar archivos incompletos o corruptos
            img.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise StorageError('VALIDATION_ERROR', 'La imagen excede el límite de descompresión seguro (decompression bomb).', 422)
        except UnidentifiedImageError:
            raise StorageError('UNSUPPORTED_MEDIA_TYPE', 'El archivo no es una imagen válida o su formato no es compatible.', 415)
        except StorageError:
            raise
        except Exception as e:
            raise StorageError('VALIDATION_ERROR', f'El archivo contiene datos de imagen corruptos o malformados: {str(e)}', 422)

    # 3. Orientación automática respetando EXIF orientation antes de descartar metadatos
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # 4. Re-codificación limpia sin bloque EXIF (descartando GPS, fechas y datos de cámara)
    output_io = io.BytesIO()
    fmt = img_format.upper()

    if fmt == 'JPEG':
        if img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(output_io, format='JPEG', quality=90, optimize=True)
        ext = 'jpg'
        mime = 'image/jpeg'
    elif fmt == 'PNG':
        if img.mode not in ('RGB', 'RGBA', 'L'):
            img = img.convert('RGBA')
        img.save(output_io, format='PNG', optimize=True)
        ext = 'png'
        mime = 'image/png'
    elif fmt == 'WEBP':
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGBA')
        img.save(output_io, format='WEBP', quality=90)
        ext = 'webp'
        mime = 'image/webp'
    else:
        raise StorageError('UNSUPPORTED_MEDIA_TYPE', 'Tipo de imagen no compatible.', 415)

    clean_bytes = output_io.getvalue()
    return clean_bytes, ext, mime

def build_photo_url(photo_id: str) -> str:
    """
    Construye una URL absoluta o relativa válida y accesible para servir la fotografía en QA.
    """
    try:
        base_url = request.host_url.rstrip('/')
        return f"{base_url}/api/v1/profile/photos/media/{photo_id}"
    except RuntimeError:
        # Fuera de contexto de petición (ej: en scripts o tests sin request activo)
        return f"http://127.0.0.1:5000/api/v1/profile/photos/media/{photo_id}"
