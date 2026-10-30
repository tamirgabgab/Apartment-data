import gzip
import json

import httpx
import pytest

from apartment_data.reference.localities import (
    Locality,
    build_aliases,
    cbs_resources_by_year,
    names_from_records,
    parse_cbs_localities,
    population_authority_resource,
)
from apartment_data.reference.names import normalize_name
from apartment_data.sources.datagov import DataGovClient, DataGovError


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("קריית אתא", "קרית אתא"),
        ("הרצלייה", "הרצליה"),
        ("פתח תקווה", "פתח תקוה"),
        ("תל אביב -יפו", "תל-אביב יפו"),
        ("תל אביב -יפו", "תל אביב־יפו"),
        ("סח׳נין", "סח'נין"),
        ("  באר   שבע ", "באר שבע"),
        ("Tel Aviv - Yafo", "tel aviv yafo"),
    ],
)
def test_normalize_name_merges_spelling_variants(a, b):
    assert normalize_name(a) == normalize_name(b)


def test_normalize_name_keeps_distinct_names_apart():
    assert normalize_name("רמת גן") != normalize_name("רמת השרון")


CBS_ROWS = [
    {
        "שם יישוב": "תל אביב -יפו",
        "סמל יישוב": 5000,
        "תעתיק": "TEL AVIV - YAFO",
        "שם מחוז": "תל אביב",
        "שם נפה": "תל אביב",
        "סמל מעמד מונציפאלי": 0,
        "שם מעמד מונציפאלי": "עירייה",
        "סך הכל אוכלוסייה 2023 - ארעי": 495230,
        "שם יישוב באנגלית": "Tel Aviv - Yafo",
    },
    {
        "שם יישוב": "שחר",
        "סמל יישוב": 7,
        "תעתיק": "SHAHAR",
        "שם מחוז": "הדרום",
        "שם נפה": "אשקלון",
        "סמל מעמד מונציפאלי": 50,
        "שם מעמד מונציפאלי": "מועצה אזורית לכיש",
        "סך הכל אוכלוסייה 2023 - ארעי": 812,
        "שם יישוב באנגלית": "Shahar",
    },
    {"שם יישוב": "ללא מעמד", "סמל יישוב": 1823, "סמל מעמד מונציפאלי": None, "תעתיק": ""},
]


def test_parse_cbs_localities():
    tlv, shahar, no_status = parse_cbs_localities(CBS_ROWS)

    assert tlv == Locality(5000, "תל אביב -יפו", "Tel Aviv - Yafo", "עירייה", "תל אביב",
                           "תל אביב", 495230, True)  # fmt: skip
    assert shahar.is_city is False
    assert shahar.population == 812
    assert no_status.is_city is False
    assert no_status.name_en is None
    assert no_status.population is None


def test_names_from_records_handles_older_column_names():
    rows = [{"סמל": 1061, "שם יישוב": "נצרת עילית", "תעתיק פרסומים": "Nazerat Illit"}]
    assert names_from_records(rows) == [("נצרת עילית", 1061), ("Nazerat Illit", 1061)]


def _loc(code):
    return Locality(code, str(code), None, None, None, None, None, False)


def test_build_aliases_prefers_lower_priority_and_skips_ties():
    result = build_aliases(
        [_loc(1), _loc(2), _loc(3)],
        [
            ("Alpha", 1, 0),
            ("Alpha", 2, 3),  # an old name of 2 that is now the name of 1
            ("Beta", 2, 1),
            ("Beta", 3, 1),  # same priority, two localities
            ("Gamma", 99, 0),  # unknown locality
        ],
    )
    assert result.aliases == {"alpha": 1}
    assert result.ambiguous == {"beta": [2, 3]}


def test_resource_selection():
    cbs = {
        "resources": [
            {"id": "a", "name": "קובץ היישובים 2023", "datastore_active": True},
            {"id": "b", "name": "קובץ היישובים 2016", "datastore_active": True},
            {"id": "c", "name": "קובץ היישובים 2015", "datastore_active": False},
        ]
    }
    assert cbs_resources_by_year(cbs) == {2023: "a", 2016: "b"}

    pa = {
        "resources": [
            {"id": "x", "format": "CSV", "datastore_active": True, "name": "רשימה - מתעדכן"},
            {"id": "y", "format": "CSV", "datastore_active": True,
             "name": "רשימה - כותרות באנגלית -מתעדכן"},
        ]
    }  # fmt: skip
    assert population_authority_resource({"resources": pa["resources"][::-1]}) == "x"


def _client(tmp_path, handler):
    transport = httpx.MockTransport(handler)
    return DataGovClient(tmp_path, delay_seconds=0, client=httpx.Client(transport=transport))


def test_datastore_records_paginates_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr("apartment_data.sources.datagov.PAGE_SIZE", 2)
    rows = [{"n": i} for i in range(5)]
    calls = []

    def handler(request):
        offset = int(request.url.params["offset"])
        calls.append(offset)
        page = rows[offset : offset + 2]
        return httpx.Response(200, json={"success": True, "result": {"records": page, "total": 5}})

    client = _client(tmp_path, handler)
    assert client.datastore_records("res") == rows
    assert calls == [0, 2, 4]

    with gzip.open(tmp_path / "datagov" / "res.json.gz", "rt", encoding="utf-8") as f:
        assert json.load(f) == rows
    assert client.datastore_records("res") == rows
    assert calls == [0, 2, 4]  # served from the cache


def test_unsuccessful_response_raises(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(200, json={"success": False, "error": {}}))
    with pytest.raises(DataGovError):
        client.package_show("missing")
