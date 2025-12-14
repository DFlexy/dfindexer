"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, unquote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.constants import STOP_WORDS
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.parsing.audio_extraction import add_audio_tag_if_needed
from utils.text.title_builder import create_standardized_title, prepare_release_title
from utils.logging import format_error, format_link_preview

logger = logging.getLogger(__name__)


# Scraper específico para Comando Torrents
class ComandScraper(BaseScraper):
    SCRAPER_TYPE = "comand"
    DEFAULT_BASE_URL = "https://comando.la/"
    DISPLAY_NAME = "Comando"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
        
        # Mapeamento de meses em português para números
        self.month_replacer = {
            'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
            'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
            'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12'
        }
    
    # Faz parsing de data localizada em português (ex: "16 de novembro de 2025")
    def _parse_localized_date(self, date_text: str) -> Optional[datetime]:
        # Padrão: "16 de novembro de 2025" ou "1 de novembro de 2025"
        pattern = r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})'
        match = re.search(pattern, date_text, re.IGNORECASE)
        if match:
            day = match.group(1).zfill(2)  # Adiciona zero à esquerda se necessário
            month_name = match.group(2).lower()
            year = match.group(3)
            
            # Converte nome do mês para número
            month = self.month_replacer.get(month_name)
            if month:
                # Formata como YYYY-MM-DD
                date_str = f"{year}-{month}-{day}"
                try:
                    date = datetime.strptime(date_str, '%Y-%m-%d')
                    # Retorna sem timezone (consistente com outros scrapers)
                    return date
                except ValueError:
                    pass
        return None
    
    # Busca torrents com variações da query
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        return self._default_search(query, filter_func)
    
    # Extrai links da página inicial
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        # Busca artigos na página
        for article in doc.select('article.post'):
            link_elem = article.select_one('header.entry-header h1.entry-title a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        
        # Se não encontrou com seletor específico, tenta alternativo
        if not links:
            for article in doc.select('article'):
                link_elem = article.select_one('h1.entry-title a, header.entry-header a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        # Converte URL relativa para absoluta
                        absolute_url = urljoin(self.base_url, href)
                        links.append(absolute_url)
        
        return links
    
    # Obtém torrents de uma página específica
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        return self._default_get_page(page, max_items)
    
    # Busca com variações da query
    def _search_variations(self, query: str) -> List[str]:
        links = []
        variations = [query]
        
        # Remove stop words
        words = [w for w in query.split() if w.lower() not in STOP_WORDS]
        if words and ' '.join(words) != query:
            variations.append(' '.join(words))
        
        # Primeira palavra (se não for stop word)
        query_words = query.split()
        if len(query_words) > 1:
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])
        
        for variation in variations:
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue
            
            # Busca artigos nos resultados
            for article in doc.select('article.post'):
                link_elem = article.select_one('header.entry-header h1.entry-title a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        # Converte URL relativa para absoluta
                        absolute_url = urljoin(self.base_url, href)
                        links.append(absolute_url)
            
            # Se não encontrou com seletor específico, tenta alternativo
            if not links:
                for article in doc.select('article'):
                    link_elem = article.select_one('h1.entry-title a, header.entry-header a')
                    if link_elem:
                        href = link_elem.get('href')
                        if href:
                            links.append(href)
        
        return list(set(links))  # Remove duplicados
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        # Garante que o link seja absoluto para o campo details
        from urllib.parse import urljoin
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        # Extrai data: primeiro tenta método específico (português), depois URL + HTML padrão
        date = None
        
        # Tentativa 1: Extrai data de div.entry-date[itemprop="datePublished"] (método específico do site)
        date_elem = doc.find('div', {'class': 'entry-date', 'itemprop': 'datePublished'})
        if date_elem:
            # Busca o link <a> dentro do div que contém a data em português
            date_link = date_elem.find('a')
            if date_link:
                date_text = date_link.get_text(strip=True)
                # Tenta fazer parsing de data localizada em português (ex: "16 de novembro de 2025")
                try:
                    date = self._parse_localized_date(date_text)
                except (ValueError, AttributeError):
                    pass
        
        # Tentativa 2: Se não encontrou, usa método padrão (URL + meta tags + elementos HTML)
        if not date:
            from utils.parsing.date_extraction import extract_date_from_page
            date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        article = doc.find('article')
        if not article:
            return []
        
        # Extrai título da página (h1.entry-title)
        page_title = ''
        title_elem = article.select_one('h1.entry-title, header.entry-header h1.entry-title')
        if title_elem:
            title_link = title_elem.find('a')
            if title_link:
                page_title = title_link.get_text(strip=True)
            else:
                page_title = title_elem.get_text(strip=True)
        
        # Extrai título original e outras informações do entry-content
        original_title = ''
        year = ''
        sizes = []
        imdb = ''
        
        entry_content = article.select_one('div.entry-content')
        if entry_content:
            # Busca título original - tenta múltiplos padrões
            html_content = str(entry_content)
            
            # Padrão 1: HTML com tags <strong>Título Original</strong>: texto<br />
            # Aceita "Título" (com acento) ou "Titulo" (sem acento)
            # Exemplo: <strong>Título Original</strong>: Rogue One<br />
            # Para antes de <span, <br, </p, </strong, ou palavras-chave
            # Captura até encontrar <span, <br, </p, </strong ou fim da string
            title_original_match = re.search(
                r'<strong>T[íi]tulo Original</strong>\s*[:\s]\s*(?:<br\s*/?>)?\s*([^<]+?)(?=<span|<br|</p|</strong|Gênero|Sinopse|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|TEMPORADA|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if title_original_match:
                original_title = title_original_match.group(1).strip()
                # Remove tags HTML restantes que possam ter sido capturadas
                original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                # Decodifica entidades HTML (&#8211; vira –, etc.)
                original_title = html.unescape(original_title)
                # Remove quebras de linha e espaços extras
                original_title = re.sub(r'\s+', ' ', original_title).strip()
                # Para antes de encontrar palavras de parada (Sinopse, Gênero, etc.)
                stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                for stop_word in stop_words:
                    if stop_word in original_title:
                        idx = original_title.index(stop_word)
                        original_title = original_title[:idx].strip()
                        break
                # Limita o tamanho máximo do título (200 caracteres)
                if len(original_title) > 200:
                    original_title = original_title[:200].strip()
                # Remove caracteres especiais do final (mas mantém dois pontos e traços no meio)
                original_title = original_title.rstrip(' .,:;')
            
            # Padrão 2: HTML com tags <b>Título Original:</b> texto<br />
            # Aceita "Título" (com acento) ou "Titulo" (sem acento)
            # Exemplo: <b>Título Original:</b> The Witcher: Blood Origin<br />
            if not original_title:
                title_original_match = re.search(
                    r'<b>T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<span|<br|</p|</b|<strong|Gênero|Sinopse|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|TEMPORADA|$)',
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    # Remove tags HTML restantes que possam ter sido capturadas
                    original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                    # Decodifica entidades HTML
                    original_title = html.unescape(original_title)
                    # Remove quebras de linha e espaços extras
                    original_title = re.sub(r'\s+', ' ', original_title).strip()
                    # Para antes de encontrar palavras de parada (Sinopse, Gênero, etc.)
                    stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                    for stop_word in stop_words:
                        if stop_word in original_title:
                            idx = original_title.index(stop_word)
                            original_title = original_title[:idx].strip()
                            break
                    # Limita o tamanho máximo do título (200 caracteres)
                    if len(original_title) > 200:
                        original_title = original_title[:200].strip()
                    # Remove caracteres especiais do final (mas mantém dois pontos e traços no meio)
                    original_title = original_title.rstrip(' .,:;')
            
            # Padrão 3: HTML sem tag <b> inicial, mas com </b> antes do texto
            # Exemplo: Titulo Original:</b> One Battle After Another<br />
            if not original_title:
                title_original_match = re.search(
                    r'T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|</b|<strong|Gênero|Sinopse|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|$)',
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                    original_title = html.unescape(original_title)
                    original_title = re.sub(r'\s+', ' ', original_title).strip()
                    # Para antes de encontrar palavras de parada (Sinopse, Gênero, etc.)
                    stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido']
                    for stop_word in stop_words:
                        if stop_word in original_title:
                            idx = original_title.index(stop_word)
                            original_title = original_title[:idx].strip()
                            break
                    original_title = original_title.rstrip(' .,:;-')
            
            # Padrão 4: Busca usando BeautifulSoup para encontrar o texto após "Título Original"
            if not original_title:
                # Procura por elementos que contenham "Título Original" ou "Titulo Original"
                for elem in entry_content.find_all(['b', 'strong', 'p', 'span']):
                    text = elem.get_text()
                    if re.search(r'T[íi]tulo Original', text, re.IGNORECASE):
                        # Pega o próximo elemento ou o texto após
                        next_elem = elem.find_next_sibling()
                        if next_elem:
                            original_title = next_elem.get_text(strip=True)
                        else:
                            # Tenta extrair do próprio elemento
                            html_elem = str(elem)
                            match = re.search(r'T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+)', html_elem, re.IGNORECASE | re.DOTALL)
                            if match:
                                original_title = match.group(1).strip()
                                original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                                original_title = html.unescape(original_title)
                        if original_title:
                            original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                            # Decodifica entidades HTML
                            original_title = html.unescape(original_title)
                            original_title = re.sub(r'\s+', ' ', original_title).strip()
                            # Para antes de encontrar palavras de parada (Sinopse, Gênero, etc.)
                            stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                            for stop_word in stop_words:
                                if stop_word in original_title:
                                    idx = original_title.index(stop_word)
                                    original_title = original_title[:idx].strip()
                                    break
                            # Limita o tamanho máximo do título (200 caracteres)
                            if len(original_title) > 200:
                                original_title = original_title[:200].strip()
                            original_title = original_title.rstrip(' .,:;')
                            break
            
            # Padrão 5: Texto puro (fallback final)
            if not original_title:
                content_text = entry_content.get_text()
                title_original_match = re.search(
                    r'T[íi]tulo Original[:\s]+([^\n]+?)(?:\n|Sinopse|Gênero|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|TEMPORADA|Temporada|$)',
                    content_text,
                    re.IGNORECASE
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    # Decodifica entidades HTML
                    original_title = html.unescape(original_title)
                    # Para antes de encontrar palavras de parada (Sinopse, Gênero, etc.)
                    stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                    for stop_word in stop_words:
                        if stop_word in original_title:
                            idx = original_title.index(stop_word)
                            original_title = original_title[:idx].strip()
                            break
                    # Limita o tamanho máximo do título (200 caracteres)
                    if len(original_title) > 200:
                        original_title = original_title[:200].strip()
                    # Remove caracteres especiais do final (mas mantém dois pontos e traços no meio)
                    original_title = original_title.rstrip(' .,:;')
            
            # Busca ano - tenta múltiplos padrões
            # Padrão 1: HTML com link <a>2025</a>
            lancamento_match = re.search(
                r'Lançamento[:\s]*</b>\s*<a[^>]*>(\d{4})</a>',
                html_content,
                re.IGNORECASE
            )
            if lancamento_match:
                year = lancamento_match.group(1).strip()
            
            # Padrão 2: Texto puro ou HTML sem link
            if not year:
                lancamento_match = re.search(
                    r'Lançamento[:\s]*</b>\s*(?:<br\s*/?>)?\s*(\d{4})',
                    html_content,
                    re.IGNORECASE
                )
                if lancamento_match:
                    year = lancamento_match.group(1).strip()
            
            # Padrão 3: Busca no texto geral usando find_year_from_text
            if not year:
                content_text = entry_content.get_text()
                y = find_year_from_text(content_text, page_title)
                if y:
                    year = y
            
            # Busca tamanhos - tenta múltiplos padrões
            # Padrão 1: Campo específico "Tamanho:"
            tamanho_match = re.search(
                r'Tamanho[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<\n]+?)(?:<br|</p|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if tamanho_match:
                tamanho_text = re.sub(r'<[^>]+>', '', tamanho_match.group(1)).strip()
                tamanho_text = html.unescape(tamanho_text)
                sizes.extend(find_sizes_from_text(tamanho_text))
            
            # Padrão 2: Busca no texto geral
            if not sizes:
                content_text = entry_content.get_text()
                sizes.extend(find_sizes_from_text(content_text))
            
            # Remove duplicados de tamanhos
            sizes = list(dict.fromkeys(sizes))
            
            # Busca IMDB - padrão específico do comando
            # Formato: <strong>IMDb</strong>:  <a href="https://www.imdb.com/title/tt19244304/" target="_blank" rel="noopener">8,0
            # Padrão 1: Busca <strong>IMDb</strong> seguido de link
            imdb_strong = entry_content.find('strong', string=re.compile(r'IMDb', re.I))
            if imdb_strong:
                # Procura link IMDB próximo ao <strong>IMDb</strong>
                parent = imdb_strong.parent
                if parent:
                    for a in parent.select('a[href*="imdb.com"]'):
                        href = a.get('href', '')
                        # Tenta padrão /pt/title/tt
                        imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                        if imdb_match:
                            imdb = imdb_match.group(1)
                            break
                        # Tenta padrão /title/tt
                        imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                        if imdb_match:
                            imdb = imdb_match.group(1)
                            break
            
            # Padrão 2: Se não encontrou, busca todos os links IMDB
            if not imdb:
                imdb_links = entry_content.select('a[href*="imdb.com"]')
                for imdb_link in imdb_links:
                    href = imdb_link.get('href', '')
                    # Tenta padrão pt/title/tt
                    imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                    if imdb_match:
                        imdb = imdb_match.group(1)
                        break
                    # Tenta padrão title/tt (sem /pt/)
                    imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                    if imdb_match:
                        imdb = imdb_match.group(1)
                        break
        
        # Extrai título traduzido
        translated_title = ''
        if entry_content:
            html_content = str(entry_content)
            
            # Padrão 1: HTML com tags <strong>Título Traduzido</strong>: texto<br />
            title_traduzido_match = re.search(
                r'<strong>T[íi]tulo Traduzido</strong>\s*[:\s]\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|</strong|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if title_traduzido_match:
                translated_title = title_traduzido_match.group(1).strip()
                translated_title = re.sub(r'<[^>]+>', '', translated_title).strip()
                translated_title = html.unescape(translated_title)
                translated_title = re.sub(r'\s+', ' ', translated_title).strip()
                translated_title = translated_title.rstrip(' .,:;-')
                # Limpa usando função auxiliar
                from utils.text.cleaning import clean_translated_title
                translated_title = clean_translated_title(translated_title)
            
            # Padrão 2: HTML com tags <b>Título Traduzido:</b> texto<br />
            if not translated_title:
                title_traduzido_match = re.search(
                    r'<b>T[íi]tulo Traduzido[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|$)', 
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_traduzido_match:
                    translated_title = title_traduzido_match.group(1).strip()
                    translated_title = re.sub(r'<[^>]+>', '', translated_title).strip()
                    translated_title = html.unescape(translated_title)
                    translated_title = re.sub(r'\s+', ' ', translated_title).strip()
                    translated_title = translated_title.rstrip(' .,:;-')
                    # Limpa usando função auxiliar
                    from utils.text.cleaning import clean_translated_title
                    translated_title = clean_translated_title(translated_title)
            
            # Padrão 3: Texto puro (fallback)
            if not translated_title:
                content_text = entry_content.get_text()
                title_traduzido_match = re.search(
                    r'T[íi]tulo Traduzido[:\s]+([^\n]+?)(?:\n|$)',
                    content_text,
                    re.IGNORECASE
                )
                if title_traduzido_match:
                    translated_title = title_traduzido_match.group(1).strip()
                    translated_title = translated_title.rstrip(' .,:;-')
        
        # Limpa o título traduzido se encontrou
        if translated_title:
            # Remove qualquer HTML que possa ter sobrado
            translated_title = re.sub(r'<[^>]+>', '', translated_title)
            translated_title = html.unescape(translated_title)
            from utils.text.cleaning import clean_translated_title
            translated_title = clean_translated_title(translated_title)
        
        # Se não encontrou título original, usa o título da página
        if not original_title:
            original_title = page_title
        
        # Extrai informações de áudio e legenda do HTML
        audio_info = None  # Para detectar áudio/idioma do HTML
        audio_html_content = ''  # Armazena HTML completo para verificação adicional
        all_paragraphs_html = []  # Coleta HTML de todos os parágrafos
        
        audio_text = ''
        legenda = ''
        
        if entry_content:
            # Primeiro tenta no HTML completo do entry_content
            content_html = str(entry_content)
            all_paragraphs_html.append(content_html)
            
            # Extrai Áudio/Idioma - busca primeiro no HTML completo
            # O site pode usar "Áudio:" ou "Idioma:" para indicar o idioma do áudio
            audio_patterns = [
                r'(?i)Áudio\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Canais|Fansub|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Status|$)',
                r'(?i)Audio\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Canais|Fansub|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Status|$)',
                r'(?i)Idioma\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Canais|Fansub|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Status|$)',
                r'(?i)<[^>]*>Áudio\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legenda|$)',
                r'(?i)<[^>]*>Audio\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legenda|$)',
                r'(?i)<[^>]*>Idioma\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legenda|$)',
            ]
            
            for pattern in audio_patterns:
                audio_match = re.search(pattern, content_html, re.DOTALL)
                if audio_match:
                    audio_text = audio_match.group(1).strip()
                    # Remove entidades HTML e tags
                    audio_text = html.unescape(audio_text)
                    audio_text = re.sub(r'<[^>]+>', '', audio_text).strip()
                    # Remove espaços extras e normaliza
                    audio_text = re.sub(r'\s+', ' ', audio_text).strip()
                    # Para antes de encontrar palavras de parada
                    stop_words = ['Legenda', 'Canais', 'Fansub', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho', 'IMDb', 'Status']
                    for stop_word in stop_words:
                        if stop_word in audio_text:
                            idx = audio_text.index(stop_word)
                            audio_text = audio_text[:idx].strip()
                            break
                    if audio_text:
                        break
            
            # Se não encontrou no HTML completo, busca nos elementos individuais
            if not audio_text:
                for elem in entry_content.find_all(['p', 'span', 'div', 'strong', 'em', 'li', 'b']):
                    elem_html = str(elem)
                    all_paragraphs_html.append(elem_html)
                    
                    for pattern in audio_patterns:
                        audio_match = re.search(pattern, elem_html, re.DOTALL)
                        if audio_match:
                            audio_text = audio_match.group(1).strip()
                            # Remove entidades HTML e tags
                            audio_text = html.unescape(audio_text)
                            audio_text = re.sub(r'<[^>]+>', '', audio_text).strip()
                            # Remove espaços extras e normaliza
                            audio_text = re.sub(r'\s+', ' ', audio_text).strip()
                            # Para antes de encontrar palavras de parada
                            stop_words = ['Legenda', 'Canais', 'Fansub', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho', 'IMDb', 'Status']
                            for stop_word in stop_words:
                                if stop_word in audio_text:
                                    idx = audio_text.index(stop_word)
                                    audio_text = audio_text[:idx].strip()
                                    break
                            if audio_text:
                                break
                    if audio_text:
                        break
            
            # Extrai Legenda - busca primeiro no HTML completo
            legenda_patterns = [
                r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Canais|Fansub|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Áudio|Audio|Status|$)',
                r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Canais|Fansub|Qualidade|$)',
                r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
            ]
            
            for pattern in legenda_patterns:
                legenda_match = re.search(pattern, content_html, re.DOTALL)
                if legenda_match:
                    legenda = legenda_match.group(1).strip()
                    # Remove entidades HTML e tags
                    legenda = html.unescape(legenda)
                    legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                    # Remove espaços extras e normaliza
                    legenda = re.sub(r'\s+', ' ', legenda).strip()
                    # Para antes de encontrar palavras de parada
                    stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Canais', 'Fansub', 'Qualidade', 'Duração', 'Formato', 'Status']
                    for stop_word in stop_words:
                        if stop_word in legenda:
                            idx = legenda.index(stop_word)
                            legenda = legenda[:idx].strip()
                            break
                    if legenda:
                        break
            
            # Se não encontrou no HTML completo, busca nos elementos individuais
            if not legenda:
                for elem in entry_content.find_all(['p', 'span', 'div', 'strong', 'em', 'li', 'b']):
                    elem_html = str(elem)
                    
                    for pattern in legenda_patterns:
                        legenda_match = re.search(pattern, elem_html, re.DOTALL)
                        if legenda_match:
                            legenda = legenda_match.group(1).strip()
                            # Remove entidades HTML e tags
                            legenda = html.unescape(legenda)
                            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                            # Remove espaços extras e normaliza
                            legenda = re.sub(r'\s+', ' ', legenda).strip()
                            # Para antes de encontrar palavras de parada
                            stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Canais', 'Fansub', 'Qualidade', 'Duração', 'Formato', 'Status']
                            for stop_word in stop_words:
                                if stop_word in legenda:
                                    idx = legenda.index(stop_word)
                                    legenda = legenda[:idx].strip()
                                    break
                            if legenda:
                                break
                    if legenda:
                        break
            
            # Concatena HTML de todos os parágrafos para verificação adicional
            if all_paragraphs_html:
                audio_html_content = ' '.join(all_paragraphs_html)
            
            # Determina audio_info baseado em Áudio e Legenda extraídos
            if audio_text or legenda:
                audio_lower = audio_text.lower() if audio_text else ''
                legenda_lower = legenda.lower() if legenda else ''
                
                # Verifica se tem português no áudio (PT-BR é considerado português)
                has_portugues_audio = (
                    'português' in audio_lower or 'portugues' in audio_lower or 
                    'pt-br' in audio_lower or 'ptbr' in audio_lower or 
                    'pt br' in audio_lower
                )
                # Verifica se tem português na legenda (PT-BR é considerado português)
                has_portugues_legenda = (
                    'português' in legenda_lower or 'portugues' in legenda_lower or 
                    'pt-br' in legenda_lower or 'ptbr' in legenda_lower or 
                    'pt br' in legenda_lower
                )
                # Verifica se tem Japonês no áudio
                has_japones_audio = 'japonês' in audio_lower or 'japones' in audio_lower or 'japanese' in audio_lower or 'jap' in audio_lower
                # Verifica se tem Inglês no áudio
                has_ingles_audio = 'inglês' in audio_lower or 'ingles' in audio_lower or 'english' in audio_lower or 'en' in audio_lower
                # Verifica se tem Inglês em qualquer lugar
                has_ingles = has_ingles_audio or 'inglês' in legenda_lower or 'ingles' in legenda_lower or 'english' in legenda_lower
                
                # Verifica se tem múltiplos idiomas no áudio (separados por | ou ,)
                has_multiple_audio = '|' in audio_text or ',' in audio_text or ' e ' in audio_lower or ' and ' in audio_lower
                
                # Lógica: Se tem português E inglês no áudio → DUAL (gera [Brazilian] e [Eng])
                if has_portugues_audio and has_ingles_audio:
                    audio_info = 'dual'
                # Se tem português E outro idioma (chinês, espanhol, etc.) → também é DUAL (gera [Brazilian])
                elif has_portugues_audio and has_multiple_audio:
                    audio_info = 'dual'  # Trata como DUAL quando tem português + outro idioma
                # Se tem apenas português no áudio → gera [Brazilian]
                elif has_portugues_audio:
                    audio_info = 'português'
                # Se tem japonês no áudio → gera [Jap]
                elif has_japones_audio:
                    audio_info = 'japonês'
                # Se tem legenda PT-BR (português) OU tem Inglês → gera [Leg]
                # PT-BR na legenda indica que o áudio é em outro idioma (geralmente inglês ou japonês) com legenda em português
                elif has_portugues_legenda or has_ingles:
                    audio_info = 'legendado'
        
        # Extrai links magnet - busca TODOS os links <a> no entry-content
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        magnet_links = []
        if entry_content:
            for link in entry_content.select('a[href]'):
                href = link.get('href', '')
                if not href:
                    continue
                
                # Resolve automaticamente (magnet direto ou protegido)
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet and resolved_magnet.startswith('magnet:') and resolved_magnet not in magnet_links:
                    magnet_links.append(resolved_magnet)
        
        if not magnet_links:
            return []
        
        # Processa cada magnet
        # IMPORTANTE: magnet_link já é o magnet resolvido (links protegidos foram resolvidos antes)
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                # Busca dados cruzados no Redis por info_hash (fallback principal)
                cross_data = None
                try:
                    from utils.text.cross_data import get_cross_data_from_redis
                    cross_data = get_cross_data_from_redis(info_hash)
                except Exception:
                    pass
                
                # Preenche campos faltantes com dados cruzados do Redis
                if cross_data:
                    if not original_title and cross_data.get('original_title_html'):
                        original_title = cross_data['original_title_html']
                    
                    if not translated_title and cross_data.get('translated_title_html'):
                        translated_title = cross_data['translated_title_html']
                    
                    if not imdb and cross_data.get('imdb'):
                        imdb = cross_data['imdb']
                
                # Extrai raw_release_title diretamente do display_name do magnet resolvido
                # NÃO modificar antes de passar para create_standardized_title
                raw_release_title = magnet_data.get('display_name', '')
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                
                # Se ainda está missing_dn, tenta buscar do cross_data
                if missing_dn and cross_data and cross_data.get('release_title_magnet'):
                    raw_release_title = cross_data['release_title_magnet']
                    missing_dn = False
                
                # Salva release_title_magnet no Redis se encontrado (para reutilização por outros scrapers)
                if not missing_dn and raw_release_title:
                    try:
                        from utils.text.storage import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, raw_release_title)
                    except Exception:
                        pass
                
                fallback_title = original_title if original_title else page_title
                original_release_title = prepare_release_title(
                    raw_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title, translated_title_html=translated_title if translated_title else None, raw_release_title_magnet=raw_release_title
                )
                
                # Adiciona [Brazilian] se detectar DUAL/DUBLADO/NACIONAL, [Eng] se LEGENDADO, [Jap] se JAPONÊS, ou ambos se houver os dois
                # Passa audio_info extraído do HTML (Áudio/Legenda) e audio_html_content para detecção adicional
                final_title = add_audio_tag_if_needed(
                    standardized_title, 
                    original_release_title, 
                    info_hash=info_hash, 
                    skip_metadata=self._skip_metadata,
                    audio_info_from_html=audio_info,
                    audio_html_content=audio_html_content
                )
                
                # Determina origem_audio_tag
                origem_audio_tag = 'N/A'
                if raw_release_title and ('dual' in raw_release_title.lower() or 'dublado' in raw_release_title.lower() or 'legendado' in raw_release_title.lower()):
                    origem_audio_tag = 'release_title_magnet'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                # Extrai tamanho do magnet se disponível
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Processa trackers usando função utilitária
                trackers = process_trackers(magnet_data)
                
                # Salva dados cruzados no Redis para reutilização por outros scrapers
                try:
                    from utils.text.cross_data import save_cross_data_to_redis
                    cross_data_to_save = {
                        'original_title_html': original_title if original_title else None,
                        'release_title_magnet': raw_release_title if not missing_dn else None,
                        'translated_title_html': translated_title if translated_title else None,
                        'imdb': imdb if imdb else None,
                        'missing_dn': missing_dn,
                        'origem_audio_tag': origem_audio_tag if origem_audio_tag != 'N/A' else None,
                        'size': size if size and size.strip() else None
                    }
                    save_cross_data_to_redis(info_hash, cross_data_to_save)
                except Exception:
                    pass
                
                torrent = {
                    'title': final_title,
                    'original_title': original_title if original_title else page_title,
                    'translated_title': translated_title if translated_title else None,
                    'details': absolute_link,
                    'year': year,
                    'imdb': imdb,
                    'audio': [],
                    'magnet_link': magnet_link,
                    'date': date.strftime('%Y-%m-%dT%H:%M:%SZ') if date else '',
                    'info_hash': info_hash,
                    'trackers': trackers,
                    'size': size,
                    'leech_count': 0,
                    'seed_count': 0,
                    'similarity': 1.0
                }
                torrents.append(torrent)
            
            except Exception as e:
                logger.error(f"Magnet error: {format_error(e)} (link: {format_link_preview(magnet_link)})")
                continue
        
        return torrents

