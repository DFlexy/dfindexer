from utils.text.storage import (
    _looks_like_bludv_processed_release_name,
    magnet_original_needs_raw_name,
    can_skip_metadata_fetch,
)

BLUDV_PROCESSED = '-S02E05-1080P-.MKV.A.Casa.do.Dragao.S02E05.WEB-DL.1080p.x264.DUAL.5.1.2024'
RAW_NAME = 'A Casa do Dragao S02E05 WEB-DL 1080p x264 DUAL 5.1'


class TestLooksLikeBludvProcessed:
    def test_detecta_titulo_processado_bludv(self):
        assert _looks_like_bludv_processed_release_name(BLUDV_PROCESSED) is True

    def test_nome_bruto_nao_e_processado(self):
        assert _looks_like_bludv_processed_release_name(RAW_NAME) is False

    def test_vazio(self):
        assert _looks_like_bludv_processed_release_name('') is False
        assert _looks_like_bludv_processed_release_name(None) is False

    def test_prefixo_sxxexx_sem_pontos_suficientes(self):
        assert _looks_like_bludv_processed_release_name('-S01E01-teste') is False


class TestMagnetOriginalNeedsRawName:
    def test_nome_processado_precisa_de_raw(self):
        assert magnet_original_needs_raw_name(BLUDV_PROCESSED) is True

    def test_nome_bruto_nao_precisa(self):
        assert magnet_original_needs_raw_name(RAW_NAME) is False

    def test_vazio_precisa(self):
        assert magnet_original_needs_raw_name('') is True
        assert magnet_original_needs_raw_name('ab') is True

    def test_igual_ao_processado_precisa(self):
        processed = 'Filme.2024.WEB-DL.1080p'
        assert magnet_original_needs_raw_name(processed, processed) is True

    def test_diferente_do_processado_nao_precisa(self):
        assert magnet_original_needs_raw_name(RAW_NAME, 'Outro.Titulo.2024') is False


class TestCanSkipMetadataFetch:
    def test_sem_cross_data_nao_pula(self):
        assert can_skip_metadata_fetch({}, None) is False

    def test_sem_size_nao_pula(self):
        cross = {'magnet_processed': 'X.2024', 'metadata_name': RAW_NAME}
        assert can_skip_metadata_fetch({}, cross) is False

    def test_com_nome_bruto_e_size_pula(self):
        cross = {'magnet_processed': 'X.2024', 'size': '1 GB', 'metadata_name': RAW_NAME}
        assert can_skip_metadata_fetch({}, cross) is True

    def test_metadata_name_processado_nao_pula(self):
        cross = {'magnet_processed': BLUDV_PROCESSED, 'size': '1 GB', 'metadata_name': BLUDV_PROCESSED}
        assert can_skip_metadata_fetch({}, cross) is False
