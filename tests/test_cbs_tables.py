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
    values = parse_table(rows, TABLES["sale"], "2026-09", unknown)

    assert {(v.geo_level, v.geo_code) for v in values} == {("district", 1), ("district", 4)}
    assert unknown == {"Atlantis"}


def test_parse_rent_table_keeps_sampling_error_and_nis_prices():
    rows = [
        ["Districts\nand no.\nof rooms", "2024", None, None, None, "2025"],
        [None, "X-XII", None, "Annual\naverage", None, "I-III"],
        [None, "Average\nprice ", "Sampling\nerror"] * 1
        + ["x", "x", "Average\nprice ", "Sampling"],
        ["Total", 4700.0, 12.0, 4600.0, 11.0, 4817.4, 13.6],
        ["4.5 +", 6700.0, 40.0, 6600.0, 41.0, 6782.2, 46.8],
    ]
    values = parse_table(rows, TABLES["rent"], "2025-09")
    q1 = [v for v in values if v.period == date(2025, 1, 1)]
    assert [(v.rooms, v.avg_price, v.n_deals, v.sampling_error) for v in q1] == [
        ("all", 4817.4, None, 13.6),
        ("4.5-6", 6782.2, None, 46.8),
    ]


def _periods(years, quarters, kind="sale", edition="2026-09"):
    width = len(quarters)
    rows = [
        ["Districts"] + years + [None] * (width - len(years)),
        [None] + quarters,
        [None] + ["Average price", "No. of transactions"] * (width // 2),
        ["Total"] + [float(i + 1) for i in range(width)],
    ]
    values = parse_table(rows, TABLES[kind], edition)
    return [(v.period.isoformat()[:7], v.avg_price) for v in values]


def test_misplaced_year_cells_do_not_shift_quarters():
    # Edition 2026-09 prints '2025' above IV-VI instead of I-III.
    quarters = ["X-XII", None, "Annual average", None, "I-III", None, "IV-VI", None]
    years = ["2024", None, None, None, None, None, "2025"]
    assert _periods(years, quarters) == [
        ("2024-10", 1000.0),
        ("2025-01", 5000.0),
        ("2025-04", 7000.0),
    ]


def test_a_duplicated_quarter_label_does_not_start_a_new_year():
    # Edition 2020-10 labels the fourth quarter of 2019 'VII-IX' a second time.
    quarters = ["Annual average", None, "I-III", None, "VII-IX", None, "VII-IX", None]
    quarters += ["Annual average", None, "I-III", None]
    years = ["2018", None, "2019"] + [None] * 7 + ["2020"]
    got = _periods(years, quarters, edition="2020-10")
    assert got == [
        ("2019-01", 3000.0),
        ("2019-04", 5000.0),
        ("2019-07", 7000.0),
        ("2020-01", 11000.0),
    ]


def test_a_missing_first_year_label_is_inferred_from_a_later_one():
    # Edition 2021-01 of the rent table prints only '2020', above the second run.
    quarters = ["X-XII", None, "Annual average", None, "I-III", None]
    years = [None, None, None, None, "2020"]
    assert _periods(years, quarters, edition="2021-01") == [
        ("2019-10", 1000.0),
        ("2020-01", 5000.0),
    ]


def test_mislabeled_measure_row_still_reads_price_first():
    rows = [
        ["Districts", "2019", None, None, None, "2020"],
        [None, "X-XII", None, "Annual average", None, "I-III"],
        [None, "Sampling errors", "No. of transactions"] * 2 + [None],
        ["Total", 3864.2, 13.0, 3805.4, 12.0, 3900.7, 13.0],
    ]
    values = parse_table(rows, TABLES["rent"], "2020-09")
    assert [(v.period.month, v.avg_price, v.sampling_error) for v in values] == [
        (10, 3864.2, 13.0),
        (1, 3900.7, 13.0),
    ]


def test_an_edition_cannot_hold_quarters_from_its_own_future():
    quarters = ["X-XII", None, "Annual average", None, "I-III", None]
    with pytest.raises(ValueError, match="not before the edition date"):
        _periods(["2025"], quarters, edition="2025-12")


def _value(edition, price):
    return AveragePrice("sale", "city", 70, date(2026, 1, 1), "all", price, 1, None, edition)


def test_merge_editions_never_lets_a_missing_price_win():
    merged = merge_editions([_value("2026-08", 1.0), _value("2026-09", None)])
    assert [(v.edition, v.avg_price) for v in merged] == [("2026-08", 1.0)]


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
