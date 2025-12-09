FROM python:3.11-slim

WORKDIR /app

# Instala dependências do sistema (gcc necessário para compilar algumas dependências Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements primeiro (melhor cache do Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Remove gcc após instalar dependências (reduz tamanho da imagem)
RUN apt-get purge -y gcc && apt-get autoremove -y && apt-get clean

# Cria usuário não-root para segurança
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app

# Copia código da aplicação
COPY app/ ./app/
COPY api/ ./api/
COPY cache/ ./cache/
COPY core/ ./core/
COPY magnet/ ./magnet/
COPY models/ ./models/
COPY scraper/ ./scraper/
COPY tracker/ ./tracker/
COPY utils/ ./utils/

# Muda para usuário não-root
USER appuser

# Expõe porta
EXPOSE 7006

# Comando padrão
CMD ["python", "-m", "app.main"]
