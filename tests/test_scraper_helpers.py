from utils.concurrency.scraper_helpers import (
    build_page_url,
    build_search_url,
    format_page_progress,
    generate_search_variations,
    limit_list,
    normalize_query_for_flaresolverr,
    should_stop_processing,
)


class TestBuildPageUrl:
    def test_pagina_1_e_a_base(self):
        assert build_page_url('https://site.com/', 'page/{}/', '1') == 'https://site.com/'

    def test_pagina_2_usa_pattern(self):
        assert build_page_url('https://site.com/', 'page/{}/', '2') == 'https://site.com/page/2/'


class TestBuildSearchUrl:
    def test_query_encodada(self):
        url = build_search_url('https://site.com/', '?s=', 'house of the dragon')
        assert url == 'https://site.com/?s=house%20of%20the%20dragon'


class TestGenerateSearchVariations:
    def test_query_original_sempre_presente(self):
        assert 'matrix' in generate_search_variations('matrix')

    def test_remove_stop_words(self):
        variations = generate_search_variations('the matrix')
        assert 'the matrix' in variations
        assert 'matrix' in variations

    def test_primeira_palavra_como_variacao(self):
        variations = generate_search_variations('matrix reloaded')
        assert 'matrix' in variations


class TestNormalizeQueryForFlaresolverr:
    def test_remove_dois_pontos_com_flaresolverr(self):
        assert normalize_query_for_flaresolverr('Movie: Sub', True) == 'Movie  Sub'

    def test_mantem_sem_flaresolverr(self):
        assert normalize_query_for_flaresolverr('Movie: Sub', False) == 'Movie: Sub'


class TestLimitList:
    def test_limita(self):
        assert limit_list([1, 2, 3, 4], 2) == [1, 2]

    def test_zero_nao_limita(self):
        assert limit_list([1, 2, 3], 0) == [1, 2, 3]


class TestShouldStopProcessing:
    def test_sem_limite(self):
        assert should_stop_processing(100, None) is False
        assert should_stop_processing(100, 0) is False

    def test_com_limite(self):
        assert should_stop_processing(5, 5) is True
        assert should_stop_processing(4, 5) is False


class TestFormatPageProgress:
    def test_formato(self):
        assert format_page_progress(1, 12) == '01/12'
