"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, quote_plus, unquote, urljoin
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
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
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
        seen_urls = set()  # Para evitar duplicatas entre variações
        variations = [query]
        
        # Primeira palavra (se não for stop word)
        # IMPORTANTE: Para queries com 3+ palavras, NÃO usa apenas a primeira palavra
        # pois isso gera muitos resultados irrelevantes (ex: "great flood 2025" → busca só "great")
        query_words = query.split()
        if len(query_words) > 1 and len(query_words) < 3:
            # Apenas para queries de 2 palavras, permite buscar só a primeira
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])
        
        for variation in variations:
            # Página 1: sempre usa index.php?s={query} (usa + para espaços)
            page = 1
            use_query_format = None  # None = ainda não detectou, True = usa query string, False = usa {query}/{page}/
            
            while True:
                if page == 1:
                    search_url = f"{self.base_url}{self.search_url}{quote_plus(variation)}"
                else:
                    # Páginas seguintes: detecta formato na primeira página
                    if use_query_format is None:
                        # Se chegou aqui, não há paginação ou formato não detectado
                        break
                    elif use_query_format:
                        # Formato: index.php?s={query}&page={page}
                        search_url = f"{self.base_url}{self.search_url}{quote_plus(variation)}&page={page}"
                    else:
                        # Formato: {query}/{page}/
                        # O site usa a query com espaços substituídos por hífens ou codificada
                        # Tenta primeiro com hífens (formato mais comum)
                        query_formatted = variation.lower().replace(' ', '-')
                        search_url = f"{self.base_url}{query_formatted}/{page}/"
                
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
                
                # Adiciona apenas links únicos
                for link in page_links:
                    absolute_url = urljoin(self.base_url, link) if link and not link.startswith('http') else link
                    if absolute_url not in seen_urls:
                        links.append(absolute_url)
                        seen_urls.add(absolute_url)
                
                # Na página 1, detecta qual formato de paginação o site está usando
                if page == 1:
                    pagination_links = doc.select('a[href], .pagination a, .wp-pagenavi a')
                    for pag_link in pagination_links:
                        href = pag_link.get('href', '').lower()
                        # Verifica se há formato {query}/{2}/ na paginação
                        # Procura por links que terminam com /2/ ou /3/ e não contêm index.php
                        if '/2/' in href or '/3/' in href:
                            if 'index.php' not in href and 'page=' not in href:
                                use_query_format = False  # Usa formato {query}/{page}/
                                break
                        # Verifica se há formato com query string page=2
                        elif "page=2" in href or "&page=2" in href or "?page=2" in href:
                            use_query_format = True  # Usa formato query string
                            break
                
                # Verifica se há próxima página
                has_next_page = False
                if page == 1 and use_query_format is None:
                    # Se não detectou formato na página 1, não há paginação
                    break
                
                pagination_links = doc.select('a[href], .pagination a, .wp-pagenavi a')
                for pag_link in pagination_links:
                    href = pag_link.get('href', '')
                    text = pag_link.get_text(strip=True).lower()
                    
                    if use_query_format:
                        # Formato query string: procura page={page+1}
                        if (f"page={page + 1}" in href) or (f"&page={page + 1}" in href):
                            has_next_page = True
                            break
                    else:
                        # Formato {query}/{page}/: procura /{page+1}/
                        if f"/{page + 1}/" in href:
                            has_next_page = True
                            break
                    
                    # Verifica texto "próxima" ou número maior
                    if text in ['próxima', 'next', '>', '»']:
                        has_next_page = True
                        break
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
        
        # Extrai informações de idioma do HTML (áudio)
        audio_info = None  # Para detectar áudio/idioma do HTML
        audio_html_content = ''  # Armazena HTML completo para verificação adicional
        all_paragraphs_html = []  # Coleta HTML de todos os parágrafos
        
        idioma = ''
        
        # Busca Idioma em div#informacoes
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
        
        # Extrai legenda usando função dedicada
        from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
        legenda = extract_legenda_from_page(doc, scraper_type='rede', article=article)
        
        # Determina legend_info baseado na legenda extraída
        legend_info = determine_legend_info(legenda) if legenda else None
        
        # Determina audio_info baseado em Idioma
        # Suporta múltiplos idiomas: "Português, Inglês" ou "Português, Japonês" (máximo 3)
        if idioma:
            idioma_lower = idioma.lower()
            
            # Lista de idiomas detectados
            idiomas_detectados = []
            
            # Verifica se tem português no idioma (áudio)
            if 'português' in idioma_lower or 'portugues' in idioma_lower:
                idiomas_detectados.append('português')
            # Verifica se tem Inglês no idioma (áudio)
            if 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower:
                idiomas_detectados.append('inglês')
            # Verifica se tem Japonês no idioma (áudio)
            if 'japonês' in idioma_lower or 'japones' in idioma_lower or 'japanese' in idioma_lower or 'jap' in idioma_lower:
                idiomas_detectados.append('japonês')
            
            # Limita a 3 idiomas no máximo
            idiomas_detectados = idiomas_detectados[:3]
            
            # Determina audio_info baseado nos idiomas detectados
            if len(idiomas_detectados) >= 2:
                # Se tem 2 ou mais idiomas, usa 'dual' (português + outro)
                if 'português' in idiomas_detectados and 'inglês' in idiomas_detectados:
                    audio_info = 'dual'  # Português + Inglês
                elif 'português' in idiomas_detectados:
                    audio_info = 'dual'  # Português + outro idioma
                else:
                    # Se não tem português mas tem múltiplos, usa o primeiro
                    audio_info = idiomas_detectados[0]
            elif len(idiomas_detectados) == 1:
                audio_info = idiomas_detectados[0]
        
        # Concatena HTML de todos os parágrafos para verificação independente de inglês e legenda
        # IMPORTANTE: Garante que a legenda extraída esteja no HTML para que add_audio_tag_if_needed possa detectá-la
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
            # Se extraiu legenda mas não está no HTML (pode ter sido extraída via texto), adiciona explicitamente
            # Isso é crítico para que add_audio_tag_if_needed detecte a legenda mesmo quando há dual audio
            if legenda and 'Legenda' not in audio_html_content and 'legenda' not in audio_html_content.lower():
                # Adiciona a legenda no formato que add_audio_tag_if_needed espera (Legenda: Português)
                audio_html_content += f' Legenda: {legenda}'
        
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
                    original_title, year, original_release_title, title_translated_html=title_translated_processed if title_translated_processed else None, magnet_original=magnet_original
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
                
                # Determina presença de legenda seguindo ordem de fallbacks
                from utils.parsing.legend_extraction import determine_legend_presence
                has_legenda = determine_legend_presence(
                    legend_info_from_html=legend_info,
                    audio_html_content=audio_html_content,
                    magnet_processed=original_release_title,
                    info_hash=info_hash,
                    skip_metadata=self._skip_metadata
                )
                
                # Salva dados cruzados no Redis para reutilização por outros scrapers
                try:
                    from utils.text.cross_data import save_cross_data_to_redis
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
                    'magnet_original': magnet_original if magnet_original else None,
                    'legend': legend_info if legend_info else None,
                    'has_legenda': has_legenda
                }
                torrents.append(torrent)
            
            except Exception as e:
                logger.error(f"Magnet error: {format_error(e)} (link: {format_link_preview(magnet_link)})")
                continue
        
        return torrents


