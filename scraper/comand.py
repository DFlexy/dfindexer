"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable
from urllib.parse import unquote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
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
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None, skip_trackers: bool = False) -> List[Dict]:
        return self._default_search(query, filter_func, skip_trackers=skip_trackers)
    
    # Extrai links da página inicial
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        # Busca artigos na página - estrutura real: article > h2.entry-title > a
        for article in doc.select('article'):
            # Tenta primeiro o seletor correto: h2.entry-title a
            link_elem = article.select_one('h2.entry-title a')
            if not link_elem:
                # Fallback: tenta outros seletores
                link_elem = article.select_one('header.entry-header h1.entry-title a, h1.entry-title a, header.entry-header a')
            
            if link_elem:
                href = link_elem.get('href')
                if href:
                    # Converte URL relativa para absoluta
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    links.append(href)
        
        return links
    
    # Obtém torrents de uma página específica
    # Obtém torrents de uma página específica
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
    # Extrai links dos resultados de busca (usa implementação base de _search_variations)
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        # Busca artigos nos resultados
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
                        links.append(href)
        return links
    
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
            # IMPORTANTE: Para antes de encontrar "Sinopse" no texto também (case-insensitive)
            title_original_match = re.search(
                r'<strong>T[íi]tulo Original</strong>\s*[:\s]\s*(?:<br\s*/?>)?\s*([^<]+?)(?=<span|<br|</p|</strong|<strong>Sinopse|<strong>Gênero|Gênero|Sinopse|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|TEMPORADA|Temporada|$)',
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
                # Para antes de encontrar palavras de parada (Sinopse, Gênero, etc.) - verifica no texto também
                stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                for stop_word in stop_words:
                    # Busca case-insensitive
                    title_lower = original_title.lower()
                    stop_lower = stop_word.lower()
                    if stop_lower in title_lower:
                        idx = title_lower.index(stop_lower)
                        original_title = original_title[:idx].strip()
                        break
                # Validação crítica: se ainda contém "Sinopse" após processamento, descarta
                if 'sinopse' in original_title.lower():
                    logger.warning(f"[Comand] Título descartado por conter 'Sinopse' após processamento: {original_title[:100]}...")
                    original_title = ''
                # Limita o tamanho máximo do título (200 caracteres)
                elif len(original_title) > 200:
                    original_title = original_title[:200].strip()
                # Remove caracteres especiais do final (mas mantém dois pontos e traços no meio)
                if original_title:
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
                        title_lower = original_title.lower()
                        stop_lower = stop_word.lower()
                        if stop_lower in title_lower:
                            idx = title_lower.index(stop_lower)
                            original_title = original_title[:idx].strip()
                            break
                    # Validação crítica: se ainda contém "Sinopse" após processamento, descarta
                    if 'sinopse' in original_title.lower():
                        logger.warning(f"[Comand] Título descartado (Padrão 2) por conter 'Sinopse': {original_title[:100]}...")
                        original_title = ''
                    # Limita o tamanho máximo do título (200 caracteres)
                    elif len(original_title) > 200:
                        original_title = original_title[:200].strip()
                    # Remove caracteres especiais do final (mas mantém dois pontos e traços no meio)
                    if original_title:
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
                        title_lower = original_title.lower()
                        stop_lower = stop_word.lower()
                        if stop_lower in title_lower:
                            idx = title_lower.index(stop_lower)
                            original_title = original_title[:idx].strip()
                            break
                    # Validação crítica: se ainda contém "Sinopse" após processamento, descarta
                    if 'sinopse' in original_title.lower():
                        logger.warning(f"[Comand] Título descartado (Padrão 3) por conter 'Sinopse': {original_title[:100]}...")
                        original_title = ''
                    if original_title:
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
                                title_lower = original_title.lower()
                                stop_lower = stop_word.lower()
                                if stop_lower in title_lower:
                                    idx = title_lower.index(stop_lower)
                                    original_title = original_title[:idx].strip()
                                    break
                            # Validação crítica: se ainda contém "Sinopse" após processamento, descarta
                            if 'sinopse' in original_title.lower():
                                logger.warning(f"[Comand] Título descartado (Padrão 4) por conter 'Sinopse': {original_title[:100]}...")
                                original_title = ''
                            # Limita o tamanho máximo do título (200 caracteres)
                            elif len(original_title) > 200:
                                original_title = original_title[:200].strip()
                            if original_title:
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
                        title_lower = original_title.lower()
                        stop_lower = stop_word.lower()
                        if stop_lower in title_lower:
                            idx = title_lower.index(stop_lower)
                            original_title = original_title[:idx].strip()
                            break
                    # Validação crítica: se ainda contém "Sinopse" após processamento, descarta
                    if 'sinopse' in original_title.lower():
                        logger.warning(f"[Comand] Título descartado (Padrão 5) por conter 'Sinopse': {original_title[:100]}...")
                        original_title = ''
                    # Limita o tamanho máximo do título (200 caracteres)
                    elif len(original_title) > 200:
                        original_title = original_title[:200].strip()
                    # Remove caracteres especiais do final (mas mantém dois pontos e traços no meio)
                    if original_title:
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
        title_translated_processed = ''
        if entry_content:
            html_content = str(entry_content)
            
            # Padrão 1: HTML com tags <strong>Título Traduzido</strong>: texto<br />
            title_traduzido_match = re.search(
                r'<strong>T[íi]tulo Traduzido</strong>\s*[:\s]\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|</strong|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if title_traduzido_match:
                title_translated_processed = title_traduzido_match.group(1).strip()
                title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed).strip()
                title_translated_processed = html.unescape(title_translated_processed)
                title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()
                title_translated_processed = title_translated_processed.rstrip(' .,:;-')
                # Limpa usando função auxiliar
                from utils.text.cleaning import clean_title_translated_processed
                title_translated_processed = clean_title_translated_processed(title_translated_processed)
            
            # Padrão 2: HTML com tags <b>Título Traduzido:</b> texto<br />
            if not title_translated_processed:
                title_traduzido_match = re.search(
                    r'<b>T[íi]tulo Traduzido[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|$)', 
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_traduzido_match:
                    title_translated_processed = title_traduzido_match.group(1).strip()
                    title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed).strip()
                    title_translated_processed = html.unescape(title_translated_processed)
                    title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()
                    title_translated_processed = title_translated_processed.rstrip(' .,:;-')
                    # Limpa usando função auxiliar
                    from utils.text.cleaning import clean_title_translated_processed
                    title_translated_processed = clean_title_translated_processed(title_translated_processed)
            
            # Padrão 3: Texto puro (fallback)
            if not title_translated_processed:
                content_text = entry_content.get_text()
                title_traduzido_match = re.search(
                    r'T[íi]tulo Traduzido[:\s]+([^\n]+?)(?:\n|$)',
                    content_text,
                    re.IGNORECASE
                )
                if title_traduzido_match:
                    title_translated_processed = title_traduzido_match.group(1).strip()
                    title_translated_processed = title_translated_processed.rstrip(' .,:;-')
        
        # Limpa o título traduzido se encontrou
        if title_translated_processed:
            # Remove qualquer HTML que possa ter sobrado
            title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
            title_translated_processed = html.unescape(title_translated_processed)
            from utils.text.cleaning import clean_title_translated_processed
            title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        # Validação adicional: se o título capturado começa com "Sinopse" ou contém indicadores de sinopse, descarta
        if original_title:
            original_title_lower = original_title.lower().strip()
            # Se começa com "sinopse" (com ou sem números), descarta
            if original_title_lower.startswith('sinopse'):
                logger.warning(f"[Comand] Título descartado por começar com 'Sinopse': {original_title[:100]}...")
                original_title = ''
            # Se o título contém palavras típicas de sinopse (descrição de personagem/plot), descarta
            elif len(original_title) > 100:
                sinopse_indicators = ['mauro', 'michel', 'joelsas', 'garoto', 'mineiro', 'adora', 'futebol', 'jogo', 'botao', 'vida', 'muda', 'completamente', 'pais', 'saem', 'ferias', 'inesperada', 'um dia', 'sua vida', 'que adora', 'anos que']
                title_lower = original_title_lower
                # Se contém múltiplos indicadores de sinopse, descarta
                indicator_count = sum(1 for indicator in sinopse_indicators if indicator in title_lower)
                if indicator_count >= 3:
                    logger.warning(f"[Comand] Título descartado por conter {indicator_count} indicadores de sinopse: {original_title[:100]}...")
                    original_title = ''
        
        # Se não encontrou título original, usa o título da página
        if not original_title:
            original_title = page_title
        
        # Extrai informações de áudio e legenda do HTML
        audio_info = ''  # Para detectar áudio/idioma do HTML
        audio_html_content = ''  # Armazena HTML completo para verificação adicional
        all_paragraphs_html = []  # Coleta HTML de todos os parágrafos
        
        if entry_content:
            # Primeiro tenta no HTML completo do entry_content (mais eficiente)
            content_html = str(entry_content)
            all_paragraphs_html.append(content_html)
            
            # Extrai informação de áudio/idioma usando função utilitária (mesma lógica do starck)
            from utils.parsing.audio_extraction import detect_audio_from_html
            audio_info = detect_audio_from_html(content_html)
            
            # Se não encontrou no HTML completo, busca nos elementos individuais
            if not audio_info:
                for p in entry_content.find_all(['p', 'span', 'div', 'strong', 'em', 'li', 'b']):
                    html_content = str(p)
                    all_paragraphs_html.append(html_content)
                    audio_info = detect_audio_from_html(html_content)
                    if audio_info:
                        break
            
            # Concatena HTML de todos os parágrafos para verificação adicional
            if all_paragraphs_html:
                audio_html_content = ' '.join(all_paragraphs_html)
            
            # Extrai legenda usando função dedicada
            from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
            legenda = extract_legenda_from_page(doc, scraper_type='comand', content_div=entry_content)
            
            # Determina legend_info baseado na legenda extraída
            legend_info = determine_legend_info(legenda) if legenda else None
        
        # Extrai links magnet - busca TODOS os links <a> no entry-content
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        # Primeiro tenta em container específico (mais rápido)
        magnet_links = []
        if entry_content:
            for link in entry_content.select('a[href]'):
                href = link.get('href', '')
                if not href:
                    continue
                
                # Resolve automaticamente (magnet direto ou protegido)
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet and resolved_magnet.startswith('magnet:'):
                    if resolved_magnet not in magnet_links:
                        magnet_links.append(resolved_magnet)
        
        # Se não encontrou links no container específico, busca em todo o documento (fallback)
        if not magnet_links:
            all_links = doc.select('a[href]')
            for link in all_links:
                href = link.get('href', '')
                if not href:
                    continue
                
                # Resolve automaticamente (magnet direto ou protegido)
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet and resolved_magnet.startswith('magnet:'):
                    if resolved_magnet not in magnet_links:
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
                    if not original_title and cross_data.get('title_original_html'):
                        original_title = cross_data['title_original_html']
                    
                    if not title_translated_processed and cross_data.get('title_translated_html'):
                        title_translated_processed = cross_data['title_translated_html']
                    
                    if not imdb and cross_data.get('imdb'):
                        imdb = cross_data['imdb']
                
                # Extrai magnet_original diretamente do display_name do magnet resolvido
                # NÃO modificar antes de passar para create_standardized_title
                magnet_original = magnet_data.get('display_name', '')
                missing_dn = not magnet_original or len(magnet_original.strip()) < 3
                
                # NOTA: Não busca cross_data aqui para não interferir no fluxo de prepare_release_title()
                # A busca de fallback (release:title, cross_data, metadata) será feita dentro de prepare_release_title()
                # quando missing_dn = True, através de get_metadata_name()
                
                # Salva magnet_processed no Redis se encontrado (para reutilização por outros scrapers)
                if not missing_dn and magnet_original:
                    try:
                        from utils.text.storage import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, magnet_original)
                    except Exception:
                        pass
                
                fallback_title = original_title if original_title else page_title
                original_release_title = prepare_release_title(
                    magnet_original,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title, title_translated_html=title_translated_processed if title_translated_processed else None, magnet_original=magnet_original
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
                if audio_info:
                    origem_audio_tag = f'HTML da página (detect_audio_from_html)'
                elif magnet_original and ('dual' in magnet_original.lower() or 'dublado' in magnet_original.lower() or 'legendado' in magnet_original.lower()):
                    origem_audio_tag = 'magnet_processed'
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
                    # Determina presença de legenda seguindo ordem de fallbacks
                    from utils.parsing.legend_extraction import determine_legend_presence
                    has_legenda = determine_legend_presence(
                        legend_info_from_html=legend_info,
                        audio_html_content=audio_html_content,
                        magnet_processed=original_release_title,
                        info_hash=info_hash,
                        skip_metadata=self._skip_metadata
                    )
                    
                    cross_data_to_save = {
                        'title_original_html': original_title if original_title else None,
                        'magnet_processed': original_release_title if original_release_title else None,
                        'magnet_original': magnet_original if magnet_original else None,
                        'title_translated_html': title_translated_processed if title_translated_processed else None,
                        'imdb': imdb if imdb else None,
                        'missing_dn': missing_dn,
                        'origem_audio_tag': origem_audio_tag if origem_audio_tag != 'N/A' else None,
                        'size': size if size and size.strip() else None,
                        'has_legenda': has_legenda,
                        'legend': legend_info if legend_info else None
                    }
                    save_cross_data_to_redis(info_hash, cross_data_to_save)
                except Exception:
                    pass
                
                torrent = {
                    'title_processed': final_title,
                    'original_title': original_title if original_title else page_title,
                    'title_translated_processed': title_translated_processed if title_translated_processed else None,
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
                    'similarity': 1.0,
                    'magnet_original': magnet_original if magnet_original else None,
                    'legend': legend_info if legend_info else None,
                    'has_legenda': has_legenda
                }
                torrents.append(torrent)
            
            except Exception as e:
                logger.error(f"Magnet error: {format_error(e)} (link: {format_link_preview(magnet_link)})")
                continue
        
        return torrents

