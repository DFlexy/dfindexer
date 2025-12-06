"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_parser import parse_date_from_string
from typing import List, Dict, Optional, Callable, Tuple
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.text_processing import (
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    detect_audio_from_html, add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)
from app.config import Config

logger = logging.getLogger(__name__)


# Scraper específico para Nerd Torrent HD
class NerdScraper(BaseScraper):
    SCRAPER_TYPE = "nerd"
    DEFAULT_BASE_URL = "https://nerdtorrenthd.net/"
    DISPLAY_NAME = "Nerd"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
    # Busca torrents com variações da query
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        return self._default_search(query, filter_func)
    
    # Extrai links da página inicial (lógica especial para separar filmes, séries e animes)
    def _extract_links_from_page(self, doc: BeautifulSoup) -> Tuple[List[str], List[str], List[str]]:
        # Separa links de filmes, séries e animes dentro das seções específicas
        filmes_links = []
        series_links = []
        animes_links = []
        
        # Encontra a seção "Últimos Filmes Torrent"
        filmes_h2 = None
        for h2 in doc.find_all('h2', class_='titulo-bloco'):
            if 'Últimos Filmes Torrent' in h2.get_text():
                filmes_h2 = h2
                break
        
        if filmes_h2:
            # Encontra o container pai (section.filmes)
            filmes_section = filmes_h2.find_parent('section', class_='filmes')
            if filmes_section:
                # Pega todos os links dentro de .listagem > article.item > a
                listagem = filmes_section.find('div', class_='listagem')
                if listagem:
                    for item in listagem.find_all('article', class_='item'):
                        link_elem = item.find('a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                filmes_links.append(href)
        
        # Encontra a seção "Últimas Séries Torrent"
        series_h2 = None
        for h2 in doc.find_all('h2', class_='titulo-bloco'):
            if 'Últimas Séries Torrent' in h2.get_text():
                series_h2 = h2
                break
        
        if series_h2:
            # Encontra o container pai (section.filmes)
            series_section = series_h2.find_parent('section', class_='filmes')
            if series_section:
                # Pega todos os links dentro de .listagem > article.item > a
                listagem = series_section.find('div', class_='listagem')
                if listagem:
                    for item in listagem.find_all('article', class_='item'):
                        link_elem = item.find('a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                series_links.append(href)
        
        # Encontra a seção "Ultimos Animes Torrent"
        animes_h2 = None
        for h2 in doc.find_all('h2', class_='titulo-bloco'):
            if 'Ultimos Animes Torrent' in h2.get_text() or 'Últimos Animes Torrent' in h2.get_text():
                animes_h2 = h2
                break
        
        if animes_h2:
            # Encontra o container pai (section.filmes)
            animes_section = animes_h2.find_parent('section', class_='filmes')
            if animes_section:
                # Pega todos os links dentro de .listagem > article.item > a
                listagem = animes_section.find('div', class_='listagem')
                if listagem:
                    for item in listagem.find_all('article', class_='item'):
                        link_elem = item.find('a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                animes_links.append(href)
        
        # Retorna tupla com filmes, séries e animes separados
        return (filmes_links, series_links, animes_links)
    
    # Obtém torrents de uma página específica (usa helper padrão com extração customizada)
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        # Prepara flags de teste/metadata/trackers (centralizado no BaseScraper)
        is_using_default_limit, skip_metadata, skip_trackers = self._prepare_page_flags(max_items)
        
        try:
            # Constrói URL da página usando função utilitária
            from utils.concurrency.scraper_helpers import (
                build_page_url, get_effective_max_items, limit_list,
                process_links_parallel, process_links_sequential
            )
            page_url = build_page_url(self.base_url, self.page_pattern, page)
            
            doc = self.get_document(page_url, self.base_url)
            if not doc:
                return []
            
            # Extrai links usando método específico do scraper (retorna tupla separada)
            filmes_links, series_links, animes_links = self._extract_links_from_page(doc)
            
            # Obtém limite efetivo usando função utilitária
            effective_max = get_effective_max_items(max_items)
            
            # Quando há limite configurado, coleta um terço de cada seção
            # Caso contrário, coleta todos de todas as seções
            if effective_max > 0:
                # Calcula um terço do limite para cada seção
                third_limit = max(1, effective_max // 3)
                
                # Limita cada seção a um terço
                filmes_links = limit_list(filmes_links, third_limit)
                series_links = limit_list(series_links, third_limit)
                animes_links = limit_list(animes_links, third_limit)
                
                logger.info(f"[Nerd] Limite configurado: {effective_max} - Coletando {len(filmes_links)} filmes, {len(series_links)} séries e {len(animes_links)} animes")
                links = filmes_links + series_links + animes_links
            else:
                # Sem limite, combina todos os links
                links = filmes_links + series_links + animes_links
                logger.debug(f"[Nerd] Sem limite - Coletando {len(filmes_links)} filmes, {len(series_links)} séries e {len(animes_links)} animes")
            
            # Quando há limite configurado, processa sequencialmente para manter ordem original
            # Caso contrário, processa em paralelo para melhor performance
            if effective_max > 0:
                all_torrents = process_links_sequential(
                    links,
                    self._get_torrents_from_page,
                    None  # Sem limite no processamento - já limitamos os links acima
                )
            else:
                all_torrents = process_links_parallel(
                    links,
                    self._get_torrents_from_page,
                    None  # Sem limite no processamento - já limitamos os links acima
                )
            
            # Enriquece torrents (usa flags preparadas pelo BaseScraper)
            enriched = self.enrich_torrents(
                all_torrents,
                skip_metadata=skip_metadata,
                skip_trackers=skip_trackers
            )
            # Retorna todos os magnets encontrados (sem limite nos resultados finais)
            return enriched
        finally:
            self._skip_metadata = False
            self._is_test = False
    
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
            
            # Tenta primeiro os seletores específicos do site (estrutura da página inicial)
            for item in doc.select('.listagem .item a'):
                href = item.get('href')
                if href:
                    absolute_url = urljoin(self.base_url, href)
                    links.append(absolute_url)
            
            # Se não encontrou com seletor específico, tenta alternativos
            if not links:
                for item in doc.select('div.listagem div.item a'):
                    href = item.get('href')
                    if href:
                        absolute_url = urljoin(self.base_url, href)
                        links.append(absolute_url)
            
            # Fallback: tenta seletores WordPress comuns
            if not links:
                for article in doc.select('article.post'):
                    link_elem = article.select_one('h2.entry-title a, h1.entry-title a, header.entry-header a')
                    if link_elem:
                        href = link_elem.get('href')
                        if href:
                            absolute_url = urljoin(self.base_url, href)
                            links.append(absolute_url)
        
        return list(set(links))  # Remove duplicados
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        # Garante que o link seja absoluto para o campo details
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da URL
        date = parse_date_from_string(link)
        
        # Fallback: Se não encontrou, usa data atual
        if not date:
            date = datetime.now()
        
        torrents = []
        
        # Tenta encontrar o conteúdo principal
        content_div = None
        content_selectors = [
            'article',
            '.entry-content',
            '.post-content',
            '.content',
            'main',
            '.main-content'
        ]
        
        for selector in content_selectors:
            content_div = doc.select_one(selector)
            if content_div:
                break
        
        if not content_div:
            return []
        
        # Extrai título da página
        page_title = ''
        title_selectors = [
            'h1.entry-title',
            'h1.post-title',
            'h1',
            '.entry-title',
            '.post-title',
            'article h1'
        ]
        
        for selector in title_selectors:
            title_elem = doc.select_one(selector)
            if title_elem:
                page_title = title_elem.get_text(strip=True)
                break
        
        # Extrai título original
        original_title = ''
        # Primeiro tenta buscar no HTML completo do content_div (para pegar casos onde está em tags quebradas)
        content_html = str(content_div)
        if re.search(r'(?i)T[íi]tulo\s+Original\s*:?', content_html):
            # Busca no HTML completo primeiro (mais confiável para tags quebradas)
            # Tenta padrão com </b> após os dois pontos (caso comum)
            html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*</b>\s*(.*?)(?:<br\s*/?>|</span|</p|</div|</strong|$)', content_html, re.DOTALL)
            if not html_match:
                # Fallback: padrão sem </b>
                html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*(.*?)(?:<br\s*/?>|</span|</p|</div|</strong|$)', content_html, re.DOTALL)
            
            if html_match:
                html_text = html_match.group(1)
                html_text = re.sub(r'<[^>]+>', '', html_text)
                html_text = html_text.strip()
                if html_text:
                    original_title = html_text
        
        # Se não encontrou no HTML completo, busca elemento por elemento
        if not original_title:
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                if re.search(r'(?i)T[íi]tulo\s+Original\s*:?', elem_html):
                    text_parts = elem_text.split('Título Original:')
                    if len(text_parts) > 1:
                        original_title = text_parts[1].strip()
                    
                    # Tenta extrair do HTML do elemento (com </b> primeiro)
                    html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*</b>\s*(.*?)(?:<br\s*/?>|</span|</p|</div|</strong|$)', elem_html, re.DOTALL)
                    if not html_match:
                        html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*(.*?)(?:<br\s*/?>|</span|</p|</div|</strong|$)', elem_html, re.DOTALL)
                    
                    if html_match:
                        html_text = html_match.group(1)
                        html_text = re.sub(r'<[^>]+>', '', html_text)
                        html_text = html_text.strip()
                        if html_text:
                            original_title = html_text
                    
                    if original_title:
                        break
        
        # Processa o título original encontrado
        if original_title:
            original_title = html.unescape(original_title)
            original_title = re.sub(r'\s+', ' ', original_title).strip()
            for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:', 'Título Traduzido:']:
                if stop in original_title:
                    original_title = original_title.split(stop)[0].strip()
                    break
        
        # Extrai título traduzido de "Baixar Título:" ou "Baixar Filme:"
        # Primeiro tenta buscar no elemento poster-info (mais específico)
        translated_title = ''
        poster_info = doc.select_one('.poster-info')
        if poster_info:
            poster_html = str(poster_info)
            poster_text = poster_info.get_text(' ', strip=True)
            
            # Busca por "Baixar Título:" ou "Baixar Filme:"
            if re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?', poster_html):
                # Tenta extrair do HTML primeiro (mais preciso)
                html_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.*?)(?:<br|</span|</p|</div|</b|$)', poster_html, re.DOTALL)
                if html_match:
                    html_text = html_match.group(1)
                    html_text = re.sub(r'<[^>]+>', '', html_text)
                    html_text = html_text.strip()
                    if html_text:
                        translated_title = html_text
                else:
                    # Fallback: extrai do texto
                    text_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.*)', poster_text)
                    if text_match:
                        translated_title = text_match.group(1).strip()
        
        # Se não encontrou no poster-info, busca em todos os elementos do content_div
        if not translated_title:
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                # Busca por "Baixar Título:" ou "Baixar Filme:"
                if re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?', elem_html):
                    # Tenta extrair do HTML primeiro (mais preciso)
                    html_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.*?)(?:<br|</span|</p|</div|</b|$)', elem_html, re.DOTALL)
                    if html_match:
                        html_text = html_match.group(1)
                        html_text = re.sub(r'<[^>]+>', '', html_text)
                        html_text = html_text.strip()
                        if html_text:
                            translated_title = html_text
                    else:
                        # Fallback: extrai do texto
                        text_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.*)', elem_text)
                        if text_match:
                            translated_title = text_match.group(1).strip()
                    
                    if translated_title:
                        break
        
        # Fallback: busca na meta tag og:description
        if not translated_title:
            og_description = doc.find('meta', property='og:description')
            if og_description:
                og_content = og_description.get('content', '')
                if og_content:
                    # Busca por "Baixar Título:" na meta description
                    # Extrai tudo até "Título Original:" ou fim da string
                    meta_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.+?)(?:\s+Título Original|$)', og_content)
                    if meta_match:
                        translated_title = meta_match.group(1).strip()
        
        # Fallback adicional: busca na meta tag og:title
        if not translated_title:
            og_title = doc.find('meta', property='og:title')
            if og_title:
                og_title_content = og_title.get('content', '')
                if og_title_content:
                    # Extrai o título da og:title (ex: "ZENSHU (2025) Torrent Dual Áudio Download")
                    # Remove ano, "Torrent", "Dual Áudio", "Download" e outras informações
                    og_title_clean = og_title_content.strip()
                    # Remove padrões comuns: (2025), Torrent, Dual Áudio, Download
                    og_title_clean = re.sub(r'\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*', ' ', og_title_clean)
                    og_title_clean = re.sub(r'\s+Torrent\s+.*$', '', og_title_clean, flags=re.IGNORECASE)
                    og_title_clean = re.sub(r'\s+Dual\s+Áudio\s+Download\s*$', '', og_title_clean, flags=re.IGNORECASE)
                    og_title_clean = re.sub(r'\s+Download\s*$', '', og_title_clean, flags=re.IGNORECASE)
                    og_title_clean = html.unescape(og_title_clean)
                    og_title_clean = re.sub(r'\s+', ' ', og_title_clean).strip()
                    if og_title_clean:
                        translated_title = og_title_clean
        
        # Processa o título traduzido encontrado
        if translated_title:
            # Remove "Torrent" do final
            translated_title = re.sub(r'\s+Torrent\s*$', '', translated_title, flags=re.IGNORECASE)
            # Remove ano entre parênteses (ex: (2025))
            translated_title = re.sub(r'\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*$', '', translated_title)
            # Remove outros padrões comuns
            translated_title = re.sub(r'\s*Torrent\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*$', '', translated_title, flags=re.IGNORECASE)
            
            translated_title = html.unescape(translated_title)
            translated_title = re.sub(r'\s+', ' ', translated_title).strip()
            
            # Para antes de outros campos (Gênero, Duração, etc.)
            for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:', 'Título Original:']:
                if stop in translated_title:
                    translated_title = translated_title.split(stop)[0].strip()
                    break
            
            if translated_title:
                from utils.text.text_processing import clean_translated_title
                translated_title = clean_translated_title(translated_title)
        
        # Fallback: usa título da página se não encontrou título original
        if not original_title:
            original_title = page_title
        
        # Extrai ano, tamanhos, áudio e IMDB
        year = ''
        sizes = []
        imdb = ''
        audio_info = ''  # Para detectar "Áudio: Português", "Multi-Áudio", "Inglês"
        
        for p in content_div.select('p, span, div'):
            text = p.get_text()
            html_content = str(p)
            
            y = find_year_from_text(text, original_title or page_title)
            if y:
                year = y
            
            sizes.extend(find_sizes_from_text(html_content))
            
            # Extrai informação de áudio usando função utilitária
            if not audio_info:
                audio_info = detect_audio_from_html(html_content)
            
            # Extrai IMDB
            if not imdb:
                imdb_em = p.find('em', string=re.compile(r'IMDb:', re.I))
                if imdb_em:
                    parent = imdb_em.parent
                    if parent:
                        for a in parent.select('a[href*="imdb.com"]'):
                            href = a.get('href', '')
                            imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                            if imdb_match:
                                imdb = imdb_match.group(1)
                                break
                            imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                            if imdb_match:
                                imdb = imdb_match.group(1)
                                break
                
                if not imdb:
                    text_lower = text.lower()
                    has_imdb_label = 'imdb' in text_lower or 'imdb:' in text_lower
                    for a in p.select('a[href*="imdb.com"]'):
                        href = a.get('href', '')
                        imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                        if imdb_match:
                            imdb = imdb_match.group(1)
                            if has_imdb_label:
                                break
                            continue
                        imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                        if imdb_match:
                            imdb = imdb_match.group(1)
                            if has_imdb_label:
                                break
                            continue
        
        # Extrai links magnet - busca TODOS os links <a> no documento
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        all_links = doc.select('a[href]')
        
        magnet_links = []
        for link in all_links:
            href = link.get('href', '')
            if not href:
                continue
            
            # Resolve automaticamente (magnet direto ou protegido)
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet and resolved_magnet.startswith('magnet:') and resolved_magnet not in magnet_links:
                magnet_links.append(resolved_magnet)
        
        if not magnet_links:
            return []
        
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
                        from utils.text.text_processing import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, raw_release_title)
                    except Exception:
                        pass
                
                fallback_title = original_title if original_title else (translated_title if translated_title else page_title or '')
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
                
                # Adiciona [Brazilian], [Eng] (via HTML) e/ou [Leg] conforme detectado
                # NÃO adiciona DUAL/PORTUGUES/LEGENDADO ao release_title - apenas passa audio_info para a função de tags
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title, info_hash=info_hash, skip_metadata=self._skip_metadata, audio_info_from_html=audio_info)
                
                # Determina origem_audio_tag
                origem_audio_tag = 'N/A'
                if audio_info:
                    origem_audio_tag = f'HTML da página (detect_audio_from_html)'
                elif raw_release_title and ('dual' in raw_release_title.lower() or 'dublado' in raw_release_title.lower() or 'legendado' in raw_release_title.lower()):
                    origem_audio_tag = 'release_title_magnet'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                # Extrai tamanho do magnet se disponível
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Salva dados cruzados no Redis para reutilização por outros scrapers
                try:
                    from utils.text.cross_data import save_cross_data_to_redis
                    cross_data_to_save = {
                        'original_title_html': original_title if original_title else None,
                        'release_title_magnet': raw_release_title if not missing_dn else None,
                        'translated_title_html': translated_title if translated_title else None,
                        'imdb': imdb if imdb else None,
                        'missing_dn': missing_dn,
                        'origem_audio_tag': origem_audio_tag if origem_audio_tag != 'N/A' else None
                    }
                    save_cross_data_to_redis(info_hash, cross_data_to_save)
                except Exception:
                    pass
                
                torrent = {
                    'title': final_title,
                    'original_title': original_title if original_title else (translated_title if translated_title else page_title),
                    'translated_title': translated_title if translated_title else None,
                    'details': absolute_link,
                    'year': year,
                    'imdb': imdb if imdb else '',
                    'audio': [],
                    'magnet_link': magnet_link,
                    'date': date.isoformat(),
                    'info_hash': info_hash,
                    'trackers': process_trackers(magnet_data),
                    'size': size,
                    'leech_count': 0,
                    'seed_count': 0,
                    'similarity': 1.0
                }
                torrents.append(torrent)
            
            except Exception as e:
                logger.error(f"Erro ao processar magnet {link}: {e}")
                continue
        
        return torrents

