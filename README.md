<div align="center">
# 💖 Apoie este projeto

**Este projeto é 100% independente e open-source.**  
💜 Seu apoio mantém o desenvolvimento ativo e faz o projeto continuar evoluindo.
**This project is 100% independent and open-source.**  
💜 Your support keeps development active and makes the project continue evolving.

** Projeto baseado no projeto em GO do colega https://github.com/felipemarinho97/torrent-indexer
** Projeto todo criado em python do zero

<a href="https://donate.stripe.com/3cI3cvehCfd18bxbPoco000" target="_blank">
  <img src="https://img.shields.io/badge/💸%20APOIAR%20ESTE%20PROJETO-00C851?style=for-the-badge" width="500" />
</a>
</div>

# DF Indexer - Python Torrent Indexer
Indexador em Python que organiza torrents brasileiros em formato padronizado, pronto para consumo por ferramentas como **Prowlarr**, **Sonarr** e **Radarr**.
Python indexer that organizes Brazilian torrents in a standardized format, ready for consumption by tools like **Prowlarr**, **Sonarr** and **Radarr**.

## 🚀 Características Principais
- ✅ **Múltiplos Scrapers**: Suporte para 7 sites de torrents brasileiros
- ✅ **Padronização Inteligente**: Títulos padronizados para facilitar matching automático
- ✅ **Metadata API**: Busca automática de tamanhos, datas e nomes via iTorrents.org
- ✅ **Tracker Scraping**: Consulta automática de trackers UDP para seeds/leechers
- ✅ **FlareSolverr**: Suporte opcional para resolver Cloudflare com sessões reutilizáveis
- ✅ **Cache Redis**: Cache inteligente para reduzir carga e latência
- ✅ **Circuit Breakers**: Proteção contra sobrecarga de serviços externos
- ✅ **Otimizações**: Filtragem antes de enriquecimento pesado para melhor performance

## 🚀 Main Features
- ✅ **Multiple Scrapers**: Support for 7 Brazilian torrent sites
- ✅ **Smart Standardization**: Standardized titles to facilitate automatic matching
- ✅ **Metadata API**: Automatic search for sizes, dates and names via iTorrents.org
- ✅ **Tracker Scraping**: Automatic UDP tracker queries for seeds/leechers
- ✅ **FlareSolverr**: Optional support to resolve Cloudflare with reusable sessions
- ✅ **Redis Cache**: Smart cache to reduce load and latency
- ✅ **Circuit Breakers**: Protection against external service overload
- ✅ **Optimizations**: Filtering before heavy enrichment for better performance


## Sites Suportados
- ✅ ** st❂rçƙ–f¡lmΞs_v③
- ✅ ** rεdƎ–tørrΞn†★★
- ✅ ** tørrεnτ–đøs–ƒ¡lmεš♡
- ✅ ** vª¢ª–tørrεnτ–m◎√
- ✅ ** l¡mªø–tørrεnτ–Ωrg
- ✅ ** ¢ømªnd◎–łå (Necessário selecionar o FlareSolverr)
- ✅ ** błµđv–ƒ¡lmεš♡

## Supported Sites
- ✅ ** st❂rçƙ–f¡lmΞs_v③
- ✅ ** rεdƎ–tørrΞn†★★
- ✅ ** tørrεnτ–đøs–ƒ¡lmεš♡
- ✅ ** vª¢ª–tørrεnτ–m◎√
- ✅ ** l¡mªø–tørrεnτ–Ωrg
- ✅ ** ¢ømªnd◎–łå (FlareSolverr selection required)
- ✅ ** błµđv–ƒ¡lmεš♡

## 🐳 Execução com Docker
### Opção 1: Docker Compose (Recomendado)
A forma mais simples de executar o projeto é usando Docker Compose, que já configura o Redis automaticamente:

## 🐳 Running with Docker
### Opção 1: Docker Compose (Recommended)
The simplest way to run the project is using Docker Compose, which automatically configures Redis:

```bash
# Construir e iniciar os serviços
docker-compose up -d

# Ver logs
docker-compose logs -f

# Parar os serviços
docker-compose down

# Parar e remover volumes (limpa dados do Redis)
docker-compose down -v
```

O Docker Compose irá:
- ✅ Iniciar o serviço Redis automaticamente
- ✅ Iniciar o serviço FlareSolverr automaticamente (opcional, para resolver Cloudflare)
- ✅ Configurar a rede entre os containers
- ✅ Persistir dados do Redis em volume nomeado
- ✅ Configurar restart automático
### Opção 2: Docker Run CLI
Se preferir executar manualmente:

Docker Compose will:
- ✅ Automatically start the Redis service
- ✅ Automatically start the FlareSolverr service (optional, to resolve Cloudflare)
- ✅ Configure the network between containers
- ✅ Persist Redis data in a named volume
- ✅ Configure automatic restart
### Option 2: Docker Run CLI
If you prefer to run manually:


```bash
# Primeiro, inicie o Redis
docker run -d \
  --name=redis \
  --restart=unless-stopped \
  -p 6379:6379 \
  redis:7-alpine

# Opcional: Inicie o FlareSolverr (para resolver Cloudflare)
docker run -d \
  --name=flaresolverr \
  --restart=unless-stopped \
  -p 8191:8191 \
  -e LOG_LEVEL=info \
  ghcr.io/flaresolverr/flaresolverr:latest

# Depois, inicie o indexer
docker run -d \
  --name=indexer \
  --restart=unless-stopped \
  -e REDIS_HOST=redis \
  -e LOG_LEVEL=1 \
  -e FLARESOLVERR_ADDRESS=http://flaresolverr:8191 \
  -p 7006:7006 \
  --link redis:redis \
  --link flaresolverr:flaresolverr \
  ghcr.io/dflexy/dfindexer:latest
```

**Nota**: O FlareSolverr é opcional. Se não for iniciado, o indexer funcionará normalmente, mas sites protegidos por Cloudflare podem retornar erro 403.
**Note**: FlareSolverr is optional. If not started, the indexer will work normally, but Cloudflare-protected sites may return a 403 error.

## 🔌 Integração com Prowlarr
1. Primeiro, baixe o arquivo de configuração prowlarr.yml neste repositorio
2. Crie um diretório chamado Custom dentro do diretório de configuração do Prowlarr, na pasta Definitions.
 .Se ele ainda não existir, você pode criá-lo no seguinte local:
 .<Prowlarr_Config_Directory>/Definitions/Custom/
3. Coloque o arquivo prowlarr.yml que você baixou dentro do diretório Custom criado no passo anterior.
4. Reinicie o Prowlarr para aplicar as alterações.
5 . Adicionar o Torrentio como Indexador Personalizado
 . Depois que o Prowlarr reiniciar, você pode adicionar o Torrentio como um indexador customizado seguindo estes passos:
 . Vá até a página Indexers no Prowlarr.
 . Clique no botão "+" para adicionar um novo indexador.
 . Digite "DF Indexer" na busca e selecione DF Indexer na lista.
 . Edite as opções padrão, se necessário, e não esqueça de adicionar
 . Salve as alterações

### Funcionalidades Configuradas
- ✅ Suporte a Filmes e Séries
- ✅ Detecção automática de categoria
- ✅ Filtragem inteligente ativada
- ✅ Conversão automática de queries (`S01` → `temporada 1`)
- ✅ Suporte opcional ao FlareSolverr (seletor no Prowlarr)
- ✅ Testes inteligentes: fazem requisições HTTP reais para verificar se o site está UP, mas pulam enriquecimento pesado e não usam Redis

## 🔌 Integration with Prowlarr
1. First, download the prowlarr.yml configuration file from this repository
2. Create a directory called Custom inside the Prowlarr configuration directory, in the Definitions folder.
 .If it doesn't exist yet, you can create it in the following location:
 .<Prowlarr_Config_Directory>/Definitions/Custom/
3. Place the prowlarr.yml file you downloaded inside the Custom directory created in the previous step.
4. Restart Prowlarr to apply the changes.
5 . Add Torrentio as Custom Indexer
 . After Prowlarr restarts, you can add Torrentio as a custom indexer by following these steps:
 . Go to the Indexers page in Prowlarr.
 . Click the "+" button to add a new indexer.
 . Type "DF Indexer" in the search and select DF Indexer from the list.
 . Edit the default options if necessary, and don't forget to add
 . Save the changes

### Configured Features
- ✅ Movies and Series support
- ✅ Automatic category detection
- ✅ Smart filtering enabled
- ✅ Automatic query conversion (`S01` → `temporada 1`)
- ✅ Optional FlareSolverr support (selector in Prowlarr)
- ✅ Smart tests: make real HTTP requests to verify if the site is UP, but skip heavy enrichment and don't use Redis

## 📝 Padronização de Títulos
Todos os títulos são padronizados no formato:

- **Episódios**: `Title.S02E01.2025.WEB-DL.1080p`
- **Episódios Múltiplos**: `Title.S02E05-06-07.2025.WEB-DL.1080p`
- **Séries Completas**: `Title.S02.2025.WEB-DL`
- **Filmes**: `Title.2025.1080p.BluRay`

**Ordem garantida**: `Título → Temporada/Episódio → Ano → Informações Técnicas`

## 📝 Title Standardization
All titles are standardized in the format:

- **Episodes**: `Title.S02E01.2025.WEB-DL.1080p`
- **Multiple Episodes**: `Title.S02E05-06-07.2025.WEB-DL.1080p`
- **Complete Series**: `Title.S02.2025.WEB-DL`
- **Movies**: `Title.2025.1080p.BluRay`

**Guaranteed order**: `Title → Season/Episode → Year → Technical Information`

## Variáveis de Ambiente
| Variável                                | Descrição                                                                | Padrão             |
|-----------------------------------------|--------------------------------------------------------------------------|--------------------|
| `PORT`                                  | Porta da API                                                             | `7006`             |
| `METRICS_PORT`                          | Porta do servidor de métricas (reservada, ainda não utilizada)           | `8081`             |
| `REDIS_HOST`                            | Host do Redis (opcional)                                                 | `localhost`        |
| `REDIS_PORT`                            | Porta do Redis                                                           | `6379`             |
| `REDIS_DB`                              | Banco lógico do Redis                                                    | `0`                |
| `HTML_CACHE_TTL_SHORT`                  | TTL do cache curto de HTML (páginas)                                     | `10m`              |
| `HTML_CACHE_TTL_LONG`                   | TTL do cache longo de HTML (páginas)                                     | `12h`              |
| `FLARESOLVERR_SESSION_TTL`              | TTL das sessões FlareSolverr                                              | `4h`               |
| `EMPTY_QUERY_MAX_LINKS`                 | Limite de links individuais a processar da página 1                      | `15`             |
| `FLARESOLVERR_ADDRESS`                  | Endereço do servidor FlareSolverr (ex: http://flaresolverr:8191)         | `None` (opcional)  |
| `LOG_LEVEL`                             | `0` (debug), `1` (info), `2` (warn), `3` (error)                         | `1`                |
| `LOG_FORMAT`                            | `console` ou `json`                                                      | `console`          |

## Environment Variables
| Variable                                 | Description                                                              | Default            |
|------------------------------------------|--------------------------------------------------------------------------|--------------------|
| `PORT`                                   | API port                                                                 | `7006`             |
| `METRICS_PORT`                           | Metrics server port (reserved, not yet used)                             | `8081`             |
| `REDIS_HOST`                             | Redis host (optional)                                                    | `localhost`        |
| `REDIS_PORT`                             | Redis port                                                               | `6379`             |
| `REDIS_DB`                               | Redis logical database                                                   | `0`                |
| `HTML_CACHE_TTL_SHORT`                   | Short HTML cache TTL (pages)                                            | `10m`              |
| `HTML_CACHE_TTL_LONG`                    | Long HTML cache TTL (pages)                                             | `12h`              |
| `FLARESOLVERR_SESSION_TTL`               | FlareSolverr session TTL                                                | `4h`               |
| `EMPTY_QUERY_MAX_LINKS`                  | Limit of individual links to process from page 1                          | `15`             |
| `FLARESOLVERR_ADDRESS`                   | FlareSolverr server address (ex: http://flaresolverr:8191)               | `None` (optional)  |
| `LOG_LEVEL`                              | `0` (debug), `1` (info), `2` (warn), `3` (error)                         | `1`                |
| `LOG_FORMAT`                             | `console` or `json`                                                      | `console`          |

### Comportamento do Cache de HTML
O sistema usa cache em dois níveis para HTML das páginas. O comportamento varia conforme o tipo de requisição:

| Situação                 | Query            | `_is_test`| HTML usa cache?              | Vê novos links?                | Observações                               |
|--------------------------|------------------|-----------|------------------------------|--------------------------------|-------------------------------------------|
| **Busca sem query**      | Vazia            | `True`    | ❌ Não (sempre busca fresco) | ✅ Sim                           | HTML nunca é salvo no Redis durante buscas sem query|
| **Busca com query**      | Com query        | `False`   | ✅ Sim (conforme TTL)        | ⚠️ Pode demorar (conforme TTL)| Novos links aparecem quando cache expira  |

**Exemplo prático** (com `HTML_CACHE_TTL_LONG=6h`):
- **10:00** - Busca com query → Salva cache (válido até 16:00)
- **10:15** - Site adiciona novos links
- **10:30** - Busca com query → Usa cache antigo → ❌ Não vê novos links
- **16:01** - Busca com query → Cache expirou → Busca fresco → ✅ Vê novos links

**Importante**: Durante buscas sem query (`_is_test=True`), o HTML sempre é buscado fresco, garantindo que novos links apareçam imediatamente. O cache de HTML afeta apenas buscas com query.

### HTML Cache Behavior
The system uses two-level caching for page HTML. Behavior varies according to request type:

| Situation                 | Query            | `_is_test`| HTML uses cache?             | Sees new links?                | Notes                                     |
|--------------------------|------------------|-----------|------------------------------|--------------------------------|-------------------------------------------|
| **Search without query** | Empty            | `True`    | ❌ No (always fetches fresh) | ✅ Yes                           | HTML is never saved to Redis during searches without query |
| **Search with query**    | With query       | `False`   | ✅ Yes (according to TTL)    | ⚠️ May be delayed (per TTL)    | New links appear when cache expires        |

**Practical example** (with `HTML_CACHE_TTL_LONG=6h`):
- **10:00** - Search with query → Saves cache (valid until 16:00)
- **10:15** - Site adds new links
- **10:30** - Search with query → Uses old cache → ❌ Doesn't see new links
- **16:01** - Search with query → Cache expired → Fetches fresh → ✅ Sees new links

**Important**: During searches without query (`_is_test=True`), HTML is always fetched fresh, ensuring new links appear immediately. HTML cache only affects searches with query.

## 🔍 API Endpoints
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Informações básicas da API |
| GET | `/indexer` | Usa scraper padrão |
| GET | `/indexer?q=foo` | Busca na fonte padrão |
| GET | `/indexer?page=2` | Paginação |
| GET | `/indexer?q=foo&filter_results=true` | Busca com filtro |
| GET | `/indexer?q=foo&use_flaresolverr=true` | Busca com FlareSolverr |
| GET | `/indexers/<tipo>?q=foo` | Usa scraper específico |

## 🔍 API Endpoints
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Basic API information |
| GET | `/indexer` | Uses default scraper |
| GET | `/indexer?q=foo` | Search in default source |
| GET | `/indexer?page=2` | Pagination |
| GET | `/indexer?q=foo&filter_results=true` | Search with filter |
| GET | `/indexer?q=foo&use_flaresolverr=true` | Search with FlareSolverr |
| GET | `/indexers/<type>?q=foo` | Uses specific scraper |

### Formato de Resposta
```json
{
  "results": [
    {
      "title": "Pluribus.S01.2025.WEB-DL",
      "original_title": "Pluribus",
      "details": "https://...",
      "year": "2025",
      "magnet_link": "magnet:?xt=urn:btih:...",
      "info_hash": "...",
      "size": "2.45 GB",
      "date": "2025-07-10T18:30:00",
      "seed_count": 10,
      "leech_count": 2
    }
  ],
  "count": 1
}
```

## 📄 Licença
Este projeto é mantido por **DFlexy**.
## 🤝 Contribuindo
Contribuições são bem-vindas! Sinta-se à vontade para abrir issues ou pull requests.
---
**Nota**: Este é um projeto de indexação de torrents. Use com responsabilidade e respeite os direitos autorais.

## 📄 License
This project is maintained by **DFlexy**.
## 🤝 Contributing
Contributions are welcome! Feel free to open issues or pull requests.
---
**Note**: This is a torrent indexing project. Use responsibly and respect copyrights.

