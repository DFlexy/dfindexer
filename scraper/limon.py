"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
import base64
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, unquote, urlparse, parse_qs, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.constants import STOP_WORDS
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.parsing.audio_extraction import add_audio_tag_if_needed
from utils.text.title_builder import create_standardized_title, prepare_release_title
from utils.logging import ScraperLogContext

logger = logging.getLogger(__name__)

# Contexto de logging centralizado para este scraper
_log_ctx = ScraperLogContext("Limon", logger)

# Scraper específico para Limon Torrents
class LimonScraper(BaseScraper):
    SCRAPER_TYPE = "limon"
    DEFAULT_BASE_URL = "https://www.limontorrents.org/"
    DISPLAY_NAME = "Limon"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
    # Extrai links dos resultados de busca
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        # Estrutura do limontorrents.org: .post > .inner > .title > a
        for item in doc.select('.post'):
            # Tenta primeiro .title > a
            link_elem = item.select_one('div.title > a')
            if not link_elem:
                # Fallback: tenta .thumb > a
                link_elem = item.select_one('div.thumb > a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        return links
    
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
        
        # Primeiras 2-3 palavras (útil para títulos longos)
        if len(query_words) > 3:
            first_words = ' '.join(query_words[:3])
            variations.append(first_words)
        
        for variation in variations:
            # Normaliza query para FlareSolverr
            from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
            normalized_variation = normalize_query_for_flaresolverr(variation, self.use_flaresolverr)
            search_url = f"{self.base_url}{self.search_url}{quote(normalized_variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue
            
            # Busca links nos resultados
            for item in doc.select('.post'):
                link_elem = item.select_one('div.title > a')
                if not link_elem:
                    link_elem = item.select_one('div.thumb > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        
        return list(set(links))  # Remove duplicados
    
    # Busca torrents
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        # Normaliza query para FlareSolverr
        from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
        query = normalize_query_for_flaresolverr(query, self.use_flaresolverr)
        # Usa busca com variações para melhorar resultados
        links = self._search_variations(query)
        
        if not links:
            return []
        
        all_torrents = []
        for link in links:
            torrents = self._get_torrents_from_page(link)
            all_torrents.extend(torrents)
        
        return self.enrich_torrents(all_torrents, filter_func=filter_func)
    
    # Extrai links da página inicial - busca apenas "Tendências de Hoje"
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        
        # Encontra a seção "Tendências de Hoje"
        # Estrutura: h2.titulo > strong com "Tendências de Hoje"
        tendencias_h2 = None
        for h2 in doc.find_all('h2', class_='titulo'):
            h2_text = h2.get_text()
            if 'Tendências de Hoje' in h2_text:
                tendencias_h2 = h2
                break
        
        if tendencias_h2:
            # Encontra o container main_title que contém o h2
            main_title_container = tendencias_h2.find_parent('div', class_='main_title')
            
            # Busca posts que vêm depois do main_title, parando quando encontrar outro main_title
            # Os posts estão como irmãos do main_title, não dentro dele
            if main_title_container:
                current = main_title_container.find_next_sibling()
                while current:
                    # Para se encontrar outro main_title (início de outra seção)
                    if current.name == 'div' and 'main_title' in current.get('class', []):
                        break
                    
                    # Para se encontrar outro h2.titulo (início de outra seção)
                    if current.name == 'h2' and 'titulo' in current.get('class', []):
                        break
                    
                    # Para se encontrar paginação
                    if current.name == 'nav' and 'pagination' in current.get('class', []):
                        break
                    
                    # Se é um post direto, extrai o link
                    if current.name == 'div' and 'post' in current.get('class', []):
                        link_elem = current.select_one('div.title > a')
                        if not link_elem:
                            link_elem = current.select_one('div.thumb > a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                absolute_url = urljoin(self.base_url, href)
                                links.append(absolute_url)
                    
                    # Também busca posts dentro de containers filhos (caso estejam aninhados)
                    for post in current.select('div.post'):
                        link_elem = post.select_one('div.title > a')
                        if not link_elem:
                            link_elem = post.select_one('div.thumb > a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                absolute_url = urljoin(self.base_url, href)
                                if absolute_url not in links:  # Evita duplicados
                                    links.append(absolute_url)
                    
                    current = current.find_next_sibling()
            
            # Se não encontrou posts após o main_title, tenta buscar todos os posts após o h2
            # mas limitando a posts que não pertencem a outra seção
            if not links:
                for post in tendencias_h2.find_all_next('div', class_='post'):
                    # Para se encontrar outro main_title antes deste post
                    prev_main_title = post.find_previous('div', class_='main_title')
                    if prev_main_title and prev_main_title != main_title_container:
                        break
                    
                    # Para se encontrar outro h2.titulo antes deste post
                    prev_h2 = post.find_previous('h2', class_='titulo')
                    if prev_h2 and prev_h2 != tendencias_h2:
                        break
                    
                    link_elem = post.select_one('div.title > a')
                    if not link_elem:
                        link_elem = post.select_one('div.thumb > a')
                    if link_elem:
                        href = link_elem.get('href')
                        if href:
                            absolute_url = urljoin(self.base_url, href)
                            if absolute_url not in links:  # Evita duplicados
                                links.append(absolute_url)
        else:
            # Fallback: se não encontrar a seção, usa comportamento padrão
            _log_ctx.info("Seção 'Tendências de Hoje' não encontrada - usando fallback genérico")
            for item in doc.select('.post'):
                link_elem = item.select_one('div.title > a')
                if not link_elem:
                    link_elem = item.select_one('div.thumb > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        absolute_url = urljoin(self.base_url, href)
                        links.append(absolute_url)
        
        return links
    
    # Obtém torrents de uma página específica
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        return self._default_get_page(page, max_items)
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        # Garante que o link seja absoluto para o campo details
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da página (tenta URL, meta tags, etc.)
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        article = doc.find('article')
        if not article:
            return []
        
        # Extrai título original
        original_title = ''
        
        # Método 1: Busca específica em div.entry-meta (estrutura padrão do site)
        entry_meta = doc.find('div', class_='entry-meta')
        if entry_meta:
            # Busca por <b> que contém "Título Original"
            for b_tag in entry_meta.find_all('b'):
                b_text = b_tag.get_text(strip=True).lower()
                if 'título original' in b_text or 'titulo original' in b_text:
                    # Método 1: Extrai diretamente do HTML bruto do parent (mais confiável)
                    parent_html = str(b_tag.parent)
                    
                    # Regex específico: captura tudo após </b> até <br>
                    patterns = [
                        r'(?i)</b>\s*([^<]+?)\s*<br\s*/?>',
                        r'(?i)</b>\s*([^<]+?)(?:<br|</div|</p|$)',
                        r'(?i)T[íi]tulo\s+Original\s*:?\s*</b>\s*([^<]+?)\s*<br',
                    ]
                    
                    next_text = ''
                    for pattern in patterns:
                        match = re.search(pattern, parent_html)
                        if match:
                            next_text = match.group(1).strip()
                            break
                    
                    if next_text:
                        next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                        next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-').replace('&iacute;', 'í')
                        next_text = ' '.join(next_text.split())
                        
                        if next_text:
                            original_title = next_text
                            break
                    
                    # Método 2: Tenta pegar o next_sibling
                    if not original_title:
                        next_sibling = b_tag.next_sibling
                        if next_sibling:
                            if hasattr(next_sibling, 'strip'):
                                next_text = str(next_sibling).strip()
                            else:
                                next_text = next_sibling.get_text(strip=True) if hasattr(next_sibling, 'get_text') else ''
                            
                            if next_text:
                                next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                                next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-')
                                if '<br' in next_text or '\n' in next_text:
                                    parts = re.split(r'<br\s*/?>|\n', next_text)
                                    if parts:
                                        next_text = parts[0].strip()
                                
                                next_text = ' '.join(next_text.split())
                                if next_text:
                                    original_title = next_text
                                    break
                    
                    # Método 3: Extrai do texto do parent fazendo split
                    if not original_title:
                        parent_text = b_tag.parent.get_text()
                        if 'Título Original:' in parent_text:
                            parts = parent_text.split('Título Original:')
                            if len(parts) > 1:
                                next_text = parts[1].strip()
                                for stop in ['Formato:', 'Qualidade:', 'Idioma:', 'Legenda:', 'Tamanho:', 'Servidor:']:
                                    if stop in next_text:
                                        next_text = next_text.split(stop)[0].strip()
                                        break
                                if '\n' in next_text:
                                    next_text = next_text.split('\n')[0].strip()
                                
                                if next_text:
                                    next_text = ' '.join(next_text.split())
                                    original_title = next_text
                                    break
        
        # Método 2: Busca em div.content e div.entry-content se não encontrou
        if not original_title:
            for content_div in doc.select('div.content, div.entry-content, .left'):
                if original_title:
                    break
                
                for b_tag in content_div.find_all('b'):
                    b_text = b_tag.get_text(strip=True).lower()
                    if 'título original' in b_text or 'titulo original' in b_text:
                        next_sibling = b_tag.next_sibling
                        if next_sibling:
                            if hasattr(next_sibling, 'strip'):
                                next_text = str(next_sibling).strip()
                            else:
                                next_text = ''
                        else:
                            next_text = ''
                        
                        if not next_text:
                            parent_html = str(b_tag.parent)
                            match = re.search(r'(?i)</b>\s*([^<]+?)(?:<br\s*/?>|</div|</p|$)', parent_html)
                            if match:
                                next_text = match.group(1).strip()
                        
                        if next_text:
                            next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                            next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-')
                            next_text = ' '.join(next_text.split())
                            if next_text:
                                original_title = next_text
                                break
                
                if original_title:
                    break
        
        # Método 3: Fallback - busca em todo o article se não encontrou
        if not original_title:
            article_text = article.get_text(' ', strip=True)
            if 'Título Original:' in article_text:
                parts = article_text.split('Título Original:')
                if len(parts) > 1:
                    title_part = parts[1].strip()
                    stops = ['\n\n', 'Formato:', 'Qualidade:', 'Idioma:', 'Legenda:', 'Tamanho:', 'Servidor:']
                    for stop in stops:
                        if stop in title_part:
                            idx = title_part.index(stop)
                            title_part = title_part[:idx]
                            break
                    title_part = ' '.join(title_part.split())
                    if title_part:
                        original_title = title_part
            
            if not original_title:
                for elem in article.find_all(['p', 'div', 'span', 'li']):
                    text = elem.get_text(strip=True)
                    if 'Título Original:' in text:
                        parts = text.split('Título Original:')
                        if len(parts) > 1:
                            title_part = parts[1].strip()
                            stops = ['\n\n', 'Formato:', 'Qualidade:', 'Idioma:', 'Legenda:', 'Tamanho:', 'Servidor:']
                            for stop in stops:
                                if stop in title_part:
                                    idx = title_part.index(stop)
                                    title_part = title_part[:idx]
                                    break
                            title_part = ' '.join(title_part.split())
                            if title_part:
                                original_title = title_part
                                break
        
        # Fallback para h1.entry-title
        if not original_title:
            title_raw = article.find('h1', class_='entry-title')
            if not title_raw:
                title_raw = article.find('h1')
            if title_raw:
                original_title = title_raw.get_text(strip=True)
                original_title = re.sub(r'\s*\(\d{4}(-\d{4})?\)\s*$', '', original_title)
        
        # Remove sufixos comuns
        original_title = original_title.replace(' Torrent Dual Áudio', '').strip()
        original_title = original_title.replace(' Torrent Dublado', '').strip()
        original_title = original_title.replace(' Torrent Legendado', '').strip()
        original_title = original_title.replace(' Torrent', '').strip()
        
        # Extrai título traduzido
        title_translated_processed = ''
        if entry_meta:
            for b_tag in entry_meta.find_all('b'):
                b_text = b_tag.get_text(strip=True).lower()
                if 'título traduzido' in b_text or 'titulo traduzido' in b_text:
                    parent_html = str(b_tag.parent)
                    patterns = [
                        r'(?i)</b>\s*([^<]+?)\s*<br\s*/?>',
                        r'(?i)</b>\s*([^<]+?)(?:<br|</div|</p|$)',
                        r'(?i)T[íi]tulo\s+Traduzido\s*:?\s*</b>\s*([^<]+?)\s*<br',
                    ]
                    next_text = ''
                    for pattern in patterns:
                        match = re.search(pattern, parent_html)
                        if match:
                            next_text = match.group(1).strip()
                            break
                    if next_text:
                        next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                        next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-').replace('&iacute;', 'í')
                        next_text = ' '.join(next_text.split())
                        if next_text:
                            title_translated_processed = next_text
                            break
        
        # Busca em div.content e div.entry-content se não encontrou
        if not title_translated_processed:
            for content_div in doc.select('div.content, div.entry-content, .left'):
                if title_translated_processed:
                    break
                for b_tag in content_div.find_all('b'):
                    b_text = b_tag.get_text(strip=True).lower()
                    if 'título traduzido' in b_text or 'titulo traduzido' in b_text:
                        parent_html = str(b_tag.parent)
                        match = re.search(r'(?i)</b>\s*([^<]+?)(?:<br\s*/?>|</div|</p|$)', parent_html)
                        if match:
                            next_text = match.group(1).strip()
                            next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                            next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-')
                            next_text = ' '.join(next_text.split())
                            if next_text:
                                title_translated_processed = next_text
                                break
                if title_translated_processed:
                    break
        
        # Busca em todo o article se não encontrou
        if not title_translated_processed and article:
            for elem in article.find_all(['p', 'div', 'span', 'li']):
                elem_text = elem.get_text(' ', strip=True)
                if 'Título Traduzido:' in elem_text:
                    parts = elem_text.split('Título Traduzido:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        stops = ['\n\n', 'Formato:', 'Qualidade:', 'Idioma:', 'Legenda:', 'Tamanho:', 'Servidor:', 'Título Original:']
                        for stop in stops:
                            if stop in title_part:
                                idx = title_part.index(stop)
                                title_part = title_part[:idx]
                                break
                        title_part = ' '.join(title_part.split())
                        if title_part:
                            title_translated_processed = title_part
                            break
        
        # Fallback: se não encontrou "Título Traduzido", tenta usar h1.entry-title
        if not title_translated_processed:
            title_raw = article.find('h1', class_='entry-title')
            if not title_raw:
                title_raw = article.find('h1')
            if title_raw:
                title_translated_processed = title_raw.get_text(strip=True)
        
        # Limpa o título traduzido se encontrou
        if title_translated_processed:
            title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
            title_translated_processed = html.unescape(title_translated_processed)
            from utils.text.cleaning import clean_title_translated_processed
            title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        title = original_title
        
        # Extrai metadados
        year = ''
        imdb = ''
        sizes = []
        audio_info = None
        audio_html_content = ''
        all_paragraphs_html = []
        
        # Extrai informações de idioma e legenda do HTML
        entry_meta_list = doc.find_all('div', class_='entry-meta')
        
        idioma = ''
        legenda = ''
        
        # Coleta HTML de todos os entry-meta para audio_html_content
        for entry_meta in entry_meta_list:
            all_paragraphs_html.append(str(entry_meta))
        
        # Busca Idioma e Legenda em todos os entry-meta
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
        
        # Determina audio_info baseado em Idioma e Legenda
        if idioma or legenda:
            idioma_lower = idioma.lower() if idioma else ''
            legenda_lower = legenda.lower() if legenda else ''
            
            has_portugues_audio = 'português' in idioma_lower or 'portugues' in idioma_lower
            has_portugues_legenda = 'português' in legenda_lower or 'portugues' in legenda_lower
            has_ingles = 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower or 'inglês' in legenda_lower or 'ingles' in legenda_lower or 'english' in legenda_lower
            
            if has_portugues_audio:
                audio_info = 'português'
            elif has_portugues_legenda or has_ingles:
                audio_info = 'legendado'
        
        # Coleta HTML de parágrafos para audio_html_content
        for p in article.select('div.content p, div.entry-content p'):
            html_content = str(p)
            all_paragraphs_html.append(html_content)
        
        # Concatena HTML de todos os parágrafos
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
        
        # Se não encontrou em entry-meta, busca em outros lugares
        if not audio_info:
            for p in article.select('div.content p, div.entry-content p'):
                text = p.get_text()
                html_content = str(p)
                
                y = find_year_from_text(text, title)
                if y:
                    year = y
                
                sizes.extend(find_sizes_from_text(html_content))
                
                if not audio_info:
                    from utils.parsing.audio_extraction import detect_audio_from_html
                    audio_info = detect_audio_from_html(html_content)
                    if audio_info:
                        break
        else:
            # Se já encontrou audio_info, ainda precisa extrair ano e tamanhos
            for p in article.select('div.entry-meta, div.content p, div.entry-content p'):
                text = p.get_text()
                html_content = str(p)
                
                y = find_year_from_text(text, title)
                if y:
                    year = y
                
                sizes.extend(find_sizes_from_text(html_content))
        
        # Remove duplicados de tamanhos
        sizes = list(dict.fromkeys(sizes))
        
        # Extrai ano do texto do article
        if not year:
            try:
                article_full_text = article.get_text(' ', strip=True)
                year_match = re.search(r'(19|20)\d{2}', article_full_text)
                if year_match:
                    year = year_match.group(0)
            except Exception:
                pass

        # Extrai IMDB
        imdb = ''
        for a in article.select('a[href*="imdb.com"]'):
            href = a.get('href', '')
            imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
            if imdb_match:
                imdb = imdb_match.group(1)
                break
            imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
            if imdb_match:
                imdb = imdb_match.group(1)
                break

        # Extrai links magnet - busca TODOS os links <a> no documento
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        # Primeiro tenta em containers específicos (mais rápido)
        magnet_links = []
        for text_content in doc.select('div.content, div.entry-content, div.modal-downloads, div#modal-downloads'):
            for a in text_content.select('a[href]'):
                href = a.get('href', '')
                if not href:
                    continue
                
                # Resolve automaticamente (magnet direto ou protegido)
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet and resolved_magnet.startswith('magnet:'):
                    # Verifica se o magnet_link resolvido tem trackers (apenas para protlink original)
                    original_href = href
                    if 'protlink=' in original_href:
                        try:
                            magnet_data = MagnetParser.parse(resolved_magnet)
                            trackers = magnet_data.get('trackers', [])
                            if not trackers:
                                from tracker.list_provider import TrackerListProvider
                                tracker_provider = TrackerListProvider(redis_client=self.redis)
                                default_trackers = tracker_provider.get_trackers()
                                if default_trackers:
                                    from urllib.parse import urlencode
                                    magnet_params = {
                                        'xt': f"urn:btih:{magnet_data.get('info_hash', '')}"
                                    }
                                    display_name = magnet_data.get('display_name', '')
                                    if display_name and display_name.strip():
                                        magnet_params['dn'] = display_name
                                    for tracker in default_trackers[:5]:
                                        magnet_params.setdefault('tr', []).append(tracker)
                                    resolved_magnet = f"magnet:?{urlencode(magnet_params, doseq=True)}"
                        except Exception:
                            pass
                    
                    # Adiciona apenas se não estiver na lista (evita duplicados)
                    if resolved_magnet not in magnet_links:
                        magnet_links.append(resolved_magnet)
                    continue
                
                # Link codificado com token
                if 'token=' in href:
                    try:
                        parsed = urlparse(href)
                        params = parse_qs(parsed.query)
                        token = params.get('token', [None])[0]
                        if token:
                            try:
                                decoded = base64.b64decode(token).decode('utf-8')
                                if decoded.startswith('magnet:'):
                                    magnet_links.append(decoded)
                            except Exception:
                                pass
                    except Exception:
                        pass
        
        # Se não encontrou links nos containers específicos, busca em todo o documento (fallback)
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
        
        # Durante testes (skip_metadata=True), limita a 1 magnet por página
        if self._skip_metadata:
            magnet_links = magnet_links[:1]
        
        # Processa cada magnet
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                # Busca dados cruzados no Redis por info_hash
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
                magnet_original = magnet_data.get('display_name', '') or ''
                missing_dn = not magnet_original or len(magnet_original.strip()) < 3
                
                # Se ainda está missing_dn, tenta buscar do cross_data
                release_title_from_cross = False
                if missing_dn and cross_data and cross_data.get('magnet_processed'):
                    cross_release = cross_data.get('magnet_processed')
                    if cross_release and cross_release != 'N/A' and len(str(cross_release).strip()) >= 3:
                        magnet_original = str(cross_release)
                        missing_dn = False
                        release_title_from_cross = True
                
                # Salva magnet_processed no Redis se encontrado
                if not missing_dn and magnet_original:
                    try:
                        from utils.text.storage import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, magnet_original)
                    except Exception:
                        pass
                
                fallback_title = title
                working_release_title = magnet_original if not missing_dn else ''
                
                original_release_title = prepare_release_title(
                    working_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                # Adiciona temporada do HTML apenas se não tiver informação de temporada/episódio
                if missing_dn:
                    has_season_ep_info = re.search(r'(?i)S\d{1,2}(?:E\d{1,2}(?:-\d{1,2})?)?', original_release_title)
                    if not has_season_ep_info and 'temporada' not in original_release_title.lower():
                        try:
                            article_text_cached = article.get_text(' ', strip=True).lower()
                            season_match = re.search(r'(\d+)\s*(?:ª|a)?\s*temporada', article_text_cached)
                            if season_match:
                                season_number = season_match.group(1)
                                if not re.search(rf'\b{season_number}\s*(?:ª|a)?\s*temporada', original_release_title, re.IGNORECASE):
                                    original_release_title = f"{original_release_title} temporada {season_number}"
                        except Exception:
                            pass
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title, title_translated_html=title_translated_processed if title_translated_processed else None, magnet_original_magnet=magnet_original
                )
                
                # Adiciona tags de áudio
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
                    origem_audio_tag = 'HTML da página (Idioma/Legenda)'
                elif magnet_original and ('dual' in magnet_original.lower() or 'dublado' in magnet_original.lower() or 'legendado' in magnet_original.lower()):
                    origem_audio_tag = 'magnet_processed'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                # Extrai tamanho
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Processa trackers
                trackers = process_trackers(magnet_data)
                
                # Se não tem trackers, usa lista dinâmica
                if not trackers:
                    try:
                        from tracker.list_provider import TrackerListProvider
                        tracker_provider = TrackerListProvider(redis_client=self.redis)
                        dynamic_trackers = tracker_provider.get_trackers()
                        if dynamic_trackers:
                            trackers = [t for t in dynamic_trackers if t.lower().startswith('udp://')]
                    except Exception:
                        pass
                
                # Salva dados cruzados no Redis
                try:
                    from utils.text.cross_data import save_cross_data_to_redis
                    cross_data_to_save = {
                        'title_original_html': original_title if original_title else None,
                        'magnet_processed': original_release_title if original_release_title else None,
                        'title_translated_html': title_translated_processed if title_translated_processed else None,
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
                    'original_title': original_title if original_title else title,
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
                    'magnet_original': magnet_original if magnet_original else None
                }
                torrents.append(torrent)
            
            except Exception as e:
                _log_ctx.error_magnet(magnet_link, e)
                continue
        
        return torrents

