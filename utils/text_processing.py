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
    'the', 'a', 'an', 'and', 'of', 'to', 'in', 'for', 'or', 'as',
    'os', 'o', 'e', 'de', 'do', 'da', 'em', 'que', 'temporada', 'season'
]

# Expressão regular para remover domínios e tags comuns em títulos
RELEASE_CLEAN_REGEX = re.compile(
    r'(?i)(COMANDO\.TO|COMANDOTORRENTS|WWW\.BLUDV\.TV|BLUDV|WWW\.COMANDOTORRENTS|'
    r'TORRENTBR|BAIXEFILMES|\[EZTVx\.to\]|\[TGx\]|\[rartv\]|\[YTS\.MX\]|'
    r'TRUFFLE|ETHEL|FLUX|GalaxyRG|WWW\.[A-Z0-9.-]+\.[A-Z]{2,}|\[ACESSE[^\]]*\])\s*-?\s*'
)


# Remove acentos e cedilha de caracteres latinos
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
        'Ç': 'C', 'Ñ': 'N'
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


# Busca o nome do torrent via metadata API quando falta display_name no magnet
def get_metadata_name(info_hash: str) -> Optional[str]:
    """
    Busca o nome do torrent via metadata API quando falta display_name no magnet.
    
    Args:
        info_hash: Info hash do torrent (hex, 40 caracteres)
        
    Returns:
        Nome do torrent se encontrado, None caso contrário
    """
    try:
        from app.config import Config
        if not Config.MAGNET_METADATA_ENABLED:
            return None
        
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
    release_title: str,
    fallback_title: str,
    year: str = '',
    missing_dn: bool = False,
    info_hash: Optional[str] = None
) -> str:
    fallback_title = (fallback_title or '').strip()

    normalized = (release_title or '').strip()
    if normalized:
        normalized = html.unescape(normalized)
        try:
            normalized = unquote(normalized)
        except Exception:
            pass
        normalized = normalized.strip()

    # FALLBACK 1: Busca do metadata quando falta dn
    if (not normalized or len(normalized) < 3) and missing_dn and info_hash:
        metadata_name = get_metadata_name(info_hash)
        if metadata_name:
            normalized = metadata_name
            missing_dn = False
    
    # FALLBACK 2: Título da página quando metadata não disponível
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
def create_standardized_title(original_title: str, year: str, release_title: str) -> str:
    def finalize_title(value: str) -> str:
        value = _apply_season_temporada_tags(value, release_title, original_title, year)
        value = _reorder_title_components(value)
        return _ensure_default_format(value)
    # Determina base_title seguindo fallback
    base_title = ''
    
    # Verifica se tem título original válido
    if original_title and original_title.strip():
        # Verifica se tem caracteres não-latinos (Russo, Chinês, Coreano, Japonês)
        has_non_latin = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff]', original_title))
        
        if not has_non_latin:
            # Título Original da página: Como base principal
            base_title = clean_title(original_title)
            base_title = remove_accents(base_title)
            # Remove informações de temporada/ano do título da página
            # IMPORTANTE: Só remove se for claramente temporada (S01, S1, S01E01) ou ano no final
            # NÃO remove números que fazem parte do título (ex: "Fantastic 4", "Ocean's 11")
            base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)  # Só remove se tiver "S" antes
            base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)  # Só remove ano no final
            base_title = base_title.replace(' ', '.')
            base_title = re.sub(r'[^\w\.\-]', '', base_title)
            base_title = base_title.strip('.')
            
            # Se já tem formato SxxExx ou SxxExx-xx no título base, retorna direto
            if re.search(r'(?i)S\d{1,2}E\d{1,2}(?:[\.\-]\d{1,2})?', base_title):
                return finalize_title(base_title)
        else:
            # Fallback1: Title Não-latinos Ex:Russo/Koreano (Usar title do magnet)
            base_title = _extract_base_title_from_release(release_title)
            return finalize_title(base_title)
    else:
        # Fallback2: Nome do magnet se página não tem título válido
        base_title = _extract_base_title_from_release(release_title)
        return finalize_title(base_title)
    
    # Processa release_title para extrair apenas informações técnicas (SxxExx, Sx, ano, qualidade, codec, etc.)
    clean_release = clean_title(release_title)
    
    # EPISÓDIOS MÚLTIPLOS: Title.S02E01-02-03.restodomagnet - detecta antes de normalizar espaços
    # Regex para detectar múltiplos episódios: S02E01-02-03, S02E01-02, S02E01.02.03, etc.
    # Padrão: S02E01-02-03, S02E01-02, S02E01.02, S02E01 - 02 - 03 (mas não S02E12.2025)
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
            episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
            season_ep_str = f"S{season}E{episode_str}"
            
            # Normaliza espaços para pontos no restante (após SxxExx-xx-xx)
            remaining_text = clean_release[season_ep_multi_match.end():]
            remaining_text = re.sub(r'\s+', '.', remaining_text)
            remaining_text = re.sub(r'\.{2,}', '.', remaining_text)
            remaining_text = remaining_text.strip('.')
            
            remaining = _extract_technical_info(remaining_text)
            remaining = _clean_remaining(remaining)
            result = finalize_title(f"{base_title}.{season_ep_str}{remaining}")
            
            return result
    
    # Normaliza espaços para pontos para facilitar processamento
    clean_release = re.sub(r'\s+', '.', clean_release)
    clean_release = re.sub(r'\.{2,}', '.', clean_release)
    clean_release = clean_release.strip('.')
    
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
            episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
            season_ep_str = f"S{season}E{episode_str}"
            
            # Extrai apenas informações técnicas do restante (após SxxExx-xx-xx)
            remaining_text = clean_release[season_ep_multi_match.end():]
            remaining = _extract_technical_info(remaining_text)
            remaining = _clean_remaining(remaining)
            result = finalize_title(f"{base_title}.{season_ep_str}{remaining}")
            
            return result
    
    # EPISÓDIOS: Title.S02E01.restodomagnet (2 dígitos) - detecta ANTES de filtrar
    season_ep_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})', clean_release)
    
    if season_ep_match:
        season = season_ep_match.group(1).zfill(2)  # 2 dígitos
        episode = season_ep_match.group(2).zfill(2)  # 2 dígitos
        season_ep_str = f"S{season}E{episode}"
        
        # Extrai apenas informações técnicas do restante (após SxxExx)
        remaining_text = clean_release[season_ep_match.end():]
        remaining = _extract_technical_info(remaining_text)
        remaining = _clean_remaining(remaining)
        return finalize_title(f"{base_title}.{season_ep_str}{remaining}")
    
    # Extrai apenas informações técnicas do release_title, removendo qualquer título
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
            remaining = clean_release[season_only_match.end():]
            # Remove ano do remaining se já foi usado
            remaining = re.sub(r'(19|20)\d{2}', '', remaining)
            remaining = _clean_remaining(remaining)
            return finalize_title(f"{base_title}.{season_str}.{year_from_release}{remaining}")
        else:
            # Sem ano, apenas Sx
            remaining = clean_release[season_only_match.end():]
            remaining = _clean_remaining(remaining)
            return finalize_title(f"{base_title}.{season_str}{remaining}")
    
    # FILMES: Title.2022.restodomagnet
    year_from_release = year
    if not year_from_release:
        year_match = re.search(r'(19|20)\d{2}', clean_release)
        if year_match:
            year_from_release = year_match.group(0)
    
    if year_from_release:
        # Remove ano do clean_release para pegar o resto (informações técnicas)
        remaining = re.sub(r'(19|20)\d{2}', '', clean_release)
        remaining = _clean_remaining(remaining)
        return finalize_title(f"{base_title}.{year_from_release}{remaining}")
    
    # Sem ano nem temporada, retorna apenas base_title com informações técnicas se houver
    if clean_release:
        remaining = _clean_remaining(clean_release)
        return finalize_title(f"{base_title}{remaining}")
    
    return finalize_title(base_title)


# Extrai o núcleo do título removendo informações técnicas redundantes
def _extract_base_title_from_release(release_title: str) -> str:
    clean_release = clean_title(release_title)
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
    
    # Pega a primeira parte significativa (até encontrar ano ou informação técnica)
    parts = clean_release.split('.')
    base_parts = []
    for part in parts:
        # Para se encontrar ano
        if re.match(r'^(19|20)\d{2}$', part):
            break
        # Para se encontrar informação técnica comum
        if re.match(r'^(WEB-DL|WEBRip|BluRay|1080p|720p|2160p|x264|x265|DUAL|DUBLADO|HDR)', part, re.IGNORECASE):
            break
        if part and len(part) > 1:
            base_parts.append(part)
    
    base_title = '.'.join(base_parts)
    base_title = re.sub(r'[^\w\.\-]', '', base_title)
    base_title = base_title.strip('.')
    
    return base_title


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
def _clean_remaining(remaining: str) -> str:
    if not remaining:
        return ''
    
    remaining = remaining.strip('.')
    if not remaining:
        return ''
    
    # Remove pontos duplicados
    remaining = re.sub(r'\.{2,}', '.', remaining)
    
    if remaining and not remaining.startswith('.'):
        remaining = '.' + remaining
    
    return remaining


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
def _apply_season_temporada_tags(title: str, release_title: str, original_title: str, year: str) -> str:
    if not title:
        return title
    
    context_parts = []
    if release_title:
        context_parts.append(release_title)
    if original_title:
        context_parts.append(original_title)
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
    
    parts = [part for part in title.split('.') if part]
    if not parts:
        return title
    
    season_episode = None
    season_only = None
    year = None
    base_parts: List[str] = []
    other_parts: List[str] = []
    structure_started = False
    
    quality_tokens = {
        'WEB-DL', 'WEBRIP', 'BLURAY', 'DVDRIP', 'HDRIP', 'HDTV', 'BDRIP',
        'BRRIP', 'CAMRIP', 'CAM', 'TSRIP', 'TS', 'TC', 'R5', 'SCR', 'DVDSCR',
        'UHD', 'FHD', 'SD', 'HDR', '4K', '2160P', '1080P', '720P', '480P'
    }
    
    for part in parts:
        clean_part = part.strip()
        if not clean_part:
            continue
        
        # Verifica episódios múltiplos primeiro: S02E05-06, S02E05-06-07, etc.
        match_episode_multi = re.match(r'(?i)^S(\d{1,2})E(\d{1,2})(?:[\.\-](\d{1,2}))+$', clean_part)
        if match_episode_multi:
            season = match_episode_multi.group(1).zfill(2)
            episode1 = int(match_episode_multi.group(2))
            episodes = [episode1]
            
            # Extrai todos os números após o primeiro episódio
            episode_numbers = re.findall(r'[\.\-](\d{1,2})', clean_part)
            for ep_str in episode_numbers:
                ep_num = int(ep_str)
                if ep_num > episodes[-1] and ep_num <= 99 and (ep_num - episodes[-1]) <= 20:
                    episodes.append(ep_num)
                else:
                    break
            
            # Se tem pelo menos 2 episódios válidos, formata como múltiplos
            if len(episodes) >= 2:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_episode = f"S{season}E{episode_str}"
                structure_started = True
                continue
        
        match_episode = re.match(r'(?i)^S(\d{1,2})E(\d{1,2})$', clean_part)
        if match_episode:
            season_episode = f"S{match_episode.group(1).zfill(2)}E{match_episode.group(2).zfill(2)}"
            structure_started = True
            continue
        
        match_season = re.match(r'(?i)^S(\d{1,2})$', clean_part)
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
        if upper_part in quality_tokens or re.match(r'^\d+\.?\d*(GB|MB)$', clean_part, re.IGNORECASE):
            other_parts.append('WEB-DL' if upper_part == 'WEB-DL' else clean_part)
            structure_started = True
            continue
        
        if re.match(r'^-[A-Z0-9]+$', clean_part, re.IGNORECASE) or re.match(r'^[A-Z0-9]+$', clean_part, re.IGNORECASE) and structure_started:
            other_parts.append(clean_part)
            structure_started = True
            continue
        
        if structure_started:
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


# Acrescenta tags de idioma (br-dub / br-leg) quando detectadas no release
def add_audio_tag_if_needed(title: str, release_title: str) -> str:
    if not release_title:
        return title

    release_lower = release_title.lower()
    tags = []

    if 'dual' in release_lower or 'dublado' in release_lower or 'nacional' in release_lower:
        tags.append('[br-dub]')

    if 'legendado' in release_lower or 'legenda' in release_lower:
        tags.append('[br-leg]')

    if tags:
        existing_tags = title.split()
        if all(tag not in existing_tags for tag in tags):
            title = f"{title} {' '.join(tags)}"

    return title


# Confere se o resultado corresponde à busca (ignorando stop words)
def check_query_match(query: str, title: str, original_title: str = '') -> bool:
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
    
    # Combina título + título original para busca
    combined_title = f"{title} {original_title}".lower()
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

         
    # Lógica de correspondência:
    # - 1 palavra: exige que corresponda
    # - 2 palavras: exige que ambas correspondam
    # - 3+ palavras: exige que pelo menos 2 correspondam
    if len(clean_query_words) == 1:
        return matches == 1
    elif len(clean_query_words) == 2:
        return matches == 2
    else:
        return matches >= 2

