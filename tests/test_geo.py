import pytest

from apartment_data.reference.geo import itm_to_wgs84, parse_cbs_coordinates


def test_grid_origin_maps_to_projection_origin():
    lat, lon = itm_to_wgs84(219529.584, 626907.390)
    assert lat == pytest.approx(31.7343936, abs=1e-7)
    assert lon == pytest.approx(35.2045169, abs=1e-7)


@pytest.mark.parametrize(
    ("code", "lat", "lon"),
    [
        (180263664864, 32.076, 34.789),  # Tel Aviv-Yafo
        (194137385051, 29.553, 34.943),  # Eilat
        (253933790871, 33.212, 35.574),  # Kiryat Shmona
    ],
)
def test_cbs_codes_of_known_cities(code, lat, lon):
    got = parse_cbs_coordinates(code)
    assert got == pytest.approx((lat, lon), abs=0.01)


@pytest.mark.parametrize("value", [None, "", "abc", 2351073910, 999999999999])
def test_invalid_codes(value):
    assert parse_cbs_coordinates(value) is None
