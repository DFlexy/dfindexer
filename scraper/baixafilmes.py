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
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title,
    STOP_WORDS
)
from utils.logging import ScraperLogContext

logger = logging.getLogger(__name__)

# Contexto de logging centralizado para este scraper
_log_ctx = ScraperLogContext("Baixa", logger)

# Scraper específico para Baixa Filmes
class BaixafilmesScraper(BaseScraper):
    SCRAPER_TYPE = "baixafilmes"
    DEFAULT_BASE_URL = "https://www.baixafilmestorrent.com.br/"
    DISPLAY_NAME = "Baixa"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
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
        
        # Primeiras 2-3 palavras (útil para títulos longos em japonês)
        if len(query_words) > 3:
            first_words = ' '.join(query_words[:3])
            variations.append(first_words)
        
        for variation in variations:
            # Normaliza query para FlareSolverr
            from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
            normalized_variation = normalize_query_for_flaresolverr(variation, self.use_flaresolverr)
            search_url = f"{self.base_url}{self.search_url}{quote(normalized_variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue
            
            # Busca links nos resultados
            for item in doc.select('.post'):
                link_elem = item.select_one('div.title > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
            
            # Se encontrou resultados, pode parar (ou continuar para coletar mais)
            # Por enquanto continua para coletar todos os resultados possíveis
        
        return list(set(links))  # Remove duplicados
    
    # Busca torrents
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        # Normaliza query para FlareSolverr (substitui dois pontos por espaço)
        from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
        query = normalize_query_for_flaresolverr(query, self.use_flaresolverr)
        # Usa busca com variações para melhorar resultados
        links = self._search_variations(query)
        
        if not links:
            return []
        
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
            _log_ctx.log_links_found(len(links), effective_max)
            
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
        
        # Extrai título traduzido
        translated_title = ''
        if entry_meta:
            # Busca por <b> que contém "Título Traduzido"
            for b_tag in entry_meta.find_all('b'):
                b_text = b_tag.get_text(strip=True).lower()
                if 'título traduzido' in b_text or 'titulo traduzido' in b_text:
                    parent_html = str(b_tag.parent)
                    patterns = [
                        r'(?i)</b>\s*([^<]+?)\s*<br\s*/?>',
                        r'(?i)</b>\s*([^<]+?)(?:<br|</div|</p|$)',
                        r'(?i)T[íi]tulo\s+Traduzido\s*:?\s*</b>\s*([^<]+?)\s*<br',
                    ]
                    next_text = ''
                    for pattern in patterns:
                        match = re.search(pattern, parent_html)
                        if match:
                            next_text = match.group(1).strip()
                            break
                    if next_text:
                        next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                        next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-').replace('&iacute;', 'í')
                        next_text = ' '.join(next_text.split())
                        if next_text:
                            translated_title = next_text
                            break
        
        # Busca em div.content e div.entry-content se não encontrou
        if not translated_title:
            for content_div in doc.select('div.content, div.entry-content, .left'):
                if translated_title:
                    break
                for b_tag in content_div.find_all('b'):
                    b_text = b_tag.get_text(strip=True).lower()
                    if 'título traduzido' in b_text or 'titulo traduzido' in b_text:
                        parent_html = str(b_tag.parent)
                        match = re.search(r'(?i)</b>\s*([^<]+?)(?:<br\s*/?>|</div|</p|$)', parent_html)
                        if match:
                            next_text = match.group(1).strip()
                            next_text = re.sub(r'<[^>]+>', '', next_text).strip()
                            next_text = next_text.replace('&nbsp;', ' ').replace('&mdash;', '-')
                            next_text = ' '.join(next_text.split())
                            if next_text:
                                translated_title = next_text
                                break
                if translated_title:
                    break
        
        # Busca em todo o article se não encontrou (mas não usa h1 como fallback)
        if not translated_title and article:
            # Busca em elementos específicos, não no texto geral do article
            for elem in article.find_all(['p', 'div', 'span', 'li']):
                elem_text = elem.get_text(' ', strip=True)
                if 'Título Traduzido:' in elem_text:
                    parts = elem_text.split('Título Traduzido:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        stops = ['\n\n', 'Formato:', 'Qualidade:', 'Idioma:', 'Legenda:', 'Tamanho:', 'Servidor:', 'Título Original:']
                        for stop in stops:
                            if stop in title_part:
                                idx = title_part.index(stop)
                                title_part = title_part[:idx]
                                break
                        title_part = ' '.join(title_part.split())
                        if title_part:
                            translated_title = title_part
                            break
        
        # Fallback: se não encontrou "Título Traduzido", tenta usar h1.entry-title
        # sempre usa como fallback (não precisa verificar não-latinos)
        if not translated_title:
            title_raw = article.find('h1', class_='entry-title')
            if not title_raw:
                title_raw = article.find('h1')
            if title_raw:
                translated_title = title_raw.get_text(strip=True)
        
        # Limpa o título traduzido se encontrou
        if translated_title:
            # Remove qualquer HTML que possa ter sobrado
            translated_title = re.sub(r'<[^>]+>', '', translated_title)
            import html
            translated_title = html.unescape(translated_title)
            from utils.text.text_processing import clean_translated_title
            translated_title = clean_translated_title(translated_title)
        
        title = original_title
        
        # Extrai metadados
        year = ''
        imdb = ''
        sizes = []
        audio_info = None  # Para detectar áudio/idioma do HTML
        
        # Extrai informações de idioma e legenda do HTML
        # Busca em div.entry-meta primeiro (estrutura padrão)
        # Pode haver múltiplos entry-meta, então busca em todos
        entry_meta_list = doc.find_all('div', class_='entry-meta')
        logger.debug(f"[Baixafilmes] entry_meta encontrados: {len(entry_meta_list)}")
        
        idioma = ''
        legenda = ''
        
        # Busca Idioma e Legenda em todos os entry-meta
        for entry_meta in entry_meta_list:
            entry_meta_html = str(entry_meta)
            
            # Extrai Idioma (só se ainda não encontrou)
            if not idioma:
                idioma_match = re.search(r'(?i)<b>Idioma:</b>\s*([^<]+?)(?:<br|</div|</p|$)', entry_meta_html)
                if idioma_match:
                    idioma = idioma_match.group(1).strip()
                    # Remove entidades HTML
                    idioma = html.unescape(idioma)
                    idioma = re.sub(r'<[^>]+>', '', idioma).strip()
            
            # Extrai Legenda (só se ainda não encontrou)
            if not legenda:
                legenda_match = re.search(r'(?i)<b>Legenda:</b>\s*([^<]+?)(?:<br|</div|</p|$)', entry_meta_html)
                if legenda_match:
                    legenda = legenda_match.group(1).strip()
                    # Remove entidades HTML
                    legenda = html.unescape(legenda)
                    legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            
            # Se já encontrou ambos, pode parar
            if idioma and legenda:
                break
        
        # Determina audio_info baseado em Idioma e Legenda (após processar todos os entry-meta)
        if idioma or legenda:
            # Lógica simplificada conforme solicitado:
            # - Se Idioma tem português → marca com [Brazilian] (via 'português')
            # - Se Legenda tem português → marca com [Leg] (via 'legendado')
            # - Se Idioma ou Legenda tem Inglês → marca com [Leg] (via 'legendado')
            # O sistema de tags é definido pelo utils (add_audio_tag_if_needed)
            idioma_lower = idioma.lower() if idioma else ''
            legenda_lower = legenda.lower() if legenda else ''
            
            logger.debug(f"[Baixafilmes] Extraído do HTML - Idioma: '{idioma}', Legenda: '{legenda}'")
            
            # Verifica se tem português no idioma (áudio)
            has_portugues_audio = 'português' in idioma_lower or 'portugues' in idioma_lower
            # Verifica se tem português na legenda
            has_portugues_legenda = 'português' in legenda_lower or 'portugues' in legenda_lower
            # Verifica se tem Inglês no idioma ou legenda
            has_ingles = 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower or 'inglês' in legenda_lower or 'ingles' in legenda_lower or 'english' in legenda_lower
            
            # Lógica simplificada:
            # Prioridade: Idioma com português primeiro (gera [Brazilian])
            # Depois: Legenda com português ou Inglês em qualquer campo (gera [Leg])
            # IMPORTANTE: Processa mesmo se idioma estiver vazio (pode ter apenas legenda)
            if has_portugues_audio:
                # Idioma tem português → gera [Brazilian]
                audio_info = 'português'
                logger.debug(f"[Baixafilmes] Detectado PORTUGUÊS: Idioma tem português → [Brazilian]")
            elif has_portugues_legenda or has_ingles:
                # Legenda tem português OU tem Inglês (em Idioma ou Legenda) → gera [Leg]
                audio_info = 'legendado'
                if has_portugues_legenda:
                    logger.debug(f"[Baixafilmes] Detectado LEGENDADO: Legenda tem português → [Leg]")
                elif has_ingles:
                    logger.debug(f"[Baixafilmes] Detectado LEGENDADO: Idioma ou Legenda tem Inglês → [Leg]")
        
        # Se não encontrou em entry-meta, busca em outros lugares
        if not audio_info:
            for p in article.select('div.content p, div.entry-content p'):
                text = p.get_text()
                html_content = str(p)
                
                # Extrai ano
                y = find_year_from_text(text, title)
                if y:
                    year = y
                
                # Extrai tamanhos
                sizes.extend(find_sizes_from_text(html_content))
                
                # Tenta detectar áudio usando função utilitária (fallback)
                if not audio_info:
                    from utils.text.text_processing import detect_audio_from_html
                    audio_info = detect_audio_from_html(html_content)
                    if audio_info:
                        break
        else:
            # Se já encontrou audio_info, ainda precisa extrair ano e tamanhos
            for p in article.select('div.entry-meta, div.content p, div.entry-content p'):
                text = p.get_text()
                html_content = str(p)
                
                # Extrai ano
                y = find_year_from_text(text, title)
                if y:
                    year = y
                
                # Extrai tamanhos
                sizes.extend(find_sizes_from_text(html_content))
        
        imdb = ''
        
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

        # Extrai links magnet - busca TODOS os links <a> no conteúdo
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        magnet_links = []
        for text_content in doc.select('div.content, div.entry-content, div.modal-downloads, div#modal-downloads'):
            for a in text_content.select('a[href]'):
                href = a.get('href', '')
                if not href:
                    continue
                
                # Resolve automaticamente (magnet direto ou protegido)
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet and resolved_magnet.startswith('magnet:'):
                    # Verifica se o magnet_link resolvido tem trackers (apenas para protlink original)
                    original_href = href
                    if 'protlink=' in original_href:
                        try:
                            magnet_data = MagnetParser.parse(resolved_magnet)
                            trackers = magnet_data.get('trackers', [])
                            if not trackers:
                                # Se não tem trackers, adiciona trackers padrão
                                from tracker.list_provider import TrackerListProvider
                                tracker_provider = TrackerListProvider(redis_client=self.redis)
                                default_trackers = tracker_provider.get_trackers()
                                if default_trackers:
                                    # Reconstrói magnet com trackers
                                    from urllib.parse import urlencode
                                    magnet_params = {
                                        'xt': f"urn:btih:{magnet_data.get('info_hash', '')}",
                                        'dn': magnet_data.get('display_name', '')
                                    }
                                    for tracker in default_trackers[:5]:  # Limita a 5 trackers
                                        magnet_params.setdefault('tr', []).append(tracker)
                                    resolved_magnet = f"magnet:?{urlencode(magnet_params, doseq=True)}"
                        except Exception:
                            pass
                    magnet_links.append(resolved_magnet)
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
                raw_release_title = magnet_data.get('display_name', '') or ''
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                
                # Se ainda está missing_dn, tenta buscar do cross_data
                release_title_from_cross = False
                if missing_dn and cross_data and cross_data.get('release_title_magnet'):
                    cross_release = cross_data.get('release_title_magnet')
                    if cross_release and cross_release != 'N/A' and len(str(cross_release).strip()) >= 3:
                        raw_release_title = str(cross_release)
                        missing_dn = False
                        release_title_from_cross = True
                
                # Salva release_title_magnet no Redis se encontrado (para reutilização por outros scrapers)
                # IMPORTANTE: Salva mesmo se veio do cross_data, para garantir que outros scrapers possam usar
                if not missing_dn and raw_release_title:
                    try:
                        from utils.text.text_processing import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, raw_release_title)
                    except Exception:
                        pass
                
                fallback_title = title
                # Usa raw_release_title diretamente, sem modificações prévias
                # As modificações de temporada devem ser feitas apenas quando missing_dn
                working_release_title = raw_release_title if not missing_dn else ''
                
                # NÃO modifica working_release_title quando não está missing_dn
                # Isso evita adicionar informações extras que podem causar duplicação
                
                original_release_title = prepare_release_title(
                    working_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                # Adiciona temporada do HTML apenas se não tiver informação de temporada/episódio no metadata
                # E apenas quando missing_dn (quando não tem display_name do magnet)
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
                    original_title, year, original_release_title, translated_title_html=translated_title if translated_title else None, raw_release_title_magnet=raw_release_title
                )
                
                # Adiciona [Brazilian] se detectar DUAL/DUBLADO/NACIONAL, [Eng] se LEGENDADO, ou ambos se houver os dois
                # Passa audio_info extraído do HTML (Idioma/Legenda)
                logger.debug(f"[Baixafilmes] Chamando add_audio_tag_if_needed com audio_info_from_html='{audio_info}'")
                final_title = add_audio_tag_if_needed(
                    standardized_title, 
                    original_release_title, 
                    info_hash=info_hash, 
                    skip_metadata=self._skip_metadata,
                    audio_info_from_html=audio_info
                )
                logger.debug(f"[Baixafilmes] Título após add_audio_tag_if_needed: '{final_title[:100]}...'")
                
                # Determina origem_audio_tag
                origem_audio_tag = 'N/A'
                if audio_info:
                    origem_audio_tag = 'HTML da página (Idioma/Legenda)'
                elif raw_release_title and ('dual' in raw_release_title.lower() or 'dublado' in raw_release_title.lower() or 'legendado' in raw_release_title.lower()):
                    origem_audio_tag = 'release_title_magnet'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
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
                
                # Salva dados cruzados no Redis para reutilização por outros scrapers
                # IMPORTANTE: Se recuperou release_title_magnet do cross_data, salva de volta para garantir persistência
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
                    'original_title': original_title if original_title else title,
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

