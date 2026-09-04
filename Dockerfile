# Usa uma versão leve do Python
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Bibliotecas de sistema para compilar o mysqlclient (MySQL 8.0, ver architecture.md)
# e o python-ldap (FEAT-027/RN-043, ADR-002 - reintroduzidas; removidas na
# reconstrucao do FEAT-012 quando ainda nao havia integracao com AD)
RUN apt-get update && apt-get install -y \
    default-mysql-client \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    libldap2-dev \
    libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependências primeiro (cache de build mais rápido)
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# FEAT-033 (ADR-004/ADR-005): RPA de anexo no portal EACE - baixa o
# Chromium do Playwright e as bibliotecas de sistema que ele precisa para
# rodar headless (--with-deps roda o apt-get sozinho). Usado pelo serviço
# rpa_eace_worker (docker-compose.yml); fica na imagem inteira porque o
# projeto usa 1 Dockerfile só para todos os serviços (mesmo padrão já
# aceito para o python-ldap, que também está na imagem toda mesmo só o
# "web" fazendo login via AD).
RUN python -m playwright install --with-deps chromium

# Copia o resto do código
COPY . /app/

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "120", "config.wsgi:application"]
