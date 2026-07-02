"""Filename convention tests: all three generations must parse and round-trip."""

from datetime import date

import pytest

from gsv_metadata_tracker.naming import (
    generate_base_filename, generate_run_filename, parse_filename,
    sanitize_city_query_str)


def test_parse_legacy_int_name():
    p = parse_filename("grand-marais--mn--usa_width_1000_height_1000_step_20.csv.gz")
    assert p.slug == "grand-marais--mn--usa"
    assert p.city_query_str == "Grand Marais, Mn, Usa"
    assert (p.width_meters, p.height_meters, p.step_meters) == (1000, 1000, 20)
    assert p.run_date is None


def test_parse_buggy_float_step_name():
    p = parse_filename("bend--or_width_5000_height_5000_step_20.0.csv.gz")
    assert p.step_meters == 20
    assert p.run_date is None


def test_parse_dated_name():
    p = parse_filename(
        "bend--oregon--united-states_width_5000_height_5000_step_20_2026-07-02.json.gz")
    assert p.run_date == date(2026, 7, 2)
    assert p.slug == "bend--oregon--united-states"


def test_parse_legacy_single_underscore_slug():
    p = parse_filename("amsterdam_nl_width_20000_height_20000_step_20.csv.gz")
    assert p.slug == "amsterdam_nl"
    assert p.width_meters == 20000


def test_parse_full_path_and_extensions():
    for ext in (".csv.gz", ".json.gz", ".csv", ".json", ".html"):
        p = parse_filename(f"/some/dir/x--y_width_10_height_20_step_5{ext}")
        assert (p.width_meters, p.height_meters, p.step_meters) == (10, 20, 5)


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_filename("cities.json.gz")


def test_generate_base_filename_int_casts_step():
    # Regression: float --step used to produce unparseable `_step_20.0` names
    name = generate_base_filename("Bend, OR", 5000.0, 5000.0, 20.0)
    assert name == "bend--or_width_5000_height_5000_step_20"
    parse_filename(name + ".csv.gz")  # must round-trip


def test_generate_run_filename_roundtrip():
    name = generate_run_filename("bend--oregon--united-states", 5000, 5000, 20,
                                 date(2026, 7, 2))
    p = parse_filename(name + ".csv.gz")
    assert p.slug == "bend--oregon--united-states"
    assert p.run_date == date(2026, 7, 2)


def test_sanitize_city_query_str():
    # Interior periods are preserved — matches all legacy data-file slugs
    assert sanitize_city_query_str("St. Louis, MO, USA") == "st.-louis--mo--usa"
    assert sanitize_city_query_str("Grand Marais") == "grand-marais"
    assert sanitize_city_query_str("Port Angeles, WA") == "port-angeles--wa"
    # Nominatim sometimes returns non-breaking spaces in place names
    assert sanitize_city_query_str("Ann\xa0Arbor Charter Township, Michigan") == \
        "ann-arbor-charter-township--michigan"
