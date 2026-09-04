FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instala o Chromium e todas as dependências de sistema que ele precisa
RUN playwright install --with-deps chromium

COPY src/ ./src/
COPY web/ ./web/

# Garante que as pastas de volume existam com permissões corretas
RUN mkdir -p input/EACE output config/logs config/screenshots data

EXPOSE 8000

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
