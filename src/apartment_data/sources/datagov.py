"""Minimal client for the data.gov.il CKAN API (https://data.gov.il/api/3/action)."""

import gzip
import json
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://data.gov.il/api/3/action"
USER_AGENT = "apartment-data/0.1 (+https://github.com/tamirgabgab/Apartment-data)"
PAGE_SIZE = 5000


class DataGovError(RuntimeError):
    """The API answered, but not with a successful CKAN response."""


class DataGovClient:
    """Throttled CKAN client that caches every datastore table as gzipped JSON."""

    def __init__(
        self,
        cache_dir: Path,
        delay_seconds: float = 1.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.delay_seconds = delay_seconds
        self._client = client or httpx.Client(
            base_url=BASE_URL, headers={"User-Agent": USER_AGENT}, timeout=60
        )
        self._last_request = 0.0

    def _action(self, action: str, **params: Any) -> Any:
        wait = self._last_request + self.delay_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        response = self._client.get(f"{BASE_URL}/{action}", params=params)
        self._last_request = time.monotonic()
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise DataGovError(f"{action} failed: {payload.get('error')}")
        return payload["result"]

    def package_show(self, package_id: str) -> dict[str, Any]:
        return self._action("package_show", id=package_id)

    def datastore_records(self, resource_id: str, refresh: bool = False) -> list[dict[str, Any]]:
        """Return every row of a datastore resource, from the local cache when present."""
        cache_file = self.cache_dir / "datagov" / f"{resource_id}.json.gz"
        if cache_file.exists() and not refresh:
            with gzip.open(cache_file, "rt", encoding="utf-8") as f:
                return json.load(f)

        records: list[dict[str, Any]] = []
        while True:
            result = self._action(
                "datastore_search", resource_id=resource_id, limit=PAGE_SIZE, offset=len(records)
            )
            records.extend(result["records"])
            if not result["records"] or len(records) >= result["total"]:
                break

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(cache_file, "wt", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
        return records
