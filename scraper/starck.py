"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.cleaning import clean_title, remove_accents
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.text.title_builder import create_standardized_title, prepare_release_title
from utils.parsing.audio_extraction import add_audio_tag_if_needed, detect_audio_from_html
from utils.logging import format_error, format_link_preview

logger = logging.getLogger(__name__)


# Scraper específico para Starck Filmes
class StarckScraper(BaseScraper):
    SCRAPER_TYPE = "starck"
    DEFAULT_BASE_URL = "https://starckfilmes-v8.com/"
    DISPLAY_NAME = "Starck"
    
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
        seen_hrefs = set()  # Para evitar duplicatas
        
        # Busca especificamente dentro de div.post-catalog (ou div.home.post-catalog)
        catalog_div = doc.select_one('div.post-catalog, div.home.post-catalog')
        if not catalog_div:
            # Fallback: busca em todo o documento
            catalog_div = doc
        
        # Itera sobre cada item dentro do catalog na ordem que aparecem
        items = catalog_div.select('.item')
        
        for item in items:
            # Busca o primeiro link <a> diretamente dentro de div.sub-item que tem atributo 'title'
            # (ignora o link dentro de h3 que tem apenas 'tabindex')
            sub_item = item.select_one('div.sub-item')
            if not sub_item:
                continue
            
            # Pega o primeiro link <a> diretamente filho de div.sub-item (não dentro de h3)
            # Este link tem o atributo 'title'
            # Usa find_all e pega o primeiro que tem title (não o que está dentro de h3)
            all_links = sub_item.find_all('a', href=lambda h: h and 'catalog' in h)
            link_elem = None
            
            for link in all_links:
                # Verifica se é o link direto (não está dentro de h3)
                # O link correto é o primeiro que tem title e não está dentro de h3
                parent_h3 = link.find_parent('h3')
                title_attr = link.get('title')
                
                if not parent_h3 and title_attr and title_attr.strip():
                    link_elem = link
                    break
            
            if link_elem:
                href = link_elem.get('href')
                title_attr = link_elem.get('title')
                
                # Verifica se tem title válido
                if href and title_attr and title_attr.strip():
                    # Normaliza href para absoluto ANTES de verificar duplicatas
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    
                    # Verifica duplicatas e adiciona
                    if href not in seen_hrefs:
                        links.append(href)
                        seen_hrefs.add(href)
        
        logger.debug(f"[Starck] Encontrados {len(items)} itens na página e extraídos {len(links)} links únicos")
        return links
    
    # Obtém torrents de uma página específica
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
    # Extrai links dos resultados de busca (usa implementação base de _search_variations)
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        seen_hrefs = set()  # Para evitar duplicatas
        
        # Busca especificamente dentro de div.post-catalog (ou div.home.post-catalog)
        catalog_div = doc.select_one('div.post-catalog, div.home.post-catalog')
        if not catalog_div:
            # Fallback: busca em todo o documento
            catalog_div = doc
        
        # Itera sobre cada item dentro do catalog
        for item in catalog_div.select('.item'):
            # Busca o primeiro link <a> diretamente dentro de div.sub-item que tem atributo 'title'
            # (ignora o link dentro de h3 que tem apenas 'tabindex')
            sub_item = item.select_one('div.sub-item')
            if not sub_item:
                continue
            
            # Pega o primeiro link <a> diretamente filho de div.sub-item (não dentro de h3)
            # Este link tem o atributo 'title'
            link_elem = sub_item.find('a', href=lambda h: h and 'catalog' in h, title=lambda t: t and t.strip())
            
            if link_elem:
                href = link_elem.get('href')
                title_attr = link_elem.get('title')
                
                # Verifica se tem title válido
                if href and title_attr and title_attr.strip():
                    # Normaliza href para absoluto ANTES de verificar duplicatas
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    
                    # Verifica duplicatas e adiciona
                    if href not in seen_hrefs:
                        links.append(href)
                        seen_hrefs.add(href)
        
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
        post = doc.find('div', class_='post')
        if not post:
            return []
        
        capa = post.find('div', class_='capa')
        if not capa:
            return []
        
        # Extrai título da página
        page_title = ''
        title_elem = capa.select_one('.post-description > h2')
        if title_elem:
            page_title = title_elem.get_text(strip=True)
        
        # Extrai título original
        original_title = ''
        for p in capa.select('.post-description p'):
            spans = p.find_all('span')
            if len(spans) >= 2:
                if 'Nome Original:' in spans[0].get_text():
                    original_title = spans[1].get_text(strip=True)
                    break
        
        # Extrai título traduzido
        title_translated_processed = ''
        for p in capa.select('.post-description p'):
            spans = p.find_all('span')
            if len(spans) >= 2:
                span_text = spans[0].get_text()
                if 'Título Traduzido:' in span_text or 'Titulo Traduzido:' in span_text:
                    # Pega o texto do segundo span, removendo qualquer HTML interno
                    span2 = spans[1]
                    # Remove todas as tags HTML internas antes de pegar o texto
                    for tag in span2.find_all(['strong', 'em', 'b', 'i']):
                        tag.unwrap()  # Remove a tag mas mantém o conteúdo
                    title_translated_processed = span2.get_text(strip=True)
                    # Remove entidades HTML
                    title_translated_processed = html.unescape(title_translated_processed)
                    from utils.text.cleaning import clean_title_translated_processed
                    title_translated_processed = clean_title_translated_processed(title_translated_processed)
                    break
        
        # Fallback: se não encontrou "Título Traduzido", usa o título do post (h2.post-title)
        # sempre usa como fallback (não precisa verificar não-latinos)
        if not title_translated_processed:
            post_title_elem = capa.select_one('h2.post-title')
            if post_title_elem:
                # Remove tags HTML e pega apenas o texto
                title_translated_processed = post_title_elem.get_text(strip=True)
                # Remove entidades HTML
                title_translated_processed = html.unescape(title_translated_processed)
                # Limpa o título traduzido
                from utils.text.cleaning import clean_title_translated_processed
                title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        # Garante que não há HTML restante (remove qualquer tag que possa ter sobrado)
        if title_translated_processed:
            # Remove todas as tags HTML que possam ter sobrado
            title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
            # Remove entidades HTML novamente (caso tenha sobrado)
            title_translated_processed = html.unescape(title_translated_processed)
            # Aplica limpeza final
            from utils.text.cleaning import clean_title_translated_processed
            title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        # Extrai ano, tamanhos, áudio e IMDB
        year = ''
        sizes = []
        imdb = ''
        audio_info = ''  # Para detectar "Idioma: Inglês", "Legenda: PT-BR"
        audio_html_content = ''  # Armazena HTML completo de TODOS os parágrafos para verificação adicional
        all_paragraphs_html = []  # Coleta HTML de todos os parágrafos
        for p in capa.select('.post-description p'):
            text = ' '.join(span.get_text() for span in p.find_all('span'))
            html_content = str(p)
            all_paragraphs_html.append(html_content)  # Coleta HTML de todos os parágrafos
            y = find_year_from_text(text, page_title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
            
            # Extrai informação de áudio/legenda usando função utilitária
            if not audio_info:
                audio_info = detect_audio_from_html(html_content)
        
        # Concatena HTML de todos os parágrafos para verificação independente de inglês e legenda
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
        
        # Extrai links magnet - busca TODOS os links <a> no post
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        # Primeiro tenta no container específico (mais rápido)
        all_links = post.select('a[href]')
        
        magnet_links = []
        for link in all_links:
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
            all_links_fallback = doc.select('a[href]')
            for link in all_links_fallback:
                href = link.get('href', '')
                if not href:
                    continue
                
                # Resolve automaticamente (magnet direto ou protegido)
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet and resolved_magnet.startswith('magnet:'):
                    if resolved_magnet not in magnet_links:
                        magnet_links.append(resolved_magnet)
        
        # Busca direta por elementos com data-u (pode estar em botões, divs, etc.)
        if not magnet_links:
            from utils.parsing.link_resolver import decode_data_u
            
            # Busca primeiro no post
            data_u_elements = post.select('[data-u]')
            
            for elem in data_u_elements:
                data_u_value = elem.get('data-u', '')
                if data_u_value:
                    decoded_magnet = decode_data_u(data_u_value)
                    if decoded_magnet and decoded_magnet.startswith('magnet:'):
                        if decoded_magnet not in magnet_links:
                            magnet_links.append(decoded_magnet)
            
            # Se não encontrou no post, busca em todo o documento
            if not magnet_links:
                data_u_elements_fallback = doc.select('[data-u]')
                
                for elem in data_u_elements_fallback:
                    data_u_value = elem.get('data-u', '')
                    if data_u_value:
                        decoded_magnet = decode_data_u(data_u_value)
                        if decoded_magnet and decoded_magnet.startswith('magnet:'):
                            if decoded_magnet not in magnet_links:
                                magnet_links.append(decoded_magnet)
        
        if not magnet_links:
            logger.debug("[Starck] ❌ Nenhum magnet encontrado após todas as tentativas")
            return []
        
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
                
                # Se ainda está missing_dn, tenta buscar do cross_data
                if missing_dn and cross_data and cross_data.get('magnet_processed'):
                    magnet_original = cross_data['magnet_processed']
                    # A limpeza de domínios e formatos será feita em prepare_release_title()
                    if magnet_original and len(magnet_original.strip()) >= 3:
                        missing_dn = False
                
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
                
                # Adiciona [Brazilian], [Eng] conforme detectado
                # NÃO adiciona DUAL/PORTUGUES/LEGENDADO ao release_title - apenas passa audio_info para a função de tags
                # Passa também o HTML para verificação independente de inglês
                # As tags são independentes: se tem "Idioma: Inglês" → [Eng]
                # SEMPRE passa o HTML se existir, mesmo que audio_info não tenha sido detectado
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title, info_hash=info_hash, skip_metadata=self._skip_metadata, audio_info_from_html=audio_info, audio_html_content=audio_html_content if audio_html_content else None)
                
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
                legenda = extract_legenda_from_page(doc, scraper_type='starck')
                
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
                
                # Extrai tamanho do magnet se disponível
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
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
                    'original_title': original_title if original_title else page_title,  # Usa nome original se disponível
                    'title_translated_processed': title_translated_processed if title_translated_processed else None,
                    'details': absolute_link,
                    'year': year,
                    'imdb': imdb,
                    'audio': [],
                    'magnet_link': magnet_link,
                    'date': date.strftime('%Y-%m-%dT%H:%M:%SZ') if date else '',
                    'info_hash': info_hash,
                    'trackers': process_trackers(magnet_data),
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

