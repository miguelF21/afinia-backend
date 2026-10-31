import os
import io
import uuid
import warnings
from typing import Optional, Tuple
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
    Almacena archivos fuera de carpetas públicas y previene directory traversal.
    """
    def __init__(self, base_folder: Optional[str] = None):
        self._base_folder = base_folder

    @property
    def base_folder(self) -> str:
        if self._base_folder:
            return self._base_folder
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
        Elimina físicamente el archivo asociado a la storage_key si existe.
        """
        if not storage_key:
            return False
            
        # Extraer el nombre de archivo base
        filename = os.path.basename(storage_key)
        target_path = os.path.normpath(os.path.join(self.base_folder, filename))
        
        if not target_path.startswith(self.base_folder):
            return False
            
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
                return True
            except OSError as e:
                current_app.logger.error(f"Error al eliminar archivo físico {target_path}: {e}")
                return False
        return False

    def get_file_path(self, storage_key: str) -> Optional[str]:
        """
        Retorna la ruta física segura del archivo si existe.
        """
        if not storage_key:
            return None
        filename = os.path.basename(storage_key)
        target_path = os.path.normpath(os.path.join(self.base_folder, filename))
        if not target_path.startswith(self.base_folder):
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
