"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_parser import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, unquote
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.text_processing import (
    find_year_from_text, find_sizes_from_text,
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)

MONTH_MAP = {
    'janeiro': 1, 'jan': 1, 'jan.': 1, 'january': 1,
    'fevereiro': 2, 'fev': 2, 'fev.': 2, 'february': 2, 'feb': 2, 'feb.': 2,
    'março': 3, 'marco': 3, 'mar': 3, 'mar.': 3, 'march': 3,
    'abril': 4, 'abr': 4, 'abr.': 4, 'april': 4, 'apr': 4, 'apr.': 4,
    'maio': 5, 'mai': 5, 'may': 5,
    'junho': 6, 'jun': 6, 'jun.': 6, 'june': 6,
    'julho': 7, 'jul': 7, 'jul.': 7, 'july': 7,
    'agosto': 8, 'ago': 8, 'ago.': 8, 'august': 8, 'aug': 8, 'aug.': 8,
    'setembro': 9, 'set': 9, 'set.': 9, 'septembro': 9, 'september': 9, 'sep': 9, 'sep.': 9,
    'outubro': 10, 'out': 10, 'out.': 10, 'october': 10, 'oct': 10, 'oct.': 10,
    'novembro': 11, 'nov': 11, 'nov.': 11, 'november': 11,
    'dezembro': 12, 'dez': 12, 'dez.': 12, 'december': 12, 'dec': 12, 'dec.': 12
}

logger = logging.getLogger(__name__)


# Scraper específico para Vaca Torrent
class VacaScraper(BaseScraper):
    SCRAPER_TYPE = "vaca"
    DEFAULT_BASE_URL = "https://vacatorrentmov.com/"
    DISPLAY_NAME = "Vaca"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "wp-admin/admin-ajax.php"
        self.page_pattern = "page/{}/"
    
    # Busca torrents usando POST request
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        # Normaliza query para FlareSolverr (substitui dois pontos por espaço)
        from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
        query = normalize_query_for_flaresolverr(query, self.use_flaresolverr)
        links = self._post_search(query, '1')
        
        all_torrents = []
        for link in links:
            torrents = self._get_torrents_from_page(link)
            all_torrents.extend(torrents)
        
        return self.enrich_torrents(all_torrents, filter_func=filter_func)
    
    # Extrai links da página inicial
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select('.i-tem_ht'):
            link_elem = item.select_one('a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        return links
    
    # Obtém torrents de uma página específica
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        return self._default_get_page(page, max_items)
    
    # Faz busca POST para WordPress AJAX endpoint
    def _post_search(self, query: str, page: str = '1') -> List[str]:
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
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        doc = self.get_document(link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da URL do link
        date = parse_date_from_string(link)
        
        # Fallback: Se não encontrou, usa data atual
        if not date:
            date = datetime.now()
        
        torrents = []
        
        # Extrai título original
        original_title = ''
        season_number = ''
        for elem in doc.find_all(True):
            text = elem.get_text()
            html_content = str(elem)
            if not season_number:
                season_match = re.search(r'(\d+)\s*(?:ª|a)?\s*temporada', text, flags=re.IGNORECASE)
                if season_match:
                    season_number = season_match.group(1).zfill(2)
            
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
        release_day: Optional[int] = None
        release_month: Optional[int] = None
        release_year = ''
        
        for li in doc.select('.col-left ul li, .content p'):
            text = li.get_text()
            html_content = str(li)
            text_clean = html.unescape(text or '').strip()
            lower_text = text_clean.lower()
            
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

            if 'ano de lançamento' in lower_text:
                year_match = re.search(r'(19|20)\d{2}', text_clean)
                if year_match:
                    release_year = year_match.group(0)
                    if not year:
                        year = release_year

            if 'data de lançamento' in lower_text and (release_day is None or release_month is None):
                value_part = text_clean.split(':', 1)
                if len(value_part) > 1:
                    value = value_part[1]
                else:
                    value = text_clean
                value = html.unescape(value).replace(',', ' ')
                value = re.sub(r'\s+', ' ', value).strip()
                tokens = [tok for tok in value.split(' ') if tok and tok.lower() not in {'de', '-', '—'}]
                if tokens:
                    day_token = tokens[0]
                    if day_token.isdigit():
                        try:
                            release_day = int(day_token)
                        except ValueError:
                            release_day = None
                    if len(tokens) > 1:
                        month_token = tokens[1].lower().strip('.')
                        release_month = MONTH_MAP.get(month_token, release_month)
                    if len(tokens) > 2 and re.match(r'(19|20)\d{2}', tokens[2]):
                        release_year = tokens[2]
                        if not year:
                            year = release_year
        
        final_year_candidate = release_year or year
        if (
            release_day
            and release_month
            and final_year_candidate
            and re.match(r'^\d{4}$', final_year_candidate)
        ):
            try:
                date = datetime(int(final_year_candidate), release_month, release_day)
                year = final_year_candidate
            except ValueError:
                pass

        # Extrai links magnet
        magnet_entries = []
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
                episode_number = ''
                context_text = ''
                parent = magnet.parent
                if parent:
                    context_text = parent.get_text(' ', strip=True)
                    bold_label = parent.find('b')
                    if bold_label:
                        context_text = f"{bold_label.get_text(' ', strip=True)}"
                if not context_text:
                    context_text = magnet.get_text(' ', strip=True)
                if not context_text and parent:
                    prev_sibling = parent.find_previous('b')
                    if prev_sibling:
                        context_text = prev_sibling.get_text(' ', strip=True)
                episode_match = re.search(r'epis[íi]dio\s*(\d+)', context_text, flags=re.IGNORECASE)
                if episode_match:
                    episode_number = episode_match.group(1).zfill(2)
                magnet_entries.append((href, episode_number))
        
        if not magnet_entries:
            return []
        
        # Remove duplicados de tamanhos
        sizes = list(dict.fromkeys(sizes))
        
        # Processa cada magnet
        for idx, (magnet_link, episode_number) in enumerate(magnet_entries):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                raw_release_title = magnet_data.get('display_name', '')
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                
                fallback_title = original_title if original_title else title
                original_release_title = prepare_release_title(
                    raw_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                if episode_number:
                    effective_season = season_number or '01'
                    episode_tag = f"S{effective_season}E{episode_number}"
                    if not re.search(r'(?i)S\d{1,2}E\d{1,2}', original_release_title):
                        rest_release = original_release_title
                        if fallback_title and rest_release.lower().startswith(fallback_title.lower()):
                            rest_release = rest_release[len(fallback_title):].strip()
                        original_release_title = fallback_title.strip()
                        if original_release_title:
                            original_release_title = f"{original_release_title} {episode_tag}".strip()
                        else:
                            original_release_title = episode_tag
                        if rest_release:
                            original_release_title = f"{original_release_title} {rest_release}".strip()
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title
                )
                
                # Adiciona (pt-br) se o título do magnet contém DUAL, DUBLADO ou NACIONAL
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title)

                if episode_number:
                    effective_season = season_number or '01'
                    episode_tag = f"S{effective_season}E{episode_number}"
                    if episode_tag.lower() not in final_title.lower():
                        parts = [part for part in final_title.split('.') if part]
                        if parts:
                            base = parts[0]
                            remaining_parts = parts[1:]
                            final_title = '.'.join([base, episode_tag] + remaining_parts) if remaining_parts else f"{base}.{episode_tag}"
                        else:
                            final_title = episode_tag
                
                # Extrai tamanho
                size = ''
                if sizes and idx < len(sizes) and sizes[idx]:
                    size = sizes[idx]
                
                trackers = process_trackers(magnet_data)
                
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


