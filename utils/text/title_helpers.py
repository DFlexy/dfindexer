# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
from typing import List

from utils.text.cleaning import clean_title, remove_accents

def _extract_base_title_from_release(magnet_processed: str) -> str:
    clean_release = clean_title(magnet_processed)
    clean_release = remove_accents(clean_release)
    
    clean_release = re.sub(r'^(19|20)\d{2}\.', '', clean_release)
    
    tech_patterns = [
        r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip)\.',
        r'^(1080p|720p|480p|2160p|4K)\.',
        r'^(x264|x265|H\.264|H\.265)\.',
    ]
    for pattern in tech_patterns:
        clean_release = re.sub(pattern, '', clean_release, flags=re.IGNORECASE)
    
    if '.' in clean_release:
        clean_release = re.sub(r'\s*\.\s*', '.', clean_release)
        clean_release = re.sub(r'\s+', '.', clean_release)
    else:
        clean_release = re.sub(r'\s+', '.', clean_release)
    
    clean_release = re.sub(r'\.{2,}', '.', clean_release)
    
    clean_release = re.sub(r'([A-Za-z0-9]+)(?<!\.)(S\d{1,2}(?:E\d{1,2})?)', r'\1.\2', clean_release, flags=re.IGNORECASE)
    
    parts = clean_release.split('.')
    base_parts = []
    for part in parts:
        if re.match(r'^S\d{1,2}(?:E\d{1,2})?$', part, re.IGNORECASE):
            break
        if re.match(r'^(19|20)\d{2}$', part):
            break
        if re.match(r'^(WEB-DL|WEBRip|BluRay|1080p|720p|2160p|FULLHD|x264|x265|DUAL|DUBLADO|HDR)', part, re.IGNORECASE):
            break
        if part and len(part) > 1:
            base_parts.append(part)
    
    base_title = '.'.join(base_parts)
    base_title = base_title.replace('-', '.').replace('/', '.')
    base_title = re.sub(r'[^\w\.]', '', base_title)
    base_title = base_title.strip('.')
    base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))
    
    return base_title

def _split_technical_components(text: str) -> str:
    if not text:
        return text
    
    if re.search(r'S\d{1,2}(?:E\d{1,2})?', text, re.IGNORECASE):
        if (re.search(r'\.S\d{1,2}E\d{1,2}\.', text, re.IGNORECASE) or 
            re.search(r'\.S\d{1,2}(?![E\d])\.', text, re.IGNORECASE) or 
            re.search(r'\.\d{3,4}p\.', text, re.IGNORECASE)):
            if not re.search(r'(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)(1080p|720p|2160p|480p|4K|UHD|FHD|FULLHD|HD|SD|HDR|x264|x265|H\.264|H\.265|AVC|HEVC)', text, re.IGNORECASE):
                return text
    
    if '.' in text:
        parts = text.split('.')
        if len(parts) >= 3:
            has_colados = any(
                (re.search(r'(WEB-DL|WEBRip|1080p|720p|x264|x265|LEGENDADO|DUAL)', part, re.IGNORECASE) 
                 and len(part) > 10)
                or '-' in part
                for part in parts
            )
            if not has_colados:
                return text
    
    result = text
    
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
    
    result = re.sub(r'\bDUAL\.(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?\b', replace_dual_audio, result, flags=re.IGNORECASE)
    
    result = re.sub(r'\bS(\d{1,2})(?![E\d])\b', replace_season, result, flags=re.IGNORECASE)
    
    result = re.sub(r'\b(19|20)\d{2}\b', replace_year, result)
    
    result = re.sub(r'\bH(264|265)\b', r'H.\1', result, flags=re.IGNORECASE)
    
    result = re.sub(r'(?<!\.)(x264|x265|H\.264|H\.265|AVC|HEVC)(?=-)', r'\1.', result, flags=re.IGNORECASE)
    
    patterns = [
        (r'(?<!\.)(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)(?!\.)', r'.\1.', re.IGNORECASE),
        (r'(?<!\.)(?<!E)(2160p|1080p|720p|480p|4K|UHD|FHD|FULLHD|HD|SD|HDR)(?!\.)', r'.\1.', re.IGNORECASE),
        (r'(?<!\.)(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)(?!\.)', r'.\1.', re.IGNORECASE),

        (r'(?<!\.)(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado|DTS-HD|TrueHD)(?!\.)', r'.\1.', re.IGNORECASE),
        (r'(?<!\.)(MKV|MP4|AVI|MPEG|MOV)(?!\.)', r'.\1.', re.IGNORECASE),
        (r'(?<!\.)(AAC|AC3|DTS|DDP)\d+\.\d+(?!\.)', r'.\1.', re.IGNORECASE),

        (r'(?<!\.)(\d+\.\d+)(?!\.)(?!\d)', r'.\1.', re.IGNORECASE),
    ]
    
    for pattern, replacement, flags in patterns:
        result = re.sub(pattern, replacement, result, flags=flags)
    
    for placeholder, dual_audio in dual_audio_placeholders.items():
        result = result.replace(placeholder, dual_audio)
    
    for placeholder, season in season_placeholders.items():
        result = result.replace(placeholder, season)
    
    for placeholder, year in year_placeholders.items():
        result = result.replace(placeholder, year)
    
    result = re.sub(r'(?<!\.)(S\d{1,2})(?![E\d])(?!\.)', r'.\1.', result, flags=re.IGNORECASE)
    
    result = re.sub(r'(?<!\.)((19|20)\d{2})(?!\.)', r'.\1.', result)
    
    result = re.sub(r'\.{2,}', '.', result)
    result = result.strip('.')
    
    return result

def _extract_technical_info(text: str) -> str:
    if not text:
        return ''
    
    text = re.sub(r'\s+', '.', text)
    
    text = re.sub(r'(WEB-DL|DTS-HD)', lambda m: m.group(1).replace('-', '___HYPHEN___'), text, flags=re.IGNORECASE)
    
    text = text.replace('-', '.')
    
    text = text.replace('___HYPHEN___', '-')
    
    text = re.sub(r'\.{2,}', '.', text)
    text = text.strip('.')
    
    if not text:
        return ''
    
    text = _split_technical_components(text)
    
    technical_parts = []
    parts = text.split('.')
    
    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue
        
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

def _clean_remaining(processed_magnet_text: str) -> str:
    if not processed_magnet_text:
        return ''
    
    processed_magnet_text = processed_magnet_text.strip('.')
    if not processed_magnet_text:
        return ''
    
    processed_magnet_text = re.sub(r'\.{2,}', '.', processed_magnet_text)
    
    if processed_magnet_text and not processed_magnet_text.startswith('.'):
        processed_magnet_text = '.' + processed_magnet_text
    
    return processed_magnet_text

def _ensure_default_format(title: str) -> str:
    if not title:
        return title
    normalized = title.lower()
    if re.search(r'(web[-\.\s]?dl|webrip|bluray|bdrip|hdrip|hdtv|dvdrip|2160p|1080p|720p|480p|4k|camrip|cam|tsrip|ts|uhd|fullhd|hdr)', normalized, re.IGNORECASE):
        return title
    if title.endswith('.'):
        return f"{title}WEB-DL"
    return f"{title}.WEB-DL"

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
    
    if 'temporada' not in release_clean:
        return title
    
    has_completo = 'completo' in release_clean or 'completa' in release_clean
    
    result = title
    season_match = re.search(r'(\d+)\s*(?:a)?\s*temporada', release_clean)
    if not season_match:
        season_match = re.search(r'temporada\s*(?:-|:)?\s*(\d+)', release_clean)
    year_str = str(year) if year else ''
    year_in_title = year_str and year_str in result
    if season_match:
        season_number_raw = season_match.group(1)
        try:
            season_num = int(season_number_raw)
            if season_num <= 0:
                if not year_in_title and year_str:
                    result = f"{result}.{year_str}"
                return result
        except (ValueError, TypeError):
            if not year_in_title and year_str:
                result = f"{result}.{year_str}"
            return result
        
        season_number = season_number_raw.zfill(2)
        has_season_info = re.search(rf'S0*{season_number_raw}(?:E\d+(?:-\d+)?|$)', result, re.IGNORECASE)
        has_any_season_ep = re.search(r'S\d{1,2}E\d{1,2}', result, re.IGNORECASE)
        
        if has_completo and has_any_season_ep:
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

def _reorder_title_components(title: str) -> str:
    if not title:
        return title
    
    title = _split_technical_components(title)
    
    parts = [part for part in title.split('.') if part]
    if not parts:
        return title
    
    season_episode = None
    season_only = None
    year = None
    base_parts: List[str] = []
    quality_parts: List[str] = []
    source_parts: List[str] = []
    codec_parts: List[str] = []
    audio_parts: List[str] = []
    other_parts: List[str] = []
    structure_started = False
    
    quality_tokens = {
        '1080P', '720P', '480P', '2160P', '4K', 'HD', 'FHD', 'UHD', 'SD', 'HDR', 'FULLHD'
    }
    source_tokens = {
        'WEB-DL', 'WEBRIP', 'BLURAY', 'DVDRIP', 'HDRIP', 'HDTV', 'BDRIP',
        'BRRIP', 'CAMRIP', 'CAM', 'TSRIP', 'TS', 'TC', 'R5', 'SCR', 'DVDSCR'
    }
    codec_tokens = {
        'X264', 'X265', 'H.264', 'H.265', 'H264', 'H265', 'AVC', 'HEVC'
    }
    audio_tokens = {
        'DUAL', 'DUBLADO', 'DDP5.1', 'ATMOS', 'AC3', 'AAC', 'MP3', 'FLAC', 'DTS', 'NACIONAL', 'LEGENDADO'
    }
    
    combined_parts = []
    i = 0
    while i < len(parts):
        part = parts[i]
        clean_part = part.strip()
        
        if i + 1 < len(parts) and re.match(r'^DUAL$', clean_part, re.IGNORECASE):
            next_part = parts[i + 1].strip()
            if re.match(r'^(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?$', next_part, re.IGNORECASE):
                combined_parts.append(f"{clean_part}.{next_part}")
                i += 2
                continue
        
        combined_parts.append(part)
        i += 1
    
    parts = combined_parts
    
    for part in parts:
        clean_part = part.strip()
        if not clean_part:
            continue
        
        match_episode_multi = re.match(r'^S(\d{1,2})E(\d{1,2})(?:[\.\-E](\d{1,2}))+$', clean_part, re.IGNORECASE)
        if match_episode_multi:
            season = match_episode_multi.group(1).zfill(2)
            episode1 = int(match_episode_multi.group(2))
            episodes = [episode1]
            
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
            
            if len(episodes) >= 2:



                if len(episodes) == 2:
                    episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                elif len(episodes) >= 5:

                    first_ep = str(episodes[0]).zfill(2)
                    last_ep = str(episodes[-1]).zfill(2)
                    season_episode = f"S{season}E{first_ep}-E{last_ep}"
                elif len(episodes) >= 3:

                    episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                else:
                    episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                structure_started = True
                continue
        
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
        
        if upper_part in quality_tokens:
            normalized_quality = clean_part.lower()
            if normalized_quality not in [q.lower() for q in quality_parts]:
                quality_parts.append(clean_part)
            structure_started = True
            continue
        elif upper_part in source_tokens:
            normalized_source = 'WEB-DL' if upper_part == 'WEB-DL' else clean_part
            if normalized_source not in source_parts:
                source_parts.append(normalized_source)
            structure_started = True
            continue
        elif upper_part in codec_tokens or re.match(r'^(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)$', clean_part, re.IGNORECASE):
            if re.match(r'^H(264|265)$', clean_part, re.IGNORECASE):
                clean_part = f'H.{clean_part[1:]}'
            normalized_codec = clean_part.lower()
            if normalized_codec not in [c.lower() for c in codec_parts]:
                codec_parts.append(clean_part)
            structure_started = True
            continue
        elif upper_part in audio_tokens or re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', clean_part, re.IGNORECASE):

            normalized_audio = clean_part.upper()
            if normalized_audio not in [a.upper() for a in audio_parts]:
                audio_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^DUAL\.(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?$', clean_part, re.IGNORECASE):
            if clean_part not in audio_parts:
                audio_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', clean_part, re.IGNORECASE):
            if clean_part not in other_parts:
                other_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^\d+\.?\d*(GB|MB)$', clean_part, re.IGNORECASE):
            structure_started = True
            continue
        
        if re.match(r'^-[A-Z0-9]+$', clean_part, re.IGNORECASE) or (re.match(r'^[A-Z0-9]+$', clean_part, re.IGNORECASE) and structure_started):
            if clean_part not in other_parts:
                other_parts.append(clean_part)
            structure_started = True
            continue
        
        if structure_started:
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
    
    ordered_parts.extend(source_parts)
    ordered_parts.extend(quality_parts)
    ordered_parts.extend(codec_parts)
    ordered_parts.extend(audio_parts)
    
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

