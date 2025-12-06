"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import List, Dict, Optional, Callable
from app.config import Config
from tracker import get_tracker_service
from magnet.metadata import fetch_metadata_from_itorrents
from magnet.parser import MagnetParser
from utils.text.text_processing import format_bytes

logger = logging.getLogger(__name__)


class TorrentEnricher:
    def __init__(self):
        self.tracker_service = get_tracker_service()
        self._last_filter_stats = None
    
    def enrich(self, torrents: List[Dict], skip_metadata: bool = False, skip_trackers: bool = False, filter_func: Optional[Callable[[Dict], bool]] = None, scraper_name: Optional[str] = None) -> List[Dict]:
        # Enriquece lista de torrents com metadata e trackers
        if not torrents:
            return torrents
        
        torrents = self._remove_duplicates(torrents)
        
        if not skip_metadata:
            self._ensure_titles_complete(torrents)
        
        total_before_filter = len(torrents)
        if filter_func:
            torrents = [t for t in torrents if filter_func(t)]
            filtered_count = total_before_filter - len(torrents)
            approved_count = len(torrents)
        else:
            filtered_count = 0
            approved_count = len(torrents)
        
        self._last_filter_stats = {
            'total': total_before_filter,
            'filtered': filtered_count,
            'approved': approved_count,
            'scraper_name': scraper_name
        }
        
        if not torrents:
            return torrents
        
        if not skip_metadata:
            self._fetch_metadata_batch(torrents)
        
        self._apply_size_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_date_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_imdb_fallback(torrents)
        
        if not skip_trackers:
            self._attach_peers(torrents)
        
        return torrents
    
    def _remove_duplicates(self, torrents: List[Dict]) -> List[Dict]:
        # Remove duplicados baseado em info_hash
        seen_hashes = set()
        unique_torrents = []
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if info_hash and len(info_hash) == 40:
                if info_hash in seen_hashes:
                    continue
                seen_hashes.add(info_hash)
            unique_torrents.append(torrent)
        return unique_torrents
    
    def _ensure_titles_complete(self, torrents: List[Dict]) -> None:
        # Garante que títulos estão completos
        for torrent in torrents:
            title = torrent.get('title', '')
            if not title or len(title.strip()) < 10:
                info_hash = torrent.get('info_hash')
                if info_hash:
                    try:
                        metadata = fetch_metadata_from_itorrents(info_hash)
                        if metadata and metadata.get('name'):
                            name = metadata.get('name', '').strip()
                            if name and len(name) >= 3:
                                torrent['title'] = name
                    except Exception:
                        pass
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        # Busca metadata em lote com semáforo global para limitar requisições simultâneas
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from utils.concurrency.metadata_semaphore import acquire_metadata_slot, release_metadata_slot
        
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
        def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
            # Adquire slot no semáforo global antes de fazer requisição
            acquire_metadata_slot()
            try:
                info_hash = torrent.get('info_hash')
                if not info_hash:
                    try:
                        magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                        info_hash = magnet_data.get('info_hash')
                    except Exception:
                        return (torrent, None)
                
                if not info_hash:
                    return (torrent, None)
                
                # Verifica cross_data primeiro (evita consulta desnecessária ao metadata)
                # Mas só pula se já tem TUDO que precisa (release_title_magnet, size, date)
                try:
                    from utils.text.cross_data import get_cross_data_from_redis
                    cross_data = get_cross_data_from_redis(info_hash)
                    if cross_data:
                        has_release_title = cross_data.get('release_title_magnet')
                        has_size = cross_data.get('size')
                        # Se já temos release_title_magnet E size no cross_data, pode pular metadata
                        # (date pode vir depois, mas não é crítico)
                        if has_release_title and has_size:
                            # Retorna None para indicar que não precisa buscar
                            return (torrent, None)
                except Exception:
                    pass
                
                metadata = fetch_metadata_from_itorrents(info_hash)
                return (torrent, metadata)
            except Exception:
                return (torrent, None)
            finally:
                # Sempre libera o slot, mesmo em caso de erro
                release_metadata_slot()
        
        if len(torrents_to_fetch) > 1:
            # Limita workers locais, mas o semáforo global controla requisições simultâneas
            max_workers = min(8, len(torrents_to_fetch))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_torrent = {
                    executor.submit(fetch_metadata_for_torrent, t): t
                    for t in torrents_to_fetch
                }
                
                for future in as_completed(future_to_torrent):
                    try:
                        torrent, metadata = future.result(timeout=10)
                        if metadata:
                            torrent['_metadata'] = metadata
                            torrent['_metadata_fetched'] = True
                    except Exception:
                        pass
        else:
            for torrent in torrents_to_fetch:
                try:
                    torrent, metadata = fetch_metadata_for_torrent(torrent)
                    if metadata:
                        torrent['_metadata'] = metadata
                        torrent['_metadata_fetched'] = True
                except Exception:
                    pass
    
    def _apply_size_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        # Aplica fallbacks para tamanho
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        
        metadata_enabled = not skip_metadata
        
        for torrent in torrents:
            html_size = torrent.get('size', '')
            info_hash = torrent.get('info_hash', '').lower()
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            
            # Primeiro, tenta buscar do cross-data
            if info_hash and len(info_hash) == 40:
                cross_data = get_cross_data_from_redis(info_hash)
                if cross_data and cross_data.get('size'):
                    cross_size = cross_data.get('size')
                    if cross_size and cross_size.strip() and cross_size != 'N/A':
                        torrent['size'] = cross_size.strip()
                        continue
            
            magnet_data = None
            try:
                magnet_data = MagnetParser.parse(magnet_link)
            except Exception:
                pass
            
            torrent['size'] = ''
            
            # Tentativa 1: Metadata API
            if metadata_enabled:
                if torrent.get('_metadata') and 'size' in torrent['_metadata']:
                    try:
                        size_bytes = torrent['_metadata']['size']
                        formatted_size = format_bytes(size_bytes)
                        if formatted_size:
                            torrent['size'] = formatted_size
                            # Salva no cross-data
                            if info_hash and len(info_hash) == 40:
                                try:
                                    save_cross_data_to_redis(info_hash, {'size': formatted_size})
                                except Exception:
                                    pass
                            continue
                    except Exception:
                        pass
            
            # Tentativa 2: Parâmetro 'xl' do magnet
            if magnet_data:
                xl = magnet_data.get('params', {}).get('xl')
                if xl:
                    try:
                        formatted_size = format_bytes(int(xl))
                        if formatted_size:
                            torrent['size'] = formatted_size
                            # Salva no cross-data
                            if info_hash and len(info_hash) == 40:
                                try:
                                    save_cross_data_to_redis(info_hash, {'size': formatted_size})
                                except Exception:
                                    pass
                            continue
                    except Exception:
                        pass
            
            # Tentativa 3: Tamanho do HTML (fallback final)
            if html_size:
                torrent['size'] = html_size
                # Salva no cross-data
                if info_hash and len(info_hash) == 40:
                    try:
                        save_cross_data_to_redis(info_hash, {'size': html_size})
                    except Exception:
                        pass
    
    def _apply_date_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        # Aplica fallbacks para data
        metadata_enabled = not skip_metadata
        
        for torrent in torrents:
            html_date = torrent.get('date', '')
            
            # Tentativa 1: Metadata API
            if metadata_enabled:
                if torrent.get('_metadata') and 'created_time' in torrent['_metadata']:
                    try:
                        created_time = torrent['_metadata']['created_time']
                        if created_time:
                            torrent['date'] = created_time
                            continue
                    except Exception:
                        pass
            
            # Tentativa 2: Data do HTML (fallback final)
            if html_date:
                torrent['date'] = html_date
    
    def _apply_imdb_fallback(self, torrents: List[Dict]) -> None:
        """
        Aplica fallback de IMDB quando não encontrado no HTML.
        Ordem de prioridade:
        1. HTML do Scraper (já extraído)
        2. Cache Redis por info_hash
        3. Cache Redis por base_title (título finalizado limpo)
        4. Metadata do torrent
        """
        from cache.redis_client import get_redis_client
        from cache.redis_keys import imdb_key, imdb_title_key
        from utils.text.text_processing import remove_accents
        import re
        
        redis = get_redis_client()
        if not redis:
            return
        
        def extract_base_title_for_imdb(title: str) -> Optional[str]:
            """
            Extrai título base do título finalizado para busca de IMDB.
            O título finalizado tem formato: base_title.SxxExx.ano.qualidade.codec...
            Remove apenas componentes técnicos variáveis (qualidade, codec, fonte, áudio)
            mantendo base_title, temporada/episódio e ano.
            """
            if not title:
                return None
            
            # Remove tags de áudio no final
            title = re.sub(r'\s*\[Brazilian\]\s*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*\[Eng\]\s*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*\[br-dub\]\s*', '', title, flags=re.IGNORECASE)
            
            # Remove componentes técnicos variáveis (qualidade, codec, fonte, áudio)
            # Mantém: base_title, SxxExx, ano
            technical_patterns = [
                r'\.WEB-DL\.?', r'\.WEBRip\.?', r'\.BluRay\.?', r'\.DVDRip\.?',
                r'\.HDRip\.?', r'\.HDTV\.?', r'\.BDRip\.?', r'\.BRRip\.?',
                r'\.1080p\.?', r'\.720p\.?', r'\.2160p\.?', r'\.4K\.?',
                r'\.HD\.?', r'\.FHD\.?', r'\.UHD\.?', r'\.SD\.?', r'\.HDR\.?',
                r'\.x264\.?', r'\.x265\.?', r'\.HEVC\.?', r'\.AVC\.?',
                r'\.DUAL\.?', r'\.DUBLADO\.?', r'\.NACIONAL\.?',
                r'\.LEGENDADO\.?', r'\.LEGENDA\.?',
            ]
            
            for pattern in technical_patterns:
                title = re.sub(pattern, '.', title, flags=re.IGNORECASE)
            
            # Remove pontos duplicados e normaliza
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip(' .')
            
            # Remove acentos para normalização (ANTES de converter para lowercase)
            title = remove_accents(title)
            
            # Converte para lowercase
            title = title.lower().strip()
            
            # Remove pontos finais e espaços extras
            title = re.sub(r'\.+$', '', title)
            title = re.sub(r'\.+', '.', title)  # Garante que não há pontos duplicados
            title = re.sub(r'\s+', ' ', title).strip()
            
            # Remove espaços e converte para pontos (garantir formato consistente)
            title = title.replace(' ', '.')
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
            
            return title if title and len(title) >= 3 else None
        
        for torrent in torrents:
            # Se já tem IMDB, salva no cache para reutilização
            imdb = torrent.get('imdb', '').strip()
            info_hash = torrent.get('info_hash', '').strip().lower()
            title = torrent.get('title', '')
            
            if imdb and imdb.startswith('tt') and imdb[2:].isdigit():
                # Salva no cache por info_hash
                if info_hash and len(info_hash) == 40:
                    try:
                        key = imdb_key(info_hash)
                        redis.setex(key, 7 * 24 * 3600, imdb)  # 7 dias
                    except Exception:
                        pass
                
                # Salva no cache por base_title
                base_title = extract_base_title_for_imdb(title)
                if base_title and len(base_title) >= 3:
                    try:
                        title_key = imdb_title_key(base_title)
                        redis.setex(title_key, 7 * 24 * 3600, imdb)  # 7 dias
                    except Exception:
                        pass
            
            # Se não tem IMDB, tenta encontrar
            if not torrent.get('imdb'):
                # Fallback 1: Cache por info_hash
                if info_hash and len(info_hash) == 40:
                    try:
                        key = imdb_key(info_hash)
                        cached_imdb = redis.get(key)
                        if cached_imdb:
                            cached_imdb_str = cached_imdb.decode('utf-8')
                            if cached_imdb_str.startswith('tt') and cached_imdb_str[2:].isdigit():
                                torrent['imdb'] = cached_imdb_str
                                continue  # Encontrou, não precisa verificar outros fallbacks
                    except Exception:
                        pass
                
                # Fallback 2: Cache por base_title
                base_title = extract_base_title_for_imdb(title)
                if base_title and len(base_title) >= 3:
                    try:
                        title_key = imdb_title_key(base_title)
                        cached_imdb = redis.get(title_key)
                        if cached_imdb:
                            cached_imdb_str = cached_imdb.decode('utf-8')
                            if cached_imdb_str.startswith('tt') and cached_imdb_str[2:].isdigit():
                                torrent['imdb'] = cached_imdb_str
                                continue
                    except Exception:
                        pass
                
                # Fallback 3: Metadata do torrent
                try:
                    magnet_link = torrent.get('magnet_link')
                    if magnet_link and info_hash:
                        metadata = torrent.get('_metadata')
                        if not metadata:
                            from magnet.metadata import fetch_metadata_from_itorrents
                            metadata = fetch_metadata_from_itorrents(info_hash)
                        
                        if metadata and metadata.get('imdb'):
                            imdb_from_metadata = metadata.get('imdb')
                            # Valida formato
                            if isinstance(imdb_from_metadata, str) and imdb_from_metadata.startswith('tt') and imdb_from_metadata[2:].isdigit():
                                torrent['imdb'] = imdb_from_metadata
                                # Salva no cache para reutilização (por info_hash e base_title)
                                if redis:
                                    try:
                                        # Salva por info_hash
                                        if info_hash and len(info_hash) == 40:
                                            key = imdb_key(info_hash)
                                            redis.setex(key, 7 * 24 * 3600, imdb_from_metadata)  # 7 dias
                                        
                                        # Salva por base_title
                                        if base_title and len(base_title) >= 3:
                                            title_key = imdb_title_key(base_title)
                                            redis.setex(title_key, 7 * 24 * 3600, imdb_from_metadata)  # 7 dias
                                        
                                    except Exception:
                                        pass
                except Exception:
                    pass
    
    def _attach_peers(self, torrents: List[Dict]) -> None:
        # Anexa dados de peers (seeds/leechers) via trackers
        from utils.parsing.magnet_utils import extract_trackers_from_magnet
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        
        # Primeiro, tenta buscar dados de tracker do cross-data
        infohash_map = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            if (torrent.get('seed_count') or 0) > 0 or (torrent.get('leech_count') or 0) > 0:
                continue
            
            # Tenta buscar do cross-data primeiro
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                # Se ambos estão presentes (mesmo que sejam 0), usa do cross-data para evitar scrape desnecessário
                if tracker_seed is not None and tracker_leech is not None:
                    torrent['seed_count'] = tracker_seed
                    torrent['leech_count'] = tracker_leech
                    continue
            
            # Se não encontrou no cross-data, adiciona para fazer scrape
            # Extrai trackers do torrent primeiro
            trackers = torrent.get('trackers') or []
            
            # Se não tem trackers no torrent, tenta extrair do magnet_link usando função utilitária
            if not trackers:
                magnet_link = torrent.get('magnet_link')
                if magnet_link:
                    trackers = extract_trackers_from_magnet(magnet_link)
            
            if trackers:
                infohash_map.setdefault(info_hash, [])
                infohash_map[info_hash].extend(trackers)
        
        if not infohash_map:
            return
        
        # Faz scrape dos trackers
        try:
            peers_map = self.tracker_service.get_peers_bulk(infohash_map)
            for torrent in torrents:
                info_hash = (torrent.get('info_hash') or '').lower()
                if not info_hash or len(info_hash) != 40:
                    continue
                
                leech_seed = peers_map.get(info_hash)
                if leech_seed:
                    leech, seed = leech_seed
                    torrent['leech_count'] = leech
                    torrent['seed_count'] = seed
                    
                    # Salva no cross-data sempre que obtém dados do tracker (mesmo se 0, para evitar consultas futuras)
                    try:
                        cross_data_to_save = {
                            'tracker_seed': seed,
                            'tracker_leech': leech
                        }
                        save_cross_data_to_redis(info_hash, cross_data_to_save)
                    except Exception:
                        pass
        except Exception:
            pass

