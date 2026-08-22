# Usa uma versão leve do Python
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Bibliotecas de sistema para compilar o mysqlclient (MySQL 8.0, ver architecture.md)
RUN apt-get update && apt-get install -y \
    default-mysql-client \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependências primeiro (cache de build mais rápido)
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copia o resto do código
COPY . /app/

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "120", "config.wsgi:application"]
