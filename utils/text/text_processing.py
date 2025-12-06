"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import logging
import re
from typing import List, Optional
from urllib.parse import unquote

logger = logging.getLogger(__name__)

# Lista de stop words utilizada para filtrar termos irrelevantes em buscas
STOP_WORDS = [
    'the', 'my', 'a', 'an', 'and', 'of', 'to', 'in', 'for', 'or', 'as',
    'os', 'o', 'e', 'de', 'do', 'da', 'em', 'que', 'temporada', 'season'
]

# Expressão regular para remover domínios e tags comuns em títulos
RELEASE_CLEAN_REGEX = re.compile(
    r'(?i)(COMANDO\.TO|COMANDOTORRENTS|WWW\.BLUDV\.TV|BLUDV|WWW\.COMANDOTORRENTS|'
    r'TORRENTBR|BAIXEFILMES|\[EZTVx\.to\]|\[TGx\]|\[rartv\]|\[YTS\.MX\]|'
    r'TRUFFLE|ETHEL|FLUX|GalaxyRG|TOONSHUB|ERAI\.RAWS|WWW\.[A-Z0-9.-]+\.[A-Z]{2,}|\[ACESSE[^\]]*\])\s*-?\s*'
)


# Remove acentos e cedilha de caracteres latinos e normaliza caracteres turcos
def remove_accents(text: str) -> str:
    replacements = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n',
        'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
        'Ó': 'O', 'Ò': 'O', 'Õ': 'O', 'Ô': 'O', 'Ö': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ç': 'C', 'Ñ': 'N',
        # Caracteres turcos
        'İ': 'I',  # I maiúsculo com ponto → I maiúsculo normal
        'ı': 'i',  # i minúsculo sem ponto → i minúsculo normal
        'ş': 's', 'Ş': 'S',
        'ğ': 'g', 'Ğ': 'G',
        'ü': 'u', 'Ü': 'U',
        'ö': 'o', 'Ö': 'O'
    }
    return ''.join(replacements.get(c, c) for c in text)


# Remove tags de sites, múltiplos espaços/pontos e normaliza o título
def clean_title(title: str) -> str:
    cleaned = RELEASE_CLEAN_REGEX.sub('', title)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'\.{2,}', '.', cleaned)
    cleaned = re.sub(r'^\.|\.$', '', cleaned)
    cleaned = re.sub(r'\s*\.\s*', '.', cleaned)
    return cleaned.strip()


def clean_translated_title(translated_title: str) -> str:
    # Limpa o título traduzido removendo tags HTML, temporadas, anos e textos extras
    if not translated_title:
        return ''
    
    # Converte para string se não for
    translated_title = str(translated_title)
    
    # Remove todas as tags HTML (incluindo <strong>, <em>, <b>, <br />, <span>, <h1>, <title>, etc.)
    # Faz múltiplas passadas para garantir remoção completa
    while re.search(r'<[^>]+>', translated_title):
        translated_title = re.sub(r'<[^>]+>', '', translated_title)
    
    # Remove entidades HTML (como &ordf;, &nbsp;, &amp;, etc.)
    translated_title = html.unescape(translated_title)
    
    # Remove "Título Traduzido:" se ainda estiver presente (pode estar em diferentes formatos)
    translated_title = re.sub(r'(?i)^\s*T[íi]tulo\s+Traduzido\s*:?\s*', '', translated_title)
    translated_title = re.sub(r'(?i)\s*T[íi]tulo\s+Traduzido\s*:?\s*', '', translated_title)
    
    # Remove entidades HTML específicas de temporada (&ordf;, &ordm;, etc.) ANTES de remover temporada
    translated_title = re.sub(r'&ordf;', '', translated_title, flags=re.IGNORECASE)
    translated_title = re.sub(r'&ordm;', '', translated_title, flags=re.IGNORECASE)
    translated_title = html.unescape(translated_title)  # Decodifica novamente após remover entidades
    
    # Remove informações de temporada (Sxx, Temporada, etc.) - múltiplos formatos
    # Remove padrões como "1ª Temporada", "2ª Temporada", "3ª Temporada", etc.
    translated_title = re.sub(r'(?i)\s*[0-9]+[ªº]\s*Temporada\s*', '', translated_title)
    translated_title = re.sub(r'(?i)\s*[0-9]+[aªº]\s*Temporada\s*', '', translated_title)
    translated_title = re.sub(r'(?i)\s*S\d{1,2}(?:E\d{1,2})?\s*', '', translated_title)
    translated_title = re.sub(r'(?i)\s*Temporada\s*', '', translated_title)
    
    # Remove "Torrent" após temporada (ex: "2ª Temporada Torrent")
    translated_title = re.sub(r'(?i)\s*Torrent\s*', '', translated_title)
    
    # Remove anos entre parênteses (ex: (2015-2025), (2025))
    translated_title = re.sub(r'\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*', '', translated_title)
    # Remove anos soltos no final (ex: "2025")
    translated_title = re.sub(r'\s+(19|20)\d{2}\s*$', '', translated_title)
    
    # Remove textos extras de sites (padrões genéricos)
    # Remove padrões como "2025 — Site Torrent – Baixe Filmes e Séries"
    translated_title = re.sub(r'(?i)\s*—\s*[^—]+Torrent\s*–\s*Baixe\s+Filmes\s+e\s+S[ée]ries\s*$', '', translated_title)
    translated_title = re.sub(r'(?i)\s*—\s*[^—]+$', '', translated_title)  # Remove "— Site Torrent – Baixe..."
    translated_title = re.sub(r'(?i)\s*–\s*[^–]+$', '', translated_title)  # Remove "– Baixe Filmes..."
    translated_title = re.sub(r'(?i)\s*Baixe\s+Filmes\s+e\s+S[ée]ries\s*', '', translated_title)
    
    # Remove caracteres especiais do final
    translated_title = translated_title.rstrip(' .,:;—–-')
    
    # Normaliza espaços
    translated_title = re.sub(r'\s+', ' ', translated_title).strip()
    
    return translated_title


# Busca o nome do torrent via metadata API quando falta display_name no magnet
def get_release_title_from_redis(info_hash: str) -> Optional[str]:
    """
    Busca release_title_magnet no Redis por info_hash.
    Retorna o release_title_magnet se encontrado, None caso contrário.
    """
    if not info_hash or len(info_hash) != 40:
        return None
    
    try:
        from cache.redis_client import get_redis_client
        from cache.redis_keys import release_title_key
        
        redis = get_redis_client()
        if not redis:
            return None
        
        key = release_title_key(info_hash)
        cached = redis.get(key)
        if cached:
            release_title = cached.decode('utf-8').strip()
            if release_title and len(release_title) >= 3:
                logger.debug(f"[REDIS RELEASE_TITLE] Encontrado para {info_hash[:16]}...: {release_title[:50]}")
                return release_title
    except Exception as e:
        logger.debug(f"[REDIS RELEASE_TITLE] Erro ao buscar: {e}")
    
    return None


def save_release_title_to_redis(info_hash: str, release_title: str) -> None:
    """
    Salva release_title_magnet no Redis por info_hash.
    """
    if not info_hash or len(info_hash) != 40:
        return
    
    if not release_title or len(release_title.strip()) < 3:
        return
    
    try:
        from cache.redis_client import get_redis_client
        from cache.redis_keys import release_title_key
        
        redis = get_redis_client()
        if not redis:
            return
        
        key = release_title_key(info_hash)
        # Salva por 7 dias (mesmo TTL do metadata)
        redis.setex(key, 7 * 24 * 3600, release_title.strip())
        logger.debug(f"[REDIS RELEASE_TITLE] Salvo para {info_hash[:16]}...: {release_title[:50]}")
    except Exception as e:
        logger.debug(f"[REDIS RELEASE_TITLE] Erro ao salvar: {e}")


def get_metadata_name(info_hash: str, skip_metadata: bool = False) -> Optional[str]:
    if skip_metadata:
        return None
    
    # Primeiro tenta buscar do cross_data (evita consulta desnecessária ao metadata)
    try:
        from utils.text.cross_data import get_cross_data_from_redis
        cross_data = get_cross_data_from_redis(info_hash)
        if cross_data and cross_data.get('release_title_magnet'):
            release_title = cross_data.get('release_title_magnet')
            if release_title and release_title != 'N/A' and len(str(release_title).strip()) >= 3:
                return str(release_title).strip()
    except Exception:
        pass
    
    # Se não encontrou no cross_data, busca do metadata
    try:
        from magnet.metadata import fetch_metadata_from_itorrents
        metadata = fetch_metadata_from_itorrents(info_hash)
        if metadata and metadata.get('name'):
            name = metadata.get('name', '').strip()
            if name and len(name) >= 3:
                return name
    except Exception:
        pass
    
    return None


# Normaliza o título original do release antes de gerar o padrão final
def prepare_release_title(
    release_title_magnet: str,
    fallback_title: str,
    year: str = '',
    missing_dn: bool = False,
    info_hash: Optional[str] = None,
    skip_metadata: bool = False
) -> str:
    fallback_title = (fallback_title or '').strip()

    normalized = (release_title_magnet or '').strip()
    if normalized:
        normalized = html.unescape(normalized)
        try:
            normalized = unquote(normalized)
        except Exception:
            pass
        normalized = normalized.strip()
        
        # Remove duplicações consecutivas do release_title_magnet antes de processar
        # Ex: "S01E04.S01E04.2025..." -> "S01E04.2025..."
        # Normaliza espaços para pontos para facilitar detecção de duplicações
        temp_normalized = re.sub(r'\s+', '.', normalized.strip())
        temp_normalized = re.sub(r'\.{2,}', '.', temp_normalized)
        
        # Remove duplicações consecutivas de qualquer parte
        parts = temp_normalized.split('.')
        cleaned_parts = []
        prev_part = None
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Compara ignorando case e normalizando
            part_lower = part.lower()
            prev_lower = prev_part.lower() if prev_part else None
            # Só adiciona se não for duplicação consecutiva
            if part_lower != prev_lower:
                cleaned_parts.append(part)
                prev_part = part
        
        normalized = '.'.join(cleaned_parts).strip('.')
        # Volta espaços para facilitar processamento posterior
        normalized = normalized.replace('.', ' ').strip()

    # FALLBACK 1: Busca release_title_magnet no Redis por info_hash (antes de buscar metadata)
    if (not normalized or len(normalized) < 3) and missing_dn and info_hash:
        redis_release_title = get_release_title_from_redis(info_hash)
        if redis_release_title:
            normalized = redis_release_title
            missing_dn = False
    
    # FALLBACK 2: Busca do metadata quando falta dn e não encontrou no Redis (apenas se não for para pular)
    if (not normalized or len(normalized) < 3) and missing_dn and info_hash and not skip_metadata:
        metadata_name = get_metadata_name(info_hash, skip_metadata=skip_metadata)
        if metadata_name:
            normalized = metadata_name
            missing_dn = False
    elif skip_metadata and (not normalized or len(normalized) < 3) and missing_dn and info_hash:
        # Em testes, não busca metadata mesmo quando falta dn
        pass
    
    # FALLBACK 3: Título da página quando metadata não disponível
    if not normalized or len(normalized) < 3:
        normalized = fallback_title
        missing_dn = True

    normalized = re.sub(r'\s+', ' ', normalized).strip()

    if year:
        year_str = str(year)
        if year_str and year_str not in normalized:
            normalized = f"{normalized} {year_str}".strip()

    if missing_dn and normalized and 'web-dl' not in normalized.lower():
        normalized = f"{normalized} WEB-DL"

    return normalized.strip()


# Constrói o título padronizado final (Title.SxxEyy.Year….)
def create_standardized_title(original_title_html: str, year: str, release_title_magnet: str, translated_title_html: Optional[str] = None, raw_release_title_magnet: Optional[str] = None) -> str:
    def finalize_title(value: str) -> str:
        value = _apply_season_temporada_tags(value, release_title_magnet, original_title_html, year)
        value = _reorder_title_components(value)
        return _ensure_default_format(value)
    # Determina base_title seguindo fallback
    base_title = ''
    
    # Verifica se tem título original válido
    if original_title_html and original_title_html.strip():
        # Verifica se tem caracteres não-latinos (Russo, Chinês, Coreano, Japonês, Tailandês, Hindi/Devanagari, Árabe, Hebreu, Grego)
        has_non_latin = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f\u0900-\u097f\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff]', original_title_html))
        
        if not has_non_latin:
            # Título Original da página: Como base principal (apenas o nome, sem SxxExx, ano, etc.)
            base_title = clean_title(original_title_html)
            base_title = remove_accents(base_title)
            # Remove informações de temporada/ano do título da página
            # IMPORTANTE: Só remove se for claramente temporada (S01, S1, S01E01) ou ano no final
            # NÃO remove números que fazem parte do título (ex: "Fantastic 4", "Ocean's 11")
            base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)  # Remove SxxExx se houver
            base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)  # Remove ano no final
            base_title = base_title.replace(' ', '.').replace('-', '.')  # Converte espaços e hífens para pontos
            base_title = re.sub(r'[^\w\.]', '', base_title)  # Remove tudo exceto letras, números e pontos
            base_title = base_title.strip('.')
            
            # Continua processando release_title_magnet para extrair SxxExx, ano e informações técnicas
            # Não retorna direto, sempre processa o release_title_magnet
        else:
            # Fallback1: Title Não-latinos Ex:Russo/Koreano
            # Verifica se release_title_magnet (raw) também tem caracteres não-latinos
            # Usa raw_release_title_magnet se disponível, senão usa release_title_magnet
            raw_to_check = raw_release_title_magnet if raw_release_title_magnet else release_title_magnet
            release_has_non_latin = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f\u0900-\u097f\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff]', raw_to_check or ''))
            
            # Se translated_title_html existe, usa ele (é preferível ao release_title_magnet quando original tem não-latinos)
            if translated_title_html and translated_title_html.strip():
                # Fallback1.1: Título Traduzido da página quando original_title_html tem não-latinos
                # Usa translated_title_html mesmo se release_title_magnet não tem não-latinos
                base_title = clean_title(translated_title_html)
                base_title = remove_accents(base_title)
                # Remove informações de temporada/ano do título traduzido (apenas o nome base)
                base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)  # Remove SxxExx se houver
                base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)  # Remove ano no final
                base_title = base_title.replace(' ', '.').replace('-', '.')  # Converte espaços e hífens para pontos
                base_title = re.sub(r'[^\w\.]', '', base_title)  # Remove tudo exceto letras, números e pontos
                base_title = base_title.strip('.')
                # Continua processando release_title_magnet para extrair SxxExx, ano e informações técnicas
            else:
                # Fallback1: Usar title do magnet (release_title_magnet) - extrai apenas o nome base
                base_title = _extract_base_title_from_release(release_title_magnet)
                # Continua processando release_title_magnet para extrair SxxExx, ano e informações técnicas
    else:
        # Fallback2: Nome do magnet se página não tem título válido
        base_title = _extract_base_title_from_release(release_title_magnet)
        return finalize_title(base_title)
    
    # Processa release_title_magnet para extrair apenas informações técnicas (SxxExx, Sx, ano, qualidade, codec, etc.)
    clean_release = clean_title(release_title_magnet)
    clean_release = remove_accents(clean_release)
    
    # Remove o base_title do clean_release antes de processar (evita duplicação)
    # Normaliza ambos removendo pontos e espaços para comparação
    base_title_normalized = re.sub(r'[\.\s]', '', base_title).lower()
    clean_release_normalized = re.sub(r'[\.\s]', '', clean_release).lower()
    
    # Se o base_title está no início do clean_release, remove
    if clean_release_normalized.startswith(base_title_normalized):
        # Encontra onde o base_title termina no clean_release original (considerando pontos)
        # Procura o padrão do base_title no início do clean_release, aceitando pontos opcionais
        base_no_dots = base_title.replace('.', '')
        # Cria padrão que aceita pontos opcionais entre letras do base_title
        # Ex: "One Punch-Man" pode corresponder a "One.Punch.Man" ou "OnePunchMan"
        if len(base_no_dots) > 0:
            base_pattern = re.escape(base_no_dots[0])  # Primeira letra (obrigatória)
            for char in base_no_dots[1:]:
                base_pattern += rf'\.?{re.escape(char)}'  # Letras seguintes com ponto opcional
            
            # Remove base_title do início (seguido de ponto, SxxExx, número, ou fim)
            # Também remove se estiver colado a SxxExx ou números (ex: "OnePunchManS03E01")
            # IMPORTANTE: Remove o base_title e qualquer ponto que o segue, mas preserva o que vem depois
            # Ex: "One.Punch.Man.S03E01" -> "S03E01"
            # Ex: "OnePunchManS03E01" -> "S03E01"
            clean_release = re.sub(rf'^{base_pattern}(?:\.|(?=S\d)|(?=\d)|$)', '', clean_release, flags=re.IGNORECASE)
        
        # Limpa pontos duplicados que podem ter ficado
        clean_release = re.sub(r'^\.+', '', clean_release)
    
    # Remove duplicações consecutivas do clean_release antes de processar
    # Ex: "S01E04.S01E04.2025..." -> "S01E04.2025..."
    # Normaliza espaços para pontos para facilitar detecção de duplicações
    temp_clean = re.sub(r'\s+', '.', clean_release.strip())
    temp_clean = re.sub(r'\.{2,}', '.', temp_clean)
    
    # Remove duplicações consecutivas de qualquer parte
    parts = temp_clean.split('.')
    cleaned_parts = []
    prev_part = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Compara ignorando case e normalizando
        part_lower = part.lower()
        prev_lower = prev_part.lower() if prev_part else None
        # Só adiciona se não for duplicação consecutiva
        if part_lower != prev_lower:
            cleaned_parts.append(part)
            prev_part = part
    
    clean_release = '.'.join(cleaned_parts).strip('.')
    
    # EPISÓDIOS MÚLTIPLOS: Formato Sonarr compatível - detecta antes de normalizar espaços
    # Regex para detectar múltiplos episódios: S02E01-02-03, S02E01-02, S02E01.02.03, etc.
    # Padrão Sonarr:
    # - 2 episódios: S02E01-02 (hífen)
    # - 3+ episódios: S02E01E02E03 (E repetido - lista explícita) ou S02E01-E05 (intervalo)
    # Busca padrão completo: S02E01-02-03 ou S02E01.02.03
    # Usa lookahead negativo para garantir que não capture ano (2025)
    season_ep_multi_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:\s*[\.\-]\s*\d{1,2}){1,}(?![0-9])', clean_release)
    
    if not season_ep_multi_match:
        # Tenta padrão alternativo sem espaços
        alt_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:[\.\-]\d{1,2}){1,}(?![0-9])', clean_release)
        if alt_match:
            season_ep_multi_match = alt_match
    
    if season_ep_multi_match:
        season = season_ep_multi_match.group(1).zfill(2)
        episode1 = int(season_ep_multi_match.group(2))
        
        # Extrai todos os episódios do match completo
        full_match = season_ep_multi_match.group(0)
        episodes = [episode1]
        
        # Extrai todos os números após o primeiro episódio (E01)
        # Busca por padrão: -02, -03, .02, .03, etc. (sem espaços após normalização)
        episode_numbers = re.findall(r'[\.\-]\s*(\d{1,2})', full_match)
        
        for ep_str in episode_numbers:
            ep_num = int(ep_str)
            # Validação: cada episódio deve ser maior que o anterior, <= 99, e diferença <= 20
            if ep_num > episodes[-1] and ep_num <= 99 and (ep_num - episodes[-1]) <= 20:
                episodes.append(ep_num)
            else:
                break  # Para se encontrar número inválido
        
        # Se tem pelo menos 2 episódios válidos, formata como múltiplos
        if len(episodes) >= 2:
            # Novo padrão Sonarr:
            # - 2 episódios: S02E01-02 (mantém hífen)
            # - 3-4 episódios: S02E01E02E03 (E repetido - lista explícita)
            # - 5+ episódios: S02E01-E05 (intervalo - primeiro-último)
            if len(episodes) == 2:
                # Duplos: mantém formato com hífen
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            elif len(episodes) >= 5:
                # 5+ episódios: usa formato de intervalo (primeiro-último)
                first_ep = str(episodes[0]).zfill(2)
                last_ep = str(episodes[-1]).zfill(2)
                season_ep_str = f"S{season}E{first_ep}-E{last_ep}"
            elif len(episodes) >= 3:
                # 3-4 episódios: usa E repetido para lista explícita
                episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            else:
                # Fallback (não deveria acontecer)
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            
            # Normaliza espaços para pontos no restante (após SxxExxExx...)
            original_magnet_text = clean_release[season_ep_multi_match.end():]
            original_magnet_text = re.sub(r'\s+', '.', original_magnet_text)
            original_magnet_text = re.sub(r'\.{2,}', '.', original_magnet_text)
            original_magnet_text = original_magnet_text.strip('.')
            # Separa componentes colados antes de extrair informações técnicas
            original_magnet_text = _split_technical_components(original_magnet_text)
            
            processed_magnet_text = _extract_technical_info(original_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            result = finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
            
            return result
    
    # Normaliza espaços para pontos para facilitar processamento
    clean_release = re.sub(r'\s+', '.', clean_release)
    clean_release = re.sub(r'\.{2,}', '.', clean_release)
    clean_release = clean_release.strip('.')
    
    # Separa componentes técnicos colados antes de processar
    clean_release = _split_technical_components(clean_release)
    
    # EPISÓDIOS MÚLTIPLOS: detecta após normalizar também
    # Regex para detectar múltiplos episódios após normalização
    season_ep_multi_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:[\.\-]\d{1,2}){1,}(?![0-9])', clean_release)
    
    if season_ep_multi_match:
        season = season_ep_multi_match.group(1).zfill(2)
        episode1 = int(season_ep_multi_match.group(2))
        
        # Extrai todos os episódios do match completo
        full_match = season_ep_multi_match.group(0)
        episodes = [episode1]
        
        # Extrai todos os números após o primeiro episódio (E01)
        # Busca por padrão: -02, -03, .02, .03, etc.
        episode_numbers = re.findall(r'[\.\-](\d{1,2})', full_match)
        for ep_str in episode_numbers:
            ep_num = int(ep_str)
            # Validação: cada episódio deve ser maior que o anterior, <= 99, e diferença <= 20
            if ep_num > episodes[-1] and ep_num <= 99 and (ep_num - episodes[-1]) <= 20:
                episodes.append(ep_num)
            else:
                break  # Para se encontrar número inválido
        
        # Se tem pelo menos 2 episódios válidos, formata como múltiplos
        if len(episodes) >= 2:
            # Novo padrão Sonarr:
            # - 2 episódios: S02E01-02 (mantém hífen)
            # - 3-4 episódios: S02E01E02E03 (E repetido - lista explícita)
            # - 5+ episódios: S02E01-E05 (intervalo - primeiro-último)
            if len(episodes) == 2:
                # Duplos: mantém formato com hífen
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            elif len(episodes) >= 5:
                # 5+ episódios: usa formato de intervalo (primeiro-último)
                first_ep = str(episodes[0]).zfill(2)
                last_ep = str(episodes[-1]).zfill(2)
                season_ep_str = f"S{season}E{first_ep}-E{last_ep}"
            elif len(episodes) >= 3:
                # 3-4 episódios: usa E repetido para lista explícita
                episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            else:
                # Fallback (não deveria acontecer)
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            
            # Extrai apenas informações técnicas do restante (após SxxExxExx...)
            original_magnet_text = clean_release[season_ep_multi_match.end():]
            # Separa componentes colados antes de extrair informações técnicas
            original_magnet_text = _split_technical_components(original_magnet_text)
            processed_magnet_text = _extract_technical_info(original_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            result = finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
            
            return result
    
    # EPISÓDIOS: Title.S02E01.restodomagnet (2 dígitos) - detecta ANTES de filtrar
    season_ep_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})', clean_release)
    
    if season_ep_match:
        season = season_ep_match.group(1).zfill(2)  # 2 dígitos
        episode = season_ep_match.group(2).zfill(2)  # 2 dígitos
        season_ep_str = f"S{season}E{episode}"
        
        # Extrai apenas informações técnicas do restante (após SxxExx)
        original_magnet_text = clean_release[season_ep_match.end():]
        # Separa componentes colados antes de extrair informações técnicas
        original_magnet_text = _split_technical_components(original_magnet_text)
        processed_magnet_text = _extract_technical_info(original_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        return finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
    
    # Extrai apenas informações técnicas do release_title_magnet, removendo qualquer título
    # Padrões técnicos: Sx, anos, qualidades, codecs, etc.
    technical_parts = []
    parts = clean_release.split('.')
    
    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue
        
        # Mantém apenas:
        # - Padrões de temporada: S01 (sem E)
        if re.match(r'^S\d{1,2}$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Anos: 2025, 2024, etc.
        elif re.match(r'^(19|20)\d{2}$', part_clean):
            technical_parts.append(part_clean)
        # - Qualidades: 1080p, 720p, 2160p, 4K, HD, FHD, UHD, etc.
        elif re.match(r'^(1080p|720p|480p|2160p|4K|HD|FHD|UHD|SD|HDR)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Codecs: x264, x265, H.264, H.265, etc.
        elif re.match(r'^(x264|x265|H\.264|H\.265|AVC|HEVC)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Fontes: WEB-DL, WEBRip, BluRay, DVDRip, HDRip, HDTV, BDRip, BRRip, etc.
        elif re.match(r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Áudio: DUAL, DUBLADO, DDP5.1, Atmos, AC3, AAC, etc.
        elif re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Outros técnicos: HDR, 5.1, 2.0, etc.
        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Formatos: MKV, MP4, AVI, etc.
        elif re.match(r'^(MKV|MP4|AVI|MPEG|MOV)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Padrões com hífen: 5.1-SF, etc. (número.ponto.número-hífen-letras/números)
        elif re.match(r'^\d+\.\d+-[A-Z0-9]+$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Release groups: -SF, -RARBG, etc. (começam com -)
        elif re.match(r'^-[A-Z0-9]+$', part_clean):
            technical_parts.append(part_clean)
        # - Números seguidos de GB/MB (tamanhos)
        elif re.match(r'^\d+\.?\d*\s*(GB|MB)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
    
    clean_release = '.'.join(technical_parts)
    
    # SÉRIES COMPLETAS: Title.S2.2022.restodomagnet (1 dígito para temporada)
    season_only_match = re.search(r'(?i)S(\d{1,2})(?:[^E]|$)', clean_release)
    if season_only_match:
        season = season_only_match.group(1).zfill(2)
        season_str = f"S{season}"
        
        # Procura ano no release ou usa year do parâmetro
        year_from_release = year
        if not year_from_release:
            year_match = re.search(r'(19|20)\d{2}', clean_release)
            if year_match:
                year_from_release = year_match.group(0)
        
        if year_from_release:
            processed_magnet_text = clean_release[season_only_match.end():]
            # Remove ano do processed_magnet_text se já foi usado
            processed_magnet_text = re.sub(r'(19|20)\d{2}', '', processed_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            return finalize_title(f"{base_title}.{season_str}.{year_from_release}{processed_magnet_text}")
        else:
            # Sem ano, apenas Sx
            processed_magnet_text = clean_release[season_only_match.end():]
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            return finalize_title(f"{base_title}.{season_str}{processed_magnet_text}")
    
    # FILMES: Title.2022.restodomagnet
    year_from_release = year
    if not year_from_release:
        year_match = re.search(r'(19|20)\d{2}', clean_release)
        if year_match:
            year_from_release = year_match.group(0)
    
    if year_from_release:
        # Remove ano do clean_release para pegar o resto (informações técnicas)
        processed_magnet_text = re.sub(r'(19|20)\d{2}', '', clean_release)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        return finalize_title(f"{base_title}.{year_from_release}{processed_magnet_text}")
    
    # Sem ano nem temporada, retorna apenas base_title com informações técnicas se houver
    if clean_release:
        processed_magnet_text = _clean_remaining(clean_release)
        return finalize_title(f"{base_title}{processed_magnet_text}")
    
    return finalize_title(base_title)


# Extrai o núcleo do título removendo informações técnicas redundantes
def _extract_base_title_from_release(release_title_magnet: str) -> str:
    clean_release = clean_title(release_title_magnet)
    clean_release = remove_accents(clean_release)
    
    # Remove anos do início
    clean_release = re.sub(r'^(19|20)\d{2}\.', '', clean_release)
    
    # Remove informações técnicas comuns do início
    tech_patterns = [
        r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip)\.',
        r'^(1080p|720p|480p|2160p|4K)\.',
        r'^(x264|x265|H\.264|H\.265)\.',
    ]
    for pattern in tech_patterns:
        clean_release = re.sub(pattern, '', clean_release, flags=re.IGNORECASE)
    
    # IMPORTANTE: Preserva pontos existentes no título original
    # Se o título já tem pontos (ex: "One.Punch.Man"), mantém os pontos
    # Se o título tem espaços (ex: "One Punch Man"), converte espaços para pontos
    
    # Primeiro, normaliza espaços para pontos (mas preserva pontos existentes)
    # Se já tem pontos, apenas normaliza espaços ao redor dos pontos
    # Se não tem pontos, converte espaços para pontos
    if '.' in clean_release:
        # Já tem pontos, apenas normaliza espaços ao redor dos pontos
        clean_release = re.sub(r'\s*\.\s*', '.', clean_release)
        clean_release = re.sub(r'\s+', '.', clean_release)  # Converte espaços restantes para pontos
    else:
        # Não tem pontos, converte espaços para pontos
        clean_release = re.sub(r'\s+', '.', clean_release)
    
    # Limpa pontos duplicados
    clean_release = re.sub(r'\.{2,}', '.', clean_release)
    
    # Separa SxxExx colado ao título (ex: "OnePunchManS03E05" -> "OnePunchMan" e "S03E05")
    # Mas preserva pontos existentes (ex: "One.Punch.Man.S03E05" já está correto, não precisa separar)
    # Só separa se não houver ponto antes do SxxExx
    # Usa [A-Za-z0-9] para capturar números também (ex: "OnePunchMan1" -> "OnePunchMan" e "1")
    clean_release = re.sub(r'(?i)([A-Za-z0-9]+)(?<!\.)(S\d{1,2}(?:E\d{1,2})?)', r'\1.\2', clean_release)
    
    # Pega a primeira parte significativa (até encontrar ano ou informação técnica)
    parts = clean_release.split('.')
    base_parts = []
    for part in parts:
        # Para se encontrar SxxExx (já separado)
        if re.match(r'^S\d{1,2}(?:E\d{1,2})?$', part, re.IGNORECASE):
            break
        # Para se encontrar ano
        if re.match(r'^(19|20)\d{2}$', part):
            break
        # Para se encontrar informação técnica comum
        if re.match(r'^(WEB-DL|WEBRip|BluRay|1080p|720p|2160p|x264|x265|DUAL|DUBLADO|HDR)', part, re.IGNORECASE):
            break
        if part and len(part) > 1:
            base_parts.append(part)
    
    base_title = '.'.join(base_parts)
    base_title = base_title.replace('-', '.')  # Converte hífens para pontos
    base_title = re.sub(r'[^\w\.]', '', base_title)  # Remove tudo exceto letras, números e pontos
    base_title = base_title.strip('.')
    
    return base_title


# Separa componentes técnicos colados (ex: "WEB-DL1080px264" -> "WEB-DL.1080p.x264")
def _split_technical_components(text: str) -> str:
    if not text:
        return text
    
    # Se já tem pontos suficientes, verifica se precisa processar
    if '.' in text:
        parts = text.split('.')
        # Se já tem mais de 2 partes separadas, provavelmente já está bem formatado
        if len(parts) >= 3:
            # Verifica se alguma parte tem componentes colados
            has_colados = any(
                re.search(r'(WEB-DL|WEBRip|1080p|720p|x264|x265|LEGENDADO|DUAL)', part, re.IGNORECASE) 
                and len(part) > 10  # Partes muito longas provavelmente têm componentes colados
                for part in parts
            )
            if not has_colados:
                return text
    
    result = text
    
    # Padrões técnicos conhecidos (em ordem de prioridade - mais específicos primeiro)
    # Usa lookbehind/lookahead negativo para evitar adicionar pontos onde já existem
    patterns = [
        # Fontes (devem vir antes de qualidades para evitar conflito com "WEB")
        (r'(?<!\.)(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)(?!\.)', r'.\1.', re.IGNORECASE),
        # Qualidades (deve vir depois de fontes para evitar conflito)
        (r'(?<!\.)(2160p|1080p|720p|480p|4K|UHD|FHD|HD|SD|HDR)(?!\.)', r'.\1.', re.IGNORECASE),
        # Codecs
        (r'(?<!\.)(x264|x265|H\.264|H\.265|AVC|HEVC)(?!\.)', r'.\1.', re.IGNORECASE),
        # Áudio
        (r'(?<!\.)(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado|DTS-HD|TrueHD)(?!\.)', r'.\1.', re.IGNORECASE),
        # Formatos
        (r'(?<!\.)(MKV|MP4|AVI|MPEG|MOV)(?!\.)', r'.\1.', re.IGNORECASE),
        # Anos (deve vir antes de números decimais para evitar conflito)
        (r'(?<!\.)((19|20)\d{2})(?!\.)', r'.\1.', re.IGNORECASE),
        # Áudio específico (5.1, 2.0, 7.1) - cuidado para não quebrar anos
        (r'(?<!\.)(\d+\.\d+)(?!\.)(?!\d)', r'.\1.', re.IGNORECASE),
    ]
    
    # Aplica cada padrão para separar componentes colados
    for pattern, replacement, flags in patterns:
        result = re.sub(pattern, replacement, result, flags=flags)
    
    # Limpa pontos duplicados e normaliza
    result = re.sub(r'\.{2,}', '.', result)
    result = result.strip('.')
    
    return result


# Mantém apenas informações técnicas relevantes (qualidade, codec, etc.)
def _extract_technical_info(text: str) -> str:
    if not text:
        return ''
    
    # Normaliza espaços para pontos
    text = re.sub(r'\s+', '.', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = text.strip('.')
    
    if not text:
        return ''
    
    # Separa componentes técnicos colados antes de processar
    text = _split_technical_components(text)
    
    technical_parts = []
    parts = text.split('.')
    
    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue
        
        # Mantém apenas informações técnicas (mesmos padrões da função principal)
        if re.match(r'^S\d{1,2}$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(19|20)\d{2}$', part_clean):
            technical_parts.append(part_clean)
        elif re.match(r'^(1080p|720p|480p|2160p|4K|HD|FHD|UHD|SD|HDR)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(x264|x265|H\.264|H\.265|AVC|HEVC)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(MKV|MP4|AVI|MPEG|MOV)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^\d+\.\d+-[A-Z0-9]+$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^-[A-Z0-9]+$', part_clean):
            technical_parts.append(part_clean)
        elif re.match(r'^\d+\.?\d*\s*(GB|MB)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
    
    return '.'.join(technical_parts)


# Ajusta a parte restante do título, evitando pontos repetidos e vazios
def _clean_remaining(processed_magnet_text: str) -> str:
    if not processed_magnet_text:
        return ''
    
    processed_magnet_text = processed_magnet_text.strip('.')
    if not processed_magnet_text:
        return ''
    
    # Remove pontos duplicados
    processed_magnet_text = re.sub(r'\.{2,}', '.', processed_magnet_text)
    
    if processed_magnet_text and not processed_magnet_text.startswith('.'):
        processed_magnet_text = '.' + processed_magnet_text
    
    return processed_magnet_text


# Garante que o título tenha ao menos uma tag de formato (Web-DL, etc.)
def _ensure_default_format(title: str) -> str:
    if not title:
        return title
    normalized = title.lower()
    if re.search(r'(?i)(web[-\.\s]?dl|webrip|bluray|bdrip|hdrip|hdtv|dvdrip|2160p|1080p|720p|480p|4k|camrip|cam|tsrip|ts|uhd|hdr)', normalized):
        return title
    if title.endswith('.'):
        return f"{title}WEB-DL"
    return f"{title}.WEB-DL"


# Força inclusão de tags de temporada encontradas na descrição original
def _apply_season_temporada_tags(title: str, release_title_magnet: str, original_title_html: str, year: str) -> str:
    if not title:
        return title
    
    context_parts = []
    if release_title_magnet:
        context_parts.append(release_title_magnet)
    if original_title_html:
        context_parts.append(original_title_html)
    if not context_parts:
        return title
    
    release_clean = remove_accents(' '.join(context_parts).lower())
    release_clean = release_clean.replace('ª', 'a').replace('º', 'o')
    if 'temporada' not in release_clean:
        return title
    
    result = title
    season_match = re.search(r'(\d+)\s*(?:a)?\s*temporada', release_clean)
    if not season_match:
        season_match = re.search(r'temporada\s*(?:-|:)?\s*(\d+)', release_clean)
    year_str = str(year) if year else ''
    if season_match:
        season_number_raw = season_match.group(1)
        season_number = season_number_raw.zfill(2)
        has_season_info = re.search(rf'(?i)S0*{season_number_raw}(?:E\d+(?:-\d+)?|$)', result)
        has_any_season_ep = re.search(r'(?i)S\d{1,2}E\d{1,2}', result)
        year_in_title = year_str and year_str in result
        if not has_season_info and not has_any_season_ep:
            if year_in_title:
                result = result.replace(f".{year_str}", '')
                result = f"{result}.S{season_number}.{year_str}"
            else:
                result = f"{result}.S{season_number}"
        elif not year_in_title and year_str:
            result = f"{result}.{year_str}"

        # Remove termos redundantes de temporada do título
        result = re.sub(r'(?i)\.?\b\d+\s*(?:a)?\s*temporada\b', '', result)
        result = re.sub(r'(?i)\.?temporada\b', '', result)
        result = re.sub(r'\.{2,}', '.', result)
        result = result.strip('.')
    elif year_str and year_str not in result:
        result = f"{result}.{year_str}"
    
    return result


# Reorganiza os componentes do título para manter ordem consistente
def _reorder_title_components(title: str) -> str:
    if not title:
        return title
    
    # Separa componentes técnicos colados antes de processar
    title = _split_technical_components(title)
    
    parts = [part for part in title.split('.') if part]
    if not parts:
        return title
    
    season_episode = None
    season_only = None
    year = None
    base_parts: List[str] = []
    quality_parts: List[str] = []  # Qualidade: 1080p, 720p, etc.
    source_parts: List[str] = []  # Fonte: WEB-DL, WEBRip, BluRay, etc.
    codec_parts: List[str] = []  # Codec: x264, x265, etc.
    audio_parts: List[str] = []  # Áudio: DUAL, DUBLADO, etc.
    other_parts: List[str] = []  # Outros: HDR, 5.1, release groups, etc.
    structure_started = False
    
    quality_tokens = {
        '1080P', '720P', '480P', '2160P', '4K', 'HD', 'FHD', 'UHD', 'SD', 'HDR'
    }
    source_tokens = {
        'WEB-DL', 'WEBRIP', 'BLURAY', 'DVDRIP', 'HDRIP', 'HDTV', 'BDRIP',
        'BRRIP', 'CAMRIP', 'CAM', 'TSRIP', 'TS', 'TC', 'R5', 'SCR', 'DVDSCR'
    }
    codec_tokens = {
        'X264', 'X265', 'H.264', 'H.265', 'AVC', 'HEVC'
    }
    audio_tokens = {
        'DUAL', 'DUBLADO', 'DDP5.1', 'ATMOS', 'AC3', 'AAC', 'MP3', 'FLAC', 'DTS', 'NACIONAL', 'LEGENDADO'
    }
    
    for part in parts:
        clean_part = part.strip()
        if not clean_part:
            continue
        
        # Verifica episódios múltiplos primeiro: S02E05-06, S02E05E06E07, S02E01-E05, etc.
        # Suporta formatos: S02E01-02 (duplo), S02E01E02E03 (lista explícita), S02E01-E05 (intervalo)
        match_episode_multi = re.match(r'^S(\d{1,2})E(\d{1,2})(?:[\.\-E](\d{1,2}))+$', clean_part, re.IGNORECASE)
        if match_episode_multi:
            season = match_episode_multi.group(1).zfill(2)
            episode1 = int(match_episode_multi.group(2))
            episodes = [episode1]
            
            # Extrai todos os números após o primeiro episódio (suporta hífen, ponto e E)
            episode_numbers = re.findall(r'[\.\-E](\d{1,2})', clean_part)
            for ep_str in episode_numbers:
                ep_num = int(ep_str)
                if ep_num > episodes[-1] and ep_num <= 99 and (ep_num - episodes[-1]) <= 20:
                    episodes.append(ep_num)
                else:
                    break
            
            # Se tem pelo menos 2 episódios válidos, formata como múltiplos
            if len(episodes) >= 2:
                # Novo padrão Sonarr:
                # - 2 episódios: S02E01-02 (mantém hífen)
                # - 3-4 episódios: S02E01E02E03 (E repetido - lista explícita)
                # - 5+ episódios: S02E01-E05 (intervalo - primeiro-último)
                if len(episodes) == 2:
                    episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                elif len(episodes) >= 5:
                    # 5+ episódios: usa formato de intervalo (primeiro-último)
                    first_ep = str(episodes[0]).zfill(2)
                    last_ep = str(episodes[-1]).zfill(2)
                    season_episode = f"S{season}E{first_ep}-E{last_ep}"
                elif len(episodes) >= 3:
                    # 3-4 episódios: usa E repetido para lista explícita
                    episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                else:
                    episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                structure_started = True
                continue
        
        match_episode = re.match(r'^S(\d{1,2})E(\d{1,2})$', clean_part, re.IGNORECASE)
        if match_episode:
            season_episode = f"S{match_episode.group(1).zfill(2)}E{match_episode.group(2).zfill(2)}"
            structure_started = True
            continue
        
        match_season = re.match(r'^S(\d{1,2})$', clean_part, re.IGNORECASE)
        if match_season:
            season_only = f"S{match_season.group(1).zfill(2)}"
            structure_started = True
            continue
        
        if re.match(r'^(19|20)\d{2}$', clean_part):
            if not year:
                year = clean_part
            structure_started = True
            continue
        
        upper_part = clean_part.upper()
        
        # Classifica componentes técnicos na ordem correta
        if upper_part in quality_tokens:
            # Qualidade: 1080p, 720p, etc. (normaliza para minúsculas)
            normalized_quality = clean_part.lower()
            if normalized_quality not in [q.lower() for q in quality_parts]:
                quality_parts.append(clean_part)
            structure_started = True
            continue
        elif upper_part in source_tokens:
            # Fonte: WEB-DL, WEBRip, BluRay, etc. (normaliza WEB-DL)
            normalized_source = 'WEB-DL' if upper_part == 'WEB-DL' else clean_part
            if normalized_source not in source_parts:
                source_parts.append(normalized_source)
            structure_started = True
            continue
        elif upper_part in codec_tokens or re.match(r'^(x264|x265|H\.264|H\.265|AVC|HEVC)$', clean_part, re.IGNORECASE):
            # Codec: x264, x265, etc. (normaliza para minúsculas)
            normalized_codec = clean_part.lower()
            if normalized_codec not in [c.lower() for c in codec_parts]:
                codec_parts.append(clean_part)
            structure_started = True
            continue
        elif upper_part in audio_tokens or re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', clean_part, re.IGNORECASE):
            # Áudio: DUAL, DUBLADO, etc. (mantém case original)
            normalized_audio = clean_part.upper()
            if normalized_audio not in [a.upper() for a in audio_parts]:
                audio_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', clean_part, re.IGNORECASE):
            # Outros técnicos de áudio/vídeo: HDR, 5.1, 2.0, etc.
            if clean_part not in other_parts:
                other_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^\d+\.?\d*(GB|MB)$', clean_part, re.IGNORECASE):
            # Tamanho: não inclui na ordenação técnica
            structure_started = True
            continue
        
        if re.match(r'^-[A-Z0-9]+$', clean_part, re.IGNORECASE) or (re.match(r'^[A-Z0-9]+$', clean_part, re.IGNORECASE) and structure_started):
            # Release groups e outros
            if clean_part not in other_parts:
                other_parts.append(clean_part)
            structure_started = True
            continue
        
        if structure_started:
            # Outros componentes técnicos não classificados
            if clean_part not in other_parts:
                other_parts.append(clean_part)
        else:
            base_parts.append(clean_part)
    
    if not base_parts and parts:
        base_parts.append(parts[0])
    
    ordered_parts = []
    ordered_parts.extend(base_parts)
    
    if season_episode:
        ordered_parts.append(season_episode)
    elif season_only:
        ordered_parts.append(season_only)
    
    if year:
        ordered_parts.append(year)
    
    # Ordem correta dos componentes técnicos: Fonte → Qualidade → Codec → Áudio → Outros
    ordered_parts.extend(source_parts)
    ordered_parts.extend(quality_parts)
    ordered_parts.extend(codec_parts)
    ordered_parts.extend(audio_parts)
    
    # Remove duplicados dos outros componentes
    dedup_other = []
    seen = set()
    for part in other_parts:
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup_other.append(part)
    
    ordered_parts.extend(dedup_other)
    
    return '.'.join(ordered_parts)


# Procura ano em texto auxiliar ou no próprio título
def find_year_from_text(text: str, title: str) -> str:
    year_match = re.search(r'(?:Lançamento|Year):\s*.*?(\d{4})', text)
    if year_match:
        return year_match.group(1)
    
    year_match = re.search(r'\((\d{4})\)', title)
    if year_match:
        return year_match.group(1)
    
    return ''


# Captura tamanhos (GB/MB) exibidos em texto livre
def find_sizes_from_text(text: str) -> List[str]:
    sizes = re.findall(r'(\d+[\.,]?\d+)\s*(GB|MB)', text)
    return [f"{size[0]} {size[1]}" for size in sizes]


# Converte bytes em string legível (KB/MB/GB…)
def format_bytes(size: int) -> str:
    try:
        size = int(size)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    value = float(size)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.2f} {units[idx]}"


# Detecta informações de áudio a partir do HTML da página
# Retorna: 'dual', 'português', 'legendado', ou None
def detect_audio_from_html(html_content: str) -> Optional[str]:
    """
    Detecta informações de áudio a partir do conteúdo HTML.
    
    Args:
        html_content: Conteúdo HTML onde buscar informações de áudio
        
    Returns:
        'dual': Se tem português E multi-áudio/inglês
        'português': Se tem apenas português
        'legendado': Se tem apenas legendado (sem português no áudio)
        None: Se não encontrou informações de áudio
    """
    if not html_content:
        return None
    
    # Verifica se tem "Português" no áudio/idioma
    has_portugues = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*.*Português', html_content)
    has_multi = re.search(r'(?i)Multi-?Áudio|Multi-?Audio', html_content)
    has_ingles = re.search(r'(?i)Inglês|Ingles|English', html_content)
    
    # Verifica se tem "Legendado" na legenda (sem português no áudio)
    has_legenda_legendado = re.search(r'(?i)Legenda\s*:?\s*.*Legendado', html_content)
    has_legenda_ingles = re.search(r'(?i)Legenda\s*:?\s*.*(?:Inglês|Ingles|English)', html_content)
    
    # Se tem português no áudio
    if has_portugues:
        if has_multi or has_ingles:
            # Tem português E multi-áudio/inglês = DUAL
            return 'dual'
        else:
            # Apenas português
            return 'português'
    
    # Se não tem português no áudio, mas tem legendado na legenda
    if has_legenda_legendado or (has_legenda_ingles and not has_portugues):
        return 'legendado'
    
    return None


# Acrescenta tags de idioma [Brazilian], [Eng] e/ou [Leg] quando detectadas no release, metadata ou HTML
def add_audio_tag_if_needed(title: str, release_title_magnet: str, info_hash: Optional[str] = None, skip_metadata: bool = False, audio_info_from_html: Optional[str] = None) -> str:
    # Remove apenas as tags que queremos usar antes de processar
    title = title.replace('[Brazilian]', '').replace('[Eng]', '').replace('[Leg]', '')
    title = re.sub(r'\s+', ' ', title).strip()
    
    # Verifica se já tem as tags corretas no título
    has_brazilian = '[Brazilian]' in title
    has_eng = '[Eng]' in title
    has_leg = '[Leg]' in title
    
    # Tenta detectar áudio no release_title_magnet primeiro
    has_brazilian_audio = False
    has_legendado = False
    has_dual = False
    
    if release_title_magnet:
        release_lower = release_title_magnet.lower()
        # Detecta DUAL (português + inglês)
        if 'dual' in release_lower:
            has_dual = True
            has_brazilian_audio = True  # DUAL também indica português
        # Detecta português (DUBLADO, NACIONAL, PORTUGUES, PORTUGUÊS)
        elif 'dublado' in release_lower or 'nacional' in release_lower or 'portugues' in release_lower or 'português' in release_lower:
            has_brazilian_audio = True
        # Detecta legendado (LEGENDADO, LEGENDA, LEG)
        if 'legendado' in release_lower or 'legenda' in release_lower or re.search(r'\bleg\b', release_lower):
            has_legendado = True
    
    # Se não encontrou no release_title_magnet e temos info_hash, tenta buscar no cross_data primeiro (evita consulta desnecessária ao metadata)
    if info_hash and not skip_metadata:
        try:
            from utils.text.cross_data import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('release_title_magnet'):
                cross_release = cross_data.get('release_title_magnet')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    # Detecta DUAL no cross_data
                    if not has_dual and 'dual' in cross_release_lower:
                        has_dual = True
                        has_brazilian_audio = True  # DUAL também indica português
                    # Detecta português no cross_data (DUBLADO, NACIONAL, PORTUGUES, PORTUGUÊS)
                    elif not has_brazilian_audio and ('dublado' in cross_release_lower or 'nacional' in cross_release_lower or 'portugues' in cross_release_lower or 'português' in cross_release_lower):
                        has_brazilian_audio = True
                    # Detecta legendado no cross_data
                    if not has_legendado and ('legendado' in cross_release_lower or 'legenda' in cross_release_lower or re.search(r'\bleg\b', cross_release_lower)):
                        has_legendado = True
        except Exception:
            pass
        
        # Só busca no metadata se ainda não encontrou todas as informações necessárias
        if not has_dual and not has_brazilian_audio and not has_legendado:
            try:
                from magnet.metadata import fetch_metadata_from_itorrents
                metadata = fetch_metadata_from_itorrents(info_hash)
                if metadata and metadata.get('name'):
                    metadata_name = metadata.get('name', '').lower()
                    # Detecta DUAL no metadata
                    if not has_dual and 'dual' in metadata_name:
                        has_dual = True
                        has_brazilian_audio = True  # DUAL também indica português
                    # Detecta português no metadata (DUBLADO, NACIONAL, PORTUGUES, PORTUGUÊS)
                    elif not has_brazilian_audio and ('dublado' in metadata_name or 'nacional' in metadata_name or 'portugues' in metadata_name or 'português' in metadata_name):
                        has_brazilian_audio = True
                    # Detecta legendado no metadata
                    if not has_legendado and ('legendado' in metadata_name or 'legenda' in metadata_name or re.search(r'\bleg\b', metadata_name)):
                        has_legendado = True
            except Exception:
                pass
    
    # Processa detecção via HTML (audio_info_from_html)
    # [Eng] só é adicionada quando detectado via HTML como 'dual' ou quando detecta DUAL em qualquer fonte
    has_eng_from_html = False
    if audio_info_from_html == 'dual':
        has_dual = True
        has_brazilian_audio = True  # DUAL também indica português
    
    # Se detectado via HTML como 'legendado', adiciona [Leg]
    if audio_info_from_html == 'legendado':
        has_legendado = True
    
    # Se detectado via HTML como 'português', adiciona [Brazilian]
    if audio_info_from_html == 'português':
        has_brazilian_audio = True
    
    # Se detectou DUAL (via HTML, release_title ou metadata), adiciona [Eng]
    if has_dual:
        has_eng_from_html = True
    
    # Adiciona tags conforme detectado
    tags_to_add = []
    if has_brazilian_audio and not has_brazilian:
        tags_to_add.append('[Brazilian]')
    if has_eng_from_html and not has_eng:
        tags_to_add.append('[Eng]')
    if has_legendado and not has_leg:
        tags_to_add.append('[Leg]')
    
    if tags_to_add:
        title = title.rstrip()
        title = f"{title} {' '.join(tags_to_add)}"

    return title


# Confere se o resultado corresponde à busca (ignorando stop words)
def check_query_match(query: str, title: str, original_title_html: str = '', translated_title_html: str = '') -> bool:
    if not query or not query.strip():
        return True  # Query vazia, não filtra
    
    # Normaliza query: remove stop words
    query_lower = query.lower().strip()
    query_words = query_lower.split()
    
    # Remove stop words e palavras muito curtas
    clean_query_words = []
    for word in query_words:
        # Remove caracteres não-alfabéticos e não-numéricos para limpeza básica
        clean_word = re.sub(r'[^a-zA-Z0-9]', '', word)
        # Mantém palavras com pelo menos 1 caractere (aceita letras únicas como "v" em "gen v")
        # e que não sejam stop words
        if len(clean_word) >= 1 and clean_word.lower() not in STOP_WORDS:
            clean_query_words.append(clean_word.lower())
    
    if len(clean_query_words) == 0:
        return True  # Se não tem palavras válidas, retorna True (não filtra)
    
    # Combina título + título original + título traduzido para busca
    combined_title = f"{title} {original_title_html} {translated_title_html}".lower()
    # Remove pontos e normaliza espaços
    combined_title = combined_title.replace('.', ' ')
    combined_title = re.sub(r'\s+', ' ', combined_title)
    
    # Remove acentos para comparação
    combined_title = remove_accents(combined_title)
    
    # Conta quantas palavras da query estão presentes no título
    matches = 0
    for query_word in clean_query_words:
        query_word_no_accent = remove_accents(query_word)
        
        # Verifica match como palavra completa usando regex com word boundaries
        pattern = r'\b' + re.escape(query_word_no_accent) + r'\b'
        if re.search(pattern, combined_title, re.IGNORECASE):
            matches += 1
            continue

        # Trata casos de temporada: query "1" deve encontrar "S1"/"S01"
        if query_word_no_accent.isdigit():
            season_patterns = [f"s{query_word_no_accent}", f"s{query_word_no_accent.zfill(2)}"]
            if any(sp in combined_title for sp in season_patterns):
                matches += 1

         
    # Verifica se o ano corresponde (importante para filmes)
    year_in_query = None
    for word in clean_query_words:
        if word.isdigit() and len(word) == 4 and word.startswith(('19', '20')):
            year_in_query = word
            break
    
    year_in_title = False
    if year_in_query:
        # Verifica ano no título (aceita pontos ou espaços ao redor, já que pontos foram convertidos para espaços)
        year_pattern = r'\b' + re.escape(year_in_query) + r'\b'
        if re.search(year_pattern, combined_title):
            year_in_title = True
    
    # Lógica de correspondência:
    # - 1 palavra: exige que corresponda
    # - 2 palavras: exige que ambas correspondam
    # - 3+ palavras: exige que pelo menos 2 correspondam
    # - Exceção: se o ano corresponde e há pelo menos 2 matches (incluindo o ano), aceita (para casos de idiomas diferentes)
    if len(clean_query_words) == 1:
        return matches == 1
    elif len(clean_query_words) == 2:
        return matches == 2
    else:
        # Para 3+ palavras: se o ano corresponde e há pelo menos 2 matches (ano + pelo menos 1 outra palavra), aceita
        # Isso evita aceitar qualquer título apenas por ter o mesmo ano
        if year_in_title and matches >= 2:
            return True
        # Caso contrário, exige pelo menos 2 correspondências
        return matches >= 2

