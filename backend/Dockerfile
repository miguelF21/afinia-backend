FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias del sistema requeridas para psycopg2 y ML
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente
COPY . .

# Exponer el puerto
EXPOSE 5000

# Comando para ejecutar (producción)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "run:app"]
