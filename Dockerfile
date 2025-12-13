FROM python:3.11-slim

WORKDIR /app

# Instala dependências do sistema necessárias para compilar lxml e outras libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements primeiro (melhor cache do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Remove dependências de compilação após instalar (reduz tamanho da imagem)
RUN apt-get purge -y gcc g++ libxml2-dev libxslt1-dev \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Cria usuário não-root para segurança
RUN useradd -m -u 1000 appuser

# Copia código da aplicação
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser api/ ./api/
COPY --chown=appuser:appuser cache/ ./cache/
COPY --chown=appuser:appuser core/ ./core/
COPY --chown=appuser:appuser magnet/ ./magnet/
COPY --chown=appuser:appuser models/ ./models/
COPY --chown=appuser:appuser scraper/ ./scraper/
COPY --chown=appuser:appuser tracker/ ./tracker/
COPY --chown=appuser:appuser utils/ ./utils/

# Muda para usuário não-root
USER appuser

# Expõe porta
EXPOSE 7006

# Comando padrão
CMD ["python", "-m", "app.main"]
