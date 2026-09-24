# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
import logging
from datetime import datetime
from utils.parsing import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import urlencode, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from scraper.base import SiteConfig
from utils.text import STOP_WORDS
from utils.text import find_sizes_from_text
from utils.log import ScraperLogContext

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("Rede", logger)

_RE_H1_TORRENT_SUFFIX = re.compile(r'\s+Torrent\b.*$', re.IGNORECASE)
_RE_YEAR = re.compile(r'\((\d{4})\)')
_RE_ISO_YEAR = re.compile(r'(\d{4})')

SITE = SiteConfig(
    # Endereço do site: ajuste aqui se o domínio mudar.
    url="https://redestorrents.com/",
    caminho_busca="index.php?busca=",
    paginacao="pagina/{}/",
    seletores={
        "card": "a.cover-link",
        "card_titulo": "article.custom-card",
        "links_paginacao": "a.page-link, .pagination a, nav[aria-label] a.page-link",
        "token_busca": 'form[role="search"] input[name="token"], input[name="token"]',
        "titulo": "h1.movie-title",
        "titulo_breadcrumb": '.breadcrumb-item.active [itemprop="name"], .breadcrumb-item.active',
        "titulo_original": "p.original-title",
        "ano": 'time[itemprop="datePublished"]',
        "data_publicacao": 'time[itemprop="dateCreated"]',
        "especificacoes": ".spec-card-glass",
        "links_download": "section.download-section, .download-list",
        "botao_download": "a.download-btn[href]",
    },
)

class RedeScraper(BaseScraper):
    SITE = SITE
    SCRAPER_TYPE = "rede"
    DISPLAY_NAME = "Rede"

    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        return self._extract_search_results(doc)

    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select(SITE.seletores["card"]):
            href = item.get('href') if item.name == 'a' else None
            if not href:
                link_elem = item if item.name == 'a' else item.select_one('a[href]')
                href = link_elem.get('href') if link_elem else None
            if href:
                links.append(href)
        return links

    def _collect_search_result_titles(self, doc: BeautifulSoup) -> Dict[str, str]:
        title_by_url: Dict[str, str] = {}
        for link in doc.select(SITE.seletores["card"]):
            href = (link.get('href') or '').strip()
            card = link.select_one(SITE.seletores["card_titulo"])
            title_text = ''
            if card:
                title_text = (card.get('data-title') or '').strip()
            if not title_text:
                title_text = (link.get('title') or link.get_text(strip=True) or '').strip()
            normalized = self._normalize_search_result_url(href)
            if normalized and title_text:
                title_by_url[normalized] = title_text
        return title_by_url

    def _get_search_token(self) -> str:
        doc = None
        try:
            doc = self._fetch_document(self.base_url, self.base_url)
        except Exception:
            doc = None
        if not doc:
            doc = self.get_document(self.base_url, self.base_url)
        if not doc:
            return ''
        token_el = doc.select_one(SITE.seletores["token_busca"])
        return (token_el.get('value') or '').strip() if token_el else ''

    def _is_search_results_page(self, doc: BeautifulSoup, query: str) -> bool:
        title_el = doc.find('title')
        title = title_el.get_text(' ', strip=True).lower() if title_el else ''
        h1 = doc.select_one('h1')
        h1_text = h1.get_text(' ', strip=True).lower() if h1 else ''
        blob = f'{title} {h1_text}'
        if any(marker in blob for marker in ('encontrados para', 'busca por', 'resultados para')):
            return True
        query_l = (query or '').strip().lower()
        return bool(query_l and query_l in h1_text and 'catálogo' not in h1_text and 'catalogo' not in h1_text)

    def _build_search_url(self, variation: str, page: int, token: str) -> str:
        params = {'hp_bot_check': '', 'busca': variation}
        if token:
            params['token'] = token
        if page > 1:
            params['page'] = str(page)
        return f"{self.base_url}index.php?{urlencode(params)}"
    
    def _search_variations(self, query: str) -> List[str]:
        links = []
        seen_urls = set()
        variations = [query]
        
        query_words = query.split()

        if len(query_words) >= 2 and query_words[-1].isdigit() and len(query_words[-1]) == 4 and query_words[-1][:2] in ('19', '20'):
            without_year = ' '.join(query_words[:-1])
            if without_year not in variations:
                variations.append(without_year)

        if len(query_words) > 1 and len(query_words) < 3:
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])

        token = self._get_search_token()
        
        for variation in variations:
            page = 1
            use_query_format = None
            
            while True:
                search_url = self._build_search_url(variation, page, token)
                
                doc = self.get_document(search_url, self.base_url)
                if not doc:
                    break

                if not self._is_search_results_page(doc, variation):
                    if page == 1 and token:
                        token = self._get_search_token()
                        search_url = self._build_search_url(variation, page, token)
                        doc = self.get_document(search_url, self.base_url)
                        if not doc or not self._is_search_results_page(doc, variation):
                            logger.debug(
                                f"[Rede] Busca não retornou resultados válidos para '{variation}'"
                            )
                            break
                    else:
                        break
                
                page_links = self._extract_search_results(doc)
                page_links = self._filter_links_by_result_titles(doc, page_links, variation)
                
                if not page_links:
                    break
                
                for link in page_links:
                    absolute_url = urljoin(self.base_url, link) if link and not link.startswith('http') else link
                    if absolute_url not in seen_urls:
                        links.append(absolute_url)
                        seen_urls.add(absolute_url)
                
                if page == 1:
                    pagination_links = doc.select(SITE.seletores["links_paginacao"])
                    for pag_link in pagination_links:
                        href = pag_link.get('href', '').lower()
                        if '/2/' in href or 'pagina/2' in href:
                            if 'index.php' not in href and 'page=' not in href:
                                use_query_format = False
                                break
                        elif "page=2" in href or "&page=2" in href or "?page=2" in href:
                            use_query_format = True
                            break
                
                has_next_page = False
                if page == 1 and use_query_format is None:
                    break
                
                pagination_links = doc.select(SITE.seletores["links_paginacao"])
                for pag_link in pagination_links:
                    href = pag_link.get('href', '')
                    text = pag_link.get_text(strip=True).lower()
                    
                    if use_query_format:
                        if (f"page={page + 1}" in href) or (f"&page={page + 1}" in href):
                            has_next_page = True
                            break
                    else:
                        if f"/{page + 1}/" in href or f"pagina/{page + 1}" in href:
                            has_next_page = True
                            break
                    
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

                if page > 20:
                    break
        
        return list(set(links))

    def _clean_page_title(self, title_text: str) -> str:
        cleaned = _RE_H1_TORRENT_SUFFIX.sub('', title_text).strip()
        if cleaned:
            return cleaned
        cleaned = re.sub(r'\s*\(\d{4}\).*$', '', title_text).strip()
        return cleaned or title_text.strip()

    def _spec_value(self, doc: BeautifulSoup, *labels: str) -> str:
        for card in doc.select(SITE.seletores["especificacoes"]):
            label_el = card.select_one('small')
            value_el = card.select_one('strong')
            if not label_el or not value_el:
                continue
            label = label_el.get_text(' ', strip=True).lower()
            if any(candidate.lower() in label for candidate in labels):
                return value_el.get_text(' ', strip=True)
        return ''

    def _parse_page_date(self, doc: BeautifulSoup, absolute_link: str):
        created = doc.select_one(SITE.seletores["data_publicacao"])
        if created is not None:
            raw_dt = (created.get('datetime') or '').strip()
            if raw_dt:
                try:
                    return datetime.fromisoformat(raw_dt)
                except ValueError:
                    pass
            text = created.get_text(' ', strip=True)
            parsed = parse_date_from_string(text)
            if parsed:
                return parsed
        from utils.parsing import extract_date_from_page
        return extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)

    def _collect_magnet_links(self, doc: BeautifulSoup) -> List[str]:
        magnet_links: List[str] = []
        scoped = []
        for block in doc.select(SITE.seletores["links_download"]):
            scoped.extend(block.select('a[href]'))
        if not scoped:
            scoped = doc.select(SITE.seletores["botao_download"])

        for link in scoped:
            href = link.get('href', '')
            if not href:
                continue
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet and resolved_magnet.startswith('magnet:'):
                if resolved_magnet not in magnet_links:
                    magnet_links.append(resolved_magnet)

        if not magnet_links:
            for link in doc.select('a[href]'):
                href = link.get('href', '')
                if not href:
                    continue
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet and resolved_magnet.startswith('magnet:'):
                    if resolved_magnet not in magnet_links:
                        magnet_links.append(resolved_magnet)
        return magnet_links
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []

        date = self._parse_page_date(doc, absolute_link)

        h1 = doc.select_one(SITE.seletores["titulo"]) or doc.find('h1')
        if not h1:
            self._log_structure_miss(absolute_link, SITE.seletores["titulo"])
            return []

        title_text = h1.get_text(strip=True)
        crumb = doc.select_one(SITE.seletores["titulo_breadcrumb"])
        if crumb:
            title = crumb.get_text(strip=True)
        else:
            title = self._clean_page_title(title_text)

        if not title:
            self._log_structure_miss(absolute_link, "título em h1.movie-title / breadcrumb")
            return []

        year = ''
        year_el = doc.select_one(SITE.seletores["ano"])
        if year_el is not None:
            year_text = year_el.get_text(strip=True)
            year_match = _RE_ISO_YEAR.search(year_text) or _RE_ISO_YEAR.search(year_el.get('datetime') or '')
            if year_match:
                year = year_match.group(1)
        if not year:
            year_match = _RE_YEAR.search(title_text)
            if year_match:
                year = year_match.group(1)

        original_el = doc.select_one(SITE.seletores["titulo_original"])
        original_title = original_el.get_text(strip=True) if original_el else ''
        title_translated_processed = title
        if not original_title:
            original_title = title
        
        if self._should_skip_page_by_query(
            title, original_title, title_translated_processed, absolute_link,
        ):
            return []

        idioma = self._spec_value(doc, 'Idioma', 'Áudio', 'Audio')
        tamanho = self._spec_value(doc, 'Tamanho')

        audio_info = None
        if idioma:
            from utils.parsing import detect_audio_from_idioma_text
            audio_info = detect_audio_from_idioma_text(idioma)

        info_blocks = []
        specs_html = ''.join(str(card) for card in doc.select(SITE.seletores["especificacoes"]))
        if specs_html:
            info_blocks.append(specs_html)
        download_html = ''.join(str(block) for block in doc.select(SITE.seletores["links_download"]))
        if download_html:
            info_blocks.append(download_html)
        if idioma:
            info_blocks.append(f'Idioma: {idioma}')
        audio_html_content = ' '.join(info_blocks)

        from utils.parsing import extract_legenda_from_page, determine_legend_info
        legenda = extract_legenda_from_page(doc, scraper_type='rede', article=doc)
        legend_info = determine_legend_info(legenda) if legenda else None
        if legenda and 'Legenda' not in audio_html_content and 'legenda' not in audio_html_content.lower():
            audio_html_content += f' Legenda: {legenda}'

        sizes = find_sizes_from_text(tamanho) if tamanho else []
        for name_el in doc.select('.download-name'):
            sizes.extend(find_sizes_from_text(name_el.get_text(' ', strip=True)))
        sizes = list(dict.fromkeys(sizes))

        magnet_links = self._collect_magnet_links(doc)
        if not magnet_links:
            return []

        from utils.parsing import extract_imdb_from_soup
        specs_root = doc.select_one(SITE.seletores["especificacoes"])
        imdb = extract_imdb_from_soup(doc, content_div=specs_root)
        
        from core.torrent_builder import build_torrents_from_magnets
        return build_torrents_from_magnets(
            magnet_links=magnet_links,
            sizes=sizes,
            page_title=title,
            original_title=original_title,
            title_translated_processed=title_translated_processed,
            year=year,
            imdb=imdb,
            audio_info=audio_info,
            audio_html_content=audio_html_content,
            absolute_link=absolute_link,
            date=date,
            legend_info=legend_info,
            skip_metadata=self._skip_metadata,
            doc=doc,
            scraper_type=self.SCRAPER_TYPE,
            log_ctx=_log_ctx,
            fallback_title_priority='original_then_page',
        )
