"Copyright (c) 2025 DFlexy"
"https://github.com/DFlexy"

import html
import re
import logging
import json
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import quote, unquote
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.text_processing import (
    find_year_from_text, find_sizes_from_text,
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)
from utils.date_parser import parse_date_from_string

logger = logging.getLogger(__name__)


class VacaTorrentScraper(BaseScraper):
    """Scraper específico para Vaca Torrent"""
    
    def __init__(self, base_url: str):
        super().__init__(base_url)
        self.search_url = "wp-admin/admin-ajax.php"
        self.page_pattern = "page/{}/"
    
    def search(self, query: str) -> List[Dict]:
        """Busca torrents usando POST request"""
        links = self._post_search(query, '1')
        
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
        for item in doc.select('.i-tem_ht'):
            link_elem = item.select_one('a')
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
    
    def _post_search(self, query: str, page: str = '1') -> List[str]:
        """Faz busca POST para WordPress AJAX endpoint"""
        target_url = f"{self.base_url}{self.search_url}"
        
        # Cria multipart form data manualmente
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        body_parts = []
        body_parts.append(f'--{boundary}')
        body_parts.append('Content-Disposition: form-data; name="action"')
        body_parts.append('')
        body_parts.append('filtrar_busca')
        body_parts.append(f'--{boundary}')
        body_parts.append('Content-Disposition: form-data; name="s"')
        body_parts.append('')
        body_parts.append(query)
        body_parts.append(f'--{boundary}')
        body_parts.append('Content-Disposition: form-data; name="tipo"')
        body_parts.append('')
        body_parts.append('todos')
        body_parts.append(f'--{boundary}')
        body_parts.append('Content-Disposition: form-data; name="paged"')
        body_parts.append('')
        body_parts.append(page)
        body_parts.append(f'--{boundary}--')
        body = '\r\n'.join(body_parts).encode('utf-8')
        
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Origin': self.base_url.rstrip('/'),
            'Referer': f"{self.base_url}/?s={quote(query)}&lang=en-US"
        }
        
        try:
            response = self.session.post(target_url, data=body, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse JSON response
            ajax_resp = response.json()
            html_content = ajax_resp.get('html', '')
            
            if not html_content:
                return []
            
            # Unescape HTML entities
            html_content = html.unescape(html_content)
            
            # Parse HTML
            from bs4 import BeautifulSoup
            doc = BeautifulSoup(html_content, 'html.parser')
            
            links = []
            for item in doc.select('.i-tem_ht'):
                link_elem = item.select_one('a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
            
            return list(set(links))
        
        except Exception as e:
            logger.error(f"Erro ao fazer busca POST {target_url}: {e}")
            return []
    
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
        
        # Extrai título original
        original_title = ''
        for elem in doc.find_all(True):
            text = elem.get_text()
            html_content = str(elem)
            
            if 'Título de Origem:' in text:
                parts = text.split('Título de Origem:')
                if len(parts) > 1:
                    title_part = parts[1].strip()
                    stops = ['\n', '</li>', '</div>', '</p>', '<div', 'Genres', 'Gênero', 'Duração', 'Ano', 'IMDb', 'Data de lançamento']
                    for stop in stops:
                        if stop in title_part:
                            idx = title_part.index(stop)
                            title_part = title_part[:idx]
                            break
                    original_title = title_part.strip()
                    break
            
            # Tenta regex no HTML
            if not original_title and html_content:
                title_regex1 = re.compile(r'(?i)<b>\s*t[íi]tulo\s+de\s+origem\s*:?\s*</b>\s*([^<\n\r]+)')
                match = title_regex1.search(html_content)
                if match:
                    original_title = match.group(1).strip()
                    break
                else:
                    title_regex2 = re.compile(r'(?i)t[íi]tulo\s+de\s+origem\s*:?\s*</b>\s*([^<\n\r]+)')
                    match = title_regex2.search(html_content)
                    if match:
                        original_title = match.group(1).strip()
                        break
        
        # Fallback para título principal
        if not original_title:
            title_raw = doc.find('h1', class_='custom-main-title')
            if not title_raw:
                title_raw = doc.find('h1')
            if title_raw:
                original_title = title_raw.get_text(strip=True)
                # Remove data de lançamento
                original_title = original_title.split('(')[0].strip()
        
        title = original_title
        
        # Extrai metadados
        year = ''
        imdb = ''
        sizes = []
        
        for li in doc.select('.col-left ul li, .content p'):
            text = li.get_text()
            html_content = str(li)
            
            # Extrai ano
            if not year:
                y = find_year_from_text(text, title)
                if y:
                    year = y
            
            # Extrai IMDB
            if not imdb:
                for a in li.select('a'):
                    href = a.get('href', '')
                    if 'imdb.com' in href:
                        imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                        if imdb_match:
                            imdb = imdb_match.group(1)
                            break
            
            # Extrai tamanhos
            sizes.extend(find_sizes_from_text(html_content))
        
        # Extrai links magnet
        magnet_links = []
        for magnet in doc.select('a[href^="magnet:"]'):
            href = magnet.get('href', '')
            if href:
                # Decodifica entidades HTML e URL encoding (pode precisar decodificar múltiplas vezes)
                href = html.unescape(href)
                # Decodifica URL encoding (pode estar duplamente codificado)
                while '%' in href:
                    new_href = unquote(href)
                    if new_href == href:  # Não mudou mais, para o loop
                        break
                    href = new_href
                magnet_links.append(href)
        
        if not magnet_links:
            return []
        
        # Remove duplicados de tamanhos
        sizes = list(dict.fromkeys(sizes))
        
        # Processa cada magnet
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                raw_release_title = magnet_data.get('display_name', '')
                fallback_title = original_title if original_title else title
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                original_release_title = prepare_release_title(
                    raw_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn
                )
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title
                )
                
                # Adiciona (pt-br) se o título do magnet contém DUAL, DUBLADO ou NACIONAL
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title)
                
                # Extrai tamanho
                size = ''
                if sizes and idx < len(sizes) and sizes[idx]:
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
