"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def process_magnet_links(
    magnet_links: List[str],
    page_data: Dict,
    scraper_instance,
    sizes: Optional[List[str]] = None
) -> List[Dict]:
    """
    Processa uma lista de magnet links e retorna torrents formatados.
    
    Centraliza a lógica comum de processamento de magnets que estava duplicada
    em todos os scrapers.
    
    Args:
        magnet_links: Lista de magnet links resolvidos
        page_data: Dicionário com dados extraídos da página:
            - original_title: Título original
            - title_translated_processed: Título traduzido
            - page_title: Título da página (fallback)
            - year: Ano
            - imdb: ID do IMDB
            - date: Data (datetime ou None)
            - absolute_link: URL da página
            - audio_info: Informação de áudio detectada do HTML
            - audio_html_content: HTML para detecção adicional de áudio
        scraper_instance: Instância do scraper (para acessar _skip_metadata)
        sizes: Lista de tamanhos extraídos (opcional)
    
    Returns:
        Lista de dicionários de torrents formatados
    """
    from magnet.parser import MagnetParser
    from utils.parsing.magnet_utils import process_trackers
    from utils.text.title_builder import create_standardized_title, prepare_release_title
    from utils.parsing.audio_extraction import add_audio_tag_if_needed
    from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
    from utils.text.storage import save_release_title_to_redis
    from utils.logging import format_error, format_link_preview
    
    torrents = []
    sizes = sizes or []
    
    # Extrai dados da página
    original_title = page_data.get('original_title', '')
    title_translated_processed = page_data.get('title_translated_processed', '')
    page_title = page_data.get('page_title', '')
    year = page_data.get('year', '')
    imdb = page_data.get('imdb', '')
    date = page_data.get('date')
    absolute_link = page_data.get('absolute_link', '')
    audio_info = page_data.get('audio_info')
    audio_html_content = page_data.get('audio_html_content', '')
    
    # Acessa flags do scraper
    skip_metadata = getattr(scraper_instance, '_skip_metadata', False)
    
    for idx, magnet_link in enumerate(magnet_links):
        try:
            magnet_data = MagnetParser.parse(magnet_link)
            info_hash = magnet_data['info_hash']
            
            # Busca dados cruzados no Redis por info_hash (fallback principal)
            cross_data = None
            try:
                cross_data = get_cross_data_from_redis(info_hash)
            except Exception:
                pass
            
            # Cria cópias locais para não modificar os originais
            local_original_title = original_title
            local_title_translated_processed = title_translated_processed
            local_imdb = imdb
            
            # Preenche campos faltantes com dados cruzados do Redis
            if cross_data:
                if not local_original_title and cross_data.get('title_original_html'):
                    local_original_title = cross_data['title_original_html']
                
                if not local_title_translated_processed and cross_data.get('title_translated_html'):
                    local_title_translated_processed = cross_data['title_translated_html']
                
                if not local_imdb and cross_data.get('imdb'):
                    local_imdb = cross_data['imdb']
            
            # Extrai magnet_original diretamente do display_name do magnet resolvido
            magnet_original = magnet_data.get('display_name', '')
            missing_dn = not magnet_original or len(magnet_original.strip()) < 3
            
            # NOTA: Não busca cross_data aqui para não interferir no fluxo de prepare_release_title()
            # A busca de fallback (release:title, cross_data, metadata) será feita dentro de prepare_release_title()
            # quando missing_dn = True, através de get_metadata_name()
            
            # Salva magnet_processed no Redis se encontrado
            if not missing_dn and magnet_original:
                try:
                    save_release_title_to_redis(info_hash, magnet_original)
                except Exception:
                    pass
            
            # Prepara fallback_title
            fallback_title = local_original_title or local_title_translated_processed or page_title or ''
            
            # Prepara release_title
            original_release_title = prepare_release_title(
                magnet_original,
                fallback_title,
                year,
                missing_dn=missing_dn,
                info_hash=info_hash if missing_dn else None,
                skip_metadata=skip_metadata
            )
            
            # Garante que title_translated_processed seja string
            title_translated_processed_str = str(local_title_translated_processed) if local_title_translated_processed else None
            if title_translated_processed_str and not isinstance(title_translated_processed_str, str):
                title_translated_processed_str = None
            
            # Cria título padronizado
            standardized_title = create_standardized_title(
                str(local_original_title) if local_original_title else '',
                year,
                original_release_title,
                title_translated_html=title_translated_processed_str,
                magnet_original=magnet_original
            )
            
            # Adiciona tags de áudio
            final_title = add_audio_tag_if_needed(
                standardized_title,
                original_release_title,
                info_hash=info_hash,
                skip_metadata=skip_metadata,
                audio_info_from_html=audio_info,
                audio_html_content=audio_html_content
            )
            
            # Determina origem_audio_tag
            origem_audio_tag = 'N/A'
            if magnet_original and ('dual' in magnet_original.lower() or 'dublado' in magnet_original.lower() or 'legendado' in magnet_original.lower()):
                origem_audio_tag = 'magnet_processed'
            elif missing_dn and info_hash:
                origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
            
            # Extrai tamanho
            size = ''
            if sizes and idx < len(sizes):
                size = sizes[idx]
            
            # Processa trackers
            trackers = process_trackers(magnet_data)
            
            # Salva dados cruzados no Redis
            try:
                cross_data_to_save = {
                    'title_original_html': str(local_original_title) if local_original_title else None,
                    'magnet_processed': original_release_title if original_release_title else None,
                    'magnet_original': magnet_original if magnet_original else None,
                    'title_translated_html': str(local_title_translated_processed) if local_title_translated_processed else None,
                    'imdb': local_imdb if local_imdb else None,
                    'missing_dn': missing_dn,
                    'origem_audio_tag': origem_audio_tag if origem_audio_tag != 'N/A' else None,
                    'size': size if size and size.strip() else None
                }
                save_cross_data_to_redis(info_hash, cross_data_to_save)
            except Exception:
                pass
            
            # Cria torrent dict
            torrent = {
                'title_processed': final_title,
                'original_title': local_original_title if local_original_title else (local_title_translated_processed if local_title_translated_processed else page_title),
                'title_translated_processed': local_title_translated_processed if local_title_translated_processed else None,
                'details': absolute_link,
                'year': year,
                'imdb': local_imdb if local_imdb else '',
                'audio': [],
                'magnet_link': magnet_link,
                'date': date.strftime('%Y-%m-%dT%H:%M:%SZ') if date else '',
                'info_hash': info_hash,
                'trackers': trackers,
                'size': size,
                'leech_count': 0,
                'seed_count': 0,
                'similarity': 1.0,
                'magnet_original': magnet_original if magnet_original else None
            }
            torrents.append(torrent)
        
        except Exception as e:
            logger.error(f"Magnet error: {format_error(e)} (link: {format_link_preview(magnet_link)})")
            continue
    
    return torrents

