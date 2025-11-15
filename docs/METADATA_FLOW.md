# Fluxo de Busca de Tamanhos - Explicação Detalhada

## 🎯 Resumo Rápido

**PARA quando encontra o tamanho!** O sistema tenta em ordem e **para assim que encontra**.

---

## 📊 Fluxo Completo (Passo a Passo)

### Quando um scraper retorna torrents:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Scraper extrai torrents do HTML                          │
│    └─ Extrai tamanho do HTML (salvo como fallback)         │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. enrich_torrents() é chamado automaticamente              │
│    └─ Para CADA torrent:                                   │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. TENTATIVA 1: Busca via Metadata API (PRIORIDADE)        │
│    └─ Chama get_torrent_size()                             │
│    └─ Metadata é mais confiável (vem do arquivo .torrent)  │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────────┐   ┌──────────────────────┐
│ Verifica CACHE   │   │ Cache Redis existe?  │
│ Redis primeiro   │   └──────────────────────┘
└──────────────────┘           │
        │                       │
        ▼                       ▼
┌──────────────────┐   ┌──────────────────────┐
│ Cache HIT?       │SIM│ Retorna do cache     │
│ (chave:          │───│ → USA → PARA AQUI ✅ │
│ metadata:hash)   │   └──────────────────────┘
└──────────────────┘
        │
       NÃO (cache miss)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Busca no iTorrents.org                                  │
│    └─ Baixa apenas HEADER do .torrent (até 512KB)         │
│    └─ Parseia bencode para extrair tamanho                 │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────────┐   ┌──────────────────────┐
│ Encontrou?       │SIM│ Cacheia no Redis     │
│                  │───│ (24 horas)            │
│                  │   │ → USA → PARA AQUI ✅  │
└──────────────────┘   └──────────────────────┘
        │
       NÃO encontrou
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. TENTATIVA 2: Parâmetro 'xl' do magnet link              │
│    └─ Parseia magnet → procura parâmetro 'xl'             │
│    └─ Se encontrou → formata e USA → PARA AQUI ✅        │
└─────────────────────────────────────────────────────────────┘
                    │
                   NÃO encontrou
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. TENTATIVA 3: Usa tamanho do HTML (FALLBACK FINAL)       │
│    └─ Usa o tamanho extraído do HTML pelo scraper         │
│    └─ Se encontrou → USA → PARA AQUI ✅                   │
└─────────────────────────────────────────────────────────────┘
                    │
                   NÃO encontrou
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. Retorna None (sem tamanho)                              │
│    └─ Torrent fica sem tamanho (não quebra nada)           │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔄 Comportamento do Cache

### Primeira vez (sem cache):
```
Torrent ABC123 → Busca iTorrents → Encontra 1.5 GB → Cacheia → Retorna
```

### Próximas vezes (com cache):
```
Torrent ABC123 → Verifica cache → ENCONTROU! → Retorna 1.5 GB (instantâneo)
```

### Expiração do cache:
```
Cache expira após 24 horas → Próxima busca faz nova requisição
```

---

## ⚡ Performance

### Com cache (99% dos casos após primeira busca):
- **Tempo**: < 1ms (apenas leitura do Redis)
- **Rede**: 0 requisições HTTP
- **iTorrents**: 0 requisições

### Sem cache (primeira vez):
- **Tempo**: ~500ms - 2s (depende da rede)
- **Rede**: 1 requisição HTTP (apenas header, ~6-64KB)
- **iTorrents**: 1 requisição (com rate limiting)

---

## 🛡️ Rate Limiting

O sistema tem rate limiting para não sobrecarregar o iTorrents:
- **2 requisições por segundo** (máximo)
- **Burst de 4** (permite 4 requisições rápidas, depois limita)

---

## ✅ Respostas às Perguntas

### 1. Fica procurando sempre ou para quando acha?
**PARA quando acha!** Assim que encontra o tamanho em qualquer etapa, usa e passa para o próximo torrent.

### 2. Como funciona o cache?
- **Primeira busca**: Faz requisição HTTP → Cacheia no Redis (24h)
- **Próximas buscas**: Lê do Redis (instantâneo)
- **Após 24h**: Cache expira → Faz nova requisição

### 3. E se não encontrar?
Não quebra nada! O torrent simplesmente fica sem tamanho (campo `size` vazio).

### 4. É rápido?
**SIM!** Com cache é instantâneo (< 1ms). Sem cache leva ~500ms-2s, mas só acontece na primeira vez por torrent.

---

## 📝 Exemplo Prático

### Cenário: 10 torrents

```
Torrent 1: Busca metadata cache → ✅ ENCONTROU (1ms) → USA metadata
Torrent 2: Busca metadata cache → ❌ Não tem
           → Busca iTorrents → ✅ Encontrou (800ms) → Cacheia → USA metadata
Torrent 3: Busca metadata cache → ✅ ENCONTROU (1ms) → USA metadata
Torrent 4: Busca metadata cache → ❌ Não tem
           → Busca iTorrents → ❌ Não encontrou
           → Tenta 'xl' → ✅ Encontrou (5ms) → USA parâmetro xl
Torrent 5: Busca metadata cache → ✅ ENCONTROU (1ms) → USA metadata
Torrent 6: Busca metadata cache → ❌ Não tem
           → Busca iTorrents → ❌ Não encontrou
           → Tenta 'xl' → ❌ Não tem
           → Usa HTML (fallback final) → ✅ USA tamanho do HTML
Torrent 7-10: Busca metadata cache → ✅ ENCONTROU (1ms cada) → USA metadata

Total: ~808ms (só 1 requisição HTTP real)
Observação: Ordem de prioridade: Metadata > Parâmetro xl > HTML
```

---

## 🎯 Conclusão

O sistema é **inteligente e eficiente**:
- ✅ Para assim que encontra
- ✅ Usa cache para evitar requisições repetidas
- ✅ Rate limiting para não sobrecarregar serviços externos
- ✅ Resiliente (falhas não quebram o sistema)
- ✅ Rápido (cache = instantâneo)

