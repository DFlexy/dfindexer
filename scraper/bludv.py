"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, urljoin
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


# Scraper específico para Bludv Filmes
class BludvScraper(BaseScraper):
    SCRAPER_TYPE = "bludv"
    DEFAULT_BASE_URL = "https://bludv.net/"
    DISPLAY_NAME = "Bludv"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
    # Busca torrents com variações da query
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        return self._default_search(query, filter_func)
    
    # Extrai links da página inicial
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        seen_links = set()  # Para deduplicar links
        
        for item in doc.select('.post'):
            # Busca o link dentro de div.title > a
            link_elem = item.select_one('div.title > a')
            if link_elem:
                href = link_elem.get('href')
                if href and href not in seen_links:
                    links.append(href)
                    seen_links.add(href)
        
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
        
        # Primeira palavra (apenas se não for stop word)
        query_words = query.split()
        if len(query_words) > 1:
            first_word = query_words[0].lower()
            # Só adiciona primeira palavra se não for stop word
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])
        
        seen_links = set()  # Para deduplicar links durante a busca
        
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
                        # Converte URL relativa para absoluta
                        absolute_url = urljoin(self.base_url, href)
                        if absolute_url not in seen_links:
                            links.append(absolute_url)
                            seen_links.add(absolute_url)
        
        return links  # Já está deduplicado via seen_links
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        # Garante que o link seja absoluto para o campo details
        from urllib.parse import urljoin
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da página (tenta URL, meta tags, etc.)
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        
        # Extrai título da página
        page_title = ''
        title_elem = doc.find('h1')
        if title_elem:
            page_title = title_elem.get_text(strip=True)
        
        # Extrai título original e traduzido
        original_title = ''
        translated_title = ''
        
        # Busca por "Título Original:" e "Título Traduzido:" no conteúdo
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')
        
        if content_div:
            # Busca por padrões de título original e traduzido usando BeautifulSoup
            # Procura em todos os elementos que possam conter essas informações
            
            # Extrai título original
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                # Verifica se contém "Título Original:" no texto ou HTML
                if re.search(r'(?i)T[íi]tulo\s+Original\s*:?', elem_html):
                    # Usa BeautifulSoup para extrair texto após o label
                    # Procura pelo texto "Título Original:" e pega o que vem depois
                    text_parts = elem_text.split('Título Original:')
                    if len(text_parts) > 1:
                        # Pega o texto após o label
                        original_title = text_parts[1].strip()
                        
                        # Tenta extrair do HTML de forma mais precisa
                        # Procura pelo padrão no HTML: Título Original: ... até <br ou </span
                        html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*(.*?)(?:<br|</span|</p|</div|$)', elem_html, re.DOTALL)
                        if html_match:
                            html_text = html_match.group(1)
                            # Remove todas as tags HTML
                            html_text = re.sub(r'<[^>]+>', '', html_text)
                            html_text = html_text.strip()
                            if html_text:
                                original_title = html_text
                        
                        # Remove entidades HTML
                        original_title = html.unescape(original_title)
                        # Remove espaços múltiplos
                        original_title = re.sub(r'\s+', ' ', original_title).strip()
                        # Para no primeiro separador comum
                        for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:', 'Título Traduzido:']:
                            if stop in original_title:
                                original_title = original_title.split(stop)[0].strip()
                                break
                        if original_title:
                            break
            
            # Extrai título traduzido
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                # Verifica se contém "Título Traduzido:" no texto ou HTML
                if re.search(r'(?i)T[íi]tulo\s+Traduzido\s*:?', elem_html):
                    # Usa BeautifulSoup para extrair texto após o label
                    text_parts = elem_text.split('Título Traduzido:')
                    if len(text_parts) > 1:
                        # Pega o texto após o label
                        translated_title = text_parts[1].strip()
                        
                        # Tenta extrair do HTML de forma mais precisa
                        html_match = re.search(r'(?i)T[íi]tulo\s+Traduzido\s*:?\s*(.*?)(?:<br|</span|</p|</div|$)', elem_html, re.DOTALL)
                        if html_match:
                            html_text = html_match.group(1)
                            # Remove todas as tags HTML
                            html_text = re.sub(r'<[^>]+>', '', html_text)
                            html_text = html_text.strip()
                            if html_text:
                                translated_title = html_text
                        
                        # Remove entidades HTML
                        translated_title = html.unescape(translated_title)
                        # Remove espaços múltiplos
                        translated_title = re.sub(r'\s+', ' ', translated_title).strip()
                        # Para no primeiro separador comum
                        for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:']:
                            if stop in translated_title:
                                translated_title = translated_title.split(stop)[0].strip()
                                break
                        if translated_title:
                            # Limpa o título traduzido
                            from utils.text.cleaning import clean_translated_title
                            translated_title = clean_translated_title(translated_title)
                            break
        
        # Fallback: usa título da página se não encontrou título original
        if not original_title:
            original_title = page_title
        
        # Extrai informações de áudio e legenda do HTML
        audio_info = None  # Para detectar áudio/idioma do HTML
        audio_html_content = ''  # Armazena HTML completo para verificação adicional
        all_paragraphs_html = []  # Coleta HTML de todos os parágrafos
        
        audio_text = ''
        legenda = ''
        
        # Extrai ano e tamanhos
        year = ''
        sizes = []
        imdb = ''
        
        if content_div:
            # Primeiro tenta no HTML completo do content_div
            content_html = str(content_div)
            all_paragraphs_html.append(content_html)
            
            # Extrai Áudio - busca primeiro no HTML completo
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
                    # Remove entidades HTML e tags
                    audio_text = html.unescape(audio_text)
                    audio_text = re.sub(r'<[^>]+>', '', audio_text).strip()
                    # Remove espaços extras e normaliza
                    audio_text = re.sub(r'\s+', ' ', audio_text).strip()
                    # Para antes de encontrar palavras de parada
                    stop_words = ['Legenda', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho', 'IMDb']
                    for stop_word in stop_words:
                        if stop_word in audio_text:
                            idx = audio_text.index(stop_word)
                            audio_text = audio_text[:idx].strip()
                            break
                    if audio_text:
                        break
            
            # Se não encontrou no HTML completo, busca nos elementos individuais
            if not audio_text:
                for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
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
                            stop_words = ['Legenda', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho', 'IMDb']
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
                r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Áudio|Audio|$)',
                r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Qualidade|$)',
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
                    stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Qualidade', 'Duração', 'Formato']
                    for stop_word in stop_words:
                        if stop_word in legenda:
                            idx = legenda.index(stop_word)
                            legenda = legenda[:idx].strip()
                            break
                    if legenda:
                        break
            
            # Se não encontrou no HTML completo, busca nos elementos individuais
            if not legenda:
                for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
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
                            stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Qualidade', 'Duração', 'Formato']
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
                # Verifica se tem Inglês no áudio
                has_ingles_audio = 'inglês' in audio_lower or 'ingles' in audio_lower or 'english' in audio_lower or 'en' in audio_lower
                # Verifica se tem Inglês em qualquer lugar
                has_ingles = has_ingles_audio or 'inglês' in legenda_lower or 'ingles' in legenda_lower or 'english' in legenda_lower
                
                # Lógica: Se tem português E inglês no áudio → DUAL (gera [Brazilian] e [Eng])
                if has_portugues_audio and has_ingles_audio:
                    audio_info = 'dual'
                # Se tem apenas português no áudio → gera [Brazilian]
                elif has_portugues_audio:
                    audio_info = 'português'
                # Se tem legenda PT-BR (português) OU tem Inglês → gera [Leg]
                # PT-BR na legenda indica que o áudio é em outro idioma (geralmente inglês) com legenda em português
                elif has_portugues_legenda or has_ingles:
                    audio_info = 'legendado'
        
        if content_div:
            for p in content_div.select('p, span, div'):
                text = p.get_text()
                html_content = str(p)
                
                # Extrai ano
                y = find_year_from_text(text, original_title or page_title)
                if y:
                    year = y
                
                # Extrai tamanhos
                sizes.extend(find_sizes_from_text(html_content))
                
                # Extrai IMDB - padrão específico do bludv
                # Formato: <strong><em>IMDb:</em></strong> <a href='https://www.imdb.com/pt/title/tt16358384/' target='_blank' rel='noopener'>7,9
                if not imdb:
                    # Busca padrão específico: <strong><em>IMDb:</em></strong> seguido de link
                    imdb_em = p.find('em', string=re.compile(r'IMDb:', re.I))
                    if imdb_em:
                        # Procura link IMDB próximo ao <em>IMDb:</em>
                        parent = imdb_em.parent
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
                    
                    # Fallback: busca por texto "IMDB" ou "IMDb" próximo
                    if not imdb:
                        text_lower = text.lower()
                        has_imdb_label = 'imdb' in text_lower or 'imdb:' in text_lower
                        for a in p.select('a[href*="imdb.com"]'):
                            href = a.get('href', '')
                            # Tenta padrão /pt/title/tt
                            imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                            if imdb_match:
                                imdb = imdb_match.group(1)
                                # Se tem label IMDB, usa este. Caso contrário, continua procurando
                                if has_imdb_label:
                                    break
                                continue
                            # Tenta padrão /title/tt
                            imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                            if imdb_match:
                                imdb = imdb_match.group(1)
                                # Se tem label IMDB, usa este. Caso contrário, continua procurando
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
        
        # Set para rastrear info_hashes já processados (deduplicação)
        seen_info_hashes = set()
        
        # Processa cada magnet
        # IMPORTANTE: magnet_link já é o magnet resolvido (links protegidos foram resolvidos antes)
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                # Deduplica por info_hash - se já vimos este hash, pula
                if info_hash in seen_info_hashes:
                    continue
                seen_info_hashes.add(info_hash)
                
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
                
                fallback_title = original_title or translated_title or page_title or ''
                original_release_title = prepare_release_title(
                    raw_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                # Garante que translated_title seja string (não Tag)
                translated_title_str = str(translated_title) if translated_title else None
                if translated_title_str and not isinstance(translated_title_str, str):
                    translated_title_str = None
                
                standardized_title = create_standardized_title(
                    str(original_title) if original_title else '', year, original_release_title, translated_title_html=translated_title_str, raw_release_title_magnet=raw_release_title
                )
                
                # Adiciona [Brazilian] se detectar DUAL/DUBLADO/NACIONAL, [Eng] se LEGENDADO, ou ambos se houver os dois
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
                # Tenta associar tamanho ao magnet pelo índice, mas se não houver tamanho suficiente,
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Salva dados cruzados no Redis para reutilização por outros scrapers
                try:
                    from utils.text.cross_data import save_cross_data_to_redis
                    cross_data_to_save = {
                        'original_title_html': str(original_title) if original_title else None,
                        'release_title_magnet': raw_release_title if not missing_dn else None,
                        'translated_title_html': str(translated_title) if translated_title else None,
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
                    'original_title': original_title if original_title else (translated_title if translated_title else page_title),
                    'translated_title': translated_title if translated_title else None,
                    'details': absolute_link,
                    'year': year,
                    'imdb': imdb if imdb else '',
                    'audio': [],
                    'magnet_link': magnet_link,
                    'date': date.strftime('%Y-%m-%dT%H:%M:%SZ') if date else '',
                    'info_hash': info_hash,
                    'trackers': process_trackers(magnet_data),
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

