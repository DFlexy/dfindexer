"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import html
import logging
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ============================================================================
# REGRAS ESPECÍFICAS POR SCRAPER - Extração de Legenda
# ============================================================================

def _extract_legenda_rede(doc: BeautifulSoup, article: Optional[BeautifulSoup] = None) -> str:
    """
    Rede: Extrai "Legenda" de div#informacoes.
    """
    legenda = ''
    
    if not article:
        article = doc.find('article')
        if not article:
            return legenda
    
    # Busca Legenda em div#informacoes
    info_div = article.find('div', id='informacoes')
    if not info_div:
        return legenda
    
    info_html = str(info_div)
    
    # Extrai Legenda - busca primeiro no HTML completo
    # Formato esperado: <strong>Legendas: </strong>\nPortuguês<br> ou <strong>Legendas: </strong>Português<br>
    # Padrão 0: Busca específica para <strong>Legendas: </strong> seguido de quebra de linha e texto
    simple_legenda_match = re.search(r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*[\n\r\t\s]*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma|$)', info_html, re.DOTALL)
    if simple_legenda_match:
        legenda = simple_legenda_match.group(1).strip()
        legenda = html.unescape(legenda)
        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
        legenda = re.sub(r'\s+', ' ', legenda).strip()
        # Para antes de encontrar palavras de parada
        stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
        for stop_word in stop_words:
            if stop_word in legenda:
                idx = legenda.index(stop_word)
                legenda = legenda[:idx].strip()
                break
        if legenda:
            return legenda
    
    # Padrão 0b: Busca simples sem tag strong (fallback)
    simple_legenda_match = re.search(r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma|$)', info_html, re.DOTALL)
    if simple_legenda_match:
        legenda = simple_legenda_match.group(1).strip()
        legenda = html.unescape(legenda)
        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
        legenda = re.sub(r'\s+', ' ', legenda).strip()
        # Para antes de encontrar palavras de parada
        stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
        for stop_word in stop_words:
            if stop_word in legenda:
                idx = legenda.index(stop_word)
                legenda = legenda[:idx].strip()
                break
        if legenda:
            return legenda
    
    # Padrões adicionais
    legenda_patterns = [
        # Padrão 1: <strong>Legendas: </strong> seguido de quebra de linha (\n) e texto na próxima linha
        r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
        # Padrão 2: <strong>Legendas: </strong> seguido diretamente de texto (mesma linha)
        r'(?i)<strong>Legendas?\s*:\s*</strong>\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
        # Padrão 3: <b>Legenda:</b> (fallback)
        r'(?i)<b>Legendas?\s*:</b>\s*([^<]+?)(?:<br|</div|</p|</b|Nota|Tamanho|$)',
        # Padrão 4: Qualquer tag com Legendas: (fallback genérico)
        r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|$)',
    ]
    
    for pattern in legenda_patterns:
        legenda_match = re.search(pattern, info_html, re.DOTALL)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            # Remove entidades HTML e tags
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            # Remove espaços extras e normaliza
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            # Para antes de encontrar palavras de parada
            stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
            for stop_word in stop_words:
                if stop_word in legenda:
                    idx = legenda.index(stop_word)
                    legenda = legenda[:idx].strip()
                    break
            if legenda:
                return legenda
    
    # Se não encontrou no HTML completo, busca nos parágrafos individuais
    for p in article.select('div#informacoes > p'):
        html_content = str(p)
        # NÃO remove quebras de linha - preserva para capturar formato <strong>Legendas: </strong>\nPortuguês<br>
        html_content_preserved = html_content.replace('\t', ' ')
        # Normaliza <br> mas preserva \n e \r
        html_content_preserved = re.sub(r'<br\s*\/?>', '<br>', html_content_preserved)
        
        # Tenta primeiro com tag <strong> (formato do site: <strong>Legendas: </strong>\nPortuguês<br>)
        # Busca o texto após </strong> que pode estar na mesma linha ou próxima linha
        # Padrão 1: <strong>Legendas: </strong> seguido de quebra de linha/tabs e texto
        legenda_match = re.search(r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*[\n\r\t]*\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)
        if not legenda_match:
            # Padrão 2: <strong>Legendas: </strong> seguido diretamente de texto (mesma linha)
            legenda_match = re.search(r'(?i)<strong>Legendas?\s*:\s*</strong>\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)
        
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            if legenda:
                return legenda
        
        # Tenta com tag <b>
        legenda_match = re.search(r'(?i)<b>Legendas?\s*:</b>\s*([^<]+?)(?:<br|</div|</p|</b|$)', html_content_preserved, re.DOTALL)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            if legenda:
                return legenda
        
        # Se não encontrou, tenta sem tag, buscando em linhas separadas
        # Busca padrão: "Legendas:" seguido de texto na mesma linha ou próxima linha
        legenda_match = re.search(r'(?i)Legendas?\s*:\s*(?:<br\s*/?>)?\s*([^<\n\r]+?)(?:<br|</div|</p|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            if legenda:
                return legenda
        
        # Último fallback: busca em linhas separadas (preservando \n)
        # Divide por <br> para processar cada parte
        parts_by_br = html_content_preserved.split('<br>')
        for i, part in enumerate(parts_by_br):
            # Verifica se tem <strong>Legendas: </strong> nesta parte
            if re.search(r'(?i)<strong>Legendas?\s*:', part):
                # Tenta pegar texto após </strong> na mesma parte (pode ter \n, \r, \t)
                match = re.search(r'(?i)</strong>\s*[\n\r\t]*\s*([^<\n\r]+?)(?:<br|$)', part, re.DOTALL)
                if match:
                    legenda = match.group(1).strip()
                    legenda = html.unescape(legenda)
                    legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                    legenda = re.sub(r'\s+', ' ', legenda).strip()
                    if legenda:
                        return legenda
                # Se não encontrou na mesma parte, tenta próxima parte (formato: <strong>Legendas: </strong>\nPortuguês<br>)
                if i + 1 < len(parts_by_br):
                    next_part = parts_by_br[i + 1]
                    # Remove tags HTML mas preserva o texto
                    next_part_clean = re.sub(r'<[^>]+>', '', next_part).strip()
                    if next_part_clean and next_part_clean not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']:
                        # Verifica se não começa com outra tag strong
                        if not re.search(r'(?i)^\s*<strong>', next_part):
                            legenda = next_part_clean.strip()
                            return legenda
            # Também verifica sem tag <strong>
            line_clean = re.sub(r'<[^>]*>', '', part).strip()
            if 'Legendas:' in line_clean or 'Legenda:' in line_clean:
                # Tenta pegar da mesma linha
                parts = line_clean.split(':')
                if len(parts) > 1:
                    extracted = ':'.join(parts[1:]).strip()
                    if extracted:
                        legenda = extracted
                        return legenda
                # Se não tem na mesma linha, tenta próxima linha
                if i + 1 < len(parts_by_br):
                    next_line = re.sub(r'<[^>]*>', '', parts_by_br[i + 1]).strip()
                    if next_line and next_line not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio']:
                        legenda = next_line
                        return legenda
    
    # Último fallback: busca direta no texto completo sem tags HTML
    info_text = info_div.get_text(separator='\n')
    # Divide por linhas para buscar "Legendas:" em uma linha e o valor na próxima
    lines = info_text.split('\n')
    for i, line in enumerate(lines):
        line_clean = line.strip()
        if re.search(r'(?i)^Legendas?\s*:', line_clean):
            # Tenta pegar da mesma linha
            match = re.search(r'(?i)Legendas?\s*:\s*(.+?)$', line_clean)
            if match:
                legenda = match.group(1).strip()
                # Para antes de encontrar palavras de parada
                stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    return legenda
            # Se não tem na mesma linha, tenta próxima linha
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and next_line not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']:
                    # Verifica se não começa com outra palavra-chave
                    if not re.search(r'(?i)^(Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma)', next_line):
                        legenda = next_line.strip()
                        return legenda
    
    # Se ainda não encontrou, tenta padrão simples em todo o texto
    legenda_match = re.search(r'(?i)Legendas?\s*:\s*([^\n]+?)(?:\n|Nota|Tamanho|Imdb|Vídeo|Áudio|$)', info_text)
    if legenda_match:
        legenda = legenda_match.group(1).strip()
        # Remove espaços extras
        legenda = re.sub(r'\s+', ' ', legenda).strip()
        # Para antes de encontrar palavras de parada
        stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
        for stop_word in stop_words:
            if stop_word in legenda:
                idx = legenda.index(stop_word)
                legenda = legenda[:idx].strip()
                break
        if legenda:
            return legenda
    
    # Fallback adicional: busca simples em cada parágrafo individual
    for p in article.select('div#informacoes > p'):
        # Usa separator='\n' para preservar quebras de linha
        p_text = p.get_text(separator='\n')
        # Divide por linhas para buscar "Legendas:" em uma linha e o valor na próxima
        lines = p_text.split('\n')
        for i, line in enumerate(lines):
            line_clean = line.strip()
            if re.search(r'(?i)^Legendas?\s*:', line_clean):
                # Tenta pegar da mesma linha
                match = re.search(r'(?i)Legendas?\s*:\s*(.+?)$', line_clean)
                if match:
                    legenda = match.group(1).strip()
                    # Para antes de encontrar palavras de parada
                    stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
                    for stop_word in stop_words:
                        if stop_word in legenda:
                            idx = legenda.index(stop_word)
                            legenda = legenda[:idx].strip()
                            break
                    if legenda:
                        return legenda
                # Se não tem na mesma linha, tenta próxima linha
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and next_line not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']:
                        # Verifica se não começa com outra palavra-chave
                        if not re.search(r'(?i)^(Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma)', next_line):
                            legenda = next_line.strip()
                            return legenda
        
        # Se ainda não encontrou, tenta padrão simples no texto completo do parágrafo
        p_text_simple = p.get_text(separator=' ')
        legenda_match = re.search(r'(?i)Legendas?\s*:\s*([^\n\r]+?)(?:\s|$|Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma)', p_text_simple)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            # Remove espaços extras
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            # Para antes de encontrar palavras de parada
            stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
            for stop_word in stop_words:
                if stop_word in legenda:
                    idx = legenda.index(stop_word)
                    legenda = legenda[:idx].strip()
                    break
            if legenda:
                return legenda
    
    return legenda


def _extract_legenda_bludv(doc: BeautifulSoup, content_div: Optional[BeautifulSoup] = None) -> str:
    """
    Bludv: Extrai "Legenda" do HTML.
    """
    legenda = ''
    
    if not content_div:
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')
    
    if content_div:
        content_html = str(content_div)
        
        # Extrai Legenda
        legenda_patterns = [
            r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Áudio|Audio|$)',
            r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Qualidade|$)',
        ]
        
        for pattern in legenda_patterns:
            legenda_match = re.search(pattern, content_html, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                # Para antes de encontrar palavras de parada
                stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Qualidade', 'Duração', 'Formato']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    return legenda
    
    return legenda


def _extract_legenda_comand(doc: BeautifulSoup, content_div: Optional[BeautifulSoup] = None) -> str:
    """
    Comando: Extrai "Legenda" do HTML.
    """
    legenda = ''
    
    if not content_div:
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')
    
    if content_div:
        content_html = str(content_div)
        
        # Extrai Legenda
        legenda_patterns = [
            r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Canais|Fansub|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Áudio|Audio|Status|$)',
            r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Canais|Fansub|Qualidade|$)',
            r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
        ]
        
        for pattern in legenda_patterns:
            legenda_match = re.search(pattern, content_html, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Canais', 'Fansub', 'Qualidade', 'Duração', 'Formato', 'Status']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    return legenda
    
    return legenda


def _extract_legenda_xfilmes(doc: BeautifulSoup, entry_meta_list: Optional[list] = None) -> str:
    """
    XFilmes: Extrai "Legenda" de div.entry-meta.
    """
    legenda = ''
    
    if not entry_meta_list:
        entry_meta_list = doc.find_all('div', class_='entry-meta')
    
    for entry_meta in entry_meta_list:
        entry_meta_html = str(entry_meta)
        
        # Extrai Legenda
        legenda_match = re.search(r'(?i)<b>Legenda:</b>\s*([^<]+?)(?:<br|</div|</p|</b|$)', entry_meta_html, re.DOTALL)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            return legenda
        else:
            legenda_match = re.search(r'(?i)Legenda\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|$)', entry_meta_html, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                return legenda
    
    return legenda


def _extract_legenda_starck(doc: BeautifulSoup, **kwargs) -> str:
    """
    Starck: Extrai "Legenda" de .post-description p.
    """
    legenda = ''
    
    # Busca em .post-description p (mesma estrutura usada para extrair áudio)
    capa = doc.find('div', class_='capa')
    if not capa:
        return legenda
    
    for p in capa.select('.post-description p'):
        html_content = str(p)
        text = ' '.join(span.get_text() for span in p.find_all('span'))
        
        # Padrões para extrair legenda
        legenda_patterns = [
            r'(?i)Legenda\s*:\s*([^<\n\r]+?)(?:<br|</p|</div|Nota|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)',
            r'(?i)<[^>]*>Legenda\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</p|</div|Nota|Tamanho|$)',
            r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</p|</div|Nota|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)',
        ]
        
        for pattern in legenda_patterns:
            legenda_match = re.search(pattern, html_content, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                # Para antes de encontrar palavras de parada
                stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Idioma']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    return legenda
        
        # Busca também no texto limpo (pode ter "S/L" ou "S.L.")
        text_lower = text.lower()
        if 'legenda' in text_lower:
            # Tenta extrair o valor após "Legenda:"
            legenda_match = re.search(r'(?i)legenda\s*:\s*([^\n\r]+?)(?:\n|Nota|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)', text, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                if legenda:
                    return legenda
    
    return legenda


def _extract_legenda_tfilme(doc: BeautifulSoup, **kwargs) -> str:
    """
    TFilme: Extrai "Legenda" de div.content.
    """
    legenda = ''
    
    # Busca em div.content primeiro (estrutura padrão do tfilme)
    article = doc.find('article')
    if not article:
        return legenda
    
    content_div = article.find('div', class_='content')
    if not content_div:
        return legenda
    
    content_html = str(content_div)
    
    # Extrai Legenda - padrão 1: <b>Legenda:</b>
    # Captura valores múltiplos separados por vírgula (ex: "PT-BR, Inglês, Espanhol")
    legenda_match = re.search(r'(?i)<b>Legenda:</b>\s*([^<]+?)(?:<br|</div|</p|</b|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)', content_html)
    if legenda_match:
        legenda = legenda_match.group(1).strip()
        # Remove entidades HTML
        legenda = html.unescape(legenda)
        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
        # Para antes de encontrar palavras de parada
        stop_words = ['Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Idioma']
        for stop_word in stop_words:
            if stop_word in legenda:
                idx = legenda.index(stop_word)
                legenda = legenda[:idx].strip()
                break
        if legenda:
            return legenda
    
    # Padrão 2: Legenda: sem tag bold
    if not legenda:
        legenda_match = re.search(r'(?i)Legenda\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)', content_html)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            # Para antes de encontrar palavras de parada
            stop_words = ['Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Idioma']
            for stop_word in stop_words:
                if stop_word in legenda:
                    idx = legenda.index(stop_word)
                    legenda = legenda[:idx].strip()
                    break
            if legenda:
                return legenda
    
    return legenda


def _extract_legenda_portal(doc: BeautifulSoup, **kwargs) -> str:
    """
    Portal: Extrai "Legenda" de div.content.
    """
    legenda = ''
    
    # Busca em div.content primeiro (estrutura padrão do portal)
    article = doc.find('article')
    if not article:
        return legenda
    
    content_div = article.find('div', class_='content')
    if not content_div:
        return legenda
    
    content_html = str(content_div)
    
    # Extrai Legenda - padrão 1: <b>Legenda:</b>
    legenda_match = re.search(r'(?i)<b>Legenda:</b>\s*([^<]+?)(?:<br|</div|</p|$)', content_html)
    if legenda_match:
        legenda = legenda_match.group(1).strip()
        # Remove entidades HTML
        legenda = html.unescape(legenda)
        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
        if legenda:
            return legenda
    
    # Padrão 2: Legenda: sem tag bold
    if not legenda:
        legenda_match = re.search(r'(?i)Legenda\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|$)', content_html)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            if legenda:
                return legenda
    
    return legenda


# Mapeamento de scrapers para funções de extração
LEGENDA_EXTRACTORS = {
    'rede': _extract_legenda_rede,
    'bludv': _extract_legenda_bludv,
    'comand': _extract_legenda_comand,
    'xfilmes': _extract_legenda_xfilmes,
    'starck': _extract_legenda_starck,
    'tfilme': _extract_legenda_tfilme,
    'portal': _extract_legenda_portal,
}


# ============================================================================
# FUNÇÃO GENÉRICA DE EXTRAÇÃO
# ============================================================================

def extract_legenda_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None, **kwargs) -> str:
    """
    Extrai informações de legenda do HTML.
    
    Args:
        doc: Documento BeautifulSoup
        scraper_type: Tipo do scraper ('rede', 'bludv', 'comand', 'xfilmes', etc.)
        **kwargs: Argumentos adicionais específicos do scraper:
            - article: Elemento article (para rede)
            - content_div: Elemento div.content (para bludv/comand)
            - entry_meta_list: Lista de div.entry-meta (para xfilmes)
    
    Returns:
        String com a legenda extraída ou string vazia se não encontrado
    """
    if not doc:
        return ''
    
    # Tenta usar função específica do scraper
    if scraper_type and scraper_type in LEGENDA_EXTRACTORS:
        try:
            extractor_func = LEGENDA_EXTRACTORS[scraper_type]
            return extractor_func(doc, **kwargs)
        except Exception as e:
            logger.debug(f"Erro ao extrair legenda com função específica de {scraper_type}: {e}")
    
    # Fallback: busca genérica
    return ''


def determine_legend_info(legenda: str, magnet_processed: Optional[str] = None, info_hash: Optional[str] = None, skip_metadata: bool = False) -> Optional[str]:
    """
    Determina legend_info baseado na legenda extraída com fallbacks.
    Suporta múltiplos valores: "Português, Inglês" ou "Português, Japonês" (máximo 3)
    
    Lógica de Legenda:
    1. FONTE PRINCIPAL: HTML (legend_info: 'Coletar o que está no campo')
    2. FALLBACK 1: Magnet (legendado/legenda/leg)
    3. FALLBACK 2: Metadata
    4. FALLBACK 3: Cross Data
    
    Args:
        legenda: Texto extraído do campo "Legenda" (HTML)
        magnet_processed: Nome do magnet processado para fallback
        info_hash: Hash do torrent para fallbacks (metadata e cross_data)
        skip_metadata: Se True, pula busca em metadata
    
    Returns:
        String com os valores detectados separados por vírgula (ex: 'legendado, inglês') ou None
        Máximo de 3 valores
    """
    # ============================================================================
    # FONTE PRINCIPAL: HTML (legend_info: 'Coletar o que está no campo')
    # ============================================================================
    
    if legenda:
        legenda_original = legenda.strip()
        legenda_lower = legenda_original.lower()
        
        # Se for exatamente "S/L" ou "S.L." (preserva o formato original)
        if legenda_original.upper() in ['S/L', 'S.L.'] or re.match(r'^\s*s[/\.]l\s*$', legenda_lower):
            return legenda_original.upper() if legenda_original.upper() in ['S/L', 'S.L.'] else legenda_original
        
        # Lista de valores detectados
        valores_detectados = []
        
        # Verifica se tem "S/L" ou "S.L." (indica legenda, mas preserva o formato)
        if 's/l' in legenda_lower or 's.l.' in legenda_lower or re.search(r'\bs[/\.]l\b', legenda_lower):
            # Preserva o formato original se possível
            if 'S/L' in legenda_original:
                valores_detectados.append('S/L')
            elif 'S.L.' in legenda_original:
                valores_detectados.append('S.L.')
            else:
                valores_detectados.append('legendado')
        
        # Verifica se tem português na legenda (PT-BR, PTBR, PT BR, Português, Portugues)
        # Não usa apenas "pt" para evitar falsos positivos (ex: "Espanhol" contém "pt")
        if ('português' in legenda_lower or 'portugues' in legenda_lower or 
            'pt-br' in legenda_lower or 'ptbr' in legenda_lower or 
            'pt br' in legenda_lower or re.search(r'\bpt\s*[-:]?\s*br\b', legenda_lower)):
            valores_detectados.append('Português')
        
        # Verifica se tem inglês na legenda (Inglês, Ingles, English, Eng)
        if ('inglês' in legenda_lower or 'ingles' in legenda_lower or 
            'english' in legenda_lower or re.search(r'\beng\b', legenda_lower)):
            valores_detectados.append('Inglês')
        
        # Verifica se tem espanhol na legenda (Espanhol, Espanol, Spanish, Esp)
        if ('espanhol' in legenda_lower or 'espanol' in legenda_lower or 
            'spanish' in legenda_lower or re.search(r'\besp\b', legenda_lower)):
            valores_detectados.append('Espanhol')
        
        # Verifica se tem japonês na legenda (Japonês, Japones, Japanese, Jap)
        if ('japonês' in legenda_lower or 'japones' in legenda_lower or 
            'japanese' in legenda_lower or re.search(r'\bjap\b', legenda_lower)):
            valores_detectados.append('Japonês')
        
        # Limita a 3 valores no máximo
        valores_detectados = valores_detectados[:3]
        
        if valores_detectados:
            # Retorna string separada por vírgula se houver múltiplos valores
            return ', '.join(valores_detectados) if len(valores_detectados) > 1 else valores_detectados[0]
    
    # ============================================================================
    # FALLBACK 1: Magnet (legendado/legenda/leg)
    # ============================================================================
    
    if magnet_processed:
        release_lower = magnet_processed.lower()
        if 'legendado' in release_lower or 'legenda' in release_lower or re.search(r'\bleg\b', release_lower):
            return 'legendado'
    
    # ============================================================================
    # FALLBACK 2: Metadata
    # ============================================================================
    
    if info_hash and not skip_metadata:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'legendado' in metadata_name or 'legenda' in metadata_name or re.search(r'\bleg\b', metadata_name):
                    return 'legendado'
        except Exception:
            pass
    
    # ============================================================================
    # FALLBACK 3: Cross Data
    # ============================================================================
    
    if info_hash and not skip_metadata:
        try:
            from utils.text.cross_data import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'legendado' in cross_release_lower or 'legenda' in cross_release_lower or re.search(r'\bleg\b', cross_release_lower):
                        return 'legendado'
        except Exception:
            pass
    
    return None


def determine_legend_presence(legend_info_from_html: Optional[str] = None, audio_html_content: Optional[str] = None, magnet_processed: Optional[str] = None, info_hash: Optional[str] = None, skip_metadata: bool = False) -> bool:
    """
    Determina se há presença de legenda seguindo a ordem de fallbacks especificada.
    Suporta múltiplos valores: "legendado, inglês" ou "legendado, japonês" (máximo 3)
    
    Lógica de detecção:
    1. HTML (legend_info: 'Coletar o que está no campo')
    2. LINK do html contém (legendado/legenda/leg)
    3. Magnet (legendado/legenda/leg)
    4. Metadata
    5. Cross Data
    
    Args:
        legend_info_from_html: Valor de legend_info extraído do HTML (ex: 'legendado' ou 'legendado, inglês')
        audio_html_content: Conteúdo HTML completo para busca
        magnet_processed: Nome do magnet processado
        info_hash: Hash do torrent para buscar metadata e cross_data
        skip_metadata: Se True, pula busca em metadata
    
    Returns:
        True se detectar legenda, False caso contrário
    """
    has_legenda = False
    
    # ============================================================================
    # FONTE PRINCIPAL: HTML (legend_info: 'Coletar o que está no campo')
    # Suporta múltiplos valores separados por vírgula (máximo 3)
    # ============================================================================
    
    if legend_info_from_html:
        # Se legend_info_from_html contém 'legendado' ou 'S/L' (pode ter múltiplos valores)
        legend_info_str = str(legend_info_from_html).lower()
        if 'legendado' in legend_info_str or 's/l' in legend_info_str or 's.l.' in legend_info_str or re.search(r'\bs[/\.]l\b', legend_info_str):
            has_legenda = True
            return has_legenda
    
    # ============================================================================
    # FALLBACK 1: LINK do html contém (legendado/legenda/leg/S/L)
    # ============================================================================
    
    if audio_html_content and not has_legenda:
        if re.search(r'(?i)(?:legendado|legenda|\bleg\b|s[/\.]l\b)', audio_html_content):
            has_legenda = True
            return has_legenda
    
    # ============================================================================
    # FALLBACK 2: Magnet (legendado/legenda/leg)
    # ============================================================================
    
    if magnet_processed and not has_legenda:
        release_lower = magnet_processed.lower()
        if 'legendado' in release_lower or 'legenda' in release_lower or re.search(r'\bleg\b', release_lower):
            has_legenda = True
            return has_legenda
    
    # ============================================================================
    # FALLBACK 3: Metadata
    # ============================================================================
    
    if info_hash and not skip_metadata and not has_legenda:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'legendado' in metadata_name or 'legenda' in metadata_name or re.search(r'\bleg\b', metadata_name):
                    has_legenda = True
                    return has_legenda
        except Exception:
            pass
    
    # ============================================================================
    # FALLBACK 4: Cross Data
    # ============================================================================
    
    if info_hash and not skip_metadata and not has_legenda:
        try:
            from utils.text.cross_data import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'legendado' in cross_release_lower or 'legenda' in cross_release_lower or re.search(r'\bleg\b', cross_release_lower):
                        has_legenda = True
                        return has_legenda
        except Exception:
            pass
    
    return has_legenda
