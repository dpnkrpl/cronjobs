#!/usr/bin/env python3
"""Collect daily trending-sector data from Groww."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Kolkata")
RETENTION_DAYS = 15
SOURCE_URL = "https://groww.in/stocks/sectors-trending"
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "trending_sectors_from_groww.json"


class NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._reading_next_data = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._reading_next_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._reading_next_data:
            self._reading_next_data = False

    def handle_data(self, data: str) -> None:
        if self._reading_next_data:
            self._parts.append(data)

    @property
    def payload(self) -> dict[str, Any]:
        if not self._parts:
            raise ValueError("Groww page did not contain its __NEXT_DATA__ payload")
        payload = json.loads("".join(self._parts))
        if not isinstance(payload, dict):
            raise ValueError("Groww page returned an invalid __NEXT_DATA__ payload")
        return payload


def fetch_sectors(timeout: int = 30) -> list[dict[str, Any]]:
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; cronjobs-market-data/1.0)",
            "Accept": "text/html",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8")

    parser = NextDataParser()
    parser.feed(html)
    sectors = parser.payload.get("props", {}).get("pageProps", {}).get("sectors")
    if not isinstance(sectors, list) or not sectors or any(
        not isinstance(sector, dict) for sector in sectors
    ):
        raise ValueError("Groww page did not contain a valid trending-sector list")
    return sectors


def _number(value: Any, field: str, *, required: bool = False) -> float | int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Expected a numeric {field}, got {value!r}")
    return value


def normalize_sector(sector: dict[str, Any], rank: int) -> dict[str, Any]:
    name = sector.get("sectorName")
    if not isinstance(name, str) or not name:
        raise ValueError(f"Sector at rank {rank} has no name")

    return {
        "rank": rank,
        "name": name,
        "industry_code": sector.get("industryCode"),
        "logo_url": sector.get("sectorLogo"),
        "dark_logo_url": sector.get("darkLogo"),
        "total_stocks": _number(sector.get("totalStocks"), "totalStocks", required=True),
        "positive_stocks": _number(
            sector.get("positiveStocks"), "positiveStocks", required=True
        ),
        "negative_stocks": _number(
            sector.get("negativeStocks"), "negativeStocks", required=True
        ),
        "day_change_percent": _number(
            sector.get("dayChangePercent"), "dayChangePercent", required=True
        ),
    }


def collect_snapshot(now: datetime | None = None) -> dict[str, Any]:
    captured_at = now.astimezone(TIMEZONE) if now else datetime.now(TIMEZONE)
    sectors = fetch_sectors()
    normalized_sectors = [
        normalize_sector(sector, rank)
        for rank, sector in enumerate(sectors, start=1)
    ]
    return {
        "date": captured_at.date().isoformat(),
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "source_url": SOURCE_URL,
        "count": len(normalized_sectors),
        "sectors": normalized_sectors,
    }


def empty_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "Groww",
        "source_url": SOURCE_URL,
        "timezone": "Asia/Kolkata",
        "retention": {
            "days": RETENTION_DAYS,
            "policy": "Keep the current date and the previous 14 calendar dates.",
        },
        "updated_at": None,
        "data": [],
    }


def update_document(
    document: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any] | None:
    records = document.get("data")
    if not isinstance(records, list):
        raise ValueError("Existing Groww sector file has an invalid 'data' field")

    current_date = datetime.strptime(snapshot["date"], "%Y-%m-%d").date()
    oldest_date = current_date - timedelta(days=RETENTION_DAYS - 1)
    retained: list[dict[str, Any]] = []
    same_date_record: dict[str, Any] | None = None
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("date"), str):
            raise ValueError("Existing Groww sector file contains an invalid daily record")
        record_date = datetime.strptime(record["date"], "%Y-%m-%d").date()
        if oldest_date <= record_date <= current_date:
            retained.append(record)
            if record["date"] == snapshot["date"]:
                same_date_record = record

    if same_date_record is not None:
        if same_date_record.get("sectors") == snapshot.get("sectors"):
            updated = {**document, "data": sorted(retained, key=lambda item: item["date"])}
            return updated if updated != document else None
        retained = [
            record for record in retained if record["date"] != snapshot["date"]
        ]
    elif any(record.get("sectors") == snapshot.get("sectors") for record in retained):
        updated = {**document, "data": sorted(retained, key=lambda item: item["date"])}
        return updated if updated != document else None

    retained.append(snapshot)
    retained.sort(key=lambda record: record["date"])
    return {
        **document,
        "data": retained,
        "updated_at": snapshot["captured_at"],
    }


def write_json_atomically(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(document, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    snapshot = collect_snapshot()
    document = empty_document()
    if DATA_FILE.exists():
        with DATA_FILE.open(encoding="utf-8") as data_file:
            document = json.load(data_file)
        if not isinstance(document, dict):
            raise ValueError("Existing Groww sector file must contain a JSON object")

    updated = update_document(document, snapshot)
    if updated is None:
        print(
            f"Skipped {snapshot['date']} sector snapshot: market data matches "
            "an existing snapshot"
        )
        return

    write_json_atomically(DATA_FILE, updated)
    print(
        f"Saved {snapshot['date']} sector snapshot to {DATA_FILE} "
        f"({snapshot['count']} sectors)"
    )


if __name__ == "__main__":
    main()