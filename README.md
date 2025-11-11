# DF Indexer - Python Indexer para torrents do Brazil


Indexador em Python que replica (e amplia) a lógica do projeto original em Go https://github.com/felipemarinho97/torrent-indexer
Para organizar torrents brasileiros em um formato padronizado, pronto para consumo por ferramentas como Prowlarr, Sonarr e Radarr.

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

| Tipo             | Domínio                          |
|------------------|----------------------------------|
| `starck`         | https://starckfilmes-v3.com/     |
| `rede_torrent`   | https://redetorrent.com/         |
| `torrent_dos_filmes` | https://torrentdosfilmes.se/ |
| `vaca_torrent`   | https://vacatorrentmov.com/      |
| `limaotorrent`   | https://limaotorrent.org/        |

Cada scraper herda de `BaseScraper` e implementa `search()` e `get_page()` utilizando BeautifulSoup para navegar na estrutura própria do site.

## Padronização de Títulos

Toda saída faz uso de `utils.text_processing.create_standardized_title()` para manter um padrão consistente:

- **Episódios**: `Title.S02E01.year.restodomagnet`
- **Séries completas**: `Title.S02.year.restodomagnet`
- **Filmes**: `Title.year.restodomagnet`
- **Faltou `dn` no magnet**: `Title.S02.year.WEB-DL` (ou `Title.year.WEB-DL`)

Regras adicionais:

- Ordenação garantida: sempre `Título → Sxx/Eyy → Ano → Qualidade/Tags` (ex.: `Pluribus.S01.2025.WEB-DL.1080p`).
- Detecta temporadas descritas no HTML (ex.: "1ª temporada", "Temporada: 1") mesmo quando o magnet não tem `dn`.
- Garante zero-padding em temporadas/episódios (`S01`, `E05`).
- Mantém termos técnicos relevantes (`CAMRip`, `TSRip`, qualidades, codecs, grupo release, etc.) sem os mover antes do título.
- Para magnets sem `dn`, força o sufixo `WEB-DL` para facilitar a identificação pelo Sonarr.
- Adiciona as tags `[br-dub]` / `[br-leg]` quando identifica conteúdo dublado ou legendado no release.
- Quando o site não informa tamanho, utiliza o parâmetro `xl` do magnet (quando presente) como fallback.
- Remove duplicata de pontos e hífens gerando um texto pronto para matching.

## Filtro de Resultados

O endpoint aceita `filter_results=true`. Quando ativado, a função `check_query_match()` garante que pelo menos parte significativa da query esteja presente no título padronizado ou no título original. A lógica ignora stop words (incluindo "temporada"/"season") e entende queries numéricas como referência a temporadas (`S01`, `S1`).

## Variáveis de Ambiente

| Variável                         | Descrição                                                                    | Padrão             |
|---------------------------------|-------------------------------------------------------------------------------|--------------------|
| `PORT`                          | Porta da API                                                                  | `7006`             |
| `REDIS_HOST`                    | Host do Redis (opcional)                                                      | `localhost`        |
| `SHORT_LIVED_CACHE_EXPIRATION`  | TTL do cache curto (HTML bruto)                                               | `10m`              |
| `LONG_LIVED_CACHE_EXPIRATION`   | TTL do cache longo                                                            | `12h`              |
| `TRACKER_SCRAPE_TIMEOUT`        | Timeout por requisição UDP aos trackers (segundos)                            | `0.5`              |
| `TRACKER_SCRAPE_RETRIES`        | Número de tentativas por tracker                                              | `2`                |
| `TRACKER_SCRAPE_MAX_TRACKERS`   | Quantidade máxima de trackers consultados por infohash (0 = ilimitado)        | `0`               |
| `TRACKER_CACHE_TTL`             | TTL do cache de seeds/leechers                                                | `24h`              |
| `SITE1`…`SITE7`                 | URLs dos sites configurados                                                   | `''`               |
| `SITE1_TYPE`…`SITE7_TYPE`       | Tipo do scraper (`starck`, `rede_torrent`, `limaotorrent`, etc.)             | `''`               |
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
  -e SITE1=https://starckfilmes-v3.com/ \
  -e SITE1_TYPE=starck \
  -e SITE2=https://redetorrent.com/ \
  -e SITE2_TYPE=rede_torrent \
  -e SITE3=https://vacatorrentmov.com/ \
  -e SITE3_TYPE=vaca_torrent \
  -e SITE4=https://limaotorrent.org/ \
  -e SITE4_TYPE=limaotorrent \
  -e SITE5=https://torrentdosfilmes.se/ \
  -e SITE5_TYPE=torrent_dos_filmes \
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
4. Escolha o site desejado através do dropdown "Indexer" (Site 1… Site 7).

O `keywordsfilters` já converte buscas como `S01` para `temporada 1`, casando com a lógica de padronização do Python.

## Notas Técnicas

- Magnet links são parseados em `magnet.parser.MagnetParser`, que suporta info_hash em hex ou base32.
- Os scrapers aplicam fallback para títulos originais e normalizam acentos/stop words.
- `_apply_season_temporada_tags` garante que temporadas encontradas no HTML sejam refletidas no título final (ex.: `S01`, `S02`).
- Palavras técnicas como `CAMRip` ou `TSRip` são preservadas para evitar perda de contexto.
- Os scrapers removem logs temporários e comentários de debug; apenas logs relevantes permanecem.

## Créditos

Projetado e mantido por **DFlexy** (https://github.com/DFlexy).

