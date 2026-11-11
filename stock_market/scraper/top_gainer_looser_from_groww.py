#!/usr/bin/env python3
"""Collect daily NIFTY 500 market lists from Groww."""

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


INDEX_ID = "GIDXNIFTY500"
TIMEZONE = ZoneInfo("Asia/Kolkata")
RETENTION_DAYS = 15
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "top_gainers_loosers_from_groww.json"
SOURCE_URLS = {
    "top_gainers": f"https://groww.in/markets/top-gainers?index={INDEX_ID}",
    "top_losers": f"https://groww.in/markets/top-losers?index={INDEX_ID}",
    "week_52_high": f"https://groww.in/markets/52-week-high?index={INDEX_ID}",
    "week_52_low": f"https://groww.in/markets/52-week-low?index={INDEX_ID}",
}


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
        return json.loads("".join(self._parts))


def fetch_page_props(url: str, timeout: int = 30) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; cronjobs-market-data/1.0)",
            "Accept": "text/html",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8")

    parser = NextDataParser()
    parser.feed(html)
    page_props = parser.payload.get("props", {}).get("pageProps")
    if not isinstance(page_props, dict):
        raise ValueError(f"Unexpected Groww page payload at {url}")
    stocks = page_props.get("stocks")
    if not isinstance(stocks, list) or any(not isinstance(stock, dict) for stock in stocks):
        raise ValueError(f"Missing or invalid stock list at {url}")
    return page_props


def _number(value: Any, field: str, *, required: bool = False) -> float | int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Expected a numeric {field}, got {value!r}")
    return value


def normalize_stock(stock: dict[str, Any], rank: int) -> dict[str, Any]:
    company_name = stock.get("companyName")
    if not isinstance(company_name, str) or not company_name:
        raise ValueError(f"Stock at rank {rank} has no company name")

    price = _number(stock.get("ltp"), "ltp", required=True)
    previous_close = _number(stock.get("close"), "close")
    change = None
    change_percent = None
    if previous_close is not None:
        change = round(price - previous_close, 4)
        if previous_close != 0:
            change_percent = round(change / previous_close * 100, 4)

    return {
        "rank": rank,
        "isin": stock.get("isin"),
        "symbol": stock.get("nseScriptCode"),
        "bse_code": stock.get("bseScriptCode"),
        "company_name": company_name,
        "company_short_name": stock.get("companyShortName"),
        "search_id": stock.get("searchId"),
        "stock_type": stock.get("type"),
        "price": price,
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_percent,
        "market_cap": _number(stock.get("marketCap"), "marketCap"),
        "average_weekly_volume": _number(stock.get("volumeWeekAvg"), "volumeWeekAvg"),
        "week_52_high": _number(stock.get("yearHigh"), "yearHigh"),
        "week_52_low": _number(stock.get("yearLow"), "yearLow"),
        "logo_url": stock.get("logoUrl"),
        "tag": stock.get("tag"),
        "tag_color": stock.get("tagColor"),
    }


def collect_snapshot(now: datetime | None = None) -> dict[str, Any]:
    captured_at = now.astimezone(TIMEZONE) if now else datetime.now(TIMEZONE)
    categories = {}
    for category, url in SOURCE_URLS.items():
        page_props = fetch_page_props(url)
        categories[category] = {
            "source_url": url,
            "count": len(page_props["stocks"]),
            "stocks": [
                normalize_stock(stock, rank)
                for rank, stock in enumerate(page_props["stocks"], start=1)
            ],
        }

    return {
        "date": captured_at.date().isoformat(),
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "index": {"id": INDEX_ID, "name": "NIFTY 500"},
        "categories": categories,
    }


def empty_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "Groww",
        "timezone": "Asia/Kolkata",
        "retention": {
            "days": RETENTION_DAYS,
            "policy": "Keep the current date and the previous 14 calendar dates.",
        },
        "updated_at": None,
        "data": [],
    }


def snapshot_matches_existing(records: list[Any], snapshot: dict[str, Any]) -> bool:
    if "index" not in snapshot or "categories" not in snapshot:
        return False

    content = (snapshot.get("index"), snapshot.get("categories"))
    return any(
        isinstance(record, dict)
        and "index" in record
        and "categories" in record
        and (record.get("index"), record.get("categories")) == content
        for record in records
    )


def update_document(
    document: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any] | None:
    records = document.get("data")
    if not isinstance(records, list):
        raise ValueError("Existing data file has an invalid 'data' field")

    if snapshot_matches_existing(records, snapshot):
        return None

    current_date = datetime.strptime(snapshot["date"], "%Y-%m-%d").date()
    oldest_date = current_date - timedelta(days=RETENTION_DAYS - 1)
    retained = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("date"), str):
            raise ValueError("Existing data file contains an invalid daily record")
        record_date = datetime.strptime(record["date"], "%Y-%m-%d").date()
        if oldest_date <= record_date < current_date:
            retained.append(record)

    retained.append(snapshot)
    retained.sort(key=lambda record: record["date"])
    document["data"] = retained
    document["updated_at"] = snapshot["captured_at"]
    return document


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
            raise ValueError("Existing data file must contain a JSON object")

    updated = update_document(document, snapshot)
    if updated is None:
        print(
            f"Skipped {snapshot['date']} snapshot: market data exactly matches "
            "an existing snapshot"
        )
        return

    write_json_atomically(DATA_FILE, updated)
    print(
        f"Saved {snapshot['date']} snapshot to {DATA_FILE} "
        f"({sum(category['count'] for category in snapshot['categories'].values())} stocks)"
    )


if __name__ == "__main__":
    main()