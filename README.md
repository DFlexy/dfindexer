<div align="center">
# 💖 Apoie este projeto

**Este projeto é 100% independente e open-source.**  
💜 Seu apoio mantém o desenvolvimento ativo e faz o projeto continuar evoluindo.

<a href="https://donate.stripe.com/3cI3cvehCfd18bxbPoco000" target="_blank">
  <img src="https://img.shields.io/badge/💸%20APOIAR%20ESTE%20PROJETO-00C851?style=for-the-badge" width="500" />
</a>
</div>

# DF Indexer - Python Torrent Indexer
Indexador em Python que organiza torrents brasileiros em formato padronizado, pronto para consumo por ferramentas como **Prowlarr**, **Sonarr** e **Radarr**.

## 🚀 Características Principais
- ✅ **Múltiplos Scrapers**: Suporte para 5 sites de torrents brasileiros
- ✅ **Padronização Inteligente**: Títulos padronizados para facilitar matching automático
- ✅ **Metadata API**: Busca automática de tamanhos, datas e nomes via iTorrents.org
- ✅ **Tracker Scraping**: Consulta automática de trackers UDP para seeds/leechers
- ✅ **Cache Redis**: Cache inteligente para reduzir carga e latência
- ✅ **Circuit Breakers**: Proteção contra sobrecarga de serviços externos
- ✅ **Otimizações**: Filtragem antes de enriquecimento pesado para melhor performance

## 🐳 Execução com Docker

### Opção 1: Docker Compose (Recomendado)
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
- ✅ Configurar a rede entre os containers
- ✅ Persistir dados do Redis em volume nomeado
- ✅ Configurar restart automático

### Opção 2: Docker Run CLI

Se preferir executar manualmente:

```bash
# Primeiro, inicie o Redis
docker run -d \
  --name=redis \
  --restart=unless-stopped \
  -p 6379:6379 \
  redis:alpine:latest

# Depois, inicie o indexer
docker run -d \
  --name=indexer \
  --restart=unless-stopped \
  -e REDIS_HOST=redis \
  -e LOG_LEVEL=1 \
  -p 7006:7006 \
  --link redis:redis \
  ghcr.io/dflexy/dfindexer:latest
```

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
 . Clique no botão “+” para adicionar um novo indexador.
 . Digite “DF Indexer” na busca e selecione DF Indexer na lista.
 . Edite as opções padrão, se necessário, e não esqueça de adicionar
 . Salve as alterações



### Funcionalidades Configuradas
- ✅ Suporte a Filmes e Séries
- ✅ Detecção automática de categoria
- ✅ Filtragem inteligente ativada
- ✅ Conversão automática de queries (`S01` → `temporada 1`)
- ✅ Testes rápidos (< 50ms) sem consultas externas

## 📝 Padronização de Títulos
Todos os títulos são padronizados no formato:

- **Episódios**: `Title.S02E01.2025.WEB-DL.1080p`
- **Episódios Múltiplos**: `Title.S02E05-06-07.2025.WEB-DL.1080p`
- **Séries Completas**: `Title.S02.2025.WEB-DL`
- **Filmes**: `Title.2025.1080p.BluRay`

**Ordem garantida**: `Título → Temporada/Episódio → Ano → Informações Técnicas`

## Variáveis de Ambiente
| Variável                      | Descrição                                                               | Padrão             |
|-------------------------------|-------------------------------------------------------------------------|--------------------|
| `PORT`                        | Porta da API                                                            | `7006`             |
| `METRICS_PORT`                | Porta do servidor de métricas (reservada, ainda não utilizada)          | `8081`             |
| `REDIS_HOST`                  | Host do Redis (opcional)                                                | `localhost`        |
| `REDIS_PORT`                  | Porta do Redis                                                          | `6379`             |
| `REDIS_DB`                    | Banco lógico do Redis                                                   | `0`                |
| `SHORT_LIVED_CACHE_EXPIRATION`| TTL do cache curto (HTML bruto)                                         | `10m`              |
| `LONG_LIVED_CACHE_EXPIRATION` | TTL do cache longo                                                      | `12h`              |
| `TRACKER_SCRAPE_TIMEOUT`      | Timeout por requisição UDP aos trackers (segundos)                      | `0.5`              |
| `TRACKER_SCRAPE_RETRIES`      | Número de tentativas por tracker                                        | `2`                |
| `TRACKER_SCRAPE_MAX_TRACKERS` | Quantidade máxima de trackers consultados por infohash (0 = ilimitado)  | `0`                |
| `TRACKER_CACHE_TTL`           | TTL do cache de seeds/leechers                                          | `24h`              |
| `MAGNET_METADATA_ENABLED`     | Habilita busca de tamanhos e datas via metadata API (iTorrents.org).    | `true`             |
| `LOG_LEVEL`                   | `0` (debug), `1` (info), `2` (warn), `3` (error)                        | `1`                |
| `LOG_FORMAT`                  | `console` ou `json`                                                     | `console`          |

## 🔍 API Endpoints
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Informações básicas da API |
| GET | `/indexer` | Usa scraper padrão |
| GET | `/indexer?q=foo` | Busca na fonte padrão |
| GET | `/indexer?page=2` | Paginação |
| GET | `/indexer?q=foo&filter_results=true` | Busca com filtro |
| GET | `/indexers/<tipo>?q=foo` | Usa scraper específico |

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

## 🎯 Otimizações
- **Filtro Inteligente**: Aplicado antes de enriquecimento pesado (metadata/trackers)
- **Busca Seletiva**: Metadata para títulos apenas quando necessário
- **Testes Rápidos**: Prowlarr tests processam apenas 3 itens sem consultas externas
- **Rate Limiting**: 1 req/s com burst de 2 tokens
- **Circuit Breakers**: Proteção automática contra serviços indisponíveis

## 📄 Licença
Este projeto é mantido por **DFlexy**.

## 🤝 Contribuindo
Contribuições são bem-vindas! Sinta-se à vontade para abrir issues ou pull requests.

---
**Nota**: Este é um projeto de indexação de torrents. Use com responsabilidade e respeite os direitos autorais.



