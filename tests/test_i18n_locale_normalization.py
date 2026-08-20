from dashboard.i18n.loader import DEFAULT_LANGUAGE, load_translations, normalize_language


def test_exact_supported_languages_remain_canonical() -> None:
    assert normalize_language("ru") == "ru"
    assert normalize_language("en") == "en"
    assert normalize_language("uz") == "uz"


def test_regional_case_and_underscore_locales_map_to_canonical_catalogs() -> None:
    assert normalize_language("EN-us") == "en"
    assert normalize_language("ru_RU") == "ru"
    assert normalize_language("uz-UZ") == "uz"


def test_accept_language_uses_first_supported_nonzero_quality_range() -> None:
    assert normalize_language("de-DE, en-US;q=0.8, uz;q=0.7") == "en"
    assert normalize_language("fr, en;q=0, uz-UZ;q=0.6") == "uz"


def test_unknown_or_empty_language_falls_back_to_default() -> None:
    assert normalize_language(None) == DEFAULT_LANGUAGE
    assert normalize_language("") == DEFAULT_LANGUAGE
    assert normalize_language("de-DE") == DEFAULT_LANGUAGE
    assert normalize_language("*") == DEFAULT_LANGUAGE


def test_regional_locale_loads_same_canonical_catalog() -> None:
    assert load_translations("en-US") == load_translations("en")
    assert load_translations("uz_UZ") == load_translations("uz")
