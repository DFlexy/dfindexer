"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import time
import uuid
import threading
from typing import Optional
import requests
from cache.redis_client import get_redis_client
from cache.redis_keys import flaresolverr_session_key, flaresolverr_created_key, flaresolverr_session_creation_failure_key
from app.config import Config
from utils.http.proxy import get_proxy_url, get_proxy_dict, is_proxy_local

logger = logging.getLogger(__name__)

# Cache em memória por requisição (apenas quando Redis não está disponível)
_request_cache = threading.local()

# Cache compartilhado global para sessões quando Redis não está disponível
# Estrutura: {base_url: (session_id, expire_at)}
_shared_sessions_cache = {}
_shared_sessions_lock = threading.Lock()

# Controle global de sessões FlareSolverr simultâneas
_session_creation_lock = threading.Lock()
_active_sessions_count = 0
_max_sessions = None

# Lock para proteger validação/invalidação de sessões (evita race conditions)
_session_validation_lock = threading.Lock()

# Locks por base_url para proteger criação de sessão (evita múltiplas threads criando simultaneamente)
_session_creation_locks = {}
_session_creation_locks_lock = threading.Lock()

def _get_session_creation_lock(base_url: str) -> threading.Lock:
    """Obtém um lock específico para criação de sessão de uma base_url"""
    global _session_creation_locks
    with _session_creation_locks_lock:
        if base_url not in _session_creation_locks:
            _session_creation_locks[base_url] = threading.Lock()
        return _session_creation_locks[base_url]

# Lock global para serializar requisições ao FlareSolverr (evita race conditions em processamento paralelo)
# Uma requisição por vez por base_url para garantir que o HTML retornado corresponde à URL solicitada
_flaresolverr_request_locks = {}
_flaresolverr_request_locks_lock = threading.Lock()

def _get_flaresolverr_lock(base_url: str) -> threading.Lock:
    """Obtém um lock específico para serializar requisições ao FlareSolverr de uma base_url"""
    global _flaresolverr_request_locks
    with _flaresolverr_request_locks_lock:
        if base_url not in _flaresolverr_request_locks:
            _flaresolverr_request_locks[base_url] = threading.Lock()
        return _flaresolverr_request_locks[base_url]

# Cache para evitar logs duplicados consecutivos
_last_log_cache = {}
_last_log_lock = threading.Lock()


class FlareSolverrClient:
    def __init__(self, address: str):
        self.address = address.rstrip('/')
        self.api_url = f"{self.address}/v1"
        self.redis = get_redis_client()
    
    def _get_session_key(self, base_url: str) -> str:
        return flaresolverr_session_key(base_url)
    
    def _get_session_created_key(self, base_url: str) -> str:
        return flaresolverr_created_key(base_url)
    
    # Obtém o limite máximo de sessões FlareSolverr simultâneas
    def _get_max_sessions(self) -> int:
        global _max_sessions
        if _max_sessions is None:
            _max_sessions = Config.FLARESOLVERR_MAX_SESSIONS if hasattr(Config, 'FLARESOLVERR_MAX_SESSIONS') else 15
        return _max_sessions
    
    # Verifica se pode criar nova sessão (respeitando limite global)
    def _can_create_session(self) -> bool:
        global _active_sessions_count, _session_creation_lock
        with _session_creation_lock:
            max_sessions = self._get_max_sessions()
            if _active_sessions_count >= max_sessions:
                logger.debug(f"FlareSolverr: limite atingido ({_active_sessions_count}/{max_sessions})")
                return False
            return True
    
    # Incrementa contador de sessões ativas
    def _increment_session_count(self):
        global _active_sessions_count, _session_creation_lock
        with _session_creation_lock:
            _active_sessions_count += 1
            logger.debug(f"FlareSolverr: sessão criada ({_active_sessions_count}/{self._get_max_sessions()})")
    
    # Decrementa contador de sessões ativas
    def _decrement_session_count(self):
        global _active_sessions_count, _session_creation_lock
        with _session_creation_lock:
            if _active_sessions_count > 0:
                _active_sessions_count -= 1
                logger.debug(f"FlareSolverr: sessão removida ({_active_sessions_count}/{self._get_max_sessions()})")
    
    def _create_session(self, base_url: str, skip_redis: bool = False) -> Optional[str]:
        # Cria nova sessão FlareSolverr (Redis primeiro, memória se Redis não disponível)
        # Verifica se houve falha recente de criação de sessão (evita tentativas muito frequentes)
        if self.redis and not skip_redis:
            try:
                failure_key = flaresolverr_session_creation_failure_key(base_url)
                if self.redis.exists(failure_key):
                    logger.warning(f"FlareSolverr: falha recente ao criar sessão para {base_url}, aguardando antes de tentar novamente")
                    return None
            except Exception:
                pass
        
        # Verifica limite global de sessões simultâneas
        if not self._can_create_session():
            # Tenta reutilizar sessão existente antes de criar nova
            if self.redis and not skip_redis:
                try:
                    session_key = self._get_session_key(base_url)
                    cached = self.redis.get(session_key)
                    if cached:
                        session_id = cached.decode('utf-8')
                        if self._validate_session(session_id):
                            logger.debug(f"FlareSolverr: reutilizando sessão (limite)")
                            return session_id
                except Exception:
                    pass
            logger.warning(f"Não é possível criar nova sessão FlareSolverr. Limite atingido ({self._get_max_sessions()} sessões).")
            return None
        
        try:
            session_id = f"dfindexer_{uuid.uuid4().hex[:12]}"
            
            payload = {
                "cmd": "sessions.create",
                "session": session_id
            }
            
            # Adiciona proxy ao payload se disponível (para FlareSolverr usar ao fazer requisições aos sites)
            proxy_url = get_proxy_url()
            if proxy_url:
                payload["proxy"] = proxy_url
            
            # Usa proxy para acessar FlareSolverr apenas se o proxy NÃO for local
            # Se o proxy for local (mesma rede), não usa proxy para acessar FlareSolverr
            proxy_dict = None
            if not is_proxy_local():
                proxy_dict = get_proxy_dict()
            
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=150,
                headers={"Content-Type": "application/json"},
                proxies=proxy_dict if proxy_dict else None
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get("status") == "ok":
                created_session_id = result.get("session")
                if created_session_id:
                    # Limpa cache de falha de criação (sessão foi criada com sucesso)
                    if self.redis and not skip_redis:
                        try:
                            failure_key = flaresolverr_session_creation_failure_key(base_url)
                            self.redis.delete(failure_key)
                        except Exception:
                            pass
                    
                    # Incrementa contador de sessões ativas
                    self._increment_session_count()
                    
                    # Tenta Redis primeiro
                    if self.redis and not skip_redis:
                        try:
                            session_key = self._get_session_key(base_url)
                            created_key = self._get_session_created_key(base_url)
                            # Protege contra race conditions ao salvar no Redis
                            with _session_validation_lock:
                                # Verifica se outra sessão já foi criada enquanto estávamos criando esta
                                existing = self.redis.get(session_key)
                                if not existing:
                                    # Nenhuma sessão existente, salva a nova
                                    self.redis.setex(session_key, Config.FLARESOLVERR_SESSION_TTL, created_session_id)
                                    self.redis.setex(created_key, Config.FLARESOLVERR_SESSION_TTL, str(int(time.time())))
                                    logger.debug(f"FlareSolverr: sessão criada e salva no cache para {base_url} (ID: {created_session_id[:20]}...)")
                                else:
                                    # Outra sessão já foi criada, usa a existente
                                    existing_session_id = existing.decode('utf-8')
                                    logger.debug(f"FlareSolverr: sessão já existe no cache para {base_url}, usando existente (ID: {existing_session_id[:20]}...)")
                                    # Destrói a sessão que acabamos de criar (não será usada)
                                    try:
                                        destroy_payload = {
                                            "cmd": "sessions.destroy",
                                            "session": created_session_id
                                        }
                                        # Usa proxy para acessar FlareSolverr apenas se o proxy NÃO for local
                                        proxy_dict = None
                                        if not is_proxy_local():
                                            proxy_dict = get_proxy_dict()
                                        requests.post(
                                            self.api_url,
                                            json=destroy_payload,
                                            timeout=5,
                                            headers={"Content-Type": "application/json"},
                                            proxies=proxy_dict if proxy_dict else None
                                        )
                                    except Exception:
                                        pass  # Ignora erros ao destruir
                                    # Decrementa contador pois não vamos usar a sessão que acabamos de criar
                                    self._decrement_session_count()
                                    return existing_session_id
                        except Exception as e:
                            logger.debug(f"FlareSolverr: erro ao salvar sessão no Redis: {type(e).__name__}")
                            pass
                    
                    logger.debug(f"FlareSolverr: sessão criada para {base_url} (ID: {created_session_id[:20]}...)")
                    return created_session_id
            
            logger.warning(f"Falha ao criar sessão FlareSolverr: {result}")
            return None
            
        except requests.exceptions.Timeout:
            logger.warning(
                f"Timeout ao criar sessão FlareSolverr (FlareSolverr pode estar demorando para iniciar Chrome). "
                f"Tente novamente em alguns segundos."
            )
            # Cacheia falha de criação (2 minutos)
            self._cache_session_creation_failure(base_url, skip_redis)
            return None
        except requests.exceptions.HTTPError as e:
            # Erro HTTP (ex: 500 Internal Server Error)
            error_msg = str(e)
            logger.error(
                f"FlareSolverr retornou erro HTTP ao criar sessão para {base_url}: {error_msg}. "
                f"O FlareSolverr pode estar com problemas (Chrome/chromedriver crashando)."
            )
            # Cacheia falha de criação (2 minutos) para evitar tentativas muito frequentes
            self._cache_session_creation_failure(base_url, skip_redis)
            return None
        except Exception as e:
            error_msg = str(e)
            is_connection_error = (
                "No route to host" in error_msg or
                "Connection refused" in error_msg or
                "Failed to establish" in error_msg or
                "Max retries exceeded" in error_msg
            )
            if is_connection_error:
                logger.warning(
                    f"FlareSolverr não está acessível em {self.api_url}. "
                    f"Verifique se o serviço está rodando e acessível."
                )
            else:
                # Extrai apenas o tipo de erro para reduzir verbosidade
                error_type = type(e).__name__
                error_msg = str(e)
                if "Connection" in error_type or "Connection refused" in error_msg or "Max retries exceeded" in error_msg:
                    logger.error(f"Erro ao criar sessão FlareSolverr para {base_url}: conexão recusada ou indisponível")
                else:
                    logger.error(f"Erro ao criar sessão FlareSolverr para {base_url}: {error_type}")
            # Cacheia falha de criação (2 minutos)
            self._cache_session_creation_failure(base_url, skip_redis)
            return None
    
    def _validate_session(self, session_id: str) -> bool:
        # Validação mais tolerante: se houver erro na validação, assume que a sessão é válida
        # (evita invalidar sessões válidas por problemas temporários no FlareSolverr)
        try:
            payload = {
                "cmd": "sessions.list"
            }
            
            # Usa proxy para acessar FlareSolverr apenas se o proxy NÃO for local
            proxy_dict = None
            if not is_proxy_local():
                proxy_dict = get_proxy_dict()
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
                proxies=proxy_dict if proxy_dict else None
            )
            response.raise_for_status()
            
            result = response.json()
            sessions = result.get("sessions", [])
            is_valid = session_id in sessions
            if not is_valid:
                logger.debug(f"FlareSolverr: sessão {session_id[:20]}... não encontrada na lista")
            return is_valid
            
        except Exception as e:
            # Em caso de erro na validação, assume que a sessão é válida
            # (evita invalidar sessões válidas por problemas temporários)
            return True
    
    def _should_log(self, log_key: str) -> bool:
        """Verifica se deve fazer log (evita duplicados - apenas uma vez por base_url)"""
        global _last_log_cache, _last_log_lock
        with _last_log_lock:
            current_time = time.time()
            # Se a mesma mensagem foi logada há menos de 60 segundos, não loga novamente
            # Isso garante que aparece apenas uma vez por consulta (mesmo que a consulta demore)
            if log_key in _last_log_cache:
                if current_time - _last_log_cache[log_key] < 60:
                    return False
            _last_log_cache[log_key] = current_time
            # Limpa cache antigo (mais de 5 minutos) para evitar crescimento infinito
            keys_to_remove = [k for k, v in _last_log_cache.items() if current_time - v > 300]
            for k in keys_to_remove:
                _last_log_cache.pop(k, None)
            return True
    
    def get_or_create_session(self, base_url: str, skip_redis: bool = False) -> Optional[str]:
        # Obtém ou cria sessão FlareSolverr (Redis primeiro, memória se Redis não disponível)
        # Protege contra race conditions quando múltiplos scrapers acessam a mesma sessão
        global _session_validation_lock
        
        # Tenta Redis primeiro (reutiliza sessão existente se disponível)
        need_to_create = False
        if self.redis and not skip_redis:
            try:
                session_key = self._get_session_key(base_url)
                cached = self.redis.get(session_key)
                if cached:
                    session_id = cached.decode('utf-8')
                    # Valida sessão com lock para evitar race conditions
                    with _session_validation_lock:
                        # Verifica novamente se ainda existe no Redis (pode ter sido removido por outro scraper)
                        cached_again = self.redis.get(session_key)
                        if cached_again and cached_again.decode('utf-8') == session_id:
                            if self._validate_session(session_id):
                                # Log apenas uma vez por base_url (não por session_id, pois pode mudar)
                                log_key = f"reused_{base_url}"
                                if self._should_log(log_key):
                                    logger.info(f"FlareSolverr: sessão encontrada e reutilizada para {base_url} (ID: {session_id[:20]}...)")
                                return session_id
                            else:
                                # Sessão inválida, remove do cache apenas se ainda for a mesma sessão
                                # (evita remover sessão que foi recriada por outro scraper)
                                cached_final = self.redis.get(session_key)
                                if cached_final and cached_final.decode('utf-8') == session_id:
                                    logger.warning(f"FlareSolverr: sessão inválida detectada, removendo do cache para {base_url} (ID: {session_id[:20]}...)")
                                    self.redis.delete(session_key)
                                    self.redis.delete(self._get_session_created_key(base_url))
                                    # Sessão removida, precisa criar nova
                                    need_to_create = True
                                else:
                                    logger.debug(f"FlareSolverr: sessão foi recriada por outro scraper para {base_url}, não removendo")
                                    # Sessão foi recriada, tentar usar a nova
                                    cached_new = self.redis.get(session_key)
                                    if cached_new:
                                        new_session_id = cached_new.decode('utf-8')
                                        if self._validate_session(new_session_id):
                                            return new_session_id
                                    need_to_create = True
                        else:
                            # Sessão foi removida/recriada, precisa criar nova
                            need_to_create = True
                else:
                    logger.debug(f"FlareSolverr: nenhuma sessão encontrada no cache para {base_url}")
                    need_to_create = True
            except Exception as e:
                logger.debug(f"FlareSolverr: erro ao obter sessão do Redis: {type(e).__name__}")
                need_to_create = True
        
        # Se não precisa criar (já encontrou sessão válida), retorna
        if not need_to_create and self.redis and not skip_redis:
            return None
        
        # Usa memória apenas se Redis não está disponível desde o início
        # IMPORTANTE: Usa cache compartilhado global (não threading.local) para permitir
        # reutilização de sessões entre threads quando Redis não está disponível
        if not self.redis or skip_redis:
            # Verifica cache compartilhado global (thread-safe)
            with _shared_sessions_lock:
                if base_url in _shared_sessions_cache:
                    session_id, expire_at = _shared_sessions_cache[base_url]
                    if time.time() < expire_at:
                        # Valida sessão antes de retornar (fora do lock para não bloquear)
                        if self._validate_session(session_id):
                            return session_id
                        else:
                            # Sessão inválida, remove do cache
                            logger.debug(f"FlareSolverr: sessão inválida no cache compartilhado, removendo para {base_url}")
                            del _shared_sessions_cache[base_url]
                    else:
                        # Expirou, remove
                        logger.debug(f"FlareSolverr: sessão expirada no cache compartilhado para {base_url}")
                        del _shared_sessions_cache[base_url]
        
        # Protege criação de sessão com lock por base_url (evita múltiplas threads criando simultaneamente)
        creation_lock = _get_session_creation_lock(base_url)
        with creation_lock:
            # Verifica novamente se outra thread já criou a sessão enquanto esperávamos o lock
            if self.redis and not skip_redis:
                try:
                    session_key = self._get_session_key(base_url)
                    cached = self.redis.get(session_key)
                    if cached:
                        session_id = cached.decode('utf-8')
                        if self._validate_session(session_id):
                            logger.debug(f"FlareSolverr: sessão já foi criada por outra thread para {base_url} (ID: {session_id[:20]}...)")
                            return session_id
                except Exception:
                    pass
        
        # Cria nova sessão (respeitando limite global)
        session_id = self._create_session(base_url, skip_redis)
        
        # Salva em cache compartilhado global se Redis não disponível
        # IMPORTANTE: Usa cache compartilhado (não threading.local) para permitir
        # reutilização de sessões entre threads
        if (not self.redis or skip_redis) and session_id:
            with _shared_sessions_lock:
                expire_at = time.time() + Config.FLARESOLVERR_SESSION_TTL
                _shared_sessions_cache[base_url] = (session_id, expire_at)
                logger.debug(f"FlareSolverr: sessão salva no cache compartilhado para {base_url} (ID: {session_id[:20]}..., expira em {Config.FLARESOLVERR_SESSION_TTL}s)")
        
        return session_id
    
    def solve(self, url: str, session_id: str, referer: str = '', base_url: str = '', skip_redis: bool = False) -> Optional[bytes]:
        try:
            payload = {
                "cmd": "request.get",
                "url": url,
                "session": session_id,
                "maxTimeout": 60000
            }
            
            # Adiciona proxy ao payload se disponível (para FlareSolverr usar ao fazer requisições aos sites)
            proxy_url = get_proxy_url()
            if proxy_url:
                payload["proxy"] = proxy_url
            
            # Usa proxy para acessar FlareSolverr apenas se o proxy NÃO for local
            # Se o proxy for local (mesma rede), não usa proxy para acessar FlareSolverr
            proxy_dict = None
            if not is_proxy_local():
                proxy_dict = get_proxy_dict()
            
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=90,
                headers={"Content-Type": "application/json"},
                proxies=proxy_dict if proxy_dict else None
            )
            
            if response.status_code == 500:
                error_detail = ""
                try:
                    error_json = response.json()
                    error_detail = error_json.get("message", "")
                except:
                    error_detail = response.text[:200] if response.text else ""
                
                # Invalida sessão apenas se o erro indicar problema específico com a sessão
                # NÃO invalida por problemas temporários do Chrome/FlareSolverr (tab crashed, chromedriver exited, etc.)
                should_invalidate = False
                is_temporary_error = False
                if base_url and error_detail:
                    error_lower = error_detail.lower()
                    # Problemas que indicam sessão inválida
                    if "session" in error_lower and ("not found" in error_lower or "invalid" in error_lower):
                        should_invalidate = True
                    # Problemas temporários do Chrome/FlareSolverr - NÃO invalidar
                    elif "tab crashed" in error_lower or "chromedriver" in error_lower or "chrome" in error_lower or "can't start new thread" in error_lower:
                        is_temporary_error = True
                        logger.debug(f"FlareSolverr: erro temporário detectado para {url[:50]}...: {error_detail[:100]}")
                        should_invalidate = False
                
                # Loga como WARNING apenas se não for erro temporário conhecido
                if not is_temporary_error:
                    logger.warning(
                        f"FlareSolverr retornou erro 500 para {url}. "
                        f"Sessão: {session_id[:20]}... Detalhes: {error_detail}"
                    )
                
                if should_invalidate:
                    self._invalidate_session(session_id, base_url, skip_redis)
                return None
            
            response.raise_for_status()
            
            result = response.json()
            if result.get("status") == "ok":
                solution = result.get("solution", {})
                html_content = solution.get("response", "")
                
                if html_content:
                    return html_content.encode('utf-8')
                else:
                    logger.warning(f"FlareSolverr retornou resposta vazia para {url[:50]}... (status=ok mas response vazio)")
                    return None
            else:
                error_msg = result.get("message", "Erro desconhecido")
                status = result.get("status", "unknown")
                logger.warning(f"FlareSolverr retornou erro para {url[:50]}...: status={status}, message={error_msg[:100]}")
                
                # Invalida sessão apenas se o erro indicar problema específico com a sessão
                # NÃO invalida por problemas temporários do Chrome/FlareSolverr
                should_invalidate = False
                if base_url and error_msg:
                    error_lower = error_msg.lower()
                    # Problemas que indicam sessão inválida
                    if "session" in error_lower and ("not found" in error_lower or "invalid" in error_lower):
                        should_invalidate = True
                    # Problemas temporários do Chrome/FlareSolverr - NÃO invalidar
                    elif "tab crashed" in error_lower or "chromedriver" in error_lower or "chrome" in error_lower:
                        logger.debug(f"FlareSolverr: erro temporário do Chrome detectado, mantendo sessão: {error_msg[:100]}")
                        should_invalidate = False
                
                if should_invalidate:
                    self._invalidate_session(session_id, base_url, skip_redis)
                
                return None
                
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout ao resolver {url} via FlareSolverr")
            return None
        except Exception as e:
            # Extrai apenas o tipo de erro e mensagem resumida
            error_type = type(e).__name__
            error_msg = str(e)
            # Resumo para erros de conexão
            if "Connection" in error_type or "Connection refused" in error_msg or "Max retries exceeded" in error_msg:
                logger.error(f"Erro ao resolver {url[:50]}... via FlareSolverr: conexão recusada ou indisponível")
            else:
                # Para outros erros, mostra apenas o tipo
                logger.error(f"Erro ao resolver {url[:50]}... via FlareSolverr: {error_type}")
            return None
    
    def _cache_session_creation_failure(self, base_url: str, skip_redis: bool = False):
        # Cacheia falha de criação de sessão para evitar tentativas muito frequentes (2 minutos)
        if self.redis and not skip_redis:
            try:
                failure_key = flaresolverr_session_creation_failure_key(base_url)
                self.redis.setex(failure_key, 120, "1")  # 2 minutos
            except Exception:
                pass
    
    def _invalidate_session(self, session_id: str, base_url: str, skip_redis: bool = False):
        # Invalida sessão (Redis primeiro, memória se Redis não disponível)
        # Protege contra race conditions quando múltiplos scrapers invalidam a mesma sessão
        global _session_validation_lock
        
        with _session_validation_lock:
            # Remove do Redis apenas se a sessão ainda for a mesma (evita remover sessão recriada)
            if self.redis and not skip_redis:
                try:
                    session_key = self._get_session_key(base_url)
                    cached = self.redis.get(session_key)
                    if cached and cached.decode('utf-8') == session_id:
                        logger.debug(f"FlareSolverr: invalidando sessão do cache para {base_url}")
                        created_key = self._get_session_created_key(base_url)
                        self.redis.delete(session_key)
                        self.redis.delete(created_key)
                    else:
                        logger.debug(f"FlareSolverr: sessão já foi recriada/invalidada por outro scraper para {base_url}")
                except Exception as e:
                    logger.debug(f"FlareSolverr: erro ao invalidar sessão no Redis: {type(e).__name__}")
                    pass
            
            # Remove do cache compartilhado global (thread-safe)
            with _shared_sessions_lock:
                if base_url in _shared_sessions_cache:
                    cached_session_id, _ = _shared_sessions_cache[base_url]
                    if cached_session_id == session_id:
                        _shared_sessions_cache.pop(base_url, None)
                        logger.debug(f"FlareSolverr: sessão removida do cache compartilhado para {base_url}")
        
        # Decrementa contador de sessões ativas
        self._decrement_session_count()
    
    def destroy_session(self, session_id: str, base_url: str):
        # Destrói sessão FlareSolverr
        try:
            payload = {
                "cmd": "sessions.destroy",
                "session": session_id
            }
            
            # Usa proxy para acessar FlareSolverr apenas se o proxy NÃO for local
            proxy_dict = None
            if not is_proxy_local():
                proxy_dict = get_proxy_dict()
            requests.post(
                self.api_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
                proxies=proxy_dict if proxy_dict else None
            )
        except Exception:
            pass  # Ignora erros ao destruir
        
        # Remove do cache (Redis e memória)
        self._invalidate_session(session_id, base_url, skip_redis=False)

