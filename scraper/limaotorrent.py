"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
import base64
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import quote, unquote, urlparse, parse_qs
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.text_processing import (
    find_year_from_text, find_sizes_from_text,
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)
from utils.date_parser import parse_date_from_string

logger = logging.getLogger(__name__)


class LimaotorrentScraper(BaseScraper):
    """Scraper específico para Limao Torrent (filme_torrent)"""
    
    def __init__(self, base_url: str):
        super().__init__(base_url)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
    def search(self, query: str) -> List[Dict]:
        """Busca torrents"""
        search_url = f"{self.base_url}{self.search_url}{quote(query)}"
        doc = self.get_document(search_url, self.base_url)
        if not doc:
            return []
        
        links = []
        for item in doc.select('.post'):
            link_elem = item.select_one('div.title > a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        
        all_torrents = []
        for link in links:
            torrents = self._get_torrents_from_page(link)
            all_torrents.extend(torrents)
        
        return self.enrich_torrents(all_torrents)
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        """Obtém torrents de uma página específica"""
        if page == '1':
            page_url = self.base_url
        else:
            page_url = f"{self.base_url}{self.page_pattern.format(page)}"
        
        doc = self.get_document(page_url, self.base_url)
        if not doc:
            return []
        
        links = []
        for item in doc.select('.post'):
            link_elem = item.select_one('div.title > a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        
        # Limita links se max_items for especificado (otimização para testes do Prowlarr)
        if max_items and max_items > 0:
            links = links[:max_items]
        
        all_torrents = []
        for link in links:
            torrents = self._get_torrents_from_page(link)
            all_torrents.extend(torrents)
            # Para testes do Prowlarr, para assim que tiver resultados suficientes
            if max_items and len(all_torrents) >= max_items:
                break
        
        enriched = self.enrich_torrents(all_torrents)
        return enriched[:max_items] if max_items else enriched
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        """Extrai torrents de uma página"""
        doc = self.get_document(link, self.base_url)
        if not doc:
            return []
        
        date = parse_date_from_string(link)
        if not date:
            date_meta = doc.find('meta', {'property': 'article:published_time'})
            if date_meta:
                date_content = date_meta.get('content', '')
                if date_content:
                    try:
                        date_content = date_content.replace('Z', '+00:00')
                        date = datetime.fromisoformat(date_content)
                    except (ValueError, AttributeError):
                        pass
            
            if not date:
                date = datetime.now()
        
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
                    logger.debug(f"[LIMAOTORRENT] HTML do parent: {parent_html[:300]}")
                    
                    # Regex específico: captura tudo após </b> até <br>
                    # Tenta múltiplos padrões para garantir que capture
                    patterns = [
                        r'(?i)</b>\s*([^<]+?)\s*<br\s*/?>',  # Padrão mais específico com <br> explícito
                        r'(?i)</b>\s*([^<]+?)(?:<br|</div|</p|$)',  # Padrão alternativo
                        r'(?i)T[íi]tulo\s+Original\s*:?\s*</b>\s*([^<]+?)\s*<br',  # Padrão completo incluindo label
                    ]
                    
                    next_text = ''
                    for pattern in patterns:
                        match = re.search(pattern, parent_html)
                        if match:
                            next_text = match.group(1).strip()
                            logger.debug(f"[LIMAOTORRENT] Texto capturado pelo regex (padrão {pattern[:30]}...): '{next_text}'")
                            break
                    
                    if next_text:
                        # Remove tags HTML se houver
                        next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                        # Remove entidades HTML comuns
                        next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-').replace('&iacute;', 'í')
                        # Normaliza espaços mas mantém o título completo
                        next_text = ' '.join(next_text.split())
                        
                        if next_text:
                            original_title = next_text
                            logger.debug(f"[LIMAOTORRENT] Título original extraído (regex HTML): '{original_title}'")
                            break
                    
                    # Método 2: Tenta pegar o next_sibling
                    if not original_title:
                        next_sibling = b_tag.next_sibling
                        if next_sibling:
                            # Se for NavigableString, pega direto
                            if hasattr(next_sibling, 'strip'):
                                next_text = str(next_sibling).strip()
                            else:
                                next_text = next_sibling.get_text(strip=True) if hasattr(next_sibling, 'get_text') else ''
                            
                            if next_text:
                                # Remove tags HTML se houver
                                next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                                # Remove entidades HTML
                                next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-')
                                # Para no primeiro <br> ou quebra de linha se houver
                                if '<br' in next_text or '\n' in next_text:
                                    parts = re.split(r'<br\s*/?>|\n', next_text)
                                    if parts:
                                        next_text = parts[0].strip()
                                
                                # Normaliza espaços mas mantém o título completo
                                next_text = ' '.join(next_text.split())
                                if next_text:
                                    original_title = next_text
                                    logger.debug(f"[LIMAOTORRENT] Título original extraído (next_sibling): '{original_title}'")
                                    break
                    
                    # Método 3: Extrai do texto do parent fazendo split
                    if not original_title:
                        parent_text = b_tag.parent.get_text()
                        if 'Título Original:' in parent_text:
                            parts = parent_text.split('Título Original:')
                            if len(parts) > 1:
                                next_text = parts[1].strip()
                                # Para no primeiro separador (Formato, Qualidade, etc) ou quebra de linha
                                for stop in ['Formato:', 'Qualidade:', 'Idioma:', 'Legenda:', 'Tamanho:', 'Servidor:']:
                                    if stop in next_text:
                                        next_text = next_text.split(stop)[0].strip()
                                        break
                                # Se não encontrou, para na primeira quebra de linha
                                if '\n' in next_text:
                                    next_text = next_text.split('\n')[0].strip()
                                
                                if next_text:
                                    next_text = ' '.join(next_text.split())
                                    original_title = next_text
                                    logger.debug(f"[LIMAOTORRENT] Título original extraído (split texto): '{original_title}'")
                                    break
        
        # Método 2: Busca em div.content e div.entry-content se não encontrou
        if not original_title:
            for content_div in doc.select('div.content, div.entry-content, .left'):
                if original_title:
                    break
                
                # Busca por <b> que contém "Título Original"
                for b_tag in content_div.find_all('b'):
                    b_text = b_tag.get_text(strip=True).lower()
                    if 'título original' in b_text or 'titulo original' in b_text:
                        # Tenta pegar do next_sibling primeiro
                        next_sibling = b_tag.next_sibling
                        if next_sibling:
                            if hasattr(next_sibling, 'strip'):
                                next_text = str(next_sibling).strip()
                            else:
                                next_text = ''
                        else:
                            next_text = ''
                        
                        # Se não encontrou, tenta extrair do HTML do parent
                        if not next_text:
                            parent_html = str(b_tag.parent)
                            match = re.search(r'(?i)</b>\s*([^<]+?)(?:<br\s*/?>|</div|</p|$)', parent_html)
                            if match:
                                next_text = match.group(1).strip()
                        
                        if next_text:
                            # Remove tags HTML
                            next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                            # Remove entidades HTML
                            next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-')
                            # Remove espaços extras e normaliza
                            next_text = ' '.join(next_text.split())
                            if next_text:
                                original_title = next_text
                                break
                
                if original_title:
                    break
        
        # Método 3: Fallback - busca em todo o article se não encontrou
        if not original_title:
            for elem in article.find_all(True):
                text = elem.get_text()
                if 'Título Original:' in text:
                    parts = text.split('Título Original:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        # Para no primeiro separador encontrado
                        stops = ['\n\n', 'Formato:', 'Qualidade:', 'Idioma:', 'Legenda:', 'Tamanho:', 'Servidor:']
                        for stop in stops:
                            if stop in title_part:
                                idx = title_part.index(stop)
                                title_part = title_part[:idx]
                                break
                        # Remove espaços extras e normaliza
                        title_part = ' '.join(title_part.split())
                        if title_part:
                            original_title = title_part
                            break
                if original_title:
                    break
        
        # Fallback para h1.entry-title
        if not original_title:
            title_raw = article.find('h1', class_='entry-title')
            if not title_raw:
                title_raw = article.find('h1')
            if title_raw:
                original_title = title_raw.get_text(strip=True)
                # Remove ano do final
                original_title = re.sub(r'\s*\(\d{4}(-\d{4})?\)\s*$', '', original_title)
        
        # Remove sufixos comuns
        original_title = original_title.replace(' Torrent Dual Áudio', '').strip()
        original_title = original_title.replace(' Torrent Dublado', '').strip()
        original_title = original_title.replace(' Torrent Legendado', '').strip()
        original_title = original_title.replace(' Torrent', '').strip()
        
        title = original_title
        
        # Extrai metadados
        year = ''
        imdb = ''
        sizes = []
        
        for p in article.select('div.entry-meta, div.content p, div.entry-content p'):
            text = p.get_text()
            
            # Extrai ano
            y = find_year_from_text(text, title)
            if y:
                year = y
            
            # Extrai tamanhos
            sizes.extend(find_sizes_from_text(text))
        
        # Extrai IMDB
        for a in article.select('div.content a, div.entry-content a'):
            href = a.get('href', '')
            if 'imdb.com' in href:
                imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                if imdb_match:
                    imdb = imdb_match.group(1)
                    break
        
        # Remove duplicados de tamanhos
        sizes = list(dict.fromkeys(sizes))
        
        if not year:
            try:
                article_full_text = article.get_text(' ', strip=True)
                year_match = re.search(r'(19|20)\d{2}', article_full_text)
                if year_match:
                    year = year_match.group(0)
            except Exception:
                pass

        # Extrai links magnet (podem estar codificados em base64)
        # Busca em div.content, div.entry-content, div.modal-downloads, div#modal-downloads (como no Go)
        magnet_links = []
        for text_content in doc.select('div.content, div.entry-content, div.modal-downloads, div#modal-downloads'):
            for a in text_content.select('a.customButton, a[href*="encurta"], a[href^="magnet"]'):
                href = a.get('href', '')
                if not href:
                    continue
                
                # Link direto magnet
                if href.startswith('magnet:'):
                    magnet_links.append(href)
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
                            except Exception as e:
                                logger.debug(f"Erro ao decodificar token: {e}")
                                pass
                    except Exception as e:
                        logger.debug(f"Erro ao parsear URL: {e}")
                        pass
        
        if not magnet_links:
            return []
        
        # Processa cada magnet
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                raw_release_title = magnet_data.get('display_name', '') or ''
                fallback_title = title
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                working_release_title = raw_release_title if raw_release_title else fallback_title
                
                # Garante que informações de temporada do HTML entrem no release_title
                try:
                    if 'temporada' not in working_release_title.lower():
                        article_text = article.get_text(' ', strip=True).lower()
                        season_match = re.search(r'(\d+)\s*(?:ª|a)?\s*temporada', article_text)
                        if season_match:
                            season_number = season_match.group(1)
                            working_release_title = f"{working_release_title} temporada {season_number}"
                except Exception:
                    pass

                original_release_title = prepare_release_title(
                    working_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn
                )
                
                logger.debug(f"[LIMAOTORRENT] Antes create_standardized_title - original_title: '{original_title}', year: '{year}', release_title: '{original_release_title[:100]}'")
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title
                )
                logger.debug(f"[LIMAOTORRENT] Depois create_standardized_title - standardized_title: '{standardized_title}'")
                
                # Adiciona (pt-br) se o título do magnet contém DUAL, DUBLADO ou NACIONAL
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title)
                logger.debug(f"[LIMAOTORRENT] Título final: '{final_title}'")
                
                # Extrai tamanho
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                trackers = magnet_data.get('trackers', [])
                
                torrent = {
                    'title': final_title,
                    'original_title': original_title if original_title else title,
                    'details': link,
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
                logger.error(f"Erro ao processar magnet {link}: {e}")
                continue
        
        return torrents
