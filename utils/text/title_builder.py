# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import re
from typing import Optional
from urllib.parse import unquote

from utils.text.cleaning import clean_title, remove_accents
from utils.text.storage import (
    get_metadata_name,
    is_release_title_incomplete,
    _is_metadata_more_complete,
)
from utils.text.title_helpers import (
    _extract_base_title_from_release,
    _split_technical_components,
    _extract_technical_info,
    _clean_remaining,
    _ensure_default_format,
    _apply_season_temporada_tags,
    _reorder_title_components,
)

def _normalize_metadata_name(metadata_name: str) -> str:
    normalized = metadata_name.strip()
    normalized = html.unescape(normalized)
    try:
        normalized = unquote(normalized)
    except Exception:
        pass
    normalized = normalized.strip()
    normalized = clean_title(normalized)
    normalized = re.sub(r'\[[^\]]*\]', '', normalized)
    normalized = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), normalized)
    temp_normalized = re.sub(r'\s+', '.', normalized.strip())
    temp_normalized = re.sub(r'\.{2,}', '.', temp_normalized)
    parts = temp_normalized.split('.')
    cleaned_parts = []
    prev_part = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_lower = part.lower()
        prev_lower = prev_part.lower() if prev_part else None
        if part_lower != prev_lower:
            cleaned_parts.append(part)
            prev_part = part
    return '.'.join(cleaned_parts).strip('.')

def prepare_release_title(
    magnet_processed: str,
    fallback_title: str,
    year: str = '',
    missing_dn: bool = False,
    info_hash: Optional[str] = None,
    skip_metadata: bool = False
) -> str:
    """Normaliza magnet_processed; usa metadata/fallback se DN incompleto; aplica ano/WEB-DL."""
    fallback_title = (fallback_title or '').strip()
    original_release_title = None
    final_missing_dn = missing_dn

    magnet_processed = (magnet_processed or '').strip()
    
    if magnet_processed and len(magnet_processed) >= 3:
        normalized = magnet_processed
        normalized = html.unescape(normalized)
        try:
            normalized = unquote(normalized)
        except Exception:
            pass
        normalized = normalized.strip()
        
        from utils.text.cleaning import clean_title
        normalized = clean_title(normalized)
        
        technical_in_brackets = []
        
        bracket_patterns = [
            r'\[(1080p|720p|480p|2160p|4K|UHD|FHD|FULLHD|HD|SD|HDR)\]',
            r'\[(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)\]',
            r'\[(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)\]',
            r'\[(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)\]',
        ]
        
        for pattern in bracket_patterns:
            matches = re.finditer(pattern, normalized, re.IGNORECASE)
            for match in matches:
                technical_in_brackets.append(match.group(1))
        
        normalized = re.sub(r'\[[^\]]*\]', '', normalized)
        
        if technical_in_brackets:
            normalized = re.sub(r'\s+', '.', normalized.strip())
            if normalized:
                normalized += '.' + '.'.join(technical_in_brackets)
            else:
                normalized = '.'.join(technical_in_brackets)
        
        normalized = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), normalized)
        
        temp_normalized = re.sub(r'\s+', '.', normalized.strip())
        temp_normalized = re.sub(r'\.{2,}', '.', temp_normalized)
        
        parts = temp_normalized.split('.')
        combined_parts = []
        for part in parts:
            clean_part = part.strip()
            if clean_part:
                combined_parts.append(clean_part)
        
        cleaned_parts = []
        prev_part = None
        for part in combined_parts:
            part = part.strip()
            if not part:
                continue
            part_lower = part.lower()
            prev_lower = prev_part.lower() if prev_part else None
            if part_lower != prev_lower:
                cleaned_parts.append(part)
                prev_part = part
        
        original_release_title = '.'.join(cleaned_parts).strip('.')
        if info_hash and not skip_metadata:
            if is_release_title_incomplete(original_release_title):
                metadata_name = get_metadata_name(info_hash, skip_metadata=skip_metadata)
                if metadata_name and _is_metadata_more_complete(
                    metadata_name, original_release_title
                ):
                    original_release_title = _normalize_metadata_name(metadata_name)
        final_missing_dn = False
    else:
        if missing_dn:

            if info_hash:
                if not skip_metadata:
                    metadata_name = get_metadata_name(info_hash, skip_metadata=skip_metadata)
                    if metadata_name and len(metadata_name.strip()) >= 3:
                        original_release_title = _normalize_metadata_name(metadata_name)
                        final_missing_dn = False
                    else:
                        original_release_title = fallback_title
                        final_missing_dn = True
                else:
                    original_release_title = fallback_title
                    final_missing_dn = True
            else:
                original_release_title = fallback_title
                final_missing_dn = True
        else:

            original_release_title = fallback_title
            final_missing_dn = False

    if not original_release_title or len(original_release_title.strip()) < 3:
        original_release_title = fallback_title
        final_missing_dn = True

    if '.' in original_release_title:
        original_release_title = re.sub(r'\s+', ' ', original_release_title)
        original_release_title = re.sub(r'\s*\.\s*', '.', original_release_title)
    else:
        original_release_title = re.sub(r'\s+', ' ', original_release_title).strip()

    if year:
        year_str = str(year)
        if year_str and year_str not in original_release_title:
            if '.' in original_release_title:
                original_release_title = f"{original_release_title}.{year_str}".strip()
            else:
                original_release_title = f"{original_release_title} {year_str}".strip()
        else:
            pass

    if final_missing_dn and original_release_title and 'web-dl' not in original_release_title.lower():
        if '.' in original_release_title:
            original_release_title = f"{original_release_title}.WEB-DL".strip()
        else:
            original_release_title = f"{original_release_title} WEB-DL".strip()
    else:
        pass

    result = original_release_title.strip()
    return result

def create_standardized_title(title_original_html: str, year: str, magnet_processed: str, title_translated_html: Optional[str] = None, magnet_original: Optional[str] = None) -> str:
    
    def finalize_title(value: str) -> str:
        release_for_season_detection = magnet_original if magnet_original else magnet_processed
        value = _apply_season_temporada_tags(value, release_for_season_detection, title_original_html, year)
        value = _reorder_title_components(value)
        return _ensure_default_format(value)
    base_title = ''
    
    if title_original_html and title_original_html.strip():
        has_non_latin = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f\u0900-\u09ff\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff\u0c00-\u0c7f\u0b80-\u0bff\u0c80-\u0cff\u0d00-\u0d7f\u0a80-\u0aff\u0b00-\u0b7f]', title_original_html))
        
        if not has_non_latin:
            base_title = clean_title(title_original_html)
            base_title = remove_accents(base_title)
            base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)
            base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)
            base_title = base_title.replace(' ', '.').replace('-', '.').replace('/', '.')
            base_title = re.sub(r'[^\w\.]', '', base_title)
            base_title = base_title.strip('.')
            base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))
            
        else:
            raw_to_check = magnet_original if magnet_original else magnet_processed
            release_has_non_latin = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f\u0900-\u09ff\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff\u0c00-\u0c7f\u0b80-\u0bff\u0c80-\u0cff\u0d00-\u0d7f\u0a80-\u0aff\u0b00-\u0b7f]', raw_to_check or ''))
            

            if title_translated_html and title_translated_html.strip():
                base_title = clean_title(title_translated_html)
                base_title = remove_accents(base_title)
                base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)
                base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)
                base_title = base_title.replace(' ', '.').replace('-', '.').replace('/', '.')
                base_title = re.sub(r'[^\w\.]', '', base_title)
                base_title = base_title.strip('.')
                base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))
            else:
                base_title = _extract_base_title_from_release(magnet_processed)
    else:
        base_title = _extract_base_title_from_release(magnet_processed)
        result = finalize_title(base_title)
        return result
    
    if magnet_original and magnet_original.strip():
        clean_release = clean_title(magnet_original)
    elif magnet_processed and magnet_processed.strip():
        clean_release = clean_title(magnet_processed)
    else:
        result = finalize_title(base_title)
        return result
    clean_release = remove_accents(clean_release)
    
    technical_in_brackets = []
    
    bracket_patterns = [
        r'\[(1080p|720p|480p|2160p|4K|UHD|FHD|FULLHD|HD|SD|HDR)\]',
        r'\[(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)\]',
        r'\[(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)\]',
        r'\[(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)\]',
    ]
    
    for pattern in bracket_patterns:
        matches = re.finditer(pattern, clean_release, re.IGNORECASE)
        for match in matches:
            technical_in_brackets.append(match.group(1))
    
    clean_release = re.sub(r'\[[^\]]*\]', '', clean_release)
    
    if technical_in_brackets:
        clean_release = re.sub(r'\s+', '.', clean_release.strip())
        if clean_release:
            clean_release += '.' + '.'.join(technical_in_brackets)
        else:
            clean_release = '.'.join(technical_in_brackets)
    
    clean_release = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), clean_release)
    
    base_title_normalized = re.sub(r'[\.\s]', '', base_title).lower()
    clean_release_normalized = re.sub(r'[\.\s]', '', clean_release).lower()
    
    if clean_release_normalized.startswith(base_title_normalized):
        base_no_dots = base_title.replace('.', '')
        if len(base_no_dots) > 0:
            base_pattern = re.escape(base_no_dots[0])
            for char in base_no_dots[1:]:
                base_pattern += rf'\.?{re.escape(char)}'
            
            match = re.match(rf'^{base_pattern}(\.)', clean_release, flags=re.IGNORECASE)
            if match:
                clean_release = clean_release[match.end():]
            else:
                clean_release = re.sub(rf'^{base_pattern}(?=S\d|(?<!\d)\d)', '', clean_release, flags=re.IGNORECASE)
        
        clean_release = re.sub(r'^\.+', '', clean_release)
    
    temp_clean = re.sub(r'\s+', '.', clean_release.strip())
    temp_clean = re.sub(r'\.{2,}', '.', temp_clean)
    
    parts = temp_clean.split('.')
    cleaned_parts = []
    prev_part = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_lower = part.lower()
        prev_lower = prev_part.lower() if prev_part else None
        if part_lower != prev_lower:
            cleaned_parts.append(part)
            prev_part = part
    
    clean_release = '.'.join(cleaned_parts).strip('.')
    


    season_ep_multi_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:\s*[\.\-]\s*\d{1,2}){1,}(?![0-9])', clean_release)
    
    if not season_ep_multi_match:
        alt_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:[\.\-]\d{1,2}){1,}(?![0-9])', clean_release)
        if alt_match:
            season_ep_multi_match = alt_match
    
    if season_ep_multi_match:
        season = season_ep_multi_match.group(1).zfill(2)
        episode1 = int(season_ep_multi_match.group(2))
        
        full_match = season_ep_multi_match.group(0)
        episodes = [episode1]
        
        episode_numbers = re.findall(r'[\.\-]\s*(\d{1,2})', full_match)
        
        for ep_str in episode_numbers:
            ep_num = int(ep_str)
            from app.config import Config
            if ep_num > episodes[-1] and ep_num <= Config.MAX_EPISODE_NUMBER and (ep_num - episodes[-1]) <= Config.MAX_EPISODE_DIFF:
                episodes.append(ep_num)
            else:
                break
        
        if len(episodes) >= 2:



            if len(episodes) == 2:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            elif len(episodes) >= 5:

                first_ep = str(episodes[0]).zfill(2)
                last_ep = str(episodes[-1]).zfill(2)
                season_ep_str = f"S{season}E{first_ep}-E{last_ep}"
            elif len(episodes) >= 3:

                episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            else:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            
            year_from_release = None
            text_before_season = clean_release[:season_ep_multi_match.start()]
            if text_before_season:
                year_match = re.search(r'(19|20)\d{2}', text_before_season)
                if year_match:
                    year_from_release = year_match.group(0)
            
            original_magnet_text = clean_release[season_ep_multi_match.end():]
            original_magnet_text = re.sub(r'\s+', '.', original_magnet_text)
            original_magnet_text = re.sub(r'\.{2,}', '.', original_magnet_text)
            original_magnet_text = original_magnet_text.strip('.')
            original_magnet_text = _split_technical_components(original_magnet_text)
            
            processed_magnet_text = _extract_technical_info(original_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            
            if year_from_release:
                result = finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
            else:
                result = finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
            
            return result
    
    clean_release = re.sub(r'\s+', '.', clean_release)
    clean_release = re.sub(r'\.{2,}', '.', clean_release)
    clean_release = clean_release.strip('.')
    

    
    season_ep_multi_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:[\.\-]\d{1,2}){1,}(?![0-9])', clean_release)
    
    if season_ep_multi_match:
        season = season_ep_multi_match.group(1).zfill(2)
        episode1 = int(season_ep_multi_match.group(2))
        
        full_match = season_ep_multi_match.group(0)
        episodes = [episode1]
        
        episode_numbers = re.findall(r'[\.\-](\d{1,2})', full_match)
        for ep_str in episode_numbers:
            ep_num = int(ep_str)
            from app.config import Config
            if ep_num > episodes[-1] and ep_num <= Config.MAX_EPISODE_NUMBER and (ep_num - episodes[-1]) <= Config.MAX_EPISODE_DIFF:
                episodes.append(ep_num)
            else:
                break
        
        if len(episodes) >= 2:



            if len(episodes) == 2:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            elif len(episodes) >= 5:

                first_ep = str(episodes[0]).zfill(2)
                last_ep = str(episodes[-1]).zfill(2)
                season_ep_str = f"S{season}E{first_ep}-E{last_ep}"
            elif len(episodes) >= 3:

                episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            else:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            
            year_from_release = None
            text_before_season = clean_release[:season_ep_multi_match.start()]
            if text_before_season:
                year_match = re.search(r'(19|20)\d{2}', text_before_season)
                if year_match:
                    year_from_release = year_match.group(0)
            
            original_magnet_text = clean_release[season_ep_multi_match.end():]
            original_magnet_text = _split_technical_components(original_magnet_text)
            processed_magnet_text = _extract_technical_info(original_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            
            if year_from_release:
                result = finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
            else:
                result = finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
            
            return result
    
    season_ep_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})', clean_release)
    
    if season_ep_match:
        season = season_ep_match.group(1).zfill(2)
        episode = season_ep_match.group(2).zfill(2)
        season_ep_str = f"S{season}E{episode}"
        
        year_from_release = None
        text_before_season = clean_release[:season_ep_match.start()]
        if text_before_season:
            year_match = re.search(r'(19|20)\d{2}', text_before_season)
            if year_match:
                year_from_release = year_match.group(0)
        
        original_magnet_text = clean_release[season_ep_match.end():]
        original_magnet_text = _split_technical_components(original_magnet_text)
        processed_magnet_text = _extract_technical_info(original_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        
        if year_from_release:
            return finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
        else:
            return finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
    
    technical_parts = []
    parts = clean_release.split('.')
    
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

        elif re.match(r'^(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)$', part_clean, re.IGNORECASE):
            if re.match(r'^H(264|265)$', part_clean, re.IGNORECASE):
                part_clean = f'H.{part_clean[1:]}'
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
    
    clean_release = '.'.join(technical_parts)
    
    season_only_match = re.search(r'(?i)S(\d{1,2})(?![E\d])(?:[^E]|$)', clean_release)
    if season_only_match:
        season_num_raw = season_only_match.group(1)
        try:
            season_num = int(season_num_raw)
            if season_num <= 0:
                season_only_match = None
            else:
                season = season_num_raw.zfill(2)
                season_str = f"S{season}"
        except (ValueError, TypeError):
            season_only_match = None
    
    if season_only_match:
        
        year_from_release = year
        if not year_from_release:
            year_match = re.search(r'(19|20)\d{2}', clean_release)
            if year_match:
                year_from_release = year_match.group(0)
        
        if year_from_release:
            processed_magnet_text = clean_release[season_only_match.end():]
            processed_magnet_text = re.sub(r'(19|20)\d{2}', '', processed_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            return finalize_title(f"{base_title}.{season_str}.{year_from_release}{processed_magnet_text}")
        else:
            processed_magnet_text = clean_release[season_only_match.end():]
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            return finalize_title(f"{base_title}.{season_str}{processed_magnet_text}")
    
    year_from_release = year
    if not year_from_release:
        year_match = re.search(r'(19|20)\d{2}', clean_release)
        if year_match:
            year_from_release = year_match.group(0)
    
    if year_from_release:
        processed_magnet_text = re.sub(r'(19|20)\d{2}', '', clean_release)
        processed_magnet_text = _split_technical_components(processed_magnet_text)
        processed_magnet_text = _extract_technical_info(processed_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        return finalize_title(f"{base_title}.{year_from_release}{processed_magnet_text}")
    
    if clean_release:
        processed_magnet_text = _split_technical_components(clean_release)
        processed_magnet_text = _extract_technical_info(processed_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        return finalize_title(f"{base_title}{processed_magnet_text}")
    
    return finalize_title(base_title)

