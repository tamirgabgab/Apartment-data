from datetime import date

import httpx

from apartment_data.sources.cbs_index import CbsIndexClient, IndexValue, parse_monthly


def _point(year, month, value, base="1993 ממוצע"):
    return {"year": year, "month": month, "currBase": {"baseDesc": base, "value": value}}


def test_parse_monthly_sorts_and_skips_other_series_and_quarters():
    pages = [
        {
            "month": [
                {"code": 40010, "date": [_point(2026, 7, 590.0), _point(1994, 1, 117.2)]},
                {"code": 99999, "name": "other", "date": [_point(2026, 7, 1.0)]},
            ],
            "quarter": [{"code": 40010, "date": [{"year": 1990, "quarter": 1, "currBase": {}}]}],
        }
    ]
    values = parse_monthly("40010", pages)

    assert [v.period for v in values] == [date(1994, 1, 1), date(2026, 7, 1)]
    assert values[1] == IndexValue("40010", "מדד מחירי דירות - כלל הארץ", date(2026, 7, 1), 590.0,
                                   "1993 ממוצע")  # fmt: skip


def test_parse_monthly_keeps_each_months_own_base():
    points = [_point(2025, 1, 101.0, "2024 ממוצע"), _point(2024, 12, 110.0, "2022 ממוצע")]
    values = parse_monthly("120010", [{"month": [{"code": 120010, "date": points}]}])
    assert [(v.value, v.base_period) for v in values] == [
        (110.0, "2022 ממוצע"),
        (101.0, "2024 ממוצע"),
    ]


def test_fetch_series_follows_pages_and_caches(tmp_path):
    seen = []

    def handler(request):
        page = int(request.url.params["Page"])
        seen.append(page)
        payload = {"month": [{"code": 1, "date": [_point(2000, page, float(page))]}],
                   "paging": {"last_page": 2}}  # fmt: skip
        return httpx.Response(200, json=payload)

    client = CbsIndexClient(tmp_path, 0, httpx.Client(transport=httpx.MockTransport(handler)))
    pages = client.fetch_series("1")

    assert seen == [1, 2]
    assert [v.value for v in parse_monthly("1", pages)] == [1.0, 2.0]
    assert (tmp_path / "cbs" / "index_1.json.gz").exists()


def test_main_keeps_going_when_one_series_fails(tmp_path, monkeypatch, capsys):
    import pytest

    from apartment_data.sources import cbs_index

    def handler(request):
        code = request.url.params["id"]
        if code == "60000":
            return httpx.Response(500, json={"Message": "Error: Price Data"})
        return httpx.Response(
            200, json={"month": [{"code": int(code), "date": [_point(2020, 1, 1.0)]}]}
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        cbs_index.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", "0")

    with pytest.raises(SystemExit, match="60000"):
        cbs_index.main(["--out", str(tmp_path)])

    out = capsys.readouterr().out
    assert "::warning::60000" in out
    assert "120010: 1 months" in out
    rows = (tmp_path / "official_indices.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + len(cbs_index.SERIES) - 1
