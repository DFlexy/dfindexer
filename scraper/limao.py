"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
import base64
from datetime import datetime
from utils.parsing.date_parser import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, unquote, urlparse, parse_qs, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.text_processing import (
    find_year_from_text, find_sizes_from_text,
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)

logger = logging.getLogger(__name__)


# Scraper específico para Limao Torrent (filme_torrent)
class LimaoScraper(BaseScraper):
    SCRAPER_TYPE = "limao"
    DEFAULT_BASE_URL = "https://tinyurl.com/limonfilmes"
    DISPLAY_NAME = "Limao"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
    # Busca torrents
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        # Normaliza query para FlareSolverr (substitui dois pontos por espaço)
        from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
        query = normalize_query_for_flaresolverr(query, self.use_flaresolverr)
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
        
        return self.enrich_torrents(all_torrents, filter_func=filter_func)
    
    # Extrai links da página inicial (lógica especial para filtrar "Novidades de Hoje")
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        # Filtra apenas a seção "Novidades de Hoje"
        # Encontra o h2 com "Novidades de Hoje"
        novidades_h2 = None
        for h2 in doc.find_all('h2'):
            if 'Novidades de Hoje' in h2.get_text():
                novidades_h2 = h2
                break
        
        if novidades_h2:
            # Encontra o post_list pai que contém a seção
            post_list = novidades_h2.find_parent('div', class_='post_list')
            if post_list:
                # Extrai apenas os links dentro desse post_list
                for item in post_list.select('.post'):
                    link_elem = item.select_one('div.title > a')
                    if link_elem:
                        href = link_elem.get('href')
                        if href:
                            links.append(href)
        else:
            # Fallback: se não encontrar a seção, usa comportamento padrão
            for item in doc.select('.post'):
                link_elem = item.select_one('div.title > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        
        return links
    
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
            
            # Extrai links usando método específico do scraper
            links = self._extract_links_from_page(doc)
            
            # Obtém limite efetivo usando função utilitária
            effective_max = get_effective_max_items(max_items)
            
            # Log para info: mostra quantos links foram encontrados e qual o limite
            total_links = len(links)
            if effective_max > 0:
                logger.info(f"[Limao] Encontrados {total_links} links na página, limitando para {effective_max}")
            else:
                logger.info(f"[Limao] Encontrados {total_links} links na página (sem limite)")
            
            # Limita links se houver limite (EMPTY_QUERY_MAX_LINKS limita quantos links processar)
            links = limit_list(links, effective_max)
            
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
    
    # Resolve link protegido (protlink) usando função utilitária compartilhada - retorna URL do magnet link ou None se não conseguir resolver
    def _resolve_protected_link(self, protlink_url: str) -> Optional[str]:
        from utils.parsing.link_resolver import resolve_protected_link
        # Passa Redis para cache de links protegidos resolvidos
        return resolve_protected_link(protlink_url, self.session, self.base_url, redis=self.redis)
    
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
        # Otimizado: busca apenas em elementos de texto (p, div, span) ao invés de todos os elementos
        if not original_title:
            # Primeiro tenta buscar diretamente no texto do article (mais rápido)
            article_text = article.get_text(' ', strip=True)
            if 'Título Original:' in article_text:
                parts = article_text.split('Título Original:')
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
            
            # Se ainda não encontrou, busca apenas em elementos específicos (mais eficiente que find_all(True))
            if not original_title:
                for elem in article.find_all(['p', 'div', 'span', 'li']):
                    text = elem.get_text(strip=True)
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
        
        # Extrai ano do texto do article (reutiliza se já foi extraído antes)
        if not year:
            try:
                # Usa o texto já extraído se disponível, senão extrai
                article_full_text = article.get_text(' ', strip=True)
                year_match = re.search(r'(19|20)\d{2}', article_full_text)
                if year_match:
                    year = year_match.group(0)
            except Exception:
                pass

        # Extrai links magnet (podem estar codificados em base64 ou protegidos com protlink)
        # Busca em div.content, div.entry-content, div.modal-downloads, div#modal-downloads (como no Go)
        # Também busca links protegidos (systemads/get.php, ?go=, etc.)
        magnet_links = []
        for text_content in doc.select('div.content, div.entry-content, div.modal-downloads, div#modal-downloads'):
            for a in text_content.select('a.customButton, a[href*="encurta"], a[href*="protlink"], a[href^="magnet"], a[href*="get.php"], a[href*="systemads"], a[href*="?go="], a[href*="&go="]'):
                href = a.get('href', '')
                if not href:
                    continue
                
                # Link direto magnet
                if href.startswith('magnet:'):
                    magnet_links.append(href)
                    continue
                
                # Link protegido - resolve usando função utilitária
                from utils.parsing.link_resolver import is_protected_link
                if is_protected_link(href):
                    try:
                        magnet_link = self._resolve_protected_link(href)
                        if magnet_link:
                            # Verifica se o magnet_link resolvido tem trackers (apenas para protlink)
                            if 'protlink=' in href:
                                try:
                                    # Verifica se o link resolvido tem trackers (apenas validação silenciosa)
                                    MagnetParser.parse(magnet_link)
                                except Exception:
                                    pass
                            magnet_links.append(magnet_link)
                    except Exception as e:
                        logger.debug(f"Erro ao resolver link protegido {href}: {e}")
                        # Continua sem adicionar o link se falhar
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
                                pass
                                pass
                    except Exception as e:
                        pass
                        pass
        
        if not magnet_links:
            return []
        
        # Durante testes (skip_metadata=True), limita a 1 magnet por página para reduzir verbosidade
        if self._skip_metadata:
            magnet_links = magnet_links[:1]
        
        # Cache do texto do article para evitar múltiplas chamadas a get_text() durante o processamento
        article_text_cached = None
        
        # Processa cada magnet
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                raw_release_title = magnet_data.get('display_name', '') or ''
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                
                fallback_title = title
                working_release_title = raw_release_title if not missing_dn else ''
                
                if not missing_dn:
                    try:
                        if 'temporada' not in working_release_title.lower():
                            if article_text_cached is None:
                                article_text_cached = article.get_text(' ', strip=True).lower()
                            season_match = re.search(r'(\d+)\s*(?:ª|a)?\s*temporada', article_text_cached)
                            if season_match:
                                season_number = season_match.group(1)
                                working_release_title = f"{working_release_title} temporada {season_number}"
                    except Exception:
                        pass

                original_release_title = prepare_release_title(
                    working_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                # Adiciona temporada do HTML apenas se não tiver informação de temporada/episódio no metadata
                if missing_dn:
                    has_season_ep_info = re.search(r'(?i)S\d{1,2}(?:E\d{1,2}(?:-\d{1,2})?)?', original_release_title)
                    if not has_season_ep_info and 'temporada' not in original_release_title.lower():
                        try:
                            if article_text_cached is None:
                                article_text_cached = article.get_text(' ', strip=True).lower()
                            season_match = re.search(r'(\d+)\s*(?:ª|a)?\s*temporada', article_text_cached)
                            if season_match:
                                season_number = season_match.group(1)
                                if not re.search(rf'\b{season_number}\s*(?:ª|a)?\s*temporada', original_release_title, re.IGNORECASE):
                                    original_release_title = f"{original_release_title} temporada {season_number}"
                        except Exception:
                            pass
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title
                )
                
                # Adiciona (pt-br) se o título do magnet contém DUAL, DUBLADO ou NACIONAL
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title)
                
                # Extrai tamanho
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Processa trackers usando função utilitária
                trackers = process_trackers(magnet_data)
                
                # Se não tem trackers no magnet_link, usa lista dinâmica de trackers como fallback
                if not trackers:
                    try:
                        from tracker.list_provider import TrackerListProvider
                        tracker_provider = TrackerListProvider(redis_client=self.redis)
                        dynamic_trackers = tracker_provider.get_trackers()
                        if dynamic_trackers:
                            # Filtra apenas trackers UDP (compatíveis com o sistema de scrape)
                            trackers = [t for t in dynamic_trackers if t.lower().startswith('udp://')]
                    except Exception:
                        pass
                
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