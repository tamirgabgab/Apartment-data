"""Normalization of locality names, so that spelling variants share one lookup key."""

import re
import unicodedata

_QUOTES = str.maketrans({"״": '"', "”": '"', "“": '"', "׳": "'", "’": "'", "‘": "'", "`": "'"})
_SEPARATORS = re.compile(r"[-־‐-―_()/,.]")
_NIQQUD = re.compile(r"[֑-ׇ]")
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lookup key for a locality name.

    Unifies quote and geresh characters, treats hyphens and maqaf as spaces, drops niqqud,
    lowercases Latin letters and collapses the doubled vav / yod of full spelling, so that
    'קריית' and 'קרית', or 'תל אביב -יפו' and 'תל-אביב יפו', get the same key.
    """
    s = unicodedata.normalize("NFKC", name).translate(_QUOTES).lower()
    s = _SEPARATORS.sub(" ", s)
    s = _NIQQUD.sub("", s)
    s = s.replace("וו", "ו").replace("יי", "י")
    return _SPACES.sub(" ", s).strip()
