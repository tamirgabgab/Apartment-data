from datetime import date

import httpx
import pytest

from apartment_data.sources.boi_rates import (
    BoiClient,
    RateValue,
    parse_mortgage_rates,
    parse_policy_rate,
)

HEADER = "SERIES_CODE,FREQ,DATA_TYPE,TIME_PERIOD,OBS_VALUE,RELEASE_STATUS\n"


def _csv(rows):
    return HEADER + "".join(f"{code},M,R,{period},{value},YP\n" for code, period, value in rows)


ALL_PARTS = [
    ("BNK_99034_LR_BIR_MRTG_467", "2026-07", "4.6"),
    ("BNK_99034_LR_BIR_MRTG_1492", "2026-07", "3.3"),
    ("BNK_99034_LR_BIR_MRTG_1489", "2026-07", "1.64"),
    ("BNK_99034_LR_BIR_MRTG_1488", "2026-07", "1.55"),
]


def test_parse_mortgage_rates_sums_benchmark_and_margin():
    rows = parse_mortgage_rates("﻿" + _csv(ALL_PARTS + [("OTHER", "2026-07", "9")]))
    by_code = {r.series_code: r for r in rows}

    assert sorted(by_code) == [
        "mortgage_fixed_cpi",
        "mortgage_fixed_unindexed",
        "mortgage_variable_cpi",
    ]
    assert by_code["mortgage_variable_cpi"].value == pytest.approx(3.19)
    assert by_code["mortgage_fixed_unindexed"] == RateValue(
        "mortgage_fixed_unindexed",
        "ריבית ממוצעת על משכנתאות חדשות - קבועה לא צמודה",
        date(2026, 7, 1),
        4.6,
    )


def test_parse_mortgage_rates_skips_months_with_a_missing_part():
    text = _csv(ALL_PARTS + [("BNK_99034_LR_BIR_MRTG_1489", "2026-08", "1.7"),
                             ("BNK_99034_LR_BIR_MRTG_1488", "2026-08", "")])  # fmt: skip
    variable = [r for r in parse_mortgage_rates(text) if r.series_code == "mortgage_variable_cpi"]
    assert [r.period for r in variable] == [date(2026, 7, 1)]


def test_parse_mortgage_rates_fails_when_a_series_disappears():
    with pytest.raises(ValueError, match="MRTG_1492"):
        parse_mortgage_rates(_csv([r for r in ALL_PARTS if "1492" not in r[0]]))


def test_parse_policy_rate_takes_the_last_day_of_each_month_and_adds_prime():
    text = _csv([
        ("MNT_RIB_BOI_D", "2026-01-31", "4.25"),
        ("MNT_RIB_BOI_D", "2026-01-05", "4.5"),
        ("MNT_RIB_BOI_D", "2026-02-02", "4.0"),
    ])  # fmt: skip
    rows = {(r.series_code, r.period): r.value for r in parse_policy_rate(text)}
    assert rows == {
        ("boi_rate", date(2026, 1, 1)): 4.25,
        ("prime", date(2026, 1, 1)): 5.75,
        ("boi_rate", date(2026, 2, 1)): 4.0,
        ("prime", date(2026, 2, 1)): 5.5,
    }


def test_fetch_csv_builds_the_url_and_caches(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, text=HEADER)

    client = BoiClient(tmp_path, 0, httpx.Client(transport=httpx.MockTransport(handler)))
    client.fetch_csv("BR", "MNT_RIB_BOI_D")

    assert seen[0].path.endswith("/BOI.STATISTICS/BR/1.0/MNT_RIB_BOI_D")
    assert seen[0].params["format"] == "csv"
    assert (tmp_path / "boi" / "BR_MNT_RIB_BOI_D.csv.gz").exists()
