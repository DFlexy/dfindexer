"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable, Tuple
from urllib.parse import unquote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.parsing.audio_extraction import add_audio_tag_if_needed
from utils.text.title_builder import create_standardized_title, prepare_release_title
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
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        # Prepara flags de teste/metadata/trackers (centralizado no BaseScraper)
        is_using_default_limit, skip_metadata, skip_trackers = self._prepare_page_flags(max_items, is_test=is_test)
        
        try:
            # Constrói URL da página usando função utilitária
            from utils.concurrency.scraper_helpers import (
                build_page_url, get_effective_max_items, limit_list,
                process_links_parallel
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
            
            # Usa processamento paralelo centralizado (mantém ordem original automaticamente)
            # NÃO passa limite de torrents - o limite já foi aplicado nos links acima
            all_torrents = process_links_parallel(
                links,
                self._get_torrents_from_page,
                None,  # Sem limite de torrents - processa todos os links limitados
                scraper_name=self.SCRAPER_TYPE if hasattr(self, 'SCRAPER_TYPE') else None,
                use_flaresolverr=self.use_flaresolverr
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
    
    # Extrai links dos resultados de busca (usa implementação base de _search_variations)
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select('.post'):
            link_elem = item.select_one('div.title > a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        return links
    
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
        title_translated_processed = ''
        for content_div in article.select('div.content'):
            html_content = str(content_div)
            
            # Tenta regex no HTML
            title_regex = re.compile(r'(?i)t[íi]tulo\s+traduzido:\s*</b>\s*([^<\n\r]+)')
            match = title_regex.search(html_content)
            if match:
                title_translated_processed = match.group(1).strip()
                # Remove qualquer HTML que possa ter sobrado
                title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
                title_translated_processed = html.unescape(title_translated_processed)
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
                            title_translated_processed = lines[0].strip()
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
                            title_translated_processed = lines[0].strip()
            if title_translated_processed:
                # Remove qualquer HTML que possa ter sobrado
                title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
                title_translated_processed = html.unescape(title_translated_processed)
                # Limpa o título traduzido
                from utils.text.cleaning import clean_title_translated_processed
                title_translated_processed = clean_title_translated_processed(title_translated_processed)
                break
        
        # Extrai ano e tamanhos
        year = ''
        sizes = []
        audio_info = None  # Para detectar áudio/idioma do HTML
        audio_html_content = ''  # Armazena HTML completo para verificação adicional
        all_paragraphs_html = []  # Coleta HTML de todos os parágrafos
        
        # Extrai informações de idioma do HTML
        # Busca em div.content primeiro (estrutura padrão do tfilme)
        content_div = article.find('div', class_='content')
        idioma = ''
        
        if content_div:
            content_html = str(content_div)
            all_paragraphs_html.append(content_html)  # Adiciona HTML completo do content
            
            # Extrai Idioma
            idioma_match = re.search(r'(?i)<b>Idioma:</b>\s*([^<]+?)(?:<br|</div|</p|$)', content_html)
            if idioma_match:
                idioma = idioma_match.group(1).strip()
                # Remove entidades HTML
                idioma = html.unescape(idioma)
                idioma = re.sub(r'<[^>]+>', '', idioma).strip()
            
            # Se não encontrou com <b>, tenta sem tag bold
            if not idioma:
                idioma_match = re.search(r'(?i)Idioma\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|$)', content_html)
                if idioma_match:
                    idioma = idioma_match.group(1).strip()
                    idioma = html.unescape(idioma)
                    idioma = re.sub(r'<[^>]+>', '', idioma).strip()
        
        # Determina audio_info baseado apenas em Idioma (legenda será tratada separadamente)
        if idioma:
            idioma_lower = idioma.lower()
            
            # Verifica se tem português no idioma (áudio)
            has_portugues_audio = 'português' in idioma_lower or 'portugues' in idioma_lower
            # Verifica se tem Inglês no idioma
            has_ingles = 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower
            
            # Lógica simplificada:
            # Prioridade: Idioma com português primeiro (gera [Brazilian])
            if has_portugues_audio:
                # Idioma tem português → gera [Brazilian]
                audio_info = 'português'
            elif has_ingles:
                # Idioma tem Inglês → pode gerar [Eng]
                audio_info = 'inglês'
        
        # Se não encontrou em content, busca em parágrafos individuais
        if not audio_info:
            for p in article.select('div.content p'):
                text = p.get_text()
                html_content = str(p)
                all_paragraphs_html.append(html_content)  # Coleta HTML de todos os parágrafos
                y = find_year_from_text(text, page_title)
                if y:
                    year = y
                sizes.extend(find_sizes_from_text(text))
                
                # Extrai informação de áudio/legenda usando função utilitária
                if not audio_info:
                    from utils.parsing.audio_extraction import detect_audio_from_html
                    audio_info = detect_audio_from_html(html_content)
        else:
            # Se já encontrou audio_info, ainda precisa extrair ano e tamanhos
            for p in article.select('div.content p'):
                text = p.get_text()
                html_content = str(p)
                all_paragraphs_html.append(html_content)  # Coleta HTML de todos os parágrafos
                y = find_year_from_text(text, page_title)
                if y:
                    year = y
                sizes.extend(find_sizes_from_text(text))
        
        # Concatena HTML de todos os parágrafos para verificação independente de inglês e legenda
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
        
        # Extrai links magnet - busca TODOS os links <a> no conteúdo
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        # Primeiro tenta em container específico (mais rápido)
        text_content = article.find('div', class_='content')
        
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
                
                fallback_title = page_title or original_title or ''
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
                
                # Extrai legenda do HTML usando função dedicada
                from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
                legenda = extract_legenda_from_page(doc, scraper_type='tfilme')
                
                # Determina legend_info baseado na legenda extraída
                legend_info = determine_legend_info(legenda) if legenda else None
                
                # Determina presença de legenda seguindo ordem de fallbacks
                from utils.parsing.legend_extraction import determine_legend_presence
                has_legenda = determine_legend_presence(
                    legend_info_from_html=legend_info,
                    audio_html_content=audio_html_content,
                    magnet_processed=original_release_title,
                    info_hash=info_hash,
                    skip_metadata=self._skip_metadata
                )
                
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
                    'magnet_original': magnet_original if magnet_original else None,
                    'similarity': 1.0,
                    'legend': legend_info if legend_info else None,
                    'has_legenda': has_legenda
                }
                torrents.append(torrent)
            
            except Exception as e:
                _log_ctx.error_magnet(magnet_link, e)
                continue
        
        return torrents


