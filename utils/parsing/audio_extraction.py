# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def detect_audio_from_idioma_text(idioma_text: str) -> Optional[str]:
    """Detecta audio_info a partir de um texto de Idioma/Áudio (lógica idiomas_detectados).

    Usado por scrapers que já extraíram o campo Idioma manualmente (bludv, rede).
    Retorna 'dual', 'português', 'inglês', 'japonês' ou None.
    """
    if not idioma_text:
        return None
    lower = idioma_text.lower()

    detectados = []
    if 'português' in lower or 'portugues' in lower or 'pt-br' in lower or 'ptbr' in lower or 'pt br' in lower:
        detectados.append('português')
    if 'inglês' in lower or 'ingles' in lower or 'english' in lower:
        detectados.append('inglês')
    if 'japonês' in lower or 'japones' in lower or 'japanese' in lower or 'jap' in lower:
        detectados.append('japonês')

    detectados = detectados[:3]
    if len(detectados) >= 2:
        if 'português' in detectados and 'inglês' in detectados:
            return 'dual'
        if 'português' in detectados:
            return 'dual'
        return detectados[0]
    if len(detectados) == 1:
        return detectados[0]
    return None


def detect_audio_from_html(html_content: str) -> Optional[str]:
    """Detecta informações de áudio a partir do conteúdo HTML"""
    if not html_content:
        return None
    
    text_content = re.sub(r'<[^>]+>', ' ', html_content)
    text_content = re.sub(r'\s+', ' ', text_content)
    
    has_idioma_label = re.search(r'(?i)(?:Áudio|Idioma)\s*:?', html_content)
    has_legenda_label = re.search(r'(?i)Legenda\s*:?', html_content)
    
    has_portugues = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*(?:<[^>]+>)*\s*.*?Português', html_content, re.DOTALL)
    if not has_portugues:
        has_portugues = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*.*?Português', text_content)
    
    has_multi = re.search(r'(?i)Multi-?Áudio|Multi-?Audio', html_content)
    
    has_ingles_audio = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*(?:<[^>]+>)*\s*.*?(?:Inglês|Ingles|English)', html_content, re.DOTALL)
    if not has_ingles_audio:
        has_ingles_audio = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*.*?(?:Inglês|Ingles|English)', text_content)
    
    has_ingles = re.search(r'(?i)Inglês|Ingles|English', html_content)
    
    has_legenda_legendado = re.search(r'(?i)Legenda\s*:?\s*(?:<[^>]+>)*\s*.*?Legendado', html_content, re.DOTALL)
    if not has_legenda_legendado:
        has_legenda_legendado = re.search(r'(?i)Legenda\s*:?\s*.*?Legendado', text_content)
    
    has_legenda_ingles = re.search(r'(?i)Legenda\s*:?\s*(?:<[^>]+>)*\s*.*?(?:Inglês|Ingles|English)', html_content, re.DOTALL)
    if not has_legenda_ingles:
        has_legenda_ingles = re.search(r'(?i)Legenda\s*:?\s*.*?(?:Inglês|Ingles|English)', text_content)
    
    has_legenda_portugues = re.search(r'(?i)Legenda\s*:?\s*(?:<[^>]+>)*\s*.*?(?:PT-BR|PTBR|Português|Portugues|PT)', html_content, re.DOTALL)
    if not has_legenda_portugues:
        has_legenda_portugues = re.search(r'(?i)Legenda\s*:?\s*.*?(?:PT-BR|PTBR|Português|Portugues|PT)', text_content)
    
    if has_portugues:
        if has_multi or has_ingles_audio or has_ingles:
            return 'dual'
        else:
            return 'português'
    
    if has_ingles_audio:
        if has_legenda_portugues:
            return 'legendado'
        return None
    

    if has_idioma_label and has_ingles:
        if has_legenda_portugues:
            return 'legendado'
        return None
    
    if has_legenda_legendado or has_legenda_portugues or (has_legenda_ingles and not has_portugues):
        return 'legendado'
    
    return None

def add_audio_tag_if_needed(title: str, magnet_processed: str, info_hash: Optional[str] = None, skip_metadata: bool = False, audio_info_from_html: Optional[str] = None, audio_html_content: Optional[str] = None) -> str:
    """Acrescenta tags de idioma [Brazilian], [Eng], [Jap] quando detectadas"""
    title = title.replace('[Brazilian]', '').replace('[Eng]', '').replace('[Jap]', '')
    title = re.sub(r'\s+', ' ', title).strip()
    
    has_brazilian = '[Brazilian]' in title
    has_eng = '[Eng]' in title
    has_jap = '[Jap]' in title
    
    has_brazilian_audio = False
    has_eng_audio = False
    has_japones_audio = False
    
    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        if 'português' in audio_info_str or 'portugues' in audio_info_str:
            has_brazilian_audio = True
    
    if magnet_processed and not has_brazilian_audio:
        release_lower = magnet_processed.lower()
        if 'dual' in release_lower or 'dublado' in release_lower or 'nacional' in release_lower or 'portugues' in release_lower or 'português' in release_lower:
            has_brazilian_audio = True
    
    if info_hash and not skip_metadata and not has_brazilian_audio:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'dual' in metadata_name or 'dublado' in metadata_name or 'nacional' in metadata_name or 'portugues' in metadata_name or 'português' in metadata_name:
                    has_brazilian_audio = True
        except Exception:
            pass
    
    if info_hash and not skip_metadata and not has_brazilian_audio:
        try:
            from utils.text.cross_data import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'dual' in cross_release_lower or 'dublado' in cross_release_lower or 'nacional' in cross_release_lower or 'portugues' in cross_release_lower or 'português' in cross_release_lower:
                        has_brazilian_audio = True
        except Exception:
            pass
    
    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        if 'inglês' in audio_info_str or 'ingles' in audio_info_str or 'english' in audio_info_str:
            has_eng_audio = True
    
    if magnet_processed and not has_eng_audio:
        release_lower = magnet_processed.lower()
        if 'dual' in release_lower or 'legendado' in release_lower or 'legenda' in release_lower or re.search(r'\bleg\b', release_lower):
            has_eng_audio = True
    
    if info_hash and not skip_metadata and not has_eng_audio:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'dual' in metadata_name or 'legendado' in metadata_name or 'legenda' in metadata_name or re.search(r'\bleg\b', metadata_name):
                    has_eng_audio = True
        except Exception:
            pass
    
    if info_hash and not skip_metadata and not has_eng_audio:
        try:
            from utils.text.cross_data import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'dual' in cross_release_lower or 'legendado' in cross_release_lower or 'legenda' in cross_release_lower or re.search(r'\bleg\b', cross_release_lower):
                        has_eng_audio = True
        except Exception:
            pass
    
    if audio_html_content and not has_eng_audio:
        if re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*(?:<[^>]+>)*\s*.*?(?:Inglês|Ingles|English)', audio_html_content, re.DOTALL):
            has_eng_audio = True
    
    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        if 'japonês' in audio_info_str or 'japones' in audio_info_str or 'japanese' in audio_info_str or 'jap' in audio_info_str:
            has_japones_audio = True
    
    if magnet_processed and not has_japones_audio:
        release_lower = magnet_processed.lower()
        if 'japonês' in release_lower or 'japones' in release_lower or 'japanese' in release_lower or re.search(r'\bjap\b', release_lower):
            has_japones_audio = True
    
    if info_hash and not skip_metadata and not has_japones_audio:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'japonês' in metadata_name or 'japones' in metadata_name or 'japanese' in metadata_name or re.search(r'\bjap\b', metadata_name):
                    has_japones_audio = True
        except Exception:
            pass
    
    if info_hash and not skip_metadata and not has_japones_audio:
        try:
            from utils.text.cross_data import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'japonês' in cross_release_lower or 'japones' in cross_release_lower or 'japanese' in cross_release_lower or re.search(r'\bjap\b', cross_release_lower):
                        has_japones_audio = True
        except Exception:
            pass
    
    tags_to_add = []
    if has_brazilian_audio and not has_brazilian:
        tags_to_add.append('[Brazilian]')
    if has_eng_audio and not has_eng:
        tags_to_add.append('[Eng]')
    if has_japones_audio and not has_jap:
        tags_to_add.append('[Jap]')
    
    if tags_to_add:
        if '[Brazilian]' in tags_to_add or '[Eng]' in tags_to_add:
            title = re.sub(r'\.?\.?DUAL(?![\.\s]?(?:5\.1|2\.0|7\.1))\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        if '[Brazilian]' in tags_to_add:
            title = re.sub(r'\.?\.?DUBLADO\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?NACIONAL\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?PORTUGUES\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?PORTUGUÊS\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        if '[Jap]' in tags_to_add:
            title = re.sub(r'\.?\.?JAPONÊS\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAPONES\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAPANESE\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAP\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        title = re.sub(r'\.?\.?LEGENDADO\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.?\.?LEGENDA\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.?\.?LEG\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.{2,}', '.', title)
        title = title.strip('.')
        
        title = title.rstrip()
        title = f"{title} {' '.join(tags_to_add)}"

    result = title
    return result
