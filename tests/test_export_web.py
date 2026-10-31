from datetime import date, datetime

import pytest

from apartment_data.export.web import build_payload, chain_cpi, quarterly_mean


def _cpi(year, month, value, base):
    return {"period": date(year, month, 1).isoformat(), "value": value, "base_period": base}


def test_chain_cpi_links_a_new_base_through_the_base_years_average():
    rows = [_cpi(2022, m, 100.0 + m, "2020 ממוצע") for m in range(1, 13)]
    rows += [_cpi(2023, 1, 101.0, "2022 ממוצע")]
    chained = chain_cpi(rows)

    # 2022 averaged 106.5 on the old base; the new base sets that average to 100.
    assert chained[date(2022, 12, 1)] == pytest.approx(112.0)
    assert chained[date(2023, 1, 1)] == pytest.approx(101.0 * 1.065)


def test_chain_cpi_refuses_a_base_it_cannot_link():
    rows = [_cpi(2022, 1, 100.0, "2020 ממוצע"), _cpi(2023, 1, 101.0, "2022 ממוצע")]
    with pytest.raises(ValueError, match="cannot link"):
        chain_cpi(rows)


def test_quarterly_mean_needs_three_months():
    monthly = {date(2025, 1, 1): 1.0, date(2025, 2, 1): 2.0, date(2025, 3, 1): 3.0}
    monthly[date(2025, 4, 1)] = 9.0
    assert quarterly_mean(monthly) == {date(2025, 1, 1): 2.0}


def _price(kind, level, code, period, rooms, price, deals=None):
    return {
        "kind": kind,
        "geo_level": level,
        "geo_code": code,
        "period": period,
        "rooms": rooms,
        "avg_price": price,
        "n_deals": deals,
    }


def test_build_payload_shapes_series_places_and_real_factor():
    localities = [
        {"locality_code": 5000, "name_he": "תל אביב -יפו", "name_en": "Tel Aviv - Yafo",
         "district": "תל אביב", "population": 495230, "lat": 32.07, "lon": 34.78},
    ]  # fmt: skip
    cpi = [_cpi(2025, m, 100.0 + (m > 3) * 10, "2024 ממוצע") for m in range(1, 7)]
    indices = [{**r, "series_code": "120010", "series_name": "CPI"} for r in cpi]
    indices += [
        {"series_code": "40010", "series_name": "HPI", "period": f"2025-0{m}-01",
         "value": 500.0, "base_period": "1993 ממוצע"}
        for m in range(1, 7)
    ]  # fmt: skip
    prices = [
        _price("sale", "city", 5000, "2025-01-01", "all", 4000000.0, 900),
        _price("sale", "city", 5000, "2025-04-01", "all", 4400000.0, 950),
        _price("sale", "national", 0, "2025-04-01", "2.5-3", 1800000.0, 5000),
        _price("rent", "district", 5, "2025-01-01", "all", 6000.0),
    ]
    payload = build_payload(localities, indices, prices, generated_at=datetime(2026, 1, 1))

    assert payload["periods"] == ["2025-01-01", "2025-04-01"]
    assert [p["id"] for p in payload["places"]] == ["n0", "d5", "c5000"]
    city = payload["places"][2]
    assert city["district"] == "d5" and city["population"] == 495230
    assert payload["series"]["sale"]["c5000"]["all"] == {
        "price": [4000000.0, 4400000.0],
        "deals": [900, 950],
    }
    assert payload["series"]["sale"]["n0"]["2.5-3"]["price"] == [None, 1800000.0]
    assert "deals" not in payload["series"]["rent"]["d5"]["all"]
    assert payload["rooms"] == {"rent": ["all"], "sale": ["all", "2.5-3"]}
    # CPI rose from 100 to 110: Q1 prices are worth 10% more in Q2 shekels.
    assert payload["real_factor"] == [1.1, 1.0]
    assert payload["real_base"] == "2025-04-01"
    assert payload["indices"]["40010"]["values"] == [500.0, 500.0]


def test_build_rates_aligns_quarters_and_starts_with_mortgage_data():
    from apartment_data.export.web import build_rates

    def row(code, period, value):
        return {"series_code": code, "series_name": code, "period": period, "value": value}

    rates = [
        row("prime", "2016-12-01", 1.6),
        row("prime", "2017-01-01", 1.6),
        row("prime", "2017-02-01", 2.2),
        row("mortgage_fixed_cpi", "2017-02-01", "3.0"),
    ]
    out = build_rates(rates, [date(2017, 1, 1), date(2017, 4, 1)])

    assert out["months"] == ["2017-02-01"]
    assert list(out["series"]) == ["mortgage_fixed_cpi", "prime"]
    assert out["series"]["prime"]["values"] == [2.2]
    # Quarterly means use every published month, also those before the chart starts.
    assert out["quarterly"]["prime"] == [1.9, None]
    assert out["quarterly"]["mortgage_fixed_cpi"] == [3.0, None]


def test_build_rates_without_data_is_empty():
    from apartment_data.export.web import build_rates

    assert build_rates([], [date(2017, 1, 1)]) == {"months": [], "series": {}, "quarterly": {}}
