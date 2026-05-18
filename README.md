<div align="center">
# 💖 Apoie este projeto

**Este projeto é 100% independente e open-source.**  
💜 Seu apoio mantém o desenvolvimento ativo e faz o projeto continuar evoluindo.

** Projeto baseado no projeto em GO do colega https://github.com/felipemarinho97/torrent-indexer

** Observação o projeto foi todo criado em python do zero

<a href="https://donate.stripe.com/3cI3cvehCfd18bxbPoco000" target="_blank">
  <img src="https://img.shields.io/badge/💸%20APOIAR%20ESTE%20PROJETO-00C851?style=for-the-badge" width="500" />
</a>
</div>

# DF Indexer - Python Torrent Indexer
Indexador em Python que organiza torrents brasileiros em formato padronizado, pronto para consumo por ferramentas como **Prowlarr**, **Sonarr** e **Radarr**.

## 🚀 Características
- ✅ **Múltiplos Scrapers**: Suporte para 7 sites de torrents brasileiros
- ✅ **Padronização Inteligente**: Títulos padronizados para facilitar matching automático
- ✅ **Metadata API**: Busca automática de tamanhos, datas e nomes via iTorrents.org
- ✅ **Tracker Scraping**: Consulta automática de trackers UDP para seeds/leechers
- ✅ **FlareSolverr**: Suporte opcional para resolver Cloudflare com sessões reutilizáveis e serialização de requisições paralelas
- ✅ **Cache Multi-Camadas**: Cache Redis + Cache HTTP local em memória (30s) para máxima performance
- ✅ **Sistema Cross-Data**: Compartilhamento de dados entre scrapers via Redis (reduz consultas desnecessárias)
- ✅ **Circuit Breakers**: Proteção contra sobrecarga de serviços externos
- ✅ **Paralelização 100%**: Processamento 100% paralelo de links para máxima velocidade
- ✅ **Connection Pooling**: Pool de conexões HTTP otimizado (50 pools, 100 maxsize) para reduzir latência
- ✅ **Rate Limiting Otimizado**: Rate limiter de metadata otimizado (6-7 req/s) para 5-10x mais rápido
- ✅ **Semáforo de Metadata**: 128 requisições simultâneas de metadata para alta concorrência
- ✅ **Otimizações**: Filtragem antes de enriquecimento pesado para melhor performance

### 📝 Padronização de Títulos
Todos os títulos são padronizados no formato:
- **Episódios**: `Title.S02E01.2025.WEB-DL.1080p`
- **Episódios Múltiplos**: `Title.S02E05-06-07.2025.WEB-DL.1080p`
- **Séries Completas**: `Title.S02.2025.WEB-DL`
- **Filmes**: `Title.2025.1080p.BluRay`

### 🎬 Tags de Idioma
O sistema adiciona automaticamente tags de idioma aos títulos quando detecta informações de áudio:
- **[Brazilian]**: Fonte Principal: HTML (`audio_info: 'português'`), Fallback 1: Magnet (`dual/dublado/nacional/portugues`), Fallback 2: Metadata, Fallback 3: Cross Data
- **[Eng]**: Fonte Principal: HTML (`audio_info: 'Inglês'`), Fallback 1: Magnet (`dual/legendado/legenda/leg`), Fallback 2: Metadata, Fallback 3: Cross Data
- **[Jap]**: Fonte Principal: HTML (`audio_info: 'japonês'`), Fallback 1: Magnet (`japonês/japones/japanese/jap`), Fallback 2: Metadata, Fallback 3: Cross Data

### 🌐 Sites Suportados
- ✅ **$†@Я©Ҝ**
- ✅ **†₣!£₥€**
- ✅ **₱ØЯ†@£**
- ✅ **Ẍ₣!£₥€$**
- ✅ **©Ø₥@₦ÐØ** - Necessário selecionar o FlareSolverr
- ✅ **฿£µÐ√** - Necessário selecionar o FlareSolverr


## 🐳 Docker

### Docker  - Opção 1: Docker Compose (Recomendado - Se encontra nos arquivos acima)
A forma mais simples de executar o projeto é usando Docker Compose, que já configura o Redis automaticamente:

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

### Docker - Opção 2: Docker Run CLI (Avançado - Se preferir executar manualmente) 

```bash
# Primeiro, crie a rede customizada (opcional, mas recomendado)
docker network create --subnet=172.50.0.0/24 --gateway=172.50.0.1 net-dfindexer

# Inicie o Redis (dados salvos em ./redis_data)
docker run -d \
  --name=redis \
  --restart=unless-stopped \
  --network=net-dfindexer \
  --ip=172.50.0.100 \
  -v $(pwd)/redis_data:/data \
  redis:7-alpine \
  redis-server --appendonly yes

# Opcional: Inicie o FlareSolverr (para resolver Cloudflare)
docker run -d \
  --name=flaresolverr \
  --restart=unless-stopped \
  --network=net-dfindexer \
  --ip=172.50.0.101 \
  -e LOG_LEVEL=info \
  -e TZ=America/Sao_Paulo \
  ghcr.io/flaresolverr/flaresolverr:latest

# Depois, inicie o indexer
docker run -d \
  --name=dfindexer \
  --restart=unless-stopped \
  --network=net-dfindexer \
  --ip=172.50.0.102 \
  -e REDIS_HOST=redis \
  -e REDIS_PORT=6379 \
  -e FLARESOLVERR_ADDRESS=http://flaresolverr:8191 \
  -e PORT=7006 \
  -e LOG_LEVEL=1 \
  -e LOG_FORMAT=console \
  -p 7006:7006 \
  ghcr.io/dflexy/dfindexer:latest
```
### ⚙️ Docker - Variáveis de Ambiente
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
| `EMPTY_QUERY_MAX_LINKS`                 | Limite de links individuais a processar da página 1                      | `16`             |
| `FLARESOLVERR_ADDRESS`                  | Endereço do servidor FlareSolverr (ex: http://flaresolverr:8191)         | `None` (opcional)  |
| `LOG_LEVEL`                             | `0` (debug), `1` (info), `2` (warn), `3` (error)                         | `1`                |
| `LOG_FORMAT`                            | `console` ou `json`                                                      | `console`          |
| `PROXY_TYPE`                            | Tipo de proxy: `http`, `https`, `socks5`, `socks5h` (opcional)           | `http`             |
| `PROXY_HOST`                            | Host do proxy (opcional)                                                 | `None`             |
| `PROXY_PORT`                            | Porta do proxy (opcional)                                                | `None`             |
| `PROXY_USER`                            | Usuário do proxy (opcional, requer PROXY_PASS)                           | `None`             |
| `PROXY_PASS`                            | Senha do proxy (opcional, requer PROXY_USER)                             | `None`             |

#### Opções de PROXY_TYPE:
- **`http`**: Proxy HTTP padrão (padrão)
- **`https`**: Proxy HTTPS (túnel HTTP sobre TLS)
- **`socks5`**: Proxy SOCKS5 (resolve DNS no cliente)
- **`socks5h`**: Proxy SOCKS5 (resolve DNS no servidor proxy - recomendado para evitar vazamentos de DNS)


## 🔌 Prowlarr

### Prowlarr  - Configuração Inicial

1. Baixe o arquivo de configuração `prowlarr.yml` neste repositório
2. Crie um diretório chamado `Custom` dentro do diretório de configuração do Prowlarr, na pasta `Definitions`
   - Se ele ainda não existir, você pode criá-lo no seguinte local:
   - `<Prowlarr_Config_Directory>/Definitions/Custom/`
3. Coloque o arquivo `prowlarr.yml` que você baixou dentro do diretório `Custom` criado no passo anterior
4. Reinicie o Prowlarr para aplicar as alterações
5. Extra(Tutorial servar https://wiki.servarr.com/prowlarr/indexers#adding-a-custom-yml-definition)

### Prowlarr - Adicionar o Indexador
1. Vá até a página **Indexers** no Prowlarr
2. Clique no botão **"+"** para adicionar um novo indexador
3. Digite **"DF Indexer"** na busca e selecione **DF Indexer** na lista
4. Edite as opções padrão, se necessário, e não esqueça de adicionar
5. Salve as alterações

### Prowlarr - Adicionar Vários Sites
Para adicionar vários sites, deve ser feita a clonagem do primeiro indexer no Prowlarr:
<img width="489" height="274" alt="image" src="https://github.com/user-attachments/assets/ea24dfee-fe1e-45a7-a55f-0bb4aab66c36" />

1. No indexer clonado, selecione outro site
2. Com isso você consegue criar vários indexadores e usar todos

### Prowlarr - Selecionar FlareSolverr para Cloudflare
Para poder selecionar o FlareSolverr:

1. Edite o indexador no Prowlarr
2. Selecione o campo **[Usar FlareSolverr]**
3. No momento, somente 3 sites precisam ser selecionados:
- ✅ **©Ø₥@₦ÐØ**
- ✅ **฿£µÐ√**
   
<img width="652" height="824" alt="image" src="https://github.com/user-attachments/assets/000c4e51-df2e-4b47-86d6-0010f026ef61" />

### FlareSolverr - Gerenciamento de Sessões

O sistema gerencia sessões do FlareSolverr de forma inteligente:

**Com Redis disponível:**
- Sessões são armazenadas no Redis e compartilhadas entre todas as threads/processos
- TTL configurável via `FLARESOLVERR_SESSION_TTL` (padrão: 4 horas)
- Reutilização automática de sessões válidas
- Invalidação automática quando sessão expira ou fica inválida

**Sem Redis (fallback):**
- Usa cache compartilhado global em memória (thread-safe)
- Sessões são compartilhadas entre todas as threads do mesmo processo
- Mesmo TTL configurável via `FLARESOLVERR_SESSION_TTL`
- Proteção contra race conditions com locks apropriados

**Proteção em Processamento Paralelo:**
- Requisições ao FlareSolverr são serializadas por `base_url` usando locks
- Evita race conditions onde HTML de uma requisição poderia ser retornado para outra
- Validação de HTML antes de salvar no cache garante que corresponde à URL solicitada

## 💾 Cache

### Cache - HTML
O sistema usa cache em **três camadas** para HTML das páginas:

1. **Cache Local (Memória)**: 30 segundos - Primeira camada, mais rápida
2. **Cache Redis (Curto)**: 10 minutos - Para páginas pequenas (< 500KB)
3. **Cache Redis (Longo)**: 12 horas - Para páginas grandes (>= 500KB)

**Validação de Cache**: O sistema valida se o HTML retornado corresponde à URL solicitada antes de salvar no cache, evitando problemas de race conditions em processamento paralelo.

### Cache - Comportamento
O comportamento varia conforme o tipo de requisição:
** Busca sem query = Consulta automatica do radarr e sonarr a cada 15 minutos
** Busca com query = Consulta manual

| Situação                 | Query            | `_is_test`| HTML usa cache?              | Vê novos links?                | Observações                                         |
|--------------------------|------------------|-----------|------------------------------|--------------------------------|-----------------------------------------------------|
| **Busca sem query**      | Vazia            | `True`    | ❌ Não (sempre busca fresco) | ✅ Sim                        | HTML nunca é salvo no Redis durante buscas sem query|
| **Busca com query**      | Com query        | `False`   | ✅ Sim (conforme TTL)        | ⚠️ Pode demorar (conforme TTL)| Novos links aparecem quando cache expira            |

### Cache - Exemplo Prático
**Exemplo prático** (com `HTML_CACHE_TTL_LONG=6h`):
- **10:00** - Busca com query → Salva cache (válido até 16:00)
- **10:15** - Site adiciona novos links
- **10:30** - Busca com query → Usa cache antigo → ❌ Não vê novos links
- **16:01** - Busca com query → Cache expirou → Busca fresco → ✅ Vê novos links

## 🔍 API

### 🔍 API WEB
http://localhost:7006/api

** Atenção - Selecionar todos pode demorar ou travar devido a demora de requisições.

** Principamente com os sites que usam Cloudflare

<img width="1252" height="819" alt="image" src="https://github.com/user-attachments/assets/423073ad-33eb-4459-ae29-1cd720bbee2e" />

### 🔍 API Endpoints
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Informações básicas da API |
| GET | `/indexer` | Usa scraper padrão |
| GET | `/indexer?q=foo` | Busca na fonte padrão |
| GET | `/indexer?page=2` | Paginação |
| GET | `/indexer?q=foo&filter_results=true` | Busca com filtro |
| GET | `/indexer?q=foo&use_flaresolverr=true` | Busca com FlareSolverr |
| GET | `/indexers/<tipo>?q=foo` | Usa scraper específico |

### Formato de Resposta

```json
{
  "results": [
    {
      "title_processed": "Pluribus.S01.2025.WEB-DL",
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

## ⚠️ Notas
** Este é um projeto de indexação de torrents. 
** Use com responsabilidade e respeite os direitos autorais.
