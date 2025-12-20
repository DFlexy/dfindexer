"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
from typing import List

from utils.text.cleaning import clean_title, remove_accents


# Extrai o núcleo do título removendo informações técnicas redundantes
def _extract_base_title_from_release(magnet_processed: str) -> str:
    clean_release = clean_title(magnet_processed)
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
    clean_release = re.sub(r'([A-Za-z0-9]+)(?<!\.)(S\d{1,2}(?:E\d{1,2})?)', r'\1.\2', clean_release, flags=re.IGNORECASE)
    
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
        if re.match(r'^(WEB-DL|WEBRip|BluRay|1080p|720p|2160p|FULLHD|x264|x265|DUAL|DUBLADO|HDR)', part, re.IGNORECASE):
            break
        if part and len(part) > 1:
            base_parts.append(part)
    
    base_title = '.'.join(base_parts)
    base_title = base_title.replace('-', '.').replace('/', '.')  # Converte hífens e barras para pontos
    base_title = re.sub(r'[^\w\.]', '', base_title)  # Remove tudo exceto letras, números e pontos
    base_title = base_title.strip('.')
    # Capitaliza cada palavra após pontos (preserva capitalização correta: Fate.Stay.Night)
    base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))
    
    return base_title


# Separa componentes técnicos colados (ex: "WEB-DL1080px264" -> "WEB-DL.1080p.x264")
def _split_technical_components(text: str) -> str:
    if not text:
        return text
    
    # IMPORTANTE: Preserva padrões já corretos como S01E01, S01, 1080p, etc.
    # Se o texto já contém esses padrões corretos e está bem formatado, não processa
    if re.search(r'S\d{1,2}(?:E\d{1,2})?', text, re.IGNORECASE):
        # Verifica se o texto já está bem formatado (com pontos separando componentes)
        # Se S01E01, S01 e 1080p já estão separados por pontos, não processa
        if (re.search(r'\.S\d{1,2}E\d{1,2}\.', text, re.IGNORECASE) or 
            re.search(r'\.S\d{1,2}(?![E\d])\.', text, re.IGNORECASE) or 
            re.search(r'\.\d{3,4}p\.', text, re.IGNORECASE)):
            # Verifica se há componentes realmente colados que precisam ser separados
            # Se não houver componentes colados (sem espaço entre eles), não processa
            if not re.search(r'(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)(1080p|720p|2160p|480p|4K|UHD|FHD|FULLHD|HD|SD|HDR|x264|x265|H\.264|H\.265|AVC|HEVC)', text, re.IGNORECASE):
                # Se não há componentes colados, retorna sem processar para preservar S01E01, S01 e 1080p
                return text
    
    # Se já tem pontos suficientes, verifica se precisa processar
    if '.' in text:
        parts = text.split('.')
        # Se já tem mais de 2 partes separadas, verifica se precisa processar
        if len(parts) >= 3:
            # Verifica se alguma parte tem componentes colados OU hífens (que precisam ser separados)
            has_colados = any(
                (re.search(r'(WEB-DL|WEBRip|1080p|720p|x264|x265|LEGENDADO|DUAL)', part, re.IGNORECASE) 
                 and len(part) > 10)  # Partes muito longas provavelmente têm componentes colados
                or '-' in part  # Partes com hífens precisam ser processadas (ex: x265-ELiTE)
                for part in parts
            )
            if not has_colados:
                return text
    
    result = text
    
    # IMPORTANTE: Preserva anos completos, padrões S01, S02, etc. ANTES de qualquer processamento
    # Substitui temporariamente por marcadores para evitar que sejam quebrados
    year_placeholders = {}
    season_placeholders = {}
    dual_audio_placeholders = {}
    year_counter = 0
    season_counter = 0
    dual_audio_counter = 0
    
    def replace_year(match):
        nonlocal year_counter
        year = match.group(0)
        placeholder = f'__YEAR_{year_counter}__'
        year_placeholders[placeholder] = year
        year_counter += 1
        return placeholder
    
    def replace_season(match):
        nonlocal season_counter
        season = match.group(0)
        placeholder = f'__SEASON_{season_counter}__'
        season_placeholders[placeholder] = season
        season_counter += 1
        return placeholder
    
    def replace_dual_audio(match):
        nonlocal dual_audio_counter
        dual_audio = match.group(0)
        placeholder = f'__DUAL_AUDIO_{dual_audio_counter}__'
        dual_audio_placeholders[placeholder] = dual_audio
        dual_audio_counter += 1
        return placeholder
    
    # IMPORTANTE: Preserva DUAL.5.1, DUAL.2.0, DUAL.7.1 ANTES de qualquer processamento
    # Esses são informações técnicas de áudio e devem ser mantidos juntos
    result = re.sub(r'\bDUAL\.(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?\b', replace_dual_audio, result, flags=re.IGNORECASE)
    
    # Preserva padrões S01, S02, etc. (temporadas completas) antes de processar
    # IMPORTANTE: Não preserva S01E01 (isso é episódio, não temporada completa)
    result = re.sub(r'\bS(\d{1,2})(?![E\d])\b', replace_season, result, flags=re.IGNORECASE)
    
    # Preserva anos completos (2021, 2023, 2024, etc.) antes de processar
    result = re.sub(r'\b(19|20)\d{2}\b', replace_year, result)
    
    # Primeiro, separa codecs seguidos de hífens e release groups (ex: x265-ELiTE -> x265.-ELiTE)
    # Isso garante que codecs sejam separados corretamente mesmo quando seguidos de hífens
    # O hífen será substituído por ponto depois em _extract_technical_info
    result = re.sub(r'(?<!\.)(x264|x265|H\.264|H\.265|AVC|HEVC)(?=-)', r'\1.', result, flags=re.IGNORECASE)
    
    # Padrões técnicos conhecidos (em ordem de prioridade - mais específicos primeiro)
    # Usa lookbehind/lookahead negativo para evitar adicionar pontos onde já existem
    patterns = [
        # Fontes (devem vir antes de qualidades para evitar conflito com "WEB")
        (r'(?<!\.)(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)(?!\.)', r'.\1.', re.IGNORECASE),
        # Qualidades (deve vir depois de fontes para evitar conflito)
        # IMPORTANTE: Não adiciona pontos se já está separado por ponto (ex: .1080p. já está correto)
        (r'(?<!\.)(?<!E)(2160p|1080p|720p|480p|4K|UHD|FHD|FULLHD|HD|SD|HDR)(?!\.)', r'.\1.', re.IGNORECASE),
        # Codecs (já processados acima, mas mantém para casos sem hífen)
        (r'(?<!\.)(x264|x265|H\.264|H\.265|AVC|HEVC)(?!\.)', r'.\1.', re.IGNORECASE),
        # Áudio
        (r'(?<!\.)(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado|DTS-HD|TrueHD)(?!\.)', r'.\1.', re.IGNORECASE),
        # Formatos
        (r'(?<!\.)(MKV|MP4|AVI|MPEG|MOV)(?!\.)', r'.\1.', re.IGNORECASE),
        # Formatos de áudio com versão: AAC2.0, AC35.1, DTS5.1, etc. (ANTES de separar números decimais genéricos)
        (r'(?<!\.)(AAC|AC3|DTS|DDP)\d+\.\d+(?!\.)', r'.\1.', re.IGNORECASE),
        # Áudio específico (5.1, 2.0, 7.1) - cuidado para não quebrar anos ou formatos de áudio
        (r'(?<!\.)(\d+\.\d+)(?!\.)(?!\d)', r'.\1.', re.IGNORECASE),
    ]
    
    # Aplica cada padrão para separar componentes colados
    for pattern, replacement, flags in patterns:
        result = re.sub(pattern, replacement, result, flags=flags)
    
    # Restaura DUAL.5.1, DUAL.2.0, DUAL.7.1 preservados
    for placeholder, dual_audio in dual_audio_placeholders.items():
        result = result.replace(placeholder, dual_audio)
    
    # Restaura temporadas preservadas
    for placeholder, season in season_placeholders.items():
        result = result.replace(placeholder, season)
    
    # Restaura anos completos preservados
    for placeholder, year in year_placeholders.items():
        result = result.replace(placeholder, year)
    
    # Adiciona pontos ao redor das temporadas se necessário (após restaurar)
    result = re.sub(r'(?<!\.)(S\d{1,2})(?![E\d])(?!\.)', r'.\1.', result, flags=re.IGNORECASE)
    
    # Adiciona pontos ao redor dos anos se necessário (após restaurar)
    result = re.sub(r'(?<!\.)((19|20)\d{2})(?!\.)', r'.\1.', result)
    
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
    
    # IMPORTANTE: Processa padrões com hífen ANTES de substituir todos os hífens
    # Isso garante que WEB-DL e DTS-HD sejam reconhecidos corretamente
    # Substitui hífens em padrões técnicos específicos por um marcador temporário
    text = re.sub(r'(WEB-DL|DTS-HD)', lambda m: m.group(1).replace('-', '___HYPHEN___'), text, flags=re.IGNORECASE)
    
    # Substitui hífens restantes por pontos para separar grupos (ex: x265-ELiTE -> x265.ELiTE)
    text = text.replace('-', '.')
    
    # Restaura os padrões com hífen originais
    text = text.replace('___HYPHEN___', '-')
    
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
        elif re.match(r'^(1080p|720p|480p|2160p|4K|HD|FHD|UHD|SD|HDR|FULLHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(x264|x265|H\.264|H\.265|AVC|HEVC)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # Formatos de áudio com versão: AAC2.0, AAC5.1, etc.
        elif re.match(r'^(AAC|AC3|DTS|DDP)\d+\.\d+$', part_clean, re.IGNORECASE):
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
    if re.search(r'(web[-\.\s]?dl|webrip|bluray|bdrip|hdrip|hdtv|dvdrip|2160p|1080p|720p|480p|4k|camrip|cam|tsrip|ts|uhd|fullhd|hdr)', normalized, re.IGNORECASE):
        return title
    if title.endswith('.'):
        return f"{title}WEB-DL"
    return f"{title}.WEB-DL"


# Força inclusão de tags de temporada encontradas na descrição original
def _apply_season_temporada_tags(title: str, magnet_processed: str, original_title_html: str, year: str) -> str:
    if not title:
        return title
    
    context_parts = []
    if magnet_processed:
        context_parts.append(magnet_processed)
    if original_title_html:
        context_parts.append(original_title_html)
    if not context_parts:
        return title
    
    release_clean = remove_accents(' '.join(context_parts).lower())
    release_clean = release_clean.replace('ª', 'a').replace('º', 'o')
    
    # IMPORTANTE: "Completo/Completa" só faz sentido em séries (temporadas completas), não em filmes
    # Se não tem temporada, é um filme - apenas retorna o título (Completo já foi removido do título base)
    if 'temporada' not in release_clean:
        return title
    
    # Detecta se tem "Completo" ou "Completa" junto com temporada (só processa se houver temporada)
    has_completo = 'completo' in release_clean or 'completa' in release_clean
    
    result = title
    season_match = re.search(r'(\d+)\s*(?:a)?\s*temporada', release_clean)
    if not season_match:
        season_match = re.search(r'temporada\s*(?:-|:)?\s*(\d+)', release_clean)
    year_str = str(year) if year else ''
    # IMPORTANTE: Define year_in_title ANTES de usar nos blocos de validação
    year_in_title = year_str and year_str in result
    if season_match:
        season_number_raw = season_match.group(1)
        # IMPORTANTE: Valida que o número da temporada é válido (maior que 0)
        # Evita gerar S00 incorretamente
        try:
            season_num = int(season_number_raw)
            if season_num <= 0:
                # Número inválido, não adiciona temporada
                if not year_in_title and year_str:
                    result = f"{result}.{year_str}"
                return result
        except (ValueError, TypeError):
            # Não é um número válido, não adiciona temporada
            if not year_in_title and year_str:
                result = f"{result}.{year_str}"
            return result
        
        season_number = season_number_raw.zfill(2)
        has_season_info = re.search(rf'S0*{season_number_raw}(?:E\d+(?:-\d+)?|$)', result, re.IGNORECASE)
        has_any_season_ep = re.search(r'S\d{1,2}E\d{1,2}', result, re.IGNORECASE)
        
        # Se tem "Completo" junto com temporada, garante que seja temporada completa (Sxx sem Exx)
        # Remove qualquer Exx que possa ter sido adicionado incorretamente
        if has_completo and has_any_season_ep:
            # Remove Exx se houver, mantendo apenas Sxx
            result = re.sub(rf'S{season_number}E\d+', f'S{season_number}', result, flags=re.IGNORECASE)
            has_any_season_ep = False
        
        if not has_season_info and not has_any_season_ep:
            if year_in_title:
                result = result.replace(f".{year_str}", '')
                result = f"{result}.S{season_number}.{year_str}"
            else:
                result = f"{result}.S{season_number}"
        elif not year_in_title and year_str:
            result = f"{result}.{year_str}"

        # Remove termos redundantes de temporada e "Completo" do título
        result = re.sub(r'\.?\b\d+\s*(?:a)?\s*temporada\s*complet[ao]?\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.?\b\d+\s*(?:a)?\s*temporada\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.?temporada\s*complet[ao]?\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.?temporada\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.?complet[ao]\b', '', result, flags=re.IGNORECASE)
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
        '1080P', '720P', '480P', '2160P', '4K', 'HD', 'FHD', 'UHD', 'SD', 'HDR', 'FULLHD'
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
    
    
    # Primeiro, detecta e combina DUAL.5.1, DUAL.2.0, DUAL.7.1 antes de processar
    # Isso garante que esses padrões técnicos sejam preservados como uma única parte
    combined_parts = []
    i = 0
    while i < len(parts):
        part = parts[i]
        clean_part = part.strip()
        
        # Verifica se é DUAL seguido de 5.1, 2.0 ou 7.1 na próxima parte
        if i + 1 < len(parts) and re.match(r'^DUAL$', clean_part, re.IGNORECASE):
            next_part = parts[i + 1].strip()
            # Verifica se a próxima parte é 5.1, 2.0, 7.1 (com ou sem sufixo como -SF)
            if re.match(r'^(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?$', next_part, re.IGNORECASE):
                # Combina DUAL.5.1, DUAL.2.0 ou DUAL.7.1
                combined_parts.append(f"{clean_part}.{next_part}")
                i += 2  # Pula ambas as partes
                continue
        
        combined_parts.append(part)
        i += 1
    
    parts = combined_parts
    
    for part in parts:
        clean_part = part.strip()
        if not clean_part:
            continue
        
        # Verifica episódios múltiplos primeiro: S02E05-06, S02E05E06E07, S02E01-E05, etc.
        # Suporta formatos: S02E01-02 (duplo), S02E01E02E03 (lista explícita), S02E01-E05 (intervalo)
        # Melhorado para capturar S01E01-02 corretamente
        match_episode_multi = re.match(r'^S(\d{1,2})E(\d{1,2})(?:[\.\-E](\d{1,2}))+$', clean_part, re.IGNORECASE)
        if match_episode_multi:
            season = match_episode_multi.group(1).zfill(2)
            episode1 = int(match_episode_multi.group(2))
            episodes = [episode1]
            
            # Extrai todos os números após o primeiro episódio (suporta hífen, ponto e E)
            # Melhorado para capturar corretamente formatos como S01E01-02
            episode_numbers = re.findall(r'[\.\-E](\d{1,2})', clean_part)
            for ep_str in episode_numbers:
                try:
                    ep_num = int(ep_str)
                    from app.config import Config
                    if ep_num > episodes[-1] and ep_num <= Config.MAX_EPISODE_NUMBER and (ep_num - episodes[-1]) <= Config.MAX_EPISODE_DIFF:
                        episodes.append(ep_num)
                    else:
                        break
                except (ValueError, TypeError):
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
        
        # Verifica também formato S01E01-02 quando não capturado pelo regex acima (fallback)
        match_episode_hyphen = re.match(r'^S(\d{1,2})E(\d{1,2})-(\d{1,2})$', clean_part, re.IGNORECASE)
        if match_episode_hyphen:
            season = match_episode_hyphen.group(1).zfill(2)
            episode1 = int(match_episode_hyphen.group(2))
            episode2 = int(match_episode_hyphen.group(3))
            if episode2 > episode1 and episode2 <= 99:
                episode_str = f"{str(episode1).zfill(2)}-{str(episode2).zfill(2)}"
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
            # NOTA: DUAL/DUBLADO/LEGENDADO serão removidos do título final em add_audio_tag_if_needed()
            # quando as tags [Brazilian], [Eng] ou [Leg] forem adicionadas
            # EXCEÇÃO: DUAL.5.1, DUAL.2.0, DUAL.7.1 são preservados (informações técnicas)
            normalized_audio = clean_part.upper()
            if normalized_audio not in [a.upper() for a in audio_parts]:
                audio_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^DUAL\.(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?$', clean_part, re.IGNORECASE):
            # DUAL.5.1, DUAL.2.0, DUAL.7.1 (com ou sem sufixo como -SF) - preserva como informação técnica
            # Vai para audio_parts mas NÃO será removido em add_audio_tag_if_needed()
            if clean_part not in audio_parts:
                audio_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', clean_part, re.IGNORECASE):
            # Outros técnicos de áudio/vídeo: HDR, 5.1, 2.0, etc.
            # NOTA: 5.1, 2.0, 7.1 só vão para other_parts se não foram combinados com DUAL
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

