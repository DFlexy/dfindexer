<div align="center">
# 💖 Apoie este projeto

**Este projeto é 100% independente e open-source.**  
💜 Seu apoio mantém o desenvolvimento ativo e faz o projeto continuar evoluindo.

<a href="https://donate.stripe.com/3cI3cvehCfd18bxbPoco000" target="_blank">
  <img src="https://img.shields.io/badge/💸%20APOIAR%20ESTE%20PROJETO-00C851?style=for-the-badge" width="500" />
</a>
</div>

# DF Indexer - Python Indexer para torrents do Brazil
 - Indexador em Python que replica (e amplia) a lógica do projeto original em Go https://github.com/felipemarinho97/torrent-indexer
 - Para organizar torrents brasileiros em um formato padronizado, pronto para consumo por ferramentas como Prowlarr, Sonarr e Radarr.

## Visão Geral
- Conecta-se a múltiplos sites de torrents e extrai títulos, links magnet, datas, tamanhos e metadados relevantes.
- Padroniza nomes de lançamentos (séries, episódios e filmes) para facilitar matching automático.
- Opcionalmente utiliza Redis para cachear o HTML bruto e reduzir carga/latência.

## Estrutura do Projeto
```
dfindexer/
├── app/              # Configurações e bootstrap da aplicação
├── api/              # Handlers Flask que expõem a API HTTP
├── cache/            # Cliente Redis (opcional)
├── magnet/           # Parser de links magnet (info_hash, display_name, trackers)
├── scraper/          # Scrapers específicos por site
├── tracker/          # Scrape de trackers UDP, cache e lista dinâmica de trackers
├── utils/            # Utilitários (títulos, datas, logging, etc.)
├── Dockerfile        # Build da imagem Docker oficial
├── prowlarr.yml      # Configuração do indexer customizado para Prowlarr
└── requirements.txt  # Dependências Python
```

## Padronização de Títulos
- **Episódios**: `Title.S02E01.year.restodomagnet`
- **Episódios Duplos**: `Title.S02E01-02.year.restodomagnet`
- **Episódios Múltiplos**: `Title.S02E01-02-03.year.restodomagnet` (triplos, quádruplos, etc.)
- **Séries completas**: `Title.S02.year.restodomagnet`
- **Filmes**: `Title.year.restodomagnet`
- **Faltou `dn` no magnet**: Usa título da página + `WEB-DL` como fallback

## Regras adicionais:
- Ordenação garantida: sempre `Título → Sxx/Eyy → Ano → Qualidade/Tags` (ex.: `Pluribus.S01.2025.WEB-DL.1080p`).
- Adiciona as tags `[br-dub]` / `[br-leg]` quando identifica conteúdo dublado ou legendado no release.

## Variáveis de Ambiente
| Variável                         | Descrição                                                                    | Padrão             |
|---------------------------------|-------------------------------------------------------------------------------|--------------------|
| `PORT`                          | Porta da API                                                                  | `7006`             |
| `METRICS_PORT`                  | Porta do servidor de métricas (reservada, ainda não utilizada)                | `8081`             |
| `REDIS_HOST`                    | Host do Redis (opcional)                                                      | `localhost`        |
| `REDIS_PORT`                    | Porta do Redis                                                                | `6379`             |
| `REDIS_DB`                      | Banco lógico do Redis                                                         | `0`                |
| `SHORT_LIVED_CACHE_EXPIRATION`  | TTL do cache curto (HTML bruto)                                               | `10m`              |
| `LONG_LIVED_CACHE_EXPIRATION`   | TTL do cache longo                                                            | `12h`              |
| `TRACKER_SCRAPE_TIMEOUT`        | Timeout por requisição UDP aos trackers (segundos)                            | `0.5`              |
| `TRACKER_SCRAPE_RETRIES`        | Número de tentativas por tracker                                              | `2`                |
| `TRACKER_SCRAPE_MAX_TRACKERS`   | Quantidade máxima de trackers consultados por infohash (0 = ilimitado)        | `0`                |
| `TRACKER_CACHE_TTL`             | TTL do cache de seeds/leechers                                                | `24h`              |
| `MAGNET_METADATA_ENABLED`       | Habilita busca de tamanhos e datas via metadata API                           | `false`            |
| `LOG_LEVEL`                     | `0` (debug), `1` (info), `2` (warn), `3` (error)                              | `1`                |
| `LOG_FORMAT`                    | `console` ou `json`                                                           | `console`          |

## Abaixo um exemplo de um docker-compose.yml para subir os 2 containers em uma nova rede.
 Edite conforme necessário
 
```bash
version: "3.9"

services:
  redis:
    image: redis:alpine
    container_name: redis
    hostname: redis
    restart: unless-stopped
    environment:
      - TZ=America/Sao_Paulo
    volumes:
      - redis_data:/data
    networks:
      df-net:
        ipv4_address: 172.20.0.10
    ports:
      - "6379:6379"

  dfindexer:
    image: ghcr.io/dflexy/dfindexer:latest
    container_name: dfindexer
    hostname: dfindexer
    restart: unless-stopped
    environment:
      - TZ=America/Sao_Paulo
      - SHORT_LIVED_CACHE_EXPIRATION=10m
      - LONG_LIVED_CACHE_EXPIRATION=7d
      - REDIS_HOST=redis
    networks:
      df-net:
        ipv4_address: 172.20.0.11
    ports:
      - "7006:7006"
    depends_on:
      - redis

volumes:
  redis_data:

networks:
  df-net:
    name: df-net
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/24
```

# Notas
** Nota: Caso o Redis não esteja disponível, o indexador continua funcionando; apenas abre mão do cache e loga um aviso.

## Integração com Prowlarr
O arquivo `prowlarr.yml` contém a definição de indexer customizado.

1. Acesse **Settings > Indexers > + > Custom**.
2. Cole o conteúdo de `prowlarr.yml` no campo de configuração.
3. Ajuste o campo `links:` se o endereço da API for diferente.
4. Escolha o scraper desejado através do dropdown "Indexer".

Para saber como instalar o custom no prowlarr procure no google por (prowlarr custom indexer yml)

## Créditos
Projetado e mantido por **DFlexy** (https://github.com/DFlexy).
