from utils.text.title_builder import (
    prepare_release_title,
    create_standardized_title,
    _normalize_metadata_name,
)


class TestPrepareReleaseTitle:
    def test_magnet_dn_normalizado_para_pontos(self):
        result = prepare_release_title(
            'House of the Dragon S02E05 WEB-DL 1080p', 'House of the Dragon', '2024',
            missing_dn=False, skip_metadata=True,
        )
        assert 'House.of.the.Dragon' in result
        assert 'S02E05' in result
        assert ' ' not in result

    def test_camrip_nao_recebe_web_dl(self):
        result = prepare_release_title(
            '', 'Filme Teste CAMRip 1080p', '2026',
            missing_dn=True, skip_metadata=True,
        )
        assert 'CAMRip' in result
        assert 'WEB-DL' not in result

    def test_missing_dn_usa_fallback_e_injeta_web_dl(self):
        result = prepare_release_title(
            '', 'Filme Teste', '2026',
            missing_dn=True, skip_metadata=True,
        )
        assert 'Filme' in result
        assert '2026' in result
        assert 'WEB-DL' in result

    def test_ano_nao_duplicado(self):
        result = prepare_release_title(
            'Filme.Teste.2024.WEB-DL.1080p', 'Filme Teste', '2024',
            missing_dn=False, skip_metadata=True,
        )
        assert result.count('2024') == 1

    def test_remove_colchetes_preservando_tags_tecnicas(self):
        result = prepare_release_title(
            'Filme Teste [1080p] [WEB-DL] [DUAL]', 'Filme Teste', '2024',
            missing_dn=False, skip_metadata=True,
        )
        assert '[' not in result and ']' not in result
        assert '1080p' in result
        assert 'WEB-DL' in result
        assert 'DUAL' in result


class TestCreateStandardizedTitle:
    def test_titulo_com_episodio(self):
        result = create_standardized_title(
            'House of the Dragon', '2024',
            'House.of.the.Dragon.S02E05.WEB-DL.1080p.x264.DUAL.5.1.2024',
            magnet_original='House of the Dragon S02E05 WEB-DL 1080p x264 DUAL 5.1',
        )
        assert 'S02E05' in result
        assert '1080p' in result.lower() or '1080P' in result

    def test_titulo_basico_filme(self):
        result = create_standardized_title(
            'Inception', '2010',
            'Inception.2010.BluRay.1080p.x264',
            magnet_original='Inception 2010 BluRay 1080p x264',
        )
        assert 'Inception' in result
        assert '2010' in result
        assert 'BluRay' in result

    def test_acentos_removidos(self):
        result = create_standardized_title(
            'A Casa do Dragão', '2024',
            'A.Casa.do.Dragao.S02E05.WEB-DL.1080p',
            magnet_original='A Casa do Dragão S02E05 WEB-DL 1080p',
        )
        assert 'ã' not in result


class TestNormalizeMetadataName:
    def test_espacos_viram_pontos(self):
        assert ' ' not in _normalize_metadata_name('Nome Com Espacos 1080p')

    def test_remove_colchetes(self):
        result = _normalize_metadata_name('Filme [Grupo] 1080p')
        assert '[' not in result and ']' not in result

    def test_partes_duplicadas_consecutivas_removidas(self):
        result = _normalize_metadata_name('Filme.Filme.2024')
        assert result.lower().count('filme') == 1
