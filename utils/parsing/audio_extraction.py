# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
import html
import logging
from typing import Optional, Dict, Tuple, Callable
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def _extract_audio_legenda_bludv(doc: BeautifulSoup, content_div: Optional[BeautifulSoup] = None) -> Tuple[str, str]:
    """Bludv: Extrai "Áudio" e "Legenda" do HTML"""
    audio_text = ''
    legenda = ''
    
    if not content_div:
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')
    
    if content_div:
        content_html = str(content_div)
        
        audio_patterns = [
            r'(?i)Áudio\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|$)',
            r'(?i)Audio\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|$)',
            r'(?i)<[^>]*>Áudio\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legenda|$)',
            r'(?i)<[^>]*>Audio\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legenda|$)',
        ]
        
        for pattern in audio_patterns:
            audio_match = re.search(pattern, content_html, re.DOTALL)
            if audio_match:
                audio_text = audio_match.group(1).strip()
                audio_text = html.unescape(audio_text)
                audio_text = re.sub(r'<[^>]+>', '', audio_text).strip()
                audio_text = re.sub(r'\s+', ' ', audio_text).strip()
                stop_words = ['Legenda', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho', 'IMDb']
                for stop_word in stop_words:
                    if stop_word in audio_text:
                        idx = audio_text.index(stop_word)
                        audio_text = audio_text[:idx].strip()
                        break
                if audio_text:
                    break
        
        legenda_patterns = [
            r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Áudio|Audio|$)',
            r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Qualidade|$)',
            r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
        ]
        
        for pattern in legenda_patterns:
            legenda_match = re.search(pattern, content_html, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Qualidade', 'Duração', 'Formato']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    break
    
    return audio_text, legenda

def _extract_audio_legenda_rede(doc: BeautifulSoup, article: Optional[BeautifulSoup] = None) -> Tuple[str, str]:
    """Rede: Extrai "Idioma" e "Legenda" de div#informacoes"""
    idioma = ''
    legenda = ''
    
    if not article:
        article = doc.find('div', class_='conteudo')
    
    if article:
        info_div = article.find('div', id='informacoes')
        if info_div:
            info_html = str(info_div)
            
            idioma_patterns = [
                r'(?i)Idioma\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|Legendas?|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|$)',
                r'(?i)<[^>]*>Idioma\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legendas?|$)',
            ]
            
            for pattern in idioma_patterns:
                idioma_match = re.search(pattern, info_html, re.DOTALL)
                if idioma_match:
                    idioma = idioma_match.group(1).strip()
                    idioma = html.unescape(idioma)
                    idioma = re.sub(r'<[^>]+>', '', idioma).strip()
                    idioma = re.sub(r'\s+', ' ', idioma).strip()
                    if idioma:
                        break
            
            legenda_patterns = [
                r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
                r'(?i)<strong>Legendas?\s*:\s*</strong>\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
                r'(?i)<b>Legendas?\s*:</b>\s*([^<]+?)(?:<br|</div|</p|</b|Nota|Tamanho|$)',
                r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|Nota|Tamanho|Imdb|$)',
                r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|$)',
            ]
            
            for pattern in legenda_patterns:
                legenda_match = re.search(pattern, info_html, re.DOTALL)
                if legenda_match:
                    legenda = legenda_match.group(1).strip()
                    legenda = html.unescape(legenda)
                    legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                    legenda = re.sub(r'\s+', ' ', legenda).strip()
                    stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio']
                    for stop_word in stop_words:
                        if stop_word in legenda:
                            idx = legenda.index(stop_word)
                            legenda = legenda[:idx].strip()
                            break
                    if legenda:
                        break
    
    return idioma, legenda

def _extract_audio_legenda_baixafilmes(doc: BeautifulSoup, entry_meta_list: Optional[list] = None) -> Tuple[str, str]:
    """XFilmes: Extrai "Idioma" e "Legenda" de div.entry-meta"""
    idioma = ''
    legenda = ''
    
    if not entry_meta_list:
        entry_meta_list = doc.find_all('div', class_='entry-meta')
    
    for entry_meta in entry_meta_list:
        entry_meta_html = str(entry_meta)
        
        if not idioma:
            idioma_match = re.search(r'(?i)<b>Idioma:</b>\s*([^<]+?)(?:<br|</div|</p|</b|$)', entry_meta_html, re.DOTALL)
            if idioma_match:
                idioma = idioma_match.group(1).strip()
                idioma = html.unescape(idioma)
                idioma = re.sub(r'<[^>]+>', '', idioma).strip()
                idioma = re.sub(r'\s+', ' ', idioma).strip()
            else:
                idioma_match = re.search(r'(?i)Idioma\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|$)', entry_meta_html, re.DOTALL)
                if idioma_match:
                    idioma = idioma_match.group(1).strip()
                    idioma = html.unescape(idioma)
                    idioma = re.sub(r'<[^>]+>', '', idioma).strip()
                    idioma = re.sub(r'\s+', ' ', idioma).strip()
        
        if not legenda:
            legenda_match = re.search(r'(?i)<b>Legenda:</b>\s*([^<]+?)(?:<br|</div|</p|</b|$)', entry_meta_html, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
            else:
                legenda_match = re.search(r'(?i)Legenda\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|$)', entry_meta_html, re.DOTALL)
                if legenda_match:
                    legenda = legenda_match.group(1).strip()
                    legenda = html.unescape(legenda)
                    legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                    legenda = re.sub(r'\s+', ' ', legenda).strip()
        
        if idioma and legenda:
            break
    
    return idioma, legenda

def _extract_audio_legenda_comand(doc: BeautifulSoup, content_div: Optional[BeautifulSoup] = None) -> Tuple[str, str]:
    """Comando: Extrai "Áudio" e "Legenda" do HTML (similar ao bludv mas com stop_words diferentes)"""
    audio_text = ''
    legenda = ''
    
    if not content_div:
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')
    
    if content_div:
        content_html = str(content_div)
        
        audio_patterns = [
            r'(?i)Áudio\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|$)',
            r'(?i)Audio\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|$)',
        ]
        
        for pattern in audio_patterns:
            audio_match = re.search(pattern, content_html, re.DOTALL)
            if audio_match:
                audio_text = audio_match.group(1).strip()
                audio_text = html.unescape(audio_text)
                audio_text = re.sub(r'<[^>]+>', '', audio_text).strip()
                audio_text = re.sub(r'\s+', ' ', audio_text).strip()
                stop_words = ['Legenda', 'Canais', 'Fansub', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho', 'IMDb', 'Status']
                for stop_word in stop_words:
                    if stop_word in audio_text:
                        idx = audio_text.index(stop_word)
                        audio_text = audio_text[:idx].strip()
                        break
                if audio_text:
                    break
        
        legenda_patterns = [
            r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Canais|Fansub|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Áudio|Audio|Status|$)',
            r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Canais|Fansub|Qualidade|$)',
            r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
        ]
        
        for pattern in legenda_patterns:
            legenda_match = re.search(pattern, content_html, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Canais', 'Fansub', 'Qualidade', 'Duração', 'Formato', 'Status']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    break
    
    return audio_text, legenda

SCRAPER_AUDIO_LEGENDA_EXTRACTORS: Dict[str, Callable] = {
    'bludv': _extract_audio_legenda_bludv,
    'rede': _extract_audio_legenda_rede,
    'xfilmes': _extract_audio_legenda_baixafilmes,
    'comand': _extract_audio_legenda_comand,
}

def extract_audio_legenda_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None, **kwargs) -> Tuple[str, str]:
    if scraper_type and scraper_type in SCRAPER_AUDIO_LEGENDA_EXTRACTORS:
        extractor = SCRAPER_AUDIO_LEGENDA_EXTRACTORS[scraper_type]
        try:
            audio, legenda = extractor(doc, **kwargs)
            if audio or legenda:
                return audio, legenda
        except Exception as e:
            logger.debug(f"Erro ao extrair áudio/legenda com regra específica do scraper {scraper_type}: {e}")
    
    for extractor in SCRAPER_AUDIO_LEGENDA_EXTRACTORS.values():
        try:
            audio, legenda = extractor(doc, **kwargs)
            if audio or legenda:
                return audio, legenda
        except Exception:
            continue
    

    return '', ''

def determine_audio_info(idioma: str, legenda: str = '', magnet_processed: Optional[str] = None, info_hash: Optional[str] = None, skip_metadata: bool = False) -> Optional[str]:
    """Determina audio_info baseado em idioma/áudio extraído com fallbacks"""
    
    if idioma:
        idioma_lower = idioma.lower()
        
        has_portugues_audio = (
            'português' in idioma_lower or 'portugues' in idioma_lower or 
            'pt-br' in idioma_lower or 'ptbr' in idioma_lower or 
            'pt br' in idioma_lower
        )
        
        has_ingles_audio = 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower or 'en' in idioma_lower
        
        has_japones_audio = 'japonês' in idioma_lower or 'japones' in idioma_lower or 'japanese' in idioma_lower or 'jap' in idioma_lower
        
        if has_portugues_audio and has_ingles_audio:
            return 'dual'
        
        if has_portugues_audio:
            return 'português'
        
        if has_japones_audio:
            return 'japonês'
    
    if magnet_processed:
        release_lower = magnet_processed.lower()
        if 'dual' in release_lower or 'dublado' in release_lower or 'nacional' in release_lower or 'portugues' in release_lower or 'português' in release_lower:
            if 'dual' in release_lower:
                return 'dual'
            return 'português'
    
    if info_hash and not skip_metadata:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'dual' in metadata_name or 'dublado' in metadata_name or 'nacional' in metadata_name or 'portugues' in metadata_name or 'português' in metadata_name:
                    if 'dual' in metadata_name:
                        return 'dual'
                    return 'português'
        except Exception:
            pass
    
    if info_hash and not skip_metadata:
        try:
            from utils.text.cross_data import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'dual' in cross_release_lower or 'dublado' in cross_release_lower or 'nacional' in cross_release_lower or 'portugues' in cross_release_lower or 'português' in cross_release_lower:
                        if 'dual' in cross_release_lower:
                            return 'dual'
                        return 'português'
        except Exception:
            pass
    
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

