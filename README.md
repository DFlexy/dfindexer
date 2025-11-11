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

Toda saída faz uso de `utils.text_processing.create_standardized_title()` para manter um padrão consistente:

- **Episódios**: `Title.S02E01.year.restodomagnet`
- **Séries completas**: `Title.S02.year.restodomagnet`
- **Filmes**: `Title.year.restodomagnet`
- **Faltou `dn` no magnet**: `Title.S02.year.WEB-DL` (ou `Title.year.WEB-DL`)

## Padronização de Títulos

Toda saída faz uso de `utils.text_processing.create_standardized_title()` para manter um padrão consistente:

- **Episódios**: `Title.S02E01.year.restodomagnet`
- **Séries completas**: `Title.S02.year.restodomagnet`
- **Filmes**: `Title.year.restodomagnet`
- **Faltou `dn` no magnet**: `Title.S02.year.WEB-DL` (ou `Title.year.WEB-DL`)


## Regras adicionais:

- Ordenação garantida: sempre `Título → Sxx/Eyy → Ano → Qualidade/Tags` (ex.: `Pluribus.S01.2025.WEB-DL.1080p`).
- Detecta temporadas descritas no HTML (ex.: "1ª temporada", "Temporada: 1") mesmo quando o magnet não tem `dn`.
- Garante zero-padding em temporadas/episódios (`S01`, `E05`).
- Mantém termos técnicos relevantes (`CAMRip`, `TSRip`, qualidades, codecs, grupo release, etc.) sem os mover antes do título.
- Para magnets sem `dn`, força o sufixo `WEB-DL` para facilitar a identificação pelo Sonarr.
- Adiciona as tags `[br-dub]` / `[br-leg]` quando identifica conteúdo dublado ou legendado no release.
- Quando o site não informa tamanho, utiliza o parâmetro `xl` do magnet (quando presente) como fallback.
- Remove duplicata de pontos e hífens gerando um texto pronto para matching.

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
| `TRACKER_SCRAPE_MAX_TRACKERS`   | Quantidade máxima de trackers consultados por infohash (0 = ilimitado)        | `0`               |
| `TRACKER_CACHE_TTL`             | TTL do cache de seeds/leechers                                                | `24h`              |
| `LOG_LEVEL`                     | `0` (debug), `1` (info), `2` (warn), `3` (error)                              | `1`                |
| `LOG_FORMAT`                    | `console` ou `json`                                                           | `console`          |

## Execução com Docker modo host
Baixe a imagem 
```bash
docker pull ghcr.io/dflexy/dfindexer:latest
```
Execute 
```bash
docker run -d \
  --name=dfindexer \
  --hostname=dfindexer \
  --restart=unless-stopped \
  --network=host \
  -e TZ=America/Sao_Paulo \
  -e SHORT_LIVED_CACHE_EXPIRATION=10m \
  -e LONG_LIVED_CACHE_EXPIRATION=7d \
  -e REDIS_HOST=redis \
  ghcr.io/dflexy/dfindexer:latest
```

# Notas
** Nota: Caso o Redis não esteja disponível, o indexador continua funcionando; apenas abre mão do cache e loga um aviso.
** Atualmente os scrapers não fazem scraping ativo de trackers para seed/leech; os campos permanecem `0` quando o site não exibe esses números.

## Integração com Prowlarr

O arquivo `prowlarr.yml` contém a definição de indexer customizado.

1. Acesse **Settings > Indexers > + > Custom**.
2. Cole o conteúdo de `prowlarr.yml` no campo de configuração.
3. Ajuste o campo `links:` se o endereço da API for diferente.
4. Escolha o scraper desejado através do dropdown "Indexer".

Para saber como instalar o custom no prowlarr procure no google por (prowlarr custom indexer yml)

## Notas Técnicas

- Magnet links são parseados em `magnet.parser.MagnetParser`, que suporta info_hash em hex ou base32.
- Os scrapers aplicam fallback para títulos originais e normalizam acentos/stop words.
- `_apply_season_temporada_tags` garante que temporadas encontradas no HTML sejam refletidas no título final (ex.: `S01`, `S02`).
- Palavras técnicas como `CAMRip` ou `TSRip` são preservadas para evitar perda de contexto.
- Os scrapers removem logs temporários e comentários de debug; apenas logs relevantes permanecem.

## Créditos

Projetado e mantido por **DFlexy** (https://github.com/DFlexy).

