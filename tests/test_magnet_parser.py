import pytest

from magnet.parser import MagnetParser

HASH = 'a' * 40
MAGNET = (
    f'magnet:?xt=urn:btih:{HASH}'
    '&dn=Filme%20Teste%202024%201080p'
    '&tr=udp%3A%2F%2Ftracker.example.com%3A80'
    '&tr=udp%3A%2F%2Ftracker2.example.com%3A1337'
)


class TestMagnetParser:
    def test_info_hash_extraido(self):
        data = MagnetParser.parse(MAGNET)
        assert data['info_hash'] == HASH

    def test_display_name_decodificado(self):
        data = MagnetParser.parse(MAGNET)
        assert data['display_name'] == 'Filme Teste 2024 1080p'

    def test_trackers_extraidos(self):
        data = MagnetParser.parse(MAGNET)
        trackers = data.get('trackers') or []
        assert any('tracker.example.com' in t for t in trackers)

    def test_magnet_sem_dn(self):
        data = MagnetParser.parse(f'magnet:?xt=urn:btih:{HASH}')
        assert data['info_hash'] == HASH
        assert data['display_name'] == ''

    def test_magnet_invalido_lanca_erro(self):
        with pytest.raises(Exception):
            MagnetParser.parse('http://nao-e-magnet.com')
