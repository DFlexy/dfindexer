"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import time
import uuid
from typing import Optional
import requests
from cache.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# TTL padrão para sessões FlareSolverr (30 minutos)
SESSION_TTL = 30 * 60  # 1800 segundos


# Cliente para comunicação com FlareSolverr com gerenciamento de sessões
class FlareSolverrClient:
    # Inicializa cliente FlareSolverr
    def __init__(self, address: str):
        self.address = address.rstrip('/')
        self.api_url = f"{self.address}/v1"
        self.redis = get_redis_client()
        self._session_cache = {}  # Cache em memória por base_url
    
    # Gera chave Redis para sessão baseada no base_url
    def _get_session_key(self, base_url: str) -> str:
        # Normaliza base_url para usar como identificador único
        normalized = base_url.rstrip('/').replace('https://', '').replace('http://', '')
        return f"flaresolverr:session:{normalized}"
    
    # Gera chave Redis para timestamp de criação da sessão
    def _get_session_created_key(self, base_url: str) -> str:
        normalized = base_url.rstrip('/').replace('https://', '').replace('http://', '')
        return f"flaresolverr:session:created:{normalized}"
    
    # Cria nova sessão no FlareSolverr - retorna session_id ou None em caso de erro
    def _create_session(self, base_url: str, skip_redis: bool = False) -> Optional[str]:
        try:
            # Gera ID único para a sessão baseado no base_url
            session_id = f"dfindexer_{uuid.uuid4().hex[:12]}"
            
            payload = {
                "cmd": "sessions.create",
                "session": session_id
            }
            
            # Timeout maior para criação de sessão (FlareSolverr pode demorar até 120s para iniciar Chrome)
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=150,  # 150 segundos para dar margem ao FlareSolverr iniciar Chrome
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get("status") == "ok":
                created_session_id = result.get("session")
                if created_session_id:
                    # Salva no Redis (se não for teste)
                    session_key = self._get_session_key(base_url)
                    created_key = self._get_session_created_key(base_url)
                    
                    if self.redis and not skip_redis:
                        try:
                            self.redis.setex(session_key, SESSION_TTL, created_session_id)
                            self.redis.setex(created_key, SESSION_TTL, str(int(time.time())))
                        except Exception:
                            pass  # Ignora erros de Redis
                    
                    # Salva em cache em memória
                    self._session_cache[base_url] = created_session_id
                    
                    logger.debug(f"Sessão FlareSolverr criada: {created_session_id} para {base_url}")
                    return created_session_id
            
            logger.warning(f"Falha ao criar sessão FlareSolverr: {result}")
            return None
            
        except requests.exceptions.Timeout:
            logger.warning(
                f"Timeout ao criar sessão FlareSolverr (FlareSolverr pode estar demorando para iniciar Chrome). "
                f"Tente novamente em alguns segundos."
            )
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
                logger.error(f"Erro ao criar sessão FlareSolverr: {e}")
            return None
    
    # Valida se uma sessão ainda existe no FlareSolverr - retorna True se existe, False caso contrário
    def _validate_session(self, session_id: str) -> bool:
        try:
            payload = {
                "cmd": "sessions.list"
            }
            
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            result = response.json()
            sessions = result.get("sessions", [])
            return session_id in sessions
            
        except Exception:
            # Em caso de erro, assume que sessão pode estar válida
            # Deixa o FlareSolverr retornar erro na requisição se inválida
            return True
    
    # Obtém sessão existente ou cria nova para o base_url - retorna session_id ou None em caso de erro
    def get_or_create_session(self, base_url: str, skip_redis: bool = False) -> Optional[str]:
        # 1. Verifica cache em memória primeiro
        if base_url in self._session_cache:
            session_id = self._session_cache[base_url]
            # Valida sessão antes de retornar
            if self._validate_session(session_id):
                return session_id
            else:
                # Sessão inválida, remove do cache
                del self._session_cache[base_url]
        
        # 2. Tenta obter do Redis (se não for teste)
        session_key = self._get_session_key(base_url)
        session_id = None
        
        if self.redis and not skip_redis:
            try:
                cached = self.redis.get(session_key)
                if cached:
                    session_id = cached.decode('utf-8')
                    # Valida se sessão ainda existe no FlareSolverr
                    if self._validate_session(session_id):
                        # Salva em cache em memória
                        self._session_cache[base_url] = session_id
                        logger.debug(f"Sessão FlareSolverr reutilizada: {session_id} para {base_url}")
                        return session_id
                    else:
                        # Sessão inválida, remove do Redis
                        self.redis.delete(session_key)
                        self.redis.delete(self._get_session_created_key(base_url))
            except Exception:
                pass  # Ignora erros de Redis
        
        # 3. Cria nova sessão
        session_id = self._create_session(base_url, skip_redis)
        return session_id
    
    # Faz requisição via FlareSolverr usando sessão existente - retorna conteúdo HTML em bytes ou None em caso de erro
    def solve(self, url: str, session_id: str, referer: str = '', base_url: str = '', skip_redis: bool = False) -> Optional[bytes]:
        try:
            payload = {
                "cmd": "request.get",
                "url": url,
                "session": session_id,
                "maxTimeout": 60000
            }
            
            # Nota: FlareSolverr v2 não suporta mais o parâmetro 'headers'
            # O referer não é mais necessário, o FlareSolverr gerencia isso automaticamente
            
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=90,  # Timeout maior para FlareSolverr
                headers={"Content-Type": "application/json"}
            )
            
            # Trata erros HTTP 500 (Internal Server Error)
            if response.status_code == 500:
                error_detail = ""
                try:
                    error_json = response.json()
                    error_detail = error_json.get("message", "")
                except:
                    error_detail = response.text[:200] if response.text else ""
                
                logger.warning(
                    f"FlareSolverr retornou erro 500 para {url}. "
                    f"Sessão: {session_id}. Detalhes: {error_detail}"
                )
                # Invalida a sessão para forçar recriação na próxima tentativa
                if base_url:
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
                    logger.warning(f"FlareSolverr retornou resposta vazia para {url}")
                    return None
            else:
                error_msg = result.get("message", "Erro desconhecido")
                logger.warning(f"FlareSolverr retornou erro para {url}: {error_msg}")
                
                # Se erro for de sessão inválida ou erro 500, remove do cache
                if "session" in error_msg.lower() or "not found" in error_msg.lower() or "500" in error_msg:
                    self._invalidate_session(session_id, base_url, skip_redis)
                
                return None
                
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout ao resolver {url} via FlareSolverr")
            return None
        except Exception as e:
            logger.error(f"Erro ao resolver {url} via FlareSolverr: {e}")
            return None
    
    # Invalida uma sessão removendo-a do cache (sem destruir no FlareSolverr)
    def _invalidate_session(self, session_id: str, base_url: str, skip_redis: bool = False):
        # Remove do cache em memória
        if base_url in self._session_cache:
            del self._session_cache[base_url]
        
        # Remove do Redis (se não for teste)
        session_key = self._get_session_key(base_url)
        created_key = self._get_session_created_key(base_url)
        
        if self.redis and not skip_redis:
            try:
                self.redis.delete(session_key)
                self.redis.delete(created_key)
            except Exception:
                pass
    
    # Destrói sessão no FlareSolverr e remove do cache
    def destroy_session(self, session_id: str, base_url: str):
        try:
            payload = {
                "cmd": "sessions.destroy",
                "session": session_id
            }
            
            requests.post(
                self.api_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"}
            )
        except Exception:
            pass  # Ignora erros ao destruir
        
        # Remove do cache
        if base_url in self._session_cache:
            del self._session_cache[base_url]
        
        session_key = self._get_session_key(base_url)
        created_key = self._get_session_created_key(base_url)
        
        if self.redis:
            try:
                self.redis.delete(session_key)
                self.redis.delete(created_key)
            except Exception:
                pass

