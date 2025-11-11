FROM python:3.11-slim

WORKDIR /app

# Instala dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código
COPY app/ ./app/
COPY api/ ./api/
COPY cache/ ./cache/
COPY magnet/ ./magnet/
COPY scraper/ ./scraper/
COPY utils/ ./utils/
COPY tracker/ ./tracker/

# Expõe porta
EXPOSE 7006

# Comando padrão
CMD ["python", "-m", "app.main"]


