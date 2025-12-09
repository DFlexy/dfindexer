"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_parser import parse_date_from_string
from typing import List, Dict, Optional, Callable, Tuple
from urllib.parse import quote, unquote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.text_processing import (
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)
from app.config import Config
from utils.logging import ScraperLogContext

logger = logging.getLogger(__name__)

# Contexto de logging centralizado para este scraper
_log_ctx = ScraperLogContext("TFilme", logger)


# Scraper específico para Torrent dos Filmes
class TfilmeScraper(BaseScraper):
    SCRAPER_TYPE = "tfilme"
    DEFAULT_BASE_URL = "https://torrentdosfilmes.se/"
    DISPLAY_NAME = "TFilme"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "category/dublado/page/{}/"
    
    # Busca torrents com variações da query
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        return self._default_search(query, filter_func)
    
    # Extrai links da página inicial (lógica especial para separar filmes e séries)
    def _extract_links_from_page(self, doc: BeautifulSoup) -> Tuple[List[str], List[str]]:
        # Separa links de filmes e séries dentro das seções específicas
        filmes_links = []
        series_links = []
        
        # Encontra a seção "Últimos Filmes Adicionados"
        filmes_h3 = None
        for h3 in doc.find_all('h3'):
            if h3.get_text(strip=True) == 'Últimos Filmes Adicionados':
                filmes_h3 = h3
                break
        
        if filmes_h3:
            # Encontra o container pai (titleGeral)
            title_geral_filmes = filmes_h3.find_parent('div', class_='titleGeral')
            if title_geral_filmes:
                # Pega todos os .post.green que vêm depois deste titleGeral
                # até encontrar o próximo titleGeral ou fim da seção
                current = title_geral_filmes.find_next_sibling()
                while current:
                    # Se encontrar outro titleGeral, para
                    if current.name == 'div' and 'titleGeral' in current.get('class', []):
                        break
                    # Se encontrar um .post.green, extrai o link
                    if current.name == 'div' and 'post' in current.get('class', []) and 'green' in current.get('class', []):
                        link_elem = current.select_one('div.title > a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                filmes_links.append(href)
                    current = current.find_next_sibling()
        
        # Encontra a seção "Últimas Séries Adicionadas"
        series_h3 = None
        for h3 in doc.find_all('h3'):
            if h3.get_text(strip=True) == 'Últimas Séries Adicionadas':
                series_h3 = h3
                break
        
        if series_h3:
            # Encontra o container pai (titleGeral)
            title_geral_series = series_h3.find_parent('div', class_='titleGeral')
            if title_geral_series:
                # Pega todos os .post.blue que vêm depois deste titleGeral
                # até encontrar o próximo titleGeral ou fim da seção
                current = title_geral_series.find_next_sibling()
                while current:
                    # Se encontrar outro titleGeral, para
                    if current.name == 'div' and 'titleGeral' in current.get('class', []):
                        break
                    # Se encontrar um .post.blue, extrai o link
                    if current.name == 'div' and 'post' in current.get('class', []) and 'blue' in current.get('class', []):
                        link_elem = current.select_one('div.title > a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                series_links.append(href)
                    current = current.find_next_sibling()
        
        # Retorna tupla com filmes e séries separados
        return (filmes_links, series_links)
    
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
            filmes_links, series_links = self._extract_links_from_page(doc)
            
            # Obtém limite efetivo usando função utilitária
            effective_max = get_effective_max_items(max_items)
            
            # Quando há limite configurado, coleta metade de cada seção
            # Caso contrário, coleta todos de ambas as seções
            if effective_max > 0:
                # Calcula metade do limite para cada seção
                half_limit = max(1, effective_max // 2)
                
                # Limita cada seção à metade
                filmes_links = limit_list(filmes_links, half_limit)
                series_links = limit_list(series_links, half_limit)
                
                _log_ctx.info(f"Limite configurado: {effective_max} - Coletando {len(filmes_links)} filmes e {len(series_links)} séries")
                links = filmes_links + series_links
            else:
                # Sem limite, combina todos os links
                links = filmes_links + series_links
            
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
            
            for item in doc.select('.post'):
                link_elem = item.select_one('div.title > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        
        return list(set(links))
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        # Garante que o link seja absoluto para o campo details
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da URL do link
        date = parse_date_from_string(link)
        
        # Fallback: Se não encontrou, usa data atual
        if not date:
            date = datetime.now()
        
        torrents = []
        article = doc.find('article')
        if not article:
            return []
        
        # Extrai título da página
        page_title = ''
        title_div = article.find('div', class_='title')
        if title_div:
            h1 = title_div.find('h1')
            if h1:
                page_title = h1.get_text(strip=True).replace(' - Download', '')
        
        if not page_title:
            return []
        
        # Extrai título original
        original_title = ''
        for content_div in article.select('div.content'):
            html_content = str(content_div)
            
            # Tenta regex no HTML
            title_regex = re.compile(r'(?i)t[íi]tulo\s+original:\s*</b>\s*([^<\n\r]+)')
            match = title_regex.search(html_content)
            if match:
                original_title = match.group(1).strip()
            else:
                # Tenta extrair do texto
                text = content_div.get_text()
                if 'Título Original:' in text:
                    parts = text.split('Título Original:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        stop_words = ['Lançamento', 'Gênero', 'IMDB', 'Duração', 'Qualidade', 'Áudio', 'Sinopse']
                        for stop_word in stop_words:
                            if stop_word in title_part:
                                idx = title_part.index(stop_word)
                                title_part = title_part[:idx]
                                break
                        lines = title_part.split('\n')
                        if lines:
                            original_title = lines[0].strip()
                elif 'Titulo Original:' in text:
                    parts = text.split('Titulo Original:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        stop_words = ['Lançamento', 'Gênero', 'IMDB', 'Duração', 'Qualidade', 'Áudio', 'Sinopse']
                        for stop_word in stop_words:
                            if stop_word in title_part:
                                idx = title_part.index(stop_word)
                                title_part = title_part[:idx]
                                break
                        lines = title_part.split('\n')
                        if lines:
                            original_title = lines[0].strip()
        
        # Extrai título traduzido
        translated_title = ''
        for content_div in article.select('div.content'):
            html_content = str(content_div)
            
            # Tenta regex no HTML
            title_regex = re.compile(r'(?i)t[íi]tulo\s+traduzido:\s*</b>\s*([^<\n\r]+)')
            match = title_regex.search(html_content)
            if match:
                translated_title = match.group(1).strip()
                # Remove qualquer HTML que possa ter sobrado
                translated_title = re.sub(r'<[^>]+>', '', translated_title)
                translated_title = html.unescape(translated_title)
            else:
                # Tenta extrair do texto
                text = content_div.get_text()
                if 'Título Traduzido:' in text:
                    parts = text.split('Título Traduzido:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        stop_words = ['Lançamento', 'Gênero', 'IMDB', 'Duração', 'Qualidade', 'Áudio', 'Sinopse', 'Título Original']
                        for stop_word in stop_words:
                            if stop_word in title_part:
                                idx = title_part.index(stop_word)
                                title_part = title_part[:idx]
                                break
                        lines = title_part.split('\n')
                        if lines:
                            translated_title = lines[0].strip()
                elif 'Titulo Traduzido:' in text:
                    parts = text.split('Titulo Traduzido:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        stop_words = ['Lançamento', 'Gênero', 'IMDB', 'Duração', 'Qualidade', 'Áudio', 'Sinopse', 'Título Original']
                        for stop_word in stop_words:
                            if stop_word in title_part:
                                idx = title_part.index(stop_word)
                                title_part = title_part[:idx]
                                break
                        lines = title_part.split('\n')
                        if lines:
                            translated_title = lines[0].strip()
            if translated_title:
                # Remove qualquer HTML que possa ter sobrado
                translated_title = re.sub(r'<[^>]+>', '', translated_title)
                translated_title = html.unescape(translated_title)
                # Limpa o título traduzido
                from utils.text.text_processing import clean_translated_title
                translated_title = clean_translated_title(translated_title)
                break
        
        # Extrai ano e tamanhos
        year = ''
        sizes = []
        for p in article.select('div.content p'):
            text = p.get_text()
            y = find_year_from_text(text, page_title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
        
        # Extrai links magnet - busca TODOS os links <a> no conteúdo
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        text_content = article.find('div', class_='content')
        if not text_content:
            return []
        
        magnet_links = []
        for link in text_content.select('a[href]'):
            href = link.get('href', '')
            if not href:
                continue
            
            # Resolve automaticamente (magnet direto ou protegido)
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet and resolved_magnet.startswith('magnet:') and resolved_magnet not in magnet_links:
                magnet_links.append(resolved_magnet)
        
        if not magnet_links:
            return []
        
        # Extrai IMDB - padrão específico do torrentdosfilmes
        # Formato: <strong>IMDb</strong>: <a href="https://www.imdb.com/title/tt33484460/" target="_blank" rel="noopener">5,7
        imdb = ''
        # Busca padrão específico: <strong>IMDb</strong> seguido de link
        imdb_strong = article.find('strong', string=re.compile(r'IMDb', re.I))
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
        
        # Se não encontrou, busca em toda a página dentro de div.content
        if not imdb:
            content_div = article.find('div', class_='content')
            if content_div:
                for a in content_div.select('a[href*="imdb.com"]'):
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
                
                fallback_title = page_title or original_title or ''
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
                
                # Adiciona [Brazilian] se detectar DUAL/DUBLADO/NACIONAL, [Eng] se LEGENDADO, ou ambos se houver os dois
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title, info_hash=info_hash, skip_metadata=self._skip_metadata)
                
                # Determina origem_audio_tag
                origem_audio_tag = 'N/A'
                if raw_release_title and ('dual' in raw_release_title.lower() or 'dublado' in raw_release_title.lower() or 'legendado' in raw_release_title.lower()):
                    origem_audio_tag = 'release_title_magnet'
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
                    'date': date.isoformat(),
                    'info_hash': info_hash,
                    'trackers': trackers,
                    'size': size,
                    'leech_count': 0,
                    'seed_count': 0,
                    'similarity': 1.0
                }
                torrents.append(torrent)
            
            except Exception as e:
                _log_ctx.error_magnet(magnet_link, e)
                continue
        
        return torrents


