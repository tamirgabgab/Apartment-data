"""Israeli Transverse Mercator (ITM) grid to latitude / longitude.

The CBS localities file stores each locality's position as one 12-digit number: the ITM
easting and northing in metres, 6 digits each. This inverse Transverse Mercator on GRS80
ignores the small Israel 1993 to WGS84 datum shift (well under 100 m), which is plenty for
placing cities on a country map.
"""

from math import cos, degrees, radians, sin, sqrt, tan

_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 1.0000067
_LAT0 = radians(31.7343936111)
_LON0 = radians(35.2045169444)
_FALSE_EASTING = 219529.584
_FALSE_NORTHING = 626907.390


def _meridian_arc(phi: float) -> float:
    e2, e4, e6 = _E2, _E2**2, _E2**3
    return _A * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * sin(4 * phi)
        - (35 * e6 / 3072) * sin(6 * phi)
    )


def itm_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """(lat, lon) in degrees for an ITM easting / northing in metres."""
    m = _meridian_arc(_LAT0) + (northing - _FALSE_NORTHING) / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * _E2**2 / 64 - 5 * _E2**3 / 256))
    e1 = (1 - sqrt(1 - _E2)) / (1 + sqrt(1 - _E2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * sin(4 * mu)
        + (151 * e1**3 / 96) * sin(6 * mu)
        + (1097 * e1**4 / 512) * sin(8 * mu)
    )
    sin1, cos1, tan1 = sin(phi1), cos(phi1), tan(phi1)
    c1 = _EP2 * cos1**2
    t1 = tan1**2
    n1 = _A / sqrt(1 - _E2 * sin1**2)
    r1 = _A * (1 - _E2) / (1 - _E2 * sin1**2) ** 1.5
    d = (easting - _FALSE_EASTING) / (n1 * _K0)

    lat = phi1 - (n1 * tan1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * _EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * _EP2 - 3 * c1**2) * d**6 / 720
    )
    lon = (
        _LON0
        + (
            d
            - (1 + 2 * t1 + c1) * d**3 / 6
            + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * _EP2 + 24 * t1**2) * d**5 / 120
        )
        / cos1
    )
    return degrees(lat), degrees(lon)


def parse_cbs_coordinates(value: object) -> tuple[float, float] | None:
    """(lat, lon) from the CBS 12-digit coordinate code, or None when it is not one."""
    if value is None:
        return None
    try:
        digits = str(int(float(str(value).strip())))
    except ValueError:
        return None
    if len(digits) != 12:
        return None
    easting, northing = int(digits[:6]), int(digits[6:])
    if not (100_000 <= easting <= 300_000 and 350_000 <= northing <= 820_000):
        return None
    lat, lon = itm_to_wgs84(easting, northing)
    return round(lat, 5), round(lon, 5)
