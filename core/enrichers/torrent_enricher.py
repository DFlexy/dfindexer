"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import List, Dict, Optional, Callable
from app.config import Config
from tracker import get_tracker_service
from magnet.metadata import fetch_metadata_from_itorrents
from magnet.parser import MagnetParser
from utils.text.utils import format_bytes

logger = logging.getLogger(__name__)


class TorrentEnricher:
    def __init__(self):
        self.tracker_service = get_tracker_service()
        self._last_filter_stats = None
    
    def enrich(self, torrents: List[Dict], skip_metadata: bool = False, skip_trackers: bool = False, filter_func: Optional[Callable[[Dict], bool]] = None, scraper_name: Optional[str] = None) -> List[Dict]:
        # Enriquece lista de torrents com metadata e trackers
        if not torrents:
            return torrents
        
        # Removida deduplicação - todos os magnets devem ser mostrados
        # torrents = self._remove_duplicates(torrents)
        
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
            # Armazena scraper_name temporariamente para uso nos logs de metadata
            self._current_scraper_name = scraper_name
            try:
                self._fetch_metadata_batch(torrents)
            finally:
                # Limpa após uso
                if hasattr(self, '_current_scraper_name'):
                    delattr(self, '_current_scraper_name')
        
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
        # OTIMIZAÇÃO: Só busca metadata se necessário para o filtro (quando não temos original_title nem title_translated_processed)
        from utils.text.cross_data import get_cross_data_from_redis
        
        for torrent in torrents:
            # Preenche original_title e title_translated_processed do cross-data ANTES do filtro
            info_hash = torrent.get('info_hash')
            if info_hash:
                try:
                    cross_data = get_cross_data_from_redis(info_hash)
                    if cross_data:
                        # Preenche original_title se não estiver preenchido
                        if not torrent.get('original_title') and cross_data.get('title_original_html'):
                            torrent['original_title'] = cross_data.get('title_original_html', '')
                        # Preenche title_translated_processed se não estiver preenchido
                        if not torrent.get('title_translated_processed') and cross_data.get('title_translated_html'):
                            torrent['title_translated_processed'] = cross_data.get('title_translated_html', '')
                        # Adiciona magnet_processed do cross-data
                        if cross_data.get('magnet_processed'):
                            torrent['magnet_processed'] = cross_data.get('magnet_processed')
                except Exception:
                    pass
            
            title = torrent.get('title_processed', '')
            original_title = torrent.get('original_title', '')
            title_translated = torrent.get('title_translated_processed', '')
            
            # OTIMIZAÇÃO: Só busca metadata se:
            # 1. Título está vazio (< 10 caracteres)
            # 2. E não temos original_title nem title_translated_processed (necessários para o filtro)
            # 3. E não foi marcado como já buscado (_metadata_fetched)
            # Isso evita buscas desnecessárias antes do filtro quando já temos dados suficientes
            needs_metadata_for_filter = (
                (not title or len(title.strip()) < 10) and
                not original_title and
                not title_translated and
                not torrent.get('_metadata_fetched')
            )
            
            if needs_metadata_for_filter and info_hash:
                try:
                    # Verifica cache primeiro para evitar busca desnecessária
                    from cache.metadata_cache import MetadataCache
                    metadata_cache = MetadataCache()
                    cached_metadata = metadata_cache.get(info_hash.lower())
                    if cached_metadata and cached_metadata.get('name'):
                        name = cached_metadata.get('name', '').strip()
                        if name and len(name) >= 3:
                            torrent['title_processed'] = name
                    else:
                        # Só busca se não está em cache (será buscado em batch depois)
                        scraper_name = getattr(self, '_current_scraper_name', None)
                        # Tenta obter título de múltiplas fontes para melhorar o log
                        title_for_log = (torrent.get('title_processed') or 
                                        torrent.get('original_title') or 
                                        torrent.get('title_translated_processed') or
                                        torrent.get('magnet_processed') or
                                        None)
                        metadata = fetch_metadata_from_itorrents(info_hash, scraper_name=scraper_name, title=title_for_log)
                        if metadata and metadata.get('name'):
                            name = metadata.get('name', '').strip()
                            if name and len(name) >= 3:
                                torrent['title_processed'] = name
                except Exception:
                    pass
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        # Busca metadata em lote com semáforo global para limitar requisições simultâneas
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from utils.concurrency.metadata_semaphore import metadata_slot
        
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
        def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
            # Obtém info_hash ANTES de adquirir slot (economiza slots)
            info_hash = torrent.get('info_hash')
            if not info_hash:
                try:
                    from magnet.parser import MagnetParser
                    magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                    info_hash = magnet_data.get('info_hash')
                except Exception:
                    return (torrent, None)
            
            if not info_hash:
                return (torrent, None)
                
            # Verifica cross_data ANTES de adquirir slot (economiza slots)
            try:
                from utils.text.cross_data import get_cross_data_from_redis
                cross_data = get_cross_data_from_redis(info_hash)
                if cross_data:
                    has_release_title = cross_data.get('magnet_processed')
                    has_size = cross_data.get('size')
                    # Se já temos magnet_processed E size no cross_data, pode pular metadata
                    if has_release_title and has_size:
                        return (torrent, None)
            except Exception:
                pass
            
            # Verifica cache de metadata ANTES de adquirir slot (economiza slots)
            try:
                from cache.metadata_cache import MetadataCache
                metadata_cache = MetadataCache()
                cached_metadata = metadata_cache.get(info_hash.lower())
                if cached_metadata:
                    return (torrent, cached_metadata)
            except Exception:
                pass
            
            # Só adquire slot se realmente precisa buscar metadata
            from utils.concurrency.metadata_semaphore import metadata_slot
            with metadata_slot():
                try:
                    from magnet.metadata import fetch_metadata_from_itorrents
                    # Obtém scraper_name e title para o log
                    scraper_name = getattr(self, '_current_scraper_name', None)
                    # Tenta obter título de múltiplas fontes para melhorar o log
                    title = (torrent.get('title_processed') or 
                            torrent.get('original_title') or 
                            torrent.get('title_translated_processed') or
                            torrent.get('magnet_processed') or
                            None)
                    metadata = fetch_metadata_from_itorrents(info_hash, scraper_name=scraper_name, title=title)
                    return (torrent, metadata)
                except Exception:
                    return (torrent, None)
        
        if len(torrents_to_fetch) > 1:
            # Limita workers locais, mas o semáforo global controla requisições simultâneas
            # Aumentado de 8 para 16 para permitir mais paralelismo (o semáforo global limita a 64)
            max_workers = min(16, len(torrents_to_fetch))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_torrent = {
                    executor.submit(fetch_metadata_for_torrent, t): t
                    for t in torrents_to_fetch
                }
                
                for future in as_completed(future_to_torrent):
                    try:
                        torrent, metadata = future.result(timeout=30)  # Aumentado de 10s para 30s
                        if metadata:
                            torrent['_metadata'] = metadata
                            torrent['_metadata_fetched'] = True
                            # Salva metadata['name'] no cross_data se disponível
                            self._save_metadata_name_to_cross_data(torrent, metadata)
                    except Exception:
                        pass
        else:
            for torrent in torrents_to_fetch:
                try:
                    torrent, metadata = fetch_metadata_for_torrent(torrent)
                    if metadata:
                        torrent['_metadata'] = metadata
                        torrent['_metadata_fetched'] = True
                        # Salva metadata['name'] no cross_data se disponível
                        self._save_metadata_name_to_cross_data(torrent, metadata)
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
        # Aplica fallbacks para data: 1) Metadata API, 2) Data atual
        from datetime import datetime
        
        for torrent in torrents:
            # Só aplica fallback se date estiver vazio
            current_date = torrent.get('date', '')
            if current_date:
                continue  # Já tem data, não precisa de fallback
            
            # Tentativa 1: Metadata API (se habilitado)
            if not skip_metadata:
                if torrent.get('_metadata') and 'created_time' in torrent['_metadata']:
                    try:
                        created_time = torrent['_metadata']['created_time']
                        if created_time:
                            # Se created_time já é string ISO, usa diretamente
                            if isinstance(created_time, str):
                                torrent['date'] = created_time
                            else:
                                # Se é timestamp, converte
                                creation_date = datetime.fromtimestamp(created_time)
                                torrent['date'] = creation_date.strftime('%Y-%m-%dT%H:%M:%SZ')
                            continue  # Encontrou no metadata, não precisa de fallback final
                    except Exception:
                        pass
            
            # Tentativa 2: Fallback final - Data atual (formato ISO 8601 com Z)
            torrent['date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    
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
        from utils.text.cleaning import remove_accents
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
            title = torrent.get('title_processed', '')
            
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
                            scraper_name = getattr(self, '_current_scraper_name', None)
                            # Tenta obter título de múltiplas fontes para melhorar o log
                            title = (torrent.get('title_processed') or 
                                    torrent.get('original_title') or 
                                    torrent.get('title_translated_processed') or
                                    torrent.get('magnet_processed') or
                                    None)
                            metadata = fetch_metadata_from_itorrents(info_hash, scraper_name=scraper_name, title=title)
                        
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
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Obtém scraper_name para logs
        scraper_name = getattr(self, '_current_scraper_name', None)
        
        # Primeiro, tenta buscar dados de tracker do cross-data
        infohash_map = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            if (torrent.get('seed_count') or 0) > 0 or (torrent.get('leech_count') or 0) > 0:
                continue
            
            # Monta identificação para o log
            log_parts = []
            if scraper_name:
                log_parts.append(f"[{scraper_name}]")
            title = torrent.get('title_processed', '')
            if title:
                title_preview = title[:120] if len(title) > 120 else title
                log_parts.append(title_preview)
            log_parts.append(f"(hash: {info_hash})")
            log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
            
            # Tenta buscar do cross-data primeiro
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                # Se ambos estão presentes, usa do cross-data (mesmo se for 0, 0 - evita scrape desnecessário)
                if tracker_seed is not None and tracker_leech is not None:
                    torrent['seed_count'] = tracker_seed
                    torrent['leech_count'] = tracker_leech
                    # Log removido - hits do Redis são muito comuns
                    continue
                else:
                    # Não tem ambos valores, prossegue para scrape
                    logger.debug(f"[Tracker] Buscando: {log_id} → Não encontrado")
            else:
                # Não encontrou no cross-data, prossegue para scrape
                logger.debug(f"[Tracker] Buscando tracker: {log_id} → Não encontrado")
            
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
                    
                    # Salva no TrackerCache se ainda não estiver salvo (garante consistência)
                    # Isso cobre casos onde (0, 0) foi retornado mas não foi salvo no TrackerCache
                    try:
                        from cache.tracker_cache import TrackerCache
                        tracker_cache = TrackerCache()
                        # Verifica se já está no cache
                        cached = tracker_cache.get(info_hash)
                        if not cached:
                            # Se não está no cache, salva (mesmo que seja 0, 0 - é sucesso)
                            tracker_data = {"leech": leech, "seed": seed}
                            tracker_cache.set(info_hash, tracker_data)
                    except Exception:
                        pass
                    
                    # Salva no cross-data sempre que obtém dados do tracker (mesmo se 0, para evitar consultas futuras)
                    saved_to_redis = False
                    try:
                        cross_data_to_save = {
                            'tracker_seed': seed,
                            'tracker_leech': leech
                        }
                        save_cross_data_to_redis(info_hash, cross_data_to_save)
                        saved_to_redis = True
                    except Exception:
                        pass
                    
                    # Log com resultado da busca e salvamento
                    log_parts = []
                    if scraper_name:
                        log_parts.append(f"[{scraper_name}]")
                    title = torrent.get('title_processed', '')
                    if title:
                        title_preview = title[:120] if len(title) > 120 else title
                        log_parts.append(title_preview)
                    log_parts.append(f"(hash: {info_hash})")
                    log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
                    
                    if saved_to_redis:
                        logger.debug(f"[Tracker] Buscando: {log_id} → Salvo no Redis")
                    else:
                        logger.debug(f"[Tracker] Buscando: {log_id} → Scrape realizado (erro ao salvar no Redis)")
        except Exception:
            pass
    
    def _save_metadata_name_to_cross_data(self, torrent: Dict, metadata: Dict) -> None:
        # Salva metadata['name'] no cross_data se disponível e mais completo que magnet_processed atual
        try:
            info_hash = torrent.get('info_hash', '').lower()
            if not info_hash or len(info_hash) != 40:
                return
            
            metadata_name = metadata.get('name', '').strip() if metadata else None
            if not metadata_name or len(metadata_name) < 3:
                return
            
            from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
            from utils.text.storage import _is_metadata_more_complete
            from utils.text.title_builder import _normalize_metadata_name
            
            # Verifica cross_data atual
            cross_data = get_cross_data_from_redis(info_hash)
            cross_magnet_processed = None
            if cross_data and cross_data.get('magnet_processed'):
                cross_magnet_processed = str(cross_data.get('magnet_processed')).strip()
            
            # Se não tem cross_data['magnet_processed'] ou metadata é mais completo, salva
            if not cross_magnet_processed or not _is_metadata_more_complete(metadata_name, cross_magnet_processed):
                # Salva metadata_name normalizado no cross_data
                normalized_metadata = _normalize_metadata_name(metadata_name)
                save_cross_data_to_redis(info_hash, {'metadata_name': metadata_name, 'magnet_processed': normalized_metadata})
        except Exception:
            pass

