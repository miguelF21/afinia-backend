import time
import threading
from functools import wraps
from flask import request, current_app
from app.utils.errors import api_error

class InMemoryRateLimiter:
    """
    Limitador de tasa de peticiones en memoria basado en ventana deslizante (sliding window).
    Diseñado para desarrollo, pruebas unitarias y entornos de instancia única.
    
    NOTA DE ARQUITECTURA PARA PRODUCCIÓN:
    En despliegues con múltiples workers (ej. Gunicorn con gevent/uvicorn o Kubernetes réplicas),
    el almacenamiento en memoria de cada worker no se comparte. Para producción distribuida,
    debe reemplazarse o respaldarse este almacén con Redis o un clúster de caché centralizado.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._records = {}  # key -> list of timestamps

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        window_start = now - window_seconds
        
        with self._lock:
            # Obtener y limpiar registros antiguos fuera de la ventana
            timestamps = self._records.get(key, [])
            valid_timestamps = [ts for ts in timestamps if ts > window_start]
            
            if len(valid_timestamps) >= max_requests:
                self._records[key] = valid_timestamps
                return True
            
            valid_timestamps.append(now)
            self._records[key] = valid_timestamps
            return False

    def clear(self):
        with self._lock:
            self._records.clear()

limiter = InMemoryRateLimiter()

def get_trusted_client_ip() -> str:
    """
    Obtiene la dirección IP real del cliente.
    Si TRUST_PROXY no está explícitamente activado, utiliza la IP de la conexión de socket (remote_addr)
    impidiendo que clientes no confiables eludan los límites manipulando cabeceras X-Forwarded-For.
    """
    if current_app.config.get('TRUST_PROXY', False):
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'

def rate_limit(limit: int = 10, window_seconds: int = 60, key_prefix: str = 'global'):
    """
    Decorador para limitar la tasa de solicitudes por IP o clave compuesta.
    Devuelve error 429 RATE_LIMITED conforme a OpenAPI.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # En modo testing o si se deshabilita explícitamente en config, ignorar
            if current_app.config.get('TESTING') and not current_app.config.get('ENABLE_RATE_LIMIT_IN_TESTS'):
                return f(*args, **kwargs)

            client_ip = get_trusted_client_ip()
            key = f"{key_prefix}:{client_ip}"
            
            if limiter.is_rate_limited(key, max_requests=limit, window_seconds=window_seconds):
                return api_error(
                    code='RATE_LIMITED',
                    message='Límite de peticiones alcanzado. Por favor, intenta de nuevo más tarde.',
                    status_code=429
                )
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
