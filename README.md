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
- ✅ **Múltiplos Scrapers**: Suporte para 6 sites de torrents brasileiros
- ✅ **Padronização Inteligente**: Títulos padronizados para facilitar matching automático
- ✅ **Metadata API**: Busca automática de tamanhos, datas e nomes via iTorrents.org
- ✅ **Tracker Scraping**: Consulta automática de trackers UDP para seeds/leechers
- ✅ **FlareSolverr**: Suporte opcional para resolver Cloudflare com sessões reutilizáveis
- ✅ **Cache Redis**: Cache inteligente para reduzir carga e latência
- ✅ **Circuit Breakers**: Proteção contra sobrecarga de serviços externos
- ✅ **Otimizações**: Filtragem antes de enriquecimento pesado para melhor performance


## Sites Suportados
- ✅ ** st❂rçƙ–f¡lmΞs_v③
- ✅ ** rεdƎ–tørrΞn†★★
- ✅ ** tørrεnτ–đøs–ƒ¡lmεš♡
- ✅ ** vª¢ª–tørrεnτ–m◎√
- ✅ ** l¡mªø–tørrεnτ–Ωrg
- ✅ ** ¢ømªnd◎–łå (Necessário selecionar o FlareSolverr)

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
- ✅ Iniciar o serviço FlareSolverr automaticamente (opcional, para resolver Cloudflare)
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
  dfindexer
```

**Nota**: O FlareSolverr é opcional. Se não for iniciado, o indexer funcionará normalmente, mas sites protegidos por Cloudflare podem retornar erro 403.

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
- ✅ Suporte opcional ao FlareSolverr (seletor no Prowlarr)
- ✅ Testes inteligentes: fazem requisições HTTP reais para verificar se o site está UP, mas pulam enriquecimento pesado e não usam Redis

## 📝 Padronização de Títulos
Todos os títulos são padronizados no formato:

- **Episódios**: `Title.S02E01.2025.WEB-DL.1080p`
- **Episódios Múltiplos**: `Title.S02E05-06-07.2025.WEB-DL.1080p`
- **Séries Completas**: `Title.S02.2025.WEB-DL`
- **Filmes**: `Title.2025.1080p.BluRay`

**Ordem garantida**: `Título → Temporada/Episódio → Ano → Informações Técnicas`

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
| `MAGNET_METADATA_ENABLED`               | Habilita busca de tamanhos e datas via metadata API (iTorrents.org).     | `true`             |
| `TRACKER_SCRAPING_ENABLED`              | Habilita scraping de trackers UDP para seeds/leechers                    | `true`             |
| `CIRCUIT_BREAKER_ENABLED`               | Habilita circuit breakers para proteção contra sobrecarga de serviços    | `true`             |
| `EMPTY_QUERY_COLLECT_METADATA_TRACKERS` | Permite coletar e salvar metadata/trackers quando query está vazia       | `true`             |
| `EMPTY_QUERY_MAX_LINKS`                 | Limite de links individuais a processar da página 1                      | `20`             |
| `FLARESOLVERR_ADDRESS`                  | Endereço do servidor FlareSolverr (ex: http://flaresolverr:8191)         | `None` (opcional)  |
| `LOG_LEVEL`                             | `0` (debug), `1` (info), `2` (warn), `3` (error)                         | `1`                |
| `LOG_FORMAT`                            | `console` ou `json`                                                      | `console`          |

### Comportamento do Cache de HTML
O sistema usa cache em dois níveis para HTML das páginas. O comportamento varia conforme o tipo de requisição:

| Situação                 | Query            | `_is_test`| HTML usa cache?              | Vê novos links?                | Observações                               |
|--------------------------|------------------|-----------|------------------------------|--------------------------------|-------------------------------------------|
| **Teste Sonarr/Prowlarr**| Vazia            | `True`    | ❌ Não (sempre busca fresco) | ✅ Sim (a cada 15min)         | HTML nunca é salvo no Redis durante testes|
| **Busca manual**         | Com query        | `False`   | ✅ Sim (conforme TTL)        | ⚠️ Pode demorar (conforme TTL)| Novos links aparecem quando cache expira  |
| **Busca sem query**      | Vazia (não teste)| `False`   | ✅ Sim (conforme TTL)        | ⚠️ Pode demorar (conforme TTL)| Comportamento igual a busca com query     |

**Exemplo prático** (com `HTML_CACHE_TTL_LONG=6h`):
- **10:00** - Busca manual → Salva cache (válido até 16:00)
- **10:15** - Site adiciona novos links
- **10:30** - Busca manual → Usa cache antigo → ❌ Não vê novos links
- **16:01** - Busca manual → Cache expirou → Busca fresco → ✅ Vê novos links

**Importante**: Durante testes do Sonarr (a cada 15 minutos), o HTML sempre é buscado fresco, garantindo que novos links apareçam imediatamente. O cache de HTML afeta apenas buscas manuais (com query).

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
- **Processamento Paralelo**: Processamento paralelo de páginas e metadata para melhor performance
- **FlareSolverr Otimizado**: Sessões reutilizáveis por site, cache de HTML evita chamadas desnecessárias
- **Testes Inteligentes**: Prowlarr tests fazem requisições HTTP reais para verificar se o site está UP
- **Ordenação por Data**: Resultados ordenados por data (mais recentes primeiro) para sincronização RSS/Sonarr
- **Circuit Breakers**: Proteção automática contra serviços indisponíveis
- **Extração de Datas Aprimorada**: Suporte para múltiplas meta tags

## 📄 Licença
Este projeto é mantido por **DFlexy**.

## 🤝 Contribuindo
Contribuições são bem-vindas! Sinta-se à vontade para abrir issues ou pull requests.

---
**Nota**: Este é um projeto de indexação de torrents. Use com responsabilidade e respeite os direitos autorais.

