"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
from typing import Optional
from urllib.parse import unquote

from utils.text.cleaning import clean_title, remove_accents
from utils.text.storage import get_metadata_name
from utils.text.title_helpers import (
    _extract_base_title_from_release,
    _split_technical_components,
    _extract_technical_info,
    _clean_remaining,
    _ensure_default_format,
    _apply_season_temporada_tags,
    _reorder_title_components,
)


# Normaliza metadata name para formato padronizado (remove tags, normaliza espaços, remove duplicações)
def _normalize_metadata_name(metadata_name: str) -> str:
    """Normaliza metadata['name'] para formato padronizado antes de salvar no cross_data"""
    normalized = metadata_name.strip()
    normalized = html.unescape(normalized)
    try:
        normalized = unquote(normalized)
    except Exception:
        pass
    normalized = normalized.strip()
    normalized = clean_title(normalized)
    normalized = re.sub(r'\[[^\]]*\]', '', normalized)
    normalized = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), normalized)
    temp_normalized = re.sub(r'\s+', '.', normalized.strip())
    temp_normalized = re.sub(r'\.{2,}', '.', temp_normalized)
    parts = temp_normalized.split('.')
    cleaned_parts = []
    prev_part = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_lower = part.lower()
        prev_lower = prev_part.lower() if prev_part else None
        if part_lower != prev_lower:
            cleaned_parts.append(part)
            prev_part = part
    return '.'.join(cleaned_parts).strip('.')


# Prepara magnet_processed: normaliza se válido, busca metadata se missing_dn=True, adiciona ano/WEB-DL se necessário
def prepare_release_title(
    magnet_processed: str,
    fallback_title: str,
    year: str = '',
    missing_dn: bool = False,
    info_hash: Optional[str] = None,
    skip_metadata: bool = False
) -> str:
    fallback_title = (fallback_title or '').strip()
    original_release_title = None
    final_missing_dn = missing_dn  # Mantém o estado original de missing_dn

    # ETAPA 1: magnet_processed está vazio ou muito curto (< 3 caracteres)?
    magnet_processed = (magnet_processed or '').strip()
    
    if magnet_processed and len(magnet_processed) >= 3:
        # SIM: magnet_processed existe e tem >= 3 caracteres
        # Normalizar (unescape, unquote, remover duplicações) e usar diretamente
        normalized = magnet_processed
        normalized = html.unescape(normalized)
        try:
            normalized = unquote(normalized)
        except Exception:
            pass
        normalized = normalized.strip()
        
        # Remove domínios e tags comuns (incluindo HIDRATORRENTS.ORG)
        from utils.text.cleaning import clean_title
        normalized = clean_title(normalized)
        
        # Remove tags entre colchetes (ex: [EA], [rich_jc], etc.)
        normalized = re.sub(r'\[[^\]]*\]', '', normalized)
        
        # Remove parênteses mas preserva o conteúdo dentro deles (normaliza espaços para pontos)
        # Ex: "(BDRip 1080p x264)" -> "BDRip.1080p.x264"
        normalized = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), normalized)
        
        # Remove duplicações consecutivas do magnet_processed
        # Ex: "S01E04.S01E04.2025..." -> "S01E04.2025..."
        # Normaliza espaços para pontos para facilitar detecção de duplicações
        temp_normalized = re.sub(r'\s+', '.', normalized.strip())
        temp_normalized = re.sub(r'\.{2,}', '.', temp_normalized)
        
        parts = temp_normalized.split('.')
        combined_parts = []
        for part in parts:
            clean_part = part.strip()
            if clean_part:
                combined_parts.append(clean_part)
        
        # Remove duplicações consecutivas de qualquer parte
        cleaned_parts = []
        prev_part = None
        for part in combined_parts:
            part = part.strip()
            if not part:
                continue
            # Compara ignorando case e normalizando
            part_lower = part.lower()
            prev_lower = prev_part.lower() if prev_part else None
            # Só adiciona se não for duplicação consecutiva
            if part_lower != prev_lower:
                cleaned_parts.append(part)
                prev_part = part
        
        original_release_title = '.'.join(cleaned_parts).strip('.')
        # IMPORTANTE: Como magnet_processed existe e tem >= 3 caracteres, missing_dn = False
        final_missing_dn = False
        # Preserva pontos - create_standardized_title precisa deles para parsing
        # → Ir direto para etapa 5 (adicionar ano se necessário)
    else:
        # NÃO: magnet_processed está vazio ou muito curto
        if missing_dn:
            # missing_dn = True: buscar metadata, depois fallback
            if info_hash:
                # Busca metadata do iTorrents.org usando info_hash
                if not skip_metadata:
                    metadata_name = get_metadata_name(info_hash, skip_metadata=skip_metadata)
                    if metadata_name and len(metadata_name.strip()) >= 3:
                        # Metadata encontrado: normaliza e usa como original_release_title
                        # IMPORTANTE: Preserva FULLHD do metadata
                        original_release_title = _normalize_metadata_name(metadata_name)
                        final_missing_dn = False  # Encontrou metadata, não está mais missing
                        # → Ir para etapa 5
                    else:
                        # Metadata não encontrado: usa fallback_title
                        original_release_title = fallback_title
                        final_missing_dn = True  # Continua missing
                        # → Ir para etapa 5
                else:
                    # skip_metadata = True: pula metadata, usa fallback
                    original_release_title = fallback_title
                    final_missing_dn = True  # Continua missing
                    # → Ir para etapa 5
            else:
                # Sem info_hash: usa fallback_title
                original_release_title = fallback_title
                final_missing_dn = True  # Continua missing
                # → Ir para etapa 5
        else:
            # missing_dn = False: usa fallback_title diretamente
            original_release_title = fallback_title
            final_missing_dn = False  # Não está missing, apenas usando fallback
            # → Ir para etapa 5

    # Garante que original_release_title não está vazio
    if not original_release_title or len(original_release_title.strip()) < 3:
        original_release_title = fallback_title
        final_missing_dn = True

    # Normaliza espaços múltiplos, mas preserva pontos
    if '.' in original_release_title:
        # Tem pontos - normaliza apenas espaços múltiplos entre palavras (não entre pontos)
        original_release_title = re.sub(r'\s+', ' ', original_release_title)
        # Remove espaços ao redor de pontos
        original_release_title = re.sub(r'\s*\.\s*', '.', original_release_title)
    else:
        # Não tem pontos - normaliza espaços
        original_release_title = re.sub(r'\s+', ' ', original_release_title).strip()

    # ETAPA 5: O ano (year) foi fornecido e NÃO está no título?
    if year:
        year_str = str(year)
        if year_str and year_str not in original_release_title:
            # Adiciona ano ao final
            if '.' in original_release_title:
                original_release_title = f"{original_release_title}.{year_str}".strip()
            else:
                original_release_title = f"{original_release_title} {year_str}".strip()
        else:
            pass

    # ETAPA 6: missing_dn = True após todo processamento?
    if final_missing_dn and original_release_title and 'web-dl' not in original_release_title.lower():
        # Adiciona WEB-DL ao final
        if '.' in original_release_title:
            original_release_title = f"{original_release_title}.WEB-DL".strip()
        else:
            original_release_title = f"{original_release_title} WEB-DL".strip()
    else:
        pass

    result = original_release_title.strip()
    return result


# Constrói o título padronizado final (Title.SxxEyy.Year….)
def create_standardized_title(title_original_html: str, year: str, magnet_processed: str, title_translated_html: Optional[str] = None, magnet_original: Optional[str] = None) -> str:
    
    def finalize_title(value: str) -> str:
        # Usa magnet_original se disponível (preserva informação original como "1ª Temporada")
        # Senão usa magnet_processed (já processado)
        release_for_season_detection = magnet_original if magnet_original else magnet_processed
        value = _apply_season_temporada_tags(value, release_for_season_detection, title_original_html, year)
        value = _reorder_title_components(value)
        return _ensure_default_format(value)
    # Determina base_title seguindo fallback
    base_title = ''
    
    # Verifica se tem título original válido
    if title_original_html and title_original_html.strip():
        # Verifica se tem caracteres não-latinos (Russo, Chinês, Coreano, Japonês, Tailandês, Hindi/Devanagari/Bengali, Árabe, Hebreu, Grego, Telugu, Tamil, Kannada, Malayalam, Gujarati, Oriya)
        has_non_latin = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f\u0900-\u09ff\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff\u0c00-\u0c7f\u0b80-\u0bff\u0c80-\u0cff\u0d00-\u0d7f\u0a80-\u0aff\u0b00-\u0b7f]', title_original_html))
        
        if not has_non_latin:
            # Título Original da página: Como base principal (apenas o nome, sem SxxExx, ano, etc.)
            base_title = clean_title(title_original_html)
            base_title = remove_accents(base_title)
            # Remove informações de temporada/ano do título da página
            # IMPORTANTE: Só remove se for claramente temporada (S01, S1, S01E01) ou ano no final
            # NÃO remove números que fazem parte do título (ex: "Fantastic 4", "Ocean's 11")
            base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)  # Remove SxxExx se houver
            base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)  # Remove ano no final
            base_title = base_title.replace(' ', '.').replace('-', '.').replace('/', '.')  # Converte espaços, hífens e barras para pontos
            base_title = re.sub(r'[^\w\.]', '', base_title)  # Remove tudo exceto letras, números e pontos
            base_title = base_title.strip('.')
            # Capitaliza cada palavra após pontos (preserva capitalização correta: Fate.Stay.Night)
            base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))
            
            # Continua processando magnet_processed para extrair SxxExx, ano e informações técnicas
            # Não retorna direto, sempre processa o magnet_processed
        else:
            # Fallback1: Title Não-latinos Ex:Russo/Koreano
            # Verifica se magnet_processed (raw) também tem caracteres não-latinos
            # Usa magnet_original se disponível, senão usa magnet_processed
            raw_to_check = magnet_original if magnet_original else magnet_processed
            release_has_non_latin = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f\u0900-\u09ff\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff\u0c00-\u0c7f\u0b80-\u0bff\u0c80-\u0cff\u0d00-\u0d7f\u0a80-\u0aff\u0b00-\u0b7f]', raw_to_check or ''))
            
            # Se title_translated_html existe, usa ele (é preferível ao magnet_processed quando original tem não-latinos)
            if title_translated_html and title_translated_html.strip():
                # Fallback1.1: Título Traduzido da página quando title_original_html tem não-latinos
                # Usa title_translated_html mesmo se magnet_processed não tem não-latinos
                base_title = clean_title(title_translated_html)
                base_title = remove_accents(base_title)
                # Remove informações de temporada/ano do título traduzido (apenas o nome base)
                base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)  # Remove SxxExx se houver
                base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)  # Remove ano no final
                base_title = base_title.replace(' ', '.').replace('-', '.').replace('/', '.')  # Converte espaços, hífens e barras para pontos
                base_title = re.sub(r'[^\w\.]', '', base_title)  # Remove tudo exceto letras, números e pontos
                base_title = base_title.strip('.')
                # Capitaliza cada palavra após pontos (preserva capitalização correta: Fate.Stay.Night)
                base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))
                # Continua processando magnet_processed para extrair SxxExx, ano e informações técnicas
            else:
                # Fallback1: Usar title do magnet (magnet_processed) - extrai apenas o nome base
                base_title = _extract_base_title_from_release(magnet_processed)
                # Continua processando magnet_processed para extrair SxxExx, ano e informações técnicas
    else:
        # Fallback2: Nome do magnet se página não tem título válido
        base_title = _extract_base_title_from_release(magnet_processed)
        result = finalize_title(base_title)
        return result
    
    # Processa magnet_processed para extrair apenas informações técnicas (SxxExx, Sx, ano, qualidade, codec, etc.)
    # IMPORTANTE: Se magnet_original está disponível e tem pontos, usa ele diretamente
    # Isso preserva a estrutura original do título do magnet/Redis
    # Prefere magnet_original quando disponível porque preserva a estrutura original
    if magnet_original and magnet_original.strip():
        # Usa magnet_original se disponível (vem do magnet/Redis com estrutura preservada)
        clean_release = clean_title(magnet_original)
    elif magnet_processed and magnet_processed.strip():
        # Usa magnet_processed (resultado de prepare_release_title) como fallback
        clean_release = clean_title(magnet_processed)
    else:
        # Se ambos estão vazios, retorna apenas base_title
        result = finalize_title(base_title)
        return result
    clean_release = remove_accents(clean_release)
    
    # Remove tags entre colchetes (ex: [EA], [rich_jc], etc.)
    clean_release = re.sub(r'\[[^\]]*\]', '', clean_release)
    
    # Remove parênteses mas preserva o conteúdo dentro deles (normaliza espaços para pontos)
    # Ex: "(BDRip 1080p x264)" -> "BDRip.1080p.x264"
    clean_release = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), clean_release)
    
    # Remove o base_title do clean_release antes de processar (evita duplicação)
    # Normaliza ambos removendo pontos e espaços para comparação
    base_title_normalized = re.sub(r'[\.\s]', '', base_title).lower()
    clean_release_normalized = re.sub(r'[\.\s]', '', clean_release).lower()
    
    # Se o base_title está no início do clean_release, remove
    if clean_release_normalized.startswith(base_title_normalized):
        # Encontra onde o base_title termina no clean_release original (considerando pontos)
        # Procura o padrão do base_title no início do clean_release, aceitando pontos opcionais
        base_no_dots = base_title.replace('.', '')
        # Cria padrão que aceita pontos opcionais entre letras do base_title
        # Ex: "One Punch-Man" pode corresponder a "One.Punch.Man" ou "OnePunchMan"
        if len(base_no_dots) > 0:
            base_pattern = re.escape(base_no_dots[0])  # Primeira letra (obrigatória)
            for char in base_no_dots[1:]:
                base_pattern += rf'\.?{re.escape(char)}'  # Letras seguintes com ponto opcional
            
            # Remove base_title do início (seguido de ponto, SxxExx, número, ou fim)
            # Também remove se estiver colado a SxxExx ou números (ex: "OnePunchManS03E01")
            # IMPORTANTE: Remove o base_title e qualquer ponto que o segue, mas preserva o que vem depois
            # Ex: "One.Punch.Man.S03E01" -> "S03E01"
            # Ex: "OnePunchManS03E01" -> "S03E01"
            # Ex: "Paradise.2025.S01E01" -> "2025.S01E01" (preserva o ano)
            # Remove base_title seguido de ponto (ou colado a SxxExx/números)
            # Mas preserva o que vem depois do ponto
            match = re.match(rf'^{base_pattern}(\.)', clean_release, flags=re.IGNORECASE)
            if match:
                # Remove base_title e o ponto que o segue
                clean_release = clean_release[match.end():]
            else:
                # Tenta remover se estiver colado (sem ponto)
                clean_release = re.sub(rf'^{base_pattern}(?=S\d|(?<!\d)\d)', '', clean_release, flags=re.IGNORECASE)
        
        # Limpa pontos duplicados que podem ter ficado
        clean_release = re.sub(r'^\.+', '', clean_release)
    
    # Remove duplicações consecutivas do clean_release antes de processar
    # Ex: "S01E04.S01E04.2025..." -> "S01E04.2025..."
    # Normaliza espaços para pontos para facilitar detecção de duplicações
    temp_clean = re.sub(r'\s+', '.', clean_release.strip())
    temp_clean = re.sub(r'\.{2,}', '.', temp_clean)
    
    # Remove duplicações consecutivas de qualquer parte
    parts = temp_clean.split('.')
    cleaned_parts = []
    prev_part = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Compara ignorando case e normalizando
        part_lower = part.lower()
        prev_lower = prev_part.lower() if prev_part else None
        # Só adiciona se não for duplicação consecutiva
        if part_lower != prev_lower:
            cleaned_parts.append(part)
            prev_part = part
    
    clean_release = '.'.join(cleaned_parts).strip('.')
    
    # EPISÓDIOS MÚLTIPLOS: Formato Sonarr compatível - detecta antes de normalizar espaços
    # Regex para detectar múltiplos episódios: S02E01-02-03, S02E01-02, S02E01.02.03, etc.
    # Padrão Sonarr:
    # - 2 episódios: S02E01-02 (hífen)
    # - 3+ episódios: S02E01E02E03 (E repetido - lista explícita) ou S02E01-E05 (intervalo)
    # Busca padrão completo: S02E01-02-03 ou S02E01.02.03
    # Usa lookahead negativo para garantir que não capture ano (2025)
    season_ep_multi_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:\s*[\.\-]\s*\d{1,2}){1,}(?![0-9])', clean_release)
    
    if not season_ep_multi_match:
        # Tenta padrão alternativo sem espaços
        alt_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:[\.\-]\d{1,2}){1,}(?![0-9])', clean_release)
        if alt_match:
            season_ep_multi_match = alt_match
    
    if season_ep_multi_match:
        season = season_ep_multi_match.group(1).zfill(2)
        episode1 = int(season_ep_multi_match.group(2))
        
        # Extrai todos os episódios do match completo
        full_match = season_ep_multi_match.group(0)
        episodes = [episode1]
        
        # Extrai todos os números após o primeiro episódio (E01)
        # Busca por padrão: -02, -03, .02, .03, etc. (sem espaços após normalização)
        episode_numbers = re.findall(r'[\.\-]\s*(\d{1,2})', full_match)
        
        for ep_str in episode_numbers:
            ep_num = int(ep_str)
            # Validação: cada episódio deve ser maior que o anterior, <= 99, e diferença <= 20
            from app.config import Config
            if ep_num > episodes[-1] and ep_num <= Config.MAX_EPISODE_NUMBER and (ep_num - episodes[-1]) <= Config.MAX_EPISODE_DIFF:
                episodes.append(ep_num)
            else:
                break  # Para se encontrar número inválido
        
        # Se tem pelo menos 2 episódios válidos, formata como múltiplos
        if len(episodes) >= 2:
            # Novo padrão Sonarr:
            # - 2 episódios: S02E01-02 (mantém hífen)
            # - 3-4 episódios: S02E01E02E03 (E repetido - lista explícita)
            # - 5+ episódios: S02E01-E05 (intervalo - primeiro-último)
            if len(episodes) == 2:
                # Duplos: mantém formato com hífen
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            elif len(episodes) >= 5:
                # 5+ episódios: usa formato de intervalo (primeiro-último)
                first_ep = str(episodes[0]).zfill(2)
                last_ep = str(episodes[-1]).zfill(2)
                season_ep_str = f"S{season}E{first_ep}-E{last_ep}"
            elif len(episodes) >= 3:
                # 3-4 episódios: usa E repetido para lista explícita
                episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            else:
                # Fallback (não deveria acontecer)
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            
            # Extrai o ano que pode estar antes do SxxExx
            year_from_release = None
            text_before_season = clean_release[:season_ep_multi_match.start()]
            if text_before_season:
                year_match = re.search(r'(19|20)\d{2}', text_before_season)
                if year_match:
                    year_from_release = year_match.group(0)
            
            # Normaliza espaços para pontos no restante (após SxxExxExx...)
            original_magnet_text = clean_release[season_ep_multi_match.end():]
            original_magnet_text = re.sub(r'\s+', '.', original_magnet_text)
            original_magnet_text = re.sub(r'\.{2,}', '.', original_magnet_text)
            original_magnet_text = original_magnet_text.strip('.')
            # Separa componentes colados antes de extrair informações técnicas
            original_magnet_text = _split_technical_components(original_magnet_text)
            
            processed_magnet_text = _extract_technical_info(original_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            
            # Monta o título: base_title + season_ep + ano (se encontrado) + informações técnicas
            # Ordem correta: Título.SxxExx.Ano.Qualidade.Codec
            if year_from_release:
                result = finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
            else:
                result = finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
            
            return result
    
    # Normaliza espaços para pontos para facilitar processamento
    clean_release = re.sub(r'\s+', '.', clean_release)
    clean_release = re.sub(r'\.{2,}', '.', clean_release)
    clean_release = clean_release.strip('.')
    
    # IMPORTANTE: NÃO chama _split_technical_components aqui porque quebra S01E01 em S01E.01
    # _split_technical_components só deve ser chamada no texto APÓS S01E01, não no clean_release completo
    
    # EPISÓDIOS MÚLTIPLOS: detecta após normalizar também
    # Regex para detectar múltiplos episódios após normalização
    season_ep_multi_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:[\.\-]\d{1,2}){1,}(?![0-9])', clean_release)
    
    if season_ep_multi_match:
        season = season_ep_multi_match.group(1).zfill(2)
        episode1 = int(season_ep_multi_match.group(2))
        
        # Extrai todos os episódios do match completo
        full_match = season_ep_multi_match.group(0)
        episodes = [episode1]
        
        # Extrai todos os números após o primeiro episódio (E01)
        # Busca por padrão: -02, -03, .02, .03, etc.
        episode_numbers = re.findall(r'[\.\-](\d{1,2})', full_match)
        for ep_str in episode_numbers:
            ep_num = int(ep_str)
            # Validação: cada episódio deve ser maior que o anterior, <= 99, e diferença <= 20
            from app.config import Config
            if ep_num > episodes[-1] and ep_num <= Config.MAX_EPISODE_NUMBER and (ep_num - episodes[-1]) <= Config.MAX_EPISODE_DIFF:
                episodes.append(ep_num)
            else:
                break  # Para se encontrar número inválido
        
        # Se tem pelo menos 2 episódios válidos, formata como múltiplos
        if len(episodes) >= 2:
            # Novo padrão Sonarr:
            # - 2 episódios: S02E01-02 (mantém hífen)
            # - 3-4 episódios: S02E01E02E03 (E repetido - lista explícita)
            # - 5+ episódios: S02E01-E05 (intervalo - primeiro-último)
            if len(episodes) == 2:
                # Duplos: mantém formato com hífen
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            elif len(episodes) >= 5:
                # 5+ episódios: usa formato de intervalo (primeiro-último)
                first_ep = str(episodes[0]).zfill(2)
                last_ep = str(episodes[-1]).zfill(2)
                season_ep_str = f"S{season}E{first_ep}-E{last_ep}"
            elif len(episodes) >= 3:
                # 3-4 episódios: usa E repetido para lista explícita
                episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            else:
                # Fallback (não deveria acontecer)
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            
            # Extrai o ano que pode estar antes do SxxExx
            year_from_release = None
            text_before_season = clean_release[:season_ep_multi_match.start()]
            if text_before_season:
                year_match = re.search(r'(19|20)\d{2}', text_before_season)
                if year_match:
                    year_from_release = year_match.group(0)
            
            # Extrai apenas informações técnicas do restante (após SxxExxExx...)
            original_magnet_text = clean_release[season_ep_multi_match.end():]
            # Separa componentes colados antes de extrair informações técnicas
            original_magnet_text = _split_technical_components(original_magnet_text)
            processed_magnet_text = _extract_technical_info(original_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            
            # Monta o título: base_title + season_ep + ano (se encontrado) + informações técnicas
            # Ordem correta: Título.SxxExx.Ano.Qualidade.Codec
            if year_from_release:
                result = finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
            else:
                result = finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
            
            return result
    
    # EPISÓDIOS: Title.S02E01.restodomagnet (2 dígitos) - detecta ANTES de filtrar
    season_ep_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})', clean_release)
    
    if season_ep_match:
        season = season_ep_match.group(1).zfill(2)  # 2 dígitos
        episode = season_ep_match.group(2).zfill(2)  # 2 dígitos
        season_ep_str = f"S{season}E{episode}"
        
        # Extrai o ano que pode estar antes do SxxExx
        year_from_release = None
        text_before_season = clean_release[:season_ep_match.start()]
        if text_before_season:
            year_match = re.search(r'(19|20)\d{2}', text_before_season)
            if year_match:
                year_from_release = year_match.group(0)
        
        # Extrai apenas informações técnicas do restante (após SxxExx)
        original_magnet_text = clean_release[season_ep_match.end():]
        # Separa componentes colados antes de extrair informações técnicas
        original_magnet_text = _split_technical_components(original_magnet_text)
        processed_magnet_text = _extract_technical_info(original_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        
        # Monta o título: base_title + season_ep + ano (se encontrado) + informações técnicas
        # Ordem correta: Título.SxxExx.Ano.Qualidade.Codec
        if year_from_release:
            return finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
        else:
            return finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")
    
    # Extrai apenas informações técnicas do magnet_processed, removendo qualquer título
    # Padrões técnicos: Sx, anos, qualidades, codecs, etc.
    
    technical_parts = []
    parts = clean_release.split('.')
    
    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue
        
        # Mantém apenas:
        # - Padrões de temporada: S01 (sem E)
        if re.match(r'^S\d{1,2}$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Anos: 2025, 2024, etc.
        elif re.match(r'^(19|20)\d{2}$', part_clean):
            technical_parts.append(part_clean)
        # - Qualidades: 1080p, 720p, 2160p, 4K, HD, FHD, UHD, FULLHD, etc.
        elif re.match(r'^(1080p|720p|480p|2160p|4K|HD|FHD|UHD|SD|HDR|FULLHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Codecs: x264, x265, H.264, H.265, etc.
        elif re.match(r'^(x264|x265|H\.264|H\.265|AVC|HEVC)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Fontes: WEB-DL, WEBRip, BluRay, DVDRip, HDRip, HDTV, BDRip, BRRip, etc.
        elif re.match(r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Áudio: DUAL, DUBLADO, DDP5.1, Atmos, AC3, AAC, etc.
        elif re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Outros técnicos: HDR, 5.1, 2.0, etc.
        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Formatos: MKV, MP4, AVI, etc.
        elif re.match(r'^(MKV|MP4|AVI|MPEG|MOV)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Padrões com hífen: 5.1-SF, etc. (número.ponto.número-hífen-letras/números)
        elif re.match(r'^\d+\.\d+-[A-Z0-9]+$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        # - Release groups: -SF, -RARBG, etc. (começam com -)
        elif re.match(r'^-[A-Z0-9]+$', part_clean):
            technical_parts.append(part_clean)
        # - Números seguidos de GB/MB (tamanhos)
        elif re.match(r'^\d+\.?\d*\s*(GB|MB)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
    
    clean_release = '.'.join(technical_parts)
    
    # SÉRIES COMPLETAS: Title.S2.2022.restodomagnet (1 dígito para temporada)
    # IMPORTANTE: Não faz match se houver E seguido de dígitos logo depois (ex: S01E01)
    season_only_match = re.search(r'(?i)S(\d{1,2})(?![E\d])(?:[^E]|$)', clean_release)
    if season_only_match:
        season_num_raw = season_only_match.group(1)
        # IMPORTANTE: Valida que o número da temporada é válido (maior que 0)
        # Evita gerar S00 incorretamente
        try:
            season_num = int(season_num_raw)
            if season_num <= 0:
                # Número inválido, não processa como temporada
                season_only_match = None
            else:
                season = season_num_raw.zfill(2)
                season_str = f"S{season}"
        except (ValueError, TypeError):
            # Não é um número válido, não processa como temporada
            season_only_match = None
    
    if season_only_match:
        
        # Procura ano no release ou usa year do parâmetro
        year_from_release = year
        if not year_from_release:
            year_match = re.search(r'(19|20)\d{2}', clean_release)
            if year_match:
                year_from_release = year_match.group(0)
        
        if year_from_release:
            processed_magnet_text = clean_release[season_only_match.end():]
            # Remove ano do processed_magnet_text se já foi usado
            processed_magnet_text = re.sub(r'(19|20)\d{2}', '', processed_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            return finalize_title(f"{base_title}.{season_str}.{year_from_release}{processed_magnet_text}")
        else:
            # Sem ano, apenas Sx
            processed_magnet_text = clean_release[season_only_match.end():]
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            return finalize_title(f"{base_title}.{season_str}{processed_magnet_text}")
    
    # FILMES: Title.2022.restodomagnet
    year_from_release = year
    if not year_from_release:
        year_match = re.search(r'(19|20)\d{2}', clean_release)
        if year_match:
            year_from_release = year_match.group(0)
    
    if year_from_release:
        # Remove ano do clean_release para pegar o resto (informações técnicas)
        processed_magnet_text = re.sub(r'(19|20)\d{2}', '', clean_release)
        # Separa componentes colados antes de extrair informações técnicas
        processed_magnet_text = _split_technical_components(processed_magnet_text)
        processed_magnet_text = _extract_technical_info(processed_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        return finalize_title(f"{base_title}.{year_from_release}{processed_magnet_text}")
    
    # Sem ano nem temporada, retorna apenas base_title com informações técnicas se houver
    if clean_release:
        # Separa componentes colados antes de extrair informações técnicas
        processed_magnet_text = _split_technical_components(clean_release)
        processed_magnet_text = _extract_technical_info(processed_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        return finalize_title(f"{base_title}{processed_magnet_text}")
    
    return finalize_title(base_title)

