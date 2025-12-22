"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import html
import logging
from typing import Optional, Dict, Tuple, Callable
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ============================================================================
# REGRAS ESPECÍFICAS POR SCRAPER - Extração de Áudio/Idioma
# NOTA: Extração de Legenda foi movida para utils/parsing/legend_extraction.py
# ============================================================================

def _extract_audio_legenda_bludv(doc: BeautifulSoup, content_div: Optional[BeautifulSoup] = None) -> Tuple[str, str]:
    """
    Bludv: Extrai "Áudio" e "Legenda" do HTML.
    DEPRECATED: Legenda foi movida para utils/parsing/legend_extraction.py
    Mantida apenas para compatibilidade.
    """
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
        
        # Extrai Áudio
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
        
        # Extrai Legenda
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
    """
    Rede: Extrai "Idioma" e "Legenda" de div#informacoes.
    DEPRECATED: Legenda foi movida para utils/parsing/legend_extraction.py
    Mantida apenas para compatibilidade.
    """
    idioma = ''
    legenda = ''
    
    if not article:
        article = doc.find('div', class_='conteudo')
    
    if article:
        info_div = article.find('div', id='informacoes')
        if info_div:
            info_html = str(info_div)
            
            # Extrai Idioma
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
            
            # Extrai Legenda
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
    """
    XFilmes: Extrai "Idioma" e "Legenda" de div.entry-meta.
    Nome da função mantido por compatibilidade histórica (anteriormente usado por baixafilmes).
    DEPRECATED: Legenda foi movida para utils/parsing/legend_extraction.py
    Mantida apenas para compatibilidade.
    """
    idioma = ''
    legenda = ''
    
    if not entry_meta_list:
        entry_meta_list = doc.find_all('div', class_='entry-meta')
    
    for entry_meta in entry_meta_list:
        entry_meta_html = str(entry_meta)
        
        # Extrai Idioma
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
        
        # Extrai Legenda
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
    """
    Comando: Extrai "Áudio" e "Legenda" do HTML (similar ao bludv mas com stop_words diferentes).
    DEPRECATED: Legenda foi movida para utils/parsing/legend_extraction.py
    Mantida apenas para compatibilidade.
    """
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
        
        # Extrai Áudio (mesmos padrões do bludv)
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
        
        # Extrai Legenda
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


# Mapeamento de scrapers para suas funções de extração específicas
SCRAPER_AUDIO_LEGENDA_EXTRACTORS: Dict[str, Callable] = {
    'bludv': _extract_audio_legenda_bludv,
    'rede': _extract_audio_legenda_rede,
    'xfilmes': _extract_audio_legenda_baixafilmes,  # XFilmes usa esta função
    'comand': _extract_audio_legenda_comand,
}


# ============================================================================
# FUNÇÕES GENÉRICAS DE EXTRAÇÃO
# ============================================================================

def extract_audio_legenda_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None, **kwargs) -> Tuple[str, str]:
    """
    Extrai informações de áudio/idioma e legenda do HTML.
    DEPRECATED: Legenda foi movida para utils/parsing/legend_extraction.py
    Use extract_legenda_from_page() para legenda e esta função apenas para compatibilidade.
    
    Args:
        doc: Documento BeautifulSoup
        scraper_type: Tipo do scraper para usar regra específica
        **kwargs: Argumentos adicionais específicos do scraper (content_div, article, entry_meta_list, etc.)
    
    Returns:
        Tupla (audio/idioma, legenda) - strings vazias se não encontrar
    """
    # Tenta primeiro com regra específica do scraper
    if scraper_type and scraper_type in SCRAPER_AUDIO_LEGENDA_EXTRACTORS:
        extractor = SCRAPER_AUDIO_LEGENDA_EXTRACTORS[scraper_type]
        try:
            audio, legenda = extractor(doc, **kwargs)
            if audio or legenda:
                return audio, legenda
        except Exception as e:
            logger.debug(f"Erro ao extrair áudio/legenda com regra específica do scraper {scraper_type}: {e}")
    
    # Fallback: tenta todas as regras específicas
    for extractor in SCRAPER_AUDIO_LEGENDA_EXTRACTORS.values():
        try:
            audio, legenda = extractor(doc, **kwargs)
            if audio or legenda:
                return audio, legenda
        except Exception:
            continue
    
    # Último fallback: busca genérica
    return '', ''


def determine_audio_info(idioma: str, legenda: str = '', magnet_processed: Optional[str] = None, info_hash: Optional[str] = None, skip_metadata: bool = False) -> Optional[str]:
    """
    Determina audio_info baseado em idioma/áudio extraído com fallbacks.
    NOTA: Parâmetro legenda mantido para compatibilidade, mas não é mais usado.
    Legenda é tratada separadamente em utils/parsing/legend_extraction.py
    
    Lógica de Audio:
    1. FONTE PRINCIPAL: HTML (audio_info: 'Coletar o que está no campo')
    2. FALLBACK 1: Magnet (dual/dublado/nacional/portugues) → marca Português, Inglês
    3. FALLBACK 2: Metadata
    4. FALLBACK 3: Cross Data
    
    Args:
        idioma: Texto extraído do campo "Idioma" ou "Áudio" (HTML)
        legenda: DEPRECATED - não é mais usado, mantido apenas para compatibilidade
        magnet_processed: Nome do magnet processado para fallback
        info_hash: Hash do torrent para fallbacks (metadata e cross_data)
        skip_metadata: Se True, pula busca em metadata
    
    Returns:
        'dual', 'português', 'japonês', ou None
    """
    # ============================================================================
    # FONTE PRINCIPAL: HTML (audio_info: 'Coletar o que está no campo')
    # ============================================================================
    
    if idioma:
        idioma_lower = idioma.lower()
        
        # Verifica se tem português no idioma/áudio
        has_portugues_audio = (
            'português' in idioma_lower or 'portugues' in idioma_lower or 
            'pt-br' in idioma_lower or 'ptbr' in idioma_lower or 
            'pt br' in idioma_lower
        )
        
        # Verifica se tem Inglês no idioma/áudio
        has_ingles_audio = 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower or 'en' in idioma_lower
        
        # Verifica se tem Japonês no idioma/áudio
        has_japones_audio = 'japonês' in idioma_lower or 'japones' in idioma_lower or 'japanese' in idioma_lower or 'jap' in idioma_lower
        
        # Lógica de determinação:
        # 1. Se tem português E inglês no idioma/áudio → DUAL
        if has_portugues_audio and has_ingles_audio:
            return 'dual'
        
        # 2. Se tem apenas português no idioma/áudio → português
        if has_portugues_audio:
            return 'português'
        
        # 3. Se tem japonês no idioma/áudio → japonês
        if has_japones_audio:
            return 'japonês'
    
    # ============================================================================
    # FALLBACK 1: Magnet (dual/dublado/nacional/portugues) → marca Português, Inglês
    # ============================================================================
    
    if magnet_processed:
        release_lower = magnet_processed.lower()
        if 'dual' in release_lower or 'dublado' in release_lower or 'nacional' in release_lower or 'portugues' in release_lower or 'português' in release_lower:
            # Se tem dual, marca Português, Inglês (dual)
            if 'dual' in release_lower:
                return 'dual'
            # Se tem dublado/nacional/portugues, marca apenas português
            return 'português'
    
    # ============================================================================
    # FALLBACK 2: Metadata
    # ============================================================================
    
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
    
    # ============================================================================
    # FALLBACK 3: Cross Data
    # ============================================================================
    
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


# ============================================================================
# FUNÇÕES DE DETECÇÃO E MANIPULAÇÃO DE TAGS DE ÁUDIO
# ============================================================================

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
    # Verifica se tem "Inglês" no áudio/idioma (não apenas na legenda)
    has_ingles_audio = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*.*(?:Inglês|Ingles|English)', html_content)
    has_ingles = re.search(r'(?i)Inglês|Ingles|English', html_content)
    
    # Verifica se tem "Legendado" na legenda (sem português no áudio)
    has_legenda_legendado = re.search(r'(?i)Legenda\s*:?\s*.*Legendado', html_content)
    has_legenda_ingles = re.search(r'(?i)Legenda\s*:?\s*.*(?:Inglês|Ingles|English)', html_content)
    # Verifica se tem português na legenda (PT-BR, Português, etc.)
    has_legenda_portugues = re.search(r'(?i)Legenda\s*:?\s*.*(?:PT-BR|PTBR|Português|Portugues|PT)', html_content)
    
    # Se tem português no áudio
    if has_portugues:
        if has_multi or has_ingles_audio or has_ingles:
            # Tem português E multi-áudio/inglês = DUAL
            return 'dual'
        else:
            # Apenas português
            return 'português'
    
    # Se tem inglês no áudio/idioma E legenda em português → legendado (mas também indica inglês)
    if has_ingles_audio and has_legenda_portugues:
        return 'legendado'  # Será tratado como legendado, mas add_audio_tag_if_needed detectará inglês
    
    # Se não tem português no áudio, mas tem legendado na legenda (PT-BR, Legendado, ou Inglês)
    if has_legenda_legendado or has_legenda_portugues or (has_legenda_ingles and not has_portugues):
        return 'legendado'
    
    return None


def add_audio_tag_if_needed(title: str, magnet_processed: str, info_hash: Optional[str] = None, skip_metadata: bool = False, audio_info_from_html: Optional[str] = None, audio_html_content: Optional[str] = None) -> str:
    """
    Acrescenta tags de idioma [Brazilian], [Eng], [Jap] quando detectadas.
    NOTA: Tag [Leg] foi removida conforme especificação.
    
    Lógica de detecção de áudio:
    1. HTML (audio_info: 'Coletar o que está no campo') - usa o valor diretamente
    2. LINK do html contém DUAL → marca Português, Inglês
    3. Nome Magnet processado (dual/dublado/nacional/portugues) → marca Português, Inglês
    4. Metadata
    5. Cross Data
    """
    # Remove apenas as tags que queremos usar antes de processar
    title = title.replace('[Brazilian]', '').replace('[Eng]', '').replace('[Jap]', '')
    title = re.sub(r'\s+', ' ', title).strip()
    
    # Verifica se já tem as tags corretas no título
    has_brazilian = '[Brazilian]' in title
    has_eng = '[Eng]' in title
    has_jap = '[Jap]' in title
    
    # Flags de detecção
    has_brazilian_audio = False
    has_eng_audio = False
    has_japones_audio = False
    
    # ============================================================================
    # TAG [Brazilian]
    # FONTE PRINCIPAL: HTML (audio_info: 'português')
    # ============================================================================
    
    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        # Para [Brazilian]: detecta apenas 'português' explicitamente
        if 'português' in audio_info_str or 'portugues' in audio_info_str:
            has_brazilian_audio = True
    
    # FALLBACK 1: Magnet (dual/dublado/nacional/portugues)
    if magnet_processed and not has_brazilian_audio:
        release_lower = magnet_processed.lower()
        if 'dual' in release_lower or 'dublado' in release_lower or 'nacional' in release_lower or 'portugues' in release_lower or 'português' in release_lower:
            has_brazilian_audio = True
    
    # FALLBACK 2: Metadata
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
    
    # FALLBACK 3: Cross Data
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
    
    # ============================================================================
    # TAG [Eng]
    # FONTE PRINCIPAL: HTML (audio_info: Inglês)
    # ============================================================================
    
    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        if 'inglês' in audio_info_str or 'ingles' in audio_info_str or 'english' in audio_info_str:
            has_eng_audio = True
    
    # FALLBACK 1: Magnet (dual/legendado/legenda/leg)
    if magnet_processed and not has_eng_audio:
        release_lower = magnet_processed.lower()
        if 'dual' in release_lower or 'legendado' in release_lower or 'legenda' in release_lower or re.search(r'\bleg\b', release_lower):
            has_eng_audio = True
    
    # FALLBACK 2: Metadata
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
    
    # FALLBACK 3: Cross Data
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
    
    # ============================================================================
    # TAG [Jap]
    # FONTE PRINCIPAL: HTML (audio_info: 'japonês')
    # ============================================================================
    
    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        if 'japonês' in audio_info_str or 'japones' in audio_info_str or 'japanese' in audio_info_str or 'jap' in audio_info_str:
            has_japones_audio = True
    
    # FALLBACK 1: Magnet (japonês/japones/japanese/jap)
    if magnet_processed and not has_japones_audio:
        release_lower = magnet_processed.lower()
        if 'japonês' in release_lower or 'japones' in release_lower or 'japanese' in release_lower or re.search(r'\bjap\b', release_lower):
            has_japones_audio = True
    
    # FALLBACK 2: Metadata
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
    
    # FALLBACK 3: Cross Data
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
    
    # ============================================================================
    # ADICIONA TAGS CONFORME DETECTADO
    # ============================================================================
    
    tags_to_add = []
    if has_brazilian_audio and not has_brazilian:
        tags_to_add.append('[Brazilian]')
    if has_eng_audio and not has_eng:
        tags_to_add.append('[Eng]')
    if has_japones_audio and not has_jap:
        tags_to_add.append('[Jap]')
    
    # Remove palavras do título se as tags correspondentes foram adicionadas
    if tags_to_add:
        # Remove DUAL se [Brazilian] ou [Eng] foi adicionado
        if '[Brazilian]' in tags_to_add or '[Eng]' in tags_to_add:
            # Remove DUAL standalone
            # IMPORTANTE: NÃO remove DUAL.5.1, DUAL.2.0 ou DUAL.7.1 (são informações técnicas de áudio)
            title = re.sub(r'\.?\.?DUAL(?![\.\s]?(?:5\.1|2\.0|7\.1))\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        # Remove DUBLADO, NACIONAL, PORTUGUES se [Brazilian] foi adicionado
        if '[Brazilian]' in tags_to_add:
            title = re.sub(r'\.?\.?DUBLADO\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?NACIONAL\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?PORTUGUES\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?PORTUGUÊS\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        # Remove JAPONÊS, JAPONES, JAPANESE, JAP se [Jap] foi adicionado
        if '[Jap]' in tags_to_add:
            title = re.sub(r'\.?\.?JAPONÊS\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAPONES\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAPANESE\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAP\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        # Remove LEGENDADO, LEGENDA, LEG (mesmo que não adicione [Leg])
        title = re.sub(r'\.?\.?LEGENDADO\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.?\.?LEGENDA\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.?\.?LEG\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.{2,}', '.', title)
        title = title.strip('.')
        
        title = title.rstrip()
        title = f"{title} {' '.join(tags_to_add)}"

    result = title
    return result

