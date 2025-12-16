"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
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


# Scraper específico para Rede Torrent
class RedeScraper(BaseScraper):
    SCRAPER_TYPE = "rede"
    DEFAULT_BASE_URL = "https://redetorrent.com/"
    DISPLAY_NAME = "Rede"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "index.php?s="
        self.page_pattern = "{}"
    
    # Busca torrents com variações da query
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        return self._default_search(query, filter_func)
    
    # Extrai links da página inicial
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select('.capa_lista'):
            link_elem = item.select_one('a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        return links
    
    # Obtém torrents de uma página específica
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        return self._default_get_page(page, max_items)
    
    # Extrai links dos resultados de busca
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select('.capa_lista'):
            link_elem = item.select_one('a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        return links
    
    # Busca com variações da query (com paginação específica do site)
    def _search_variations(self, query: str) -> List[str]:
        links = []
        variations = [query]
        
        # Primeira palavra (se não for stop word)
        query_words = query.split()
        if len(query_words) > 1:
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])
        
        for variation in variations:
            # Página 1: index.php?s={query}
            page = 1
            while True:
                if page == 1:
                    search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
                else:
                    # Páginas seguintes: {query}/{page}/
                    search_url = f"{self.base_url}{quote(variation)}/{page}/"
                
                doc = self.get_document(search_url, self.base_url)
                if not doc:
                    break
                
                page_links = []
                for item in doc.select('.capa_lista'):
                    link_elem = item.select_one('a')
                    if link_elem:
                        href = link_elem.get('href')
                        if href:
                            page_links.append(href)
                
                # Se não encontrou links nesta página, para
                if not page_links:
                    break
                
                links.extend(page_links)
                
                # Verifica se há próxima página
                # Procura por links de paginação que indiquem próxima página
                has_next_page = False
                pagination_links = doc.select('a[href*="/"], .pagination a, .wp-pagenavi a')
                for pag_link in pagination_links:
                    href = pag_link.get('href', '')
                    text = pag_link.get_text(strip=True).lower()
                    # Verifica se há link para próxima página (número maior ou texto "próxima")
                    if (f"/{page + 1}/" in href) or (text in ['próxima', 'next', '>', '»']):
                        has_next_page = True
                        break
                    # Verifica se há número de página maior na paginação
                    try:
                        page_num = int(text)
                        if page_num > page:
                            has_next_page = True
                            break
                    except ValueError:
                        pass
                
                if not has_next_page:
                    break
                
                page += 1
                # Limite de segurança: máximo 20 páginas
                if page > 20:
                    break
        
        return list(set(links))
    
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
        article = doc.find('div', class_='conteudo')
        if not article:
            return []
        
        # Extrai título e ano do h1
        h1 = article.find('h1')
        if not h1:
            return []
        
        title_text = h1.get_text(strip=True)
        # Padrão: "Title - Subtitle (YYYY)" ou "Title (YYYY)"
        title_match = re.search(r'^(.*?)(?: - (.*?))? \((\d{4})\)', title_text)
        if not title_match:
            return []
        
        title = title_match.group(1).strip()
        year = title_match.group(3).strip()
        
        # Extrai título original
        original_title = ''
        for p in article.select('div#informacoes > p'):
            html_content = str(p)
            html_content = html_content.replace('\n', '').replace('\t', '')
            html_content = re.sub(r'<br\s*\/?>', '<br>', html_content)
            lines = html_content.split('<br>')
            
            for line in lines:
                line = re.sub(r'<[^>]*>', '', line).strip()
                if 'Título Original:' in line:
                    title_regex = re.compile(r'Título Original:\s*([^\n\r]{1,200}?)(?:\s*(?:Gênero|Ano|Duração|Direção|Elenco|Sinopse|$))')
                    match = title_regex.search(line)
                    if match:
                        original_title = match.group(1).strip()
                    else:
                        parts = line.split('Título Original:')
                        if len(parts) > 1:
                            extracted = parts[1].strip()
                            if len(extracted) > 200:
                                extracted = extracted[:200]
                            stop_regex = re.compile(r'^[^.!?]*[.!?]')
                            stop_match = stop_regex.search(extracted)
                            if stop_match:
                                extracted = stop_match.group(0)
                            original_title = extracted.strip()
                    
                    original_title = original_title.rstrip(' .,:;-')
                    break
        
        # Extrai título traduzido
        title_translated_processed = ''
        for p in article.select('div#informacoes > p'):
            html_content = str(p)
            html_content = html_content.replace('\n', '').replace('\t', '')
            html_content = re.sub(r'<br\s*\/?>', '<br>', html_content)
            lines = html_content.split('<br>')
            
            for line in lines:
                line_clean = re.sub(r'<[^>]*>', '', line).strip()
                if 'Título Traduzido:' in line_clean:
                    title_regex = re.compile(r'Título Traduzido:\s*([^\n\r]{1,200}?)(?:\s*(?:Gênero|Ano|Duração|Direção|Elenco|Sinopse|Título Original|$))')
                    match = title_regex.search(line_clean)
                    if match:
                        title_translated_processed = match.group(1).strip()
                    else:
                        parts = line_clean.split('Título Traduzido:')
                        if len(parts) > 1:
                            extracted = parts[1].strip()
                            if len(extracted) > 200:
                                extracted = extracted[:200]
                            stop_regex = re.compile(r'^[^.!?]*[.!?]')
                            stop_match = stop_regex.search(extracted)
                            if stop_match:
                                extracted = stop_match.group(0)
                            title_translated_processed = extracted.strip()
                    
                    title_translated_processed = title_translated_processed.rstrip(' .,:;-')
                    break
            if title_translated_processed:
                break
        
        if not original_title:
            original_title = title
        
        # Extrai informações de idioma e legenda do HTML
        audio_info = None  # Para detectar áudio/idioma do HTML
        audio_html_content = ''  # Armazena HTML completo para verificação adicional
        all_paragraphs_html = []  # Coleta HTML de todos os parágrafos
        
        idioma = ''
        legenda = ''
        
        # Busca Idioma e Legenda em div#informacoes
        # Primeiro tenta no HTML completo, depois nos parágrafos individuais
        info_div = article.find('div', id='informacoes')
        if info_div:
            info_html = str(info_div)
            all_paragraphs_html.append(info_html)
            
            # Extrai Idioma - busca primeiro no HTML completo
            idioma_patterns = [
                r'(?i)Idioma\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|Legendas?|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|$)',
                r'(?i)<[^>]*>Idioma\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legendas?|$)',
            ]
            
            for pattern in idioma_patterns:
                idioma_match = re.search(pattern, info_html, re.DOTALL)
                if idioma_match:
                    idioma = idioma_match.group(1).strip()
                    # Remove entidades HTML e tags
                    idioma = html.unescape(idioma)
                    idioma = re.sub(r'<[^>]+>', '', idioma).strip()
                    # Remove espaços extras e normaliza
                    idioma = re.sub(r'\s+', ' ', idioma).strip()
                    if idioma:
                        break
            
            # Se não encontrou no HTML completo, busca nos parágrafos individuais
            if not idioma:
                for p in article.select('div#informacoes > p'):
                    html_content = str(p)
                    html_content = html_content.replace('\n', '').replace('\t', '')
                    html_content = re.sub(r'<br\s*\/?>', '<br>', html_content)
                    lines = html_content.split('<br>')
                    
                    for line in lines:
                        line_clean = re.sub(r'<[^>]*>', '', line).strip()
                        if 'Idioma:' in line_clean:
                            # Extrai o valor após "Idioma:"
                            parts = line_clean.split('Idioma:')
                            if len(parts) > 1:
                                extracted = parts[1].strip()
                                # Para antes de encontrar "Legendas", "Qualidade", etc.
                                stop_words = ['Legendas', 'Legenda', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho']
                                for stop_word in stop_words:
                                    if stop_word in extracted:
                                        idx = extracted.index(stop_word)
                                        extracted = extracted[:idx]
                                        break
                                idioma = extracted.strip()
                                if idioma:
                                    break
                    if idioma:
                        break
            
            # Extrai Legenda - busca primeiro no HTML completo
            # Formato esperado: <strong>Legendas: </strong>\nPortuguês<br> ou <strong>Legendas: </strong>Português<br>
            legenda_patterns = [
                # Padrão 1: <strong>Legendas: </strong> seguido de quebra de linha (\n) e texto na próxima linha
                r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
                # Padrão 2: <strong>Legendas: </strong> seguido diretamente de texto (mesma linha)
                r'(?i)<strong>Legendas?\s*:\s*</strong>\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
                # Padrão 3: <b>Legenda:</b> (fallback)
                r'(?i)<b>Legendas?\s*:</b>\s*([^<]+?)(?:<br|</div|</p|</b|Nota|Tamanho|$)',
                # Padrão 4: Legendas: sem tag (fallback)
                r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|Nota|Tamanho|Imdb|$)',
                # Padrão 5: Qualquer tag com Legendas: (fallback genérico)
                r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|$)',
            ]
            
            for pattern in legenda_patterns:
                legenda_match = re.search(pattern, info_html, re.DOTALL)
                if legenda_match:
                    legenda = legenda_match.group(1).strip()
                    # Remove entidades HTML e tags
                    legenda = html.unescape(legenda)
                    legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                    # Remove espaços extras e normaliza
                    legenda = re.sub(r'\s+', ' ', legenda).strip()
                    # Para antes de encontrar palavras de parada
                    stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio']
                    for stop_word in stop_words:
                        if stop_word in legenda:
                            idx = legenda.index(stop_word)
                            legenda = legenda[:idx].strip()
                            break
                    if legenda:
                        break
            
            # Se não encontrou no HTML completo, busca nos parágrafos individuais
            if not legenda:
                for p in article.select('div#informacoes > p'):
                    html_content = str(p)
                    # NÃO remove quebras de linha - preserva para capturar formato <strong>Legendas: </strong>\nPortuguês<br>
                    html_content_preserved = html_content.replace('\t', ' ')
                    # Normaliza <br> mas preserva \n
                    html_content_preserved = re.sub(r'<br\s*\/?>', '<br>', html_content_preserved)
                    
                    # Tenta primeiro com tag <strong> (formato do site: <strong>Legendas: </strong>\nPortuguês<br>)
                    # Busca o texto após </strong> que pode estar na mesma linha ou próxima linha
                    # Padrão 1: <strong>Legendas: </strong> seguido de quebra de linha e texto
                    legenda_match = re.search(r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)
                    if not legenda_match:
                        # Padrão 2: <strong>Legendas: </strong> seguido diretamente de texto (mesma linha)
                        legenda_match = re.search(r'(?i)<strong>Legendas?\s*:\s*</strong>\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)
                    
                    if legenda_match:
                        legenda = legenda_match.group(1).strip()
                        legenda = html.unescape(legenda)
                        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                        legenda = re.sub(r'\s+', ' ', legenda).strip()
                        if legenda:
                            break
                    
                    # Tenta com tag <b>
                    if not legenda:
                        legenda_match = re.search(r'(?i)<b>Legendas?\s*:</b>\s*([^<]+?)(?:<br|</div|</p|</b|$)', html_content_preserved, re.DOTALL)
                        if legenda_match:
                            legenda = legenda_match.group(1).strip()
                            legenda = html.unescape(legenda)
                            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                            legenda = re.sub(r'\s+', ' ', legenda).strip()
                            if legenda:
                                break
                    
                    # Se não encontrou, tenta sem tag, buscando em linhas separadas
                    if not legenda:
                        # Busca padrão: "Legendas:" seguido de texto na mesma linha ou próxima linha
                        legenda_match = re.search(r'(?i)Legendas?\s*:\s*(?:<br\s*/?>)?\s*([^<\n\r]+?)(?:<br|</div|</p|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)
                        if legenda_match:
                            legenda = legenda_match.group(1).strip()
                            legenda = html.unescape(legenda)
                            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                            legenda = re.sub(r'\s+', ' ', legenda).strip()
                            if legenda:
                                break
                        
                        # Último fallback: busca em linhas separadas (preservando \n)
                        if not legenda:
                            # Divide por <br> para processar cada parte
                            parts_by_br = html_content_preserved.split('<br>')
                            for i, part in enumerate(parts_by_br):
                                # Verifica se tem <strong>Legendas: </strong> nesta parte
                                if re.search(r'(?i)<strong>Legendas?\s*:', part):
                                    # Tenta pegar texto após </strong> na mesma parte (pode ter \n)
                                    match = re.search(r'(?i)</strong>\s*\n\s*([^<\n\r]+?)(?:<br|$)', part, re.DOTALL)
                                    if not match:
                                        # Tenta sem \n (mesma linha)
                                        match = re.search(r'(?i)</strong>\s*([^<\n\r]+?)(?:<br|$)', part, re.DOTALL)
                                    if match:
                                        legenda = match.group(1).strip()
                                        legenda = html.unescape(legenda)
                                        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                                        legenda = re.sub(r'\s+', ' ', legenda).strip()
                                        if legenda:
                                            break
                                    # Se não encontrou na mesma parte, tenta próxima parte
                                    if i + 1 < len(parts_by_br):
                                        next_part = re.sub(r'<[^>]*>', '', parts_by_br[i + 1]).strip()
                                        if next_part and next_part not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio']:
                                            legenda = next_part.strip()
                                            break
                                # Também verifica sem tag <strong>
                                line_clean = re.sub(r'<[^>]*>', '', part).strip()
                                if 'Legendas:' in line_clean or 'Legenda:' in line_clean:
                                    # Tenta pegar da mesma linha
                                    parts = line_clean.split(':')
                                    if len(parts) > 1:
                                        extracted = ':'.join(parts[1:]).strip()
                                        if extracted:
                                            legenda = extracted
                                            break
                                    # Se não tem na mesma linha, tenta próxima linha
                                    if i + 1 < len(parts_by_br):
                                        next_line = re.sub(r'<[^>]*>', '', parts_by_br[i + 1]).strip()
                                        if next_line and next_line not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio']:
                                            legenda = next_line
                                            break
                                if legenda:
                                    break
                    if legenda:
                        break
            
            # Último fallback: busca direta no texto completo sem tags HTML
            if not legenda:
                info_text = info_div.get_text(separator='\n')
                legenda_match = re.search(r'(?i)Legendas?\s*:\s*([^\n]+?)(?:\n|Nota|Tamanho|Imdb|Vídeo|Áudio|$)', info_text)
                if legenda_match:
                    legenda = legenda_match.group(1).strip()
                    # Remove espaços extras
                    legenda = re.sub(r'\s+', ' ', legenda).strip()
                    # Para antes de encontrar palavras de parada
                    stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio']
                    for stop_word in stop_words:
                        if stop_word in legenda:
                            idx = legenda.index(stop_word)
                            legenda = legenda[:idx].strip()
                            break
        
        # Determina audio_info baseado em Idioma e Legenda
        if idioma or legenda:
            idioma_lower = idioma.lower() if idioma else ''
            legenda_lower = legenda.lower() if legenda else ''
            
            # Verifica se tem português no idioma (áudio)
            has_portugues_audio = 'português' in idioma_lower or 'portugues' in idioma_lower
            # Verifica se tem português na legenda
            has_portugues_legenda = 'português' in legenda_lower or 'portugues' in legenda_lower
            # Verifica se tem Inglês no idioma (áudio)
            has_ingles_audio = 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower
            # Verifica se tem Inglês em qualquer lugar
            has_ingles = has_ingles_audio or 'inglês' in legenda_lower or 'ingles' in legenda_lower or 'english' in legenda_lower
            
            # Lógica melhorada:
            # Se tem português E inglês no idioma → DUAL (gera [Brazilian] e [Eng])
            if has_portugues_audio and has_ingles_audio:
                audio_info = 'dual'
            # Se tem apenas português no idioma → gera [Brazilian]
            elif has_portugues_audio:
                audio_info = 'português'
            # Se tem legenda com português OU tem Inglês → gera [Leg]
            elif has_portugues_legenda or has_ingles:
                audio_info = 'legendado'
        
        # Concatena HTML de todos os parágrafos para verificação independente de inglês e legenda
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
        
        # Extrai tamanhos
        sizes = []
        for p in article.select('div#informacoes > p'):
            html_content = str(p)
            html_content = html_content.replace('\n', '').replace('\t', '')
            html_content = re.sub(r'<br\s*\/?>', '<br>', html_content)
            lines = html_content.split('<br>')
            
            text = '\n'.join(re.sub(r'<[^>]*>', '', line).strip() for line in lines)
            y = find_year_from_text(text, title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
        
        # Extrai links magnet - busca TODOS os links <a> no conteúdo
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        # Primeiro tenta em container específico (mais rápido)
        text_content = article.find('div', class_='apenas_itemprop')
        
        magnet_links = []
        if text_content:
            for link in text_content.select('a[href]'):
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
        
        # Extrai IMDB - prioriza links dentro de div#informacoes (conteúdo principal)
        imdb = ''
        # Primeiro busca dentro de div#informacoes (conteúdo principal)
        info_div = article.find('div', id='informacoes')
        if info_div:
            for a in info_div.select('a'):
                href = a.get('href', '')
                if 'imdb.com' in href:
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
        
        # Se não encontrou em div#informacoes, busca em toda a página
        if not imdb:
            for a in article.select('a'):
                href = a.get('href', '')
                if 'imdb.com' in href:
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
        
        # Remove duplicados de tamanhos
        sizes = list(dict.fromkeys(sizes))
        
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
                
                # Se ainda está missing_dn, tenta buscar do cross_data
                if missing_dn and cross_data and cross_data.get('magnet_processed'):
                    magnet_original = cross_data['magnet_processed']
                    missing_dn = False
                
                # Salva magnet_processed no Redis se encontrado (para reutilização por outros scrapers)
                if not missing_dn and magnet_original:
                    try:
                        from utils.text.storage import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, magnet_original)
                    except Exception:
                        pass
                
                fallback_title = original_title if original_title else title
                original_release_title = prepare_release_title(
                    magnet_original,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title, title_translated_html=title_translated_processed if title_translated_processed else None, magnet_original_magnet=magnet_original
                )
                
                # Adiciona [Brazilian] se detectar DUAL/DUBLADO/NACIONAL, [Eng] se LEGENDADO, ou ambos se houver os dois
                # Passa audio_info extraído do HTML (Idioma/Legenda) e audio_html_content para detecção adicional
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
                if magnet_original and ('dual' in magnet_original.lower() or 'dublado' in magnet_original.lower() or 'legendado' in magnet_original.lower()):
                    origem_audio_tag = 'magnet_processed'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                # Extrai tamanho
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Processa trackers usando função utilitária
                trackers = process_trackers(magnet_data)
                
                # Salva dados cruzados no Redis para reutilização por outros scrapers
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
                logger.error(f"Magnet error: {format_error(e)} (link: {format_link_preview(magnet_link)})")
                continue
        
        return torrents


