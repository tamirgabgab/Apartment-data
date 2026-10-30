from datetime import date

import httpx
import pytest

from apartment_data.sources.cbs_tables import (
    TABLES,
    AveragePrice,
    CbsTablesClient,
    merge_editions,
    months,
    normalize_rooms,
    parse_table,
)

HEADER = [
    ["Table 2.2 Average Prices of Dwellings"],
    ["Districts\nand no.\nof rooms", "2025", None, None, None, "2026", None],
    [None, "X-XII", None, "Annual\naverage", None, "I-III", None],
    [None, "Average\nprice ", "No. of\ntransac-\ntions"] * 1
    + ["Average\nprice ", "No. of\ntransac-\ntions", "Average\nprice ", "No. of\ntransac-\ntions"],
]


def _sale_rows(body):
    return HEADER + [[None]] + body + [["(1) footnote"], ["Tel Aviv - 5000", 1, 1, 1, 1, 1, 1]]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("1-2", "1-2"),
        ("3-2.5", "2.5-3"),
        ("2.5-3", "2.5-3"),
        ("6-5.5", "5.5-6"),
        ("4.5 +", "4.5-6"),
        ("up to 2 rooms", "1-2"),
        ("Ashdod - 70", None),
        ("Total", None),
    ],
)
def test_normalize_rooms(label, expected):
    assert normalize_rooms(label) == expected


def test_parse_sale_table_with_codes_sections_and_footnotes():
    rows = _sale_rows(
        [
            ["Total", 2350.9, 19493, 2340.3, 81199, 2371.8, 14389],
            ["3-2.5", 1790.7, 5469, 1803.4, 23198, "-", 3],
            ["Residential Districts"],
            ["Jerusalem District - 1", 2891.9, 1677, 2874.7, 7498, 3113.1, 1371],
            ["Big cities"],
            ["Ashdod - 70", 2036.9, 517, 2137.8, 2322, 2188.5, 427],
            ["Haifa", 1500.0, 900, 1, 1, 1600.0, 800],
        ]
    )
    values = parse_table(rows, TABLES["sale"], "2026-09")

    # The annual average columns are skipped, the footnote ends the table.
    assert {v.period for v in values} == {date(2025, 10, 1), date(2026, 1, 1)}
    by_key = {(v.geo_level, v.geo_code, v.rooms, v.period): v for v in values}
    national = by_key[("national", 0, "all", date(2026, 1, 1))]
    assert national.avg_price == 2371800.0
    assert national.n_deals == 14389
    assert by_key[("national", 0, "2.5-3", date(2026, 1, 1))].avg_price is None
    assert by_key[("district", 1, "all", date(2025, 10, 1))].avg_price == 2891900.0
    assert by_key[("city", 70, "all", date(2026, 1, 1))].n_deals == 427
    # A big city printed without a code is resolved by name.
    assert by_key[("city", 4000, "all", date(2026, 1, 1))].avg_price == 1600000.0
    assert len(values) == 10


def test_old_editions_without_sections_are_districts_and_unknown_places_are_skipped():
    rows = _sale_rows(
        [
            ["Jerusalem", 1777.5, 1870, 1, 1, 1888.3, 1430],
            ["Centeral", 1.0, 1, 1, 1, 2.0, 2],
            ["Big cities"],
            ["Atlantis", 1.0, 1, 1, 1, 1.0, 1],
            ["1-2", 1.0, 1, 1, 1, 1.0, 1],
        ]
    )
    unknown = set()
    values = parse_table(rows, TABLES["sale"], "2020-01", unknown)

    assert {(v.geo_level, v.geo_code) for v in values} == {("district", 1), ("district", 4)}
    assert unknown == {"Atlantis"}


def test_parse_rent_table_keeps_sampling_error_and_nis_prices():
    rows = [
        ["Districts\nand no.\nof rooms", "2025"],
        [None, "I-III"],
        [None, "Average\nprice ", "Sampling\nerror"],
        ["Total", 4817.4, 13.6],
        ["4.5 +", 6782.2, 46.8],
    ]
    values = parse_table(rows, TABLES["rent"], "2025-09")
    assert [(v.rooms, v.avg_price, v.n_deals, v.sampling_error) for v in values] == [
        ("all", 4817.4, None, 13.6),
        ("4.5-6", 6782.2, None, 46.8),
    ]


def _value(edition, price):
    return AveragePrice("sale", "city", 70, date(2026, 1, 1), "all", price, 1, None, edition)


def test_merge_editions_keeps_newest():
    merged = merge_editions(
        [_value("2026-08", 1.0), _value("2026-09", 2.0), _value("2025-01", 3.0)]
    )
    assert [(v.edition, v.avg_price) for v in merged] == [("2026-09", 2.0)]


def test_months_cross_year():
    assert list(months((2025, 11), (2026, 2))) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


def test_edition_download_detects_missing_files_and_caches(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("2019/price01aa/aa2_2_e.xls"):
            return httpx.Response(200, content=b"\xd0\xcf\x11\xe0 fake xls")
        return httpx.Response(200, content=b"<html>not found</html>")

    client = CbsTablesClient(tmp_path, 0, httpx.Client(transport=httpx.MockTransport(handler)))
    spec = TABLES["sale"]

    assert client.edition(spec, 2019, 1).startswith(b"\xd0\xcf\x11\xe0")
    assert client.edition(spec, 2019, 2) is None
    n = len(calls)
    assert client.edition(spec, 2019, 1) is not None  # cached file
    assert client.edition(spec, 2019, 2) is None  # cached as missing
    assert len(calls) == n
