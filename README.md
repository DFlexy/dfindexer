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
- ✅ Vários scrapers de torrents brasileiros, com títulos padronizados para Sonarr/Radarr
- ✅ Metadata (iTorrents.org), trackers UDP (seeds/leechers) e tags de idioma automáticas
- ✅ FlareSolverr opcional para sites com Cloudflare
- ✅ Cache Redis + memória, cross-data entre scrapers e circuit breakers
- ✅ Processamento paralelo de links, com filtro antes do enriquecimento pesado

### 📝 Padronização de Títulos
Todos os títulos são padronizados no formato:
- **Episódios**: `Title.S02E01.2025.WEB-DL.1080p`
- **Episódios Múltiplos**: `Title.S02E05-06-07.2025.WEB-DL.1080p`
- **Séries Completas**: `Title.S02.2025.WEB-DL`
- **Filmes**: `Title.2025.1080p.BluRay`

### 🎬 Tags de Idioma
Tags adicionadas ao título conforme áudio detectado (HTML → magnet → metadata → cache):
- **[Brazilian]** — português / dublado / nacional
- **[Eng]** — inglês / legendado
- **[Jap]** — japonês

### 🌐 Sites Suportados
- ✅ **$†@Я©Ҝ**
- ✅ **Я€Ð€**
- ✅ **†₣!£₥€**
- ✅ **₱ØЯ†@£**
- ✅ **Ẍ₣!£₥€$**
- ✅ **©Ø₥@₦ÐØ** - Necessário selecionar o FlareSolverr
- ✅ **฿£µÐ√** - Necessário selecionar o FlareSolverr


## 🐳 Docker

Os exemplos abaixo usam **`network_mode: host`**: os containers compartilham a rede do host (sem rede bridge customizada). 
Serviços ficam em `localhost` nas portas padrão — Redis `6379`, FlareSolverr `8191`, API `7006`, Prowlarr `9696`.

> **Requisito:** `host` funciona nativamente no **Linux**. No Docker Desktop (Windows/macOS) o comportamento pode ser limitado; prefira Linux ou VM para produção.

### Docker — Opção 1: Docker Compose (recomendado)

O `docker-compose.yml` do repositório já define Redis, FlareSolverr, indexer e Prowlarr em modo host:

```bash
# Iniciar os serviços
docker compose up -d

# Ver logs
docker compose logs -f

# Parar os serviços
docker compose down

# Parar e remover volumes (limpa dados do Redis em ./redis_data)
docker compose down -v
```

O Compose irá:
- ✅ Subir Redis, FlareSolverr, DF Indexer e Prowlarr com **`network_mode: host`**
- ✅ Persistir dados do Redis em `./redis_data`
- ✅ Configurar `REDIS_HOST` e `FLARESOLVERR_ADDRESS` apontando para `localhost`
- ✅ Configurar restart automático

**API:** `http://localhost:7006/` · **Prowlarr:** `http://localhost:9696/`

O `prowlarr.yml` usa `http://localhost:7006/` como URL base — compatível com essa stack em host.

### Docker — Opção 2: Docker Run (manual)

```bash
# Redis (porta 6379 no host)
docker run -d \
  --name=redis \
  --restart=unless-stopped \
  --network=host \
  -v "$(pwd)/redis_data:/data" \
  redis:7-alpine \
  redis-server --appendonly yes

# FlareSolverr (porta 8191 no host)
docker run -d \
  --name=flaresolverr \
  --restart=unless-stopped \
  --network=host \
  -e LOG_LEVEL=info \
  -e TZ=America/Sao_Paulo \
  ghcr.io/flaresolverr/flaresolverr:latest

# DF Indexer (porta 7006 no host)
docker run -d \
  --name=dfindexer \
  --restart=unless-stopped \
  --network=host \
  -e REDIS_HOST=localhost \
  -e REDIS_PORT=6379 \
  -e FLARESOLVERR_ADDRESS=http://localhost:8191 \
  -e PORT=7006 \
  -e LOG_LEVEL=1 \
  -e LOG_FORMAT=console \
  ghcr.io/dflexy/dfindexer:latest
```

Com `--network=host` não é necessário `-p` para publicar portas: o processo escuta diretamente no host.

### ⚙️ Docker — Variáveis de ambiente
| Variável                                | Descrição                                                                | Padrão             |
|-----------------------------------------|--------------------------------------------------------------------------|--------------------|
| `PORT`                                  | Porta da API                                                             | `7006`             |
| `METRICS_PORT`                          | Porta do servidor de métricas (reservada, ainda não utilizada)           | `8081`             |
| `REDIS_HOST`                            | Host do Redis (com Docker host: use `localhost`)                         | `localhost`        |
| `REDIS_PORT`                            | Porta do Redis                                                           | `6379`             |
| `REDIS_DB`                              | Banco lógico do Redis                                                    | `0`                |
| `HTML_CACHE_TTL_SHORT`                  | TTL do cache curto de HTML (páginas)                                     | `10m`              |
| `HTML_CACHE_TTL_LONG`                   | TTL do cache longo de HTML (páginas)                                     | `12h`              |
| `FLARESOLVERR_SESSION_TTL`              | TTL das sessões FlareSolverr                                              | `4h`               |
| `EMPTY_QUERY_MAX_LINKS`                 | Limite de links individuais a processar da página 1                      | `16`             |
| `FLARESOLVERR_ADDRESS`                  | Endereço do FlareSolverr (Docker host: `http://localhost:8191`)          | `None` (opcional)  |
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

1. No indexer clonado, selecione outro site no campo **Scraper** (valores por: `starck`, `rede`, `comand`, etc.)
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

### 🔍 API WEB
http://localhost:7006/api

** Atenção - Selecionar todos pode demorar ou travar devido a demora de requisições.

** Principamente com os sites que usam Cloudflare

<img width="1252" height="819" alt="image" src="https://github.com/user-attachments/assets/423073ad-33eb-4459-ae29-1cd720bbee2e" />

## 📄 Licença
Este projeto é mantido por **DFlexy**.

## 🤝 Contribuindo
Contribuições são bem-vindas! Sinta-se à vontade para abrir issues ou pull requests.

## ⚠️ Notas
** Este é um projeto de indexação de torrents. 
** Use com responsabilidade e respeite os direitos autorais.
