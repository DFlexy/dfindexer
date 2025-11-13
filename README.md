# DF Indexer - Python Torrent Indexer

Indexador em Python que replica (e amplia) a lógica do projeto original em Go para organizar torrents brasileiros em um formato padronizado, pronto para consumo por ferramentas como Prowlarr, Sonarr e Radarr.

## Visão Geral

- Conecta-se a múltiplos sites de torrents e extrai títulos, links magnet, datas, tamanhos e metadados relevantes.
- Consulta trackers UDP automaticamente para preencher seeds/leechers, com cache e lista dinâmica de trackers (sem fallback estático).
- Padroniza nomes de lançamentos (séries, episódios e filmes) para facilitar matching automático.
- Opcionalmente utiliza Redis para cachear o HTML bruto e reduzir carga/latência.
- Exponde uma API JSON simples que pode ser acoplada ao Prowlarr via `prowlarr.yml`.

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

## Scrapers Suportados

| Tipo             | Domínio                        | Observações principais                                    |
|------------------|--------------------------------|-----------------------------------------------------------|
| `starck.py`      | https://starckfilmes-v3.com/   | Magnet direto no HTML, títulos completos                  |
| `rede.py`        | https://redetorrent.com/       | Estrutura semelhante ao projeto Go                        |
| `tfilme.py`      | https://torrentdosfilmes.se/   | Precisa tratar metas de temporada/ano dentro do conteúdo  |
| `vaca.py`        | https://vacatorrentmov.com/    | Magnet em múltiplos botões, fallback para base64          |
| `limao.py`       | https://limaotorrent.org/      | Links via Vialink (token base64), temporada no HTML       |

Cada classe de scraper expõe `DEFAULT_BASE_URL` com a URL oficial, podendo ser sobrescrita ao instanciar o scraper com o parâmetro opcional `base_url`.

Cada scraper herda de `BaseScraper` e implementa `search()` e `get_page()` utilizando BeautifulSoup para navegar na estrutura própria do site.

## Padronização de Títulos

Toda saída faz uso de `utils.text_processing.create_standardized_title()` para manter um padrão consistente:

- **Episódios**: `Title.S02E01.year.restodomagnet`
- **Episódios Duplos**: `Title.S02E01-02.year.restodomagnet`
- **Episódios Múltiplos**: `Title.S02E01-02-03.year.restodomagnet` (triplos, quádruplos, etc.)
- **Séries completas**: `Title.S02.year.restodomagnet`
- **Filmes**: `Title.year.restodomagnet`
- **Faltou `dn` no magnet**: Usa título da página + `WEB-DL` como fallback

Regras adicionais:

- Ordenação garantida: sempre `Título → Sxx/Eyy → Ano → Qualidade/Tags` (ex.: `Pluribus.S01.2025.WEB-DL.1080p`).
- Detecta temporadas descritas no HTML (ex.: "1ª temporada", "Temporada: 1") mesmo quando o magnet não tem `dn`.
- Garante zero-padding em temporadas/episódios (`S01`, `E05`).
- Suporta episódios múltiplos (duplos, triplos, quádruplos, etc.) com validação rigorosa para evitar falsos positivos.
- Mantém termos técnicos relevantes (`CAMRip`, `TSRip`, qualidades, codecs, grupo release, etc.) sem os mover antes do título.
- Para magnets sem `dn`, usa título da página + `WEB-DL` como fallback para garantir performance.
- Adiciona as tags `[br-dub]` / `[br-leg]` quando identifica conteúdo dublado ou legendado no release.
- Quando o site não informa tamanho, busca via metadata API (iTorrents.org) como padrão, com fallback para o parâmetro `xl` do magnet.
- Remove duplicata de pontos e hífens gerando um texto pronto para matching.

### Busca de Tamanhos, Datas e Nomes via Metadata API

O sistema utiliza uma estratégia de fallback em múltiplas camadas para obter informações de torrents:

#### Tamanhos:
1. **Tamanho do HTML** (extraído pelo scraper específico)
2. **Metadata API** (iTorrents.org) - busca automática quando habilitada via `MAGNET_METADATA_ENABLED=true`
3. **Parâmetro 'xl' do magnet** - fallback quando metadata não está disponível

#### Datas:
1. **Creation Date do Torrent** (via metadata API) - **PADRÃO**: Usa a data de criação real do arquivo .torrent (timestamp Unix extraído do bencode)
2. **Data do HTML** (extraída pelo scraper) - **FALLBACK**: Data de publicação do post no site (usada apenas quando `creation_date` não está disponível)

#### Nomes (quando falta `dn` no magnet):
1. **Metadata API** (iTorrents.org) - **FALLBACK 1**: Busca o nome completo do torrent via metadata API, preservando formato original (ex: "Pluribus S01E01-02 WEB-DL 1080p x264 DUAL 5.1")
2. **Título da página + WEB-DL** - **FALLBACK 2**: Usa título da página quando metadata não está disponível

> **Importante**: Quando `MAGNET_METADATA_ENABLED=true`, o sistema busca simultaneamente tamanho, data de criação e nome do torrent via metadata API, reutilizando a mesma requisição HTTP e cache (24 horas no Redis). O nome do metadata é sempre tentado primeiro quando falta `dn` no magnet, garantindo maior precisão e preservação do formato original do release.

#### Otimização de Performance - Busca Inteligente de Metadata

O sistema implementa uma estratégia otimizada para evitar buscas desnecessárias de metadata:

**Fluxo Otimizado:**
1. **Torrents SEM `dn` (display_name vazio ou muito curto)**:
   - Busca metadata para título **ANTES do filtro** (via `prepare_release_title`)
   - Garante que o filtro tenha títulos completos para trabalhar corretamente
   - Evita filtrar torrents válidos que precisam de metadata para ter título completo

2. **Torrents COM `dn` completo**:
   - **NÃO busca** metadata para título (já têm título completo)
   - Busca metadata para size/date **APENAS DEPOIS do filtro**
   - Evita trabalho desnecessário para torrents que serão descartados

3. **Trackers**:
   - Buscados **APENAS DEPOIS do filtro**
   - Evita consultas UDP desnecessárias para torrents que serão descartados

**Resultado**: Redução significativa de requisições HTTP/UDP quando há muitos resultados que serão filtrados, melhorando performance e reduzindo carga nos serviços externos.

### Circuit Breaker e Resiliência

O sistema implementa circuit breakers avançados para evitar requisições desnecessárias quando serviços externos estão indisponíveis:

#### Metadata API (iTorrents.org)

**Circuit Breaker para Timeouts:**
- **Threshold**: 3 timeouts consecutivos
- **Duração de desabilitação**: 5 minutos
- **Comportamento**: Após 3 timeouts, o sistema para de tentar buscar metadados por 5 minutos, evitando sobrecarga
- **Recuperação**: Sucessos resetam o contador de timeouts automaticamente

**Circuit Breaker para Erros 503 (Service Unavailable):**
- **Threshold**: 5 erros 503 consecutivos
- **Duração de desabilitação**: 5 minutos
- **Comportamento**: Quando o servidor retorna muitos erros 503, o sistema desabilita automaticamente a busca de metadata
- **Cache de falhas**: Erros 503 são cacheados por 5 minutos por hash individual, evitando tentativas repetidas
- **Recuperação**: Sucessos resetam o contador de erros 503 automaticamente

**Rate Limiting:**
- **Taxa**: 1 requisição por segundo (mais conservador para evitar sobrecarga)
- **Burst**: 2 tokens (permite até 2 requisições rápidas quando há tokens disponíveis)
- **Implementação**: Rate limiter global thread-safe que garante que não excedemos a taxa mesmo com múltiplas threads

**Tratamento de Erros:**
- **Erros 503**: Detectados e cacheados por 5 minutos (não tenta uppercase após 503)
- **Timeouts**: Timeout reduzido para 5s (connect) + 3s (read) = máximo 8s por requisição
- **Evita tentativas duplicadas**: Lock por hash evita requisições simultâneas ao mesmo torrent
- **Cache de falhas**: Falhas individuais são cacheadas para evitar tentativas repetidas

**Lock por Hash:**
- Sistema de lock por hash evita requisições simultâneas ao mesmo torrent
- Verifica cache novamente após adquirir lock (outra thread pode ter cacheado)
- Evita tentativas duplicadas quando múltiplas threads processam o mesmo hash

#### Tracker List Provider
- **Threshold**: 3 timeouts consecutivos ao buscar lista de trackers
- **Duração de desabilitação**: 5 minutos
- **Comportamento**: Após 3 timeouts ao buscar trackers remotos, o sistema usa apenas trackers em cache por 5 minutos
- **Recuperação**: Sucessos resetam o contador de timeouts automaticamente

Ambos os circuit breakers utilizam Redis para compartilhar o estado entre instâncias e são totalmente transparentes ao usuário, garantindo que o sistema continue funcionando mesmo quando serviços externos estão temporariamente indisponíveis.

## Filtro de Resultados

O endpoint aceita `filter_results=true`. Quando ativado, a função `check_query_match()` garante que pelo menos parte significativa da query esteja presente no título padronizado ou no título original. A lógica ignora stop words (incluindo "temporada"/"season") e entende queries numéricas como referência a temporadas (`S01`, `S1`).

### Otimização do Filtro

O filtro é aplicado de forma inteligente para maximizar performance:

1. **Garantia de Títulos Completos**: Antes de aplicar o filtro, o sistema garante que todos os títulos estão completos:
   - Torrents sem `dn` já buscaram metadata para título no `prepare_release_title`
   - Torrents com títulos muito curtos (< 10 chars) têm metadata buscado como fallback
   - Isso garante que o filtro funcione corretamente com títulos completos

2. **Filtro Antes de Enriquecimento Pesado**: O filtro é aplicado **ANTES** de:
   - Buscar trackers (evita consultas UDP desnecessárias)
   - Buscar metadata para size/date (evita requisições HTTP desnecessárias)
   
3. **Resultado**: Redução significativa de requisições externas quando há muitos resultados que serão filtrados, melhorando performance e reduzindo carga nos serviços externos (iTorrents.org e trackers UDP).

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
| `MAGNET_METADATA_ENABLED`       | Habilita busca de tamanhos e datas via metadata API (iTorrents.org).          | `false`            |
| `LOG_LEVEL`                     | `0` (debug), `1` (info), `2` (warn), `3` (error)                              | `1`                |
| `LOG_FORMAT`                    | `console` ou `json`                                                           | `console`          |

## Build e Execução com Docker

```bash
docker build -t dfindexer .

docker run -d \
  --name=indexer \
  --hostname=indexer \
  --dns=172.30.0.254 \
  --network=lan \
  --ip=172.20.0.27 \
  --restart=unless-stopped \
  -e TZ=America/Sao_Paulo \
  -e SHORT_LIVED_CACHE_EXPIRATION=10m \
  -e LONG_LIVED_CACHE_EXPIRATION=7d \
  -e REDIS_HOST=redis \
  -e LOG_LEVEL=1 \
  -e LOG_FORMAT=console \
  -p 7006:7006 \
  dfindexer
```

> **Nota:** Caso o Redis não esteja disponível, o indexador continua funcionando; apenas abre mão do cache e loga um aviso.

## Endpoints HTTP

| Método | Rota                         | Descrição                                                    |
|--------|------------------------------|--------------------------------------------------------------|
| GET    | `/`                           | Informações básicas da API                                   |
| GET    | `/indexer`                    | Usa o scraper padrão configurado                             |
| GET    | `/indexer?q=foo`              | Busca na fonte padrão                                        |
| GET    | `/indexer?page=2`             | Paginação simples                                            |
| GET    | `/indexer?q=foo&filter_results=true` | Busca com filtro inteligente                              |
| GET    | `/indexers/<tipo>?q=foo`      | Usa o scraper informado (`starck`, `limao`, `tfilme`, …)     |

A resposta sempre segue o formato:

```json
{
  "results": [
    {
      "title": "Pluribus.S01.2025 (pt-br)",
      "original_title": "Pluribus",
      "details": "https://...",
      "year": "2025",
      "imdb": "tt0123456",
      "audio": [],
      "magnet_link": "magnet:?xt=urn:btih:...",
      "date": "2025-07-10T18:30:00",
      "info_hash": "...",
      "trackers": ["udp://tracker.opentrackr.org:1337/announce", ...],
      "size": "2.45 GB",
      "leech_count": 0,
      "seed_count": 0,
      "similarity": 1.0
    }
  ],
  "count": 1
}
```

Os scrapers fazem scraping ativo de trackers UDP para preencher seeds/leechers quando disponível. Os campos permanecem `0` quando:
- O site não exibe esses números no HTML
- Os trackers não respondem dentro do timeout configurado
- É um teste do Prowlarr (otimização automática)

O campo `date` utiliza a data de criação do torrent (via metadata API) como principal, com fallback para a data de publicação do post no site quando a metadata não está disponível.

## Integração com Prowlarr

O arquivo `prowlarr.yml` contém a definição de indexer customizado.

1. Acesse **Settings > Indexers > + > Custom**.
2. Cole o conteúdo de `prowlarr.yml` no campo de configuração.
3. Ajuste o campo `links:` se o endereço da API for diferente.
4. Escolha o scraper desejado através do dropdown "Indexer".

O `keywordsfilters` já converte buscas como `S01` para `temporada 1`, casando com a lógica de padronização do Python.

## Desenvolvimento Local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app.main run --port 7006
```

### Execução de Scrapers Isolados

Você pode testar um scraper específico via shell Python:

```python
from scraper.limao import LimaoScraper
scraper = LimaoScraper()
results = scraper.search("pluribus temporada 1")
print(results[0]["title"])
```

Ou, para cenários de CLI/automação baseados apenas no `type`:

```python
from scraper import create_scraper

scraper = create_scraper("limao")  # usa a URL padrão embutida
print(scraper.get_page())
```

## Notas Técnicas

- **Magnet Links**: Parseados em `magnet.parser.MagnetParser`, que suporta info_hash em hex ou base32.
- **Títulos**: Os scrapers aplicam fallback para títulos originais e normalizam acentos/stop words.
- **Episódios Duplos**: O sistema detecta e padroniza episódios duplos no formato `S02E05-06`, preservando o traço entre os episódios.
- **Temporadas**: `_apply_season_temporada_tags` garante que temporadas encontradas no HTML sejam refletidas no título final (ex.: `S01`, `S02`).
- **Tags Técnicas**: Palavras técnicas como `CAMRip` ou `TSRip` são preservadas para evitar perda de contexto.
- **Metadata API**: Busca automática de tamanhos e datas via iTorrents.org com cache Redis (24h) e rate limiting otimizado (1 req/s com burst de 2). A mesma requisição HTTP busca ambos os metadados simultaneamente para otimizar performance.
- **Circuit Breakers Avançados**: 
  - Sistema de circuit breakers duplo para Metadata API (timeouts e erros 503)
  - Threshold de 3 timeouts consecutivos ou 5 erros 503 consecutivos
  - Desabilitação automática por 5 minutos quando serviços estão indisponíveis
  - Cache de falhas individuais por hash (5 minutos para 503, 1 minuto para outros erros)
- **Rate Limiting Inteligente**: 
  - 1 requisição por segundo (mais conservador)
  - Burst de 2 tokens para permitir requisições rápidas ocasionais
  - Thread-safe com locks para evitar race conditions
- **Tratamento de Erros Robusto**:
  - Erros 503 não tentam uppercase (indica serviço indisponível, não hash incorreto)
  - Timeouts reduzidos para 5s connect + 3s read (máximo 8s por requisição)
  - Lock por hash evita requisições simultâneas ao mesmo torrent
  - Cache de falhas evita tentativas repetidas
- **Datas**: O campo `date` prioriza a data de criação real do torrent (`creation_date`) obtida via metadata API, usando a data de publicação do post HTML como fallback. Isso garante maior precisão na idade dos torrents.
- **Otimizações de Performance**:
  - Filtro aplicado antes de buscar trackers e metadata para size/date
  - Torrents com `dn` completo não buscam metadata para título
  - Torrents sem `dn` buscam metadata para título antes do filtro
  - Testes do Prowlarr automaticamente limitam processamento e desabilitam metadata/trackers
- **Scrapers Dinâmicos**: Todos os scrapers herdam automaticamente otimizações e funcionalidades do `BaseScraper`.

## Histórico de Melhorias e Otimizações

### Otimizações de Performance (Novembro 2025)

#### 1. Filtro Inteligente Antes de Enriquecimento
- **Problema**: Trackers e metadata eram buscados para todos os torrents, mesmo os que seriam filtrados depois
- **Solução**: Filtro aplicado antes de buscar trackers e metadata para size/date
- **Resultado**: Redução significativa de requisições HTTP/UDP quando há muitos resultados

#### 2. Busca Seletiva de Metadata para Títulos
- **Problema**: Busca de metadata para títulos era feita mesmo quando não necessário
- **Solução**: 
  - Torrents sem `dn`: Buscam metadata para título ANTES do filtro (necessário para filtro funcionar)
  - Torrents com `dn`: NÃO buscam metadata para título (já têm título completo)
- **Resultado**: Evita buscas desnecessárias de metadata para títulos

#### 3. Rate Limiting Otimizado
- **Problema**: Rate limiting muito agressivo (2 req/s) causava muitos erros 503
- **Solução**: Reduzido para 1 req/s com burst de 2 tokens
- **Resultado**: Menos sobrecarga no servidor iTorrents.org, menos erros 503

#### 4. Tratamento de Erros 503
- **Problema**: Erros 503 ainda tentavam uppercase, causando requisições duplicadas
- **Solução**: 
  - Erros 503 não tentam uppercase (indica serviço indisponível)
  - Cache de falhas 503 por 5 minutos
  - Circuit breaker específico para erros 503 (5 erros consecutivos)
- **Resultado**: Evita tentativas desnecessárias quando serviço está indisponível

#### 5. Timeouts Reduzidos
- **Problema**: Timeout de 15 segundos era muito longo, causando esperas desnecessárias
- **Solução**: Reduzido para 5s (connect) + 3s (read) = máximo 8s por requisição
- **Resultado**: Respostas mais rápidas quando servidor está lento

#### 6. Lock por Hash
- **Problema**: Múltiplas threads faziam requisições simultâneas ao mesmo hash
- **Solução**: Sistema de lock por hash evita requisições simultâneas
- **Resultado**: Evita requisições duplicadas e reduz carga no servidor

#### 7. Cache de Falhas Melhorado
- **Problema**: Falhas não eram cacheadas adequadamente, causando tentativas repetidas
- **Solução**: 
  - Cache de falhas 503 por 5 minutos
  - Cache de falhas gerais por 1 minuto
  - Verificação de cache antes de fazer requisições
- **Resultado**: Evita tentativas repetidas após falhas

#### 8. Circuit Breaker Duplo
- **Problema**: Circuit breaker só detectava timeouts, não erros 503
- **Solução**: 
  - Circuit breaker para timeouts (3 consecutivos)
  - Circuit breaker para erros 503 (5 consecutivos)
  - Ambos desabilitam metadata por 5 minutos
- **Resultado**: Sistema mais resiliente quando serviços externos estão indisponíveis

### Melhorias de Código

- Adicionado suporte para `filter_func` opcional em `enrich_torrents` para aplicar filtro antes do enriquecimento
- Método `_ensure_titles_complete` garante títulos completos antes do filtro
- Melhor tratamento de erros HTTP com cache específico por tipo de erro
- Documentação melhorada com comentários explicativos sobre otimizações
- Todos os scrapers atualizados para aceitar `filter_func` no método `search`

## Créditos

Projetado e mantido por **DFlexy** (https://github.com/DFlexy).
