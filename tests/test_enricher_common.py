from datetime import datetime

from core.enrichers.enricher_common import (
    apply_date_fallback,
    extract_base_title_for_imdb,
    parse_cross_data,
    build_tracker_log_id,
)


class TestExtractBaseTitleForImdb:
    def test_remove_tags_tecnicas(self):
        result = extract_base_title_for_imdb('Inception.2010.WEB-DL.1080p.x264.DUAL')
        assert 'web-dl' not in result
        assert '1080p' not in result
        assert 'x264' not in result
        assert 'inception' in result

    def test_remove_marcadores_de_idioma(self):
        result = extract_base_title_for_imdb('Filme.2024.1080p [Brazilian]')
        assert 'brazilian' not in result

    def test_titulo_curto_retorna_none(self):
        assert extract_base_title_for_imdb('ab') is None
        assert extract_base_title_for_imdb('') is None
        assert extract_base_title_for_imdb(None) is None

    def test_lowercase_e_sem_acentos(self):
        result = extract_base_title_for_imdb('A Casa do Dragão')
        assert result == result.lower()
        assert 'ã' not in result


class TestApplyDateFallback:
    def test_data_existente_preservada(self):
        torrent = {'date': '2024-01-01T00:00:00Z'}
        apply_date_fallback([torrent])
        assert torrent['date'] == '2024-01-01T00:00:00Z'

    def test_data_da_metadata_usada(self):
        ts = int(datetime(2023, 5, 10).timestamp())
        torrent = {'date': '', '_metadata': {'created_time': ts}}
        apply_date_fallback([torrent], skip_metadata=False)
        assert torrent['date'].startswith('2023-05-10')

    def test_sem_nada_usa_data_atual(self):
        torrent = {'date': ''}
        apply_date_fallback([torrent])
        assert torrent['date']
        assert 'T' in torrent['date']

    def test_skip_metadata_ignora_created_time(self):
        ts = int(datetime(2023, 5, 10).timestamp())
        torrent = {'date': '', '_metadata': {'created_time': ts}}
        apply_date_fallback([torrent], skip_metadata=True)
        assert not torrent['date'].startswith('2023-05-10')


class TestParseCrossData:
    def test_conversao_de_tipos(self):
        raw = {
            b'missing_dn': b'true',
            b'has_legenda': b'false',
            b'tracker_seed': b'12',
            b'tracker_leech': b'N/A',
            b'magnet_processed': b'Filme.2024',
            b'size': b'N/A',
        }
        parsed = parse_cross_data(raw)
        assert parsed['missing_dn'] is True
        assert parsed['has_legenda'] is False
        assert parsed['tracker_seed'] == 12
        assert parsed['tracker_leech'] == 0
        assert parsed['magnet_processed'] == 'Filme.2024'
        assert parsed['size'] is None

    def test_mapa_vazio(self):
        assert parse_cross_data({}) == {}
        assert parse_cross_data(None) == {}


class TestBuildTrackerLogId:
    def test_com_scraper_e_titulo(self):
        torrent = {'title_processed': 'Filme.2024.1080p'}
        log_id = build_tracker_log_id(torrent, 'Bludv', 'a' * 40)
        assert '[Bludv]' in log_id
        assert 'Filme.2024.1080p' in log_id
        assert 'a' * 40 in log_id

    def test_titulo_longo_truncado(self):
        torrent = {'title_processed': 'X' * 300}
        log_id = build_tracker_log_id(torrent, None, 'b' * 40)
        assert 'X' * 121 not in log_id
