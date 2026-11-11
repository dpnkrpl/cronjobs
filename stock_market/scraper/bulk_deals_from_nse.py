#!/usr/bin/env python3
"""Collect NSE bulk-deal table data and maintain a dated JSON history."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo


BASE_URL = "https://www.nseindia.com"
PAGE_URL = f"{BASE_URL}/market-data/large-deals"
API_URL = f"{BASE_URL}/api/snapshot-capital-market-largedeal"
TIMEZONE = ZoneInfo("Asia/Kolkata")
RETENTION_DATES = 15
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "bulk_deals_from_nse.json"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _request_headers(*, api: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    }
    if api:
        headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Referer": PAGE_URL,
                "X-Requested-With": "XMLHttpRequest",
            }
        )
    else:
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    return headers


def fetch_bulk_deals(timeout: int = 30) -> dict[str, Any]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(Request(PAGE_URL, headers=_request_headers()), timeout=timeout) as response:
        response.read()

    with opener.open(
        Request(API_URL, headers=_request_headers(api=True)),
        timeout=timeout,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("NSE bulk-deals API returned an invalid response")
    rows = payload.get("BULK_DEALS_DATA")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("NSE response did not contain a valid bulk-deals table")
    return payload


def parse_table_date(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Bulk-deal row has an invalid date: {value!r}")
    try:
        return datetime.strptime(value.strip(), "%d-%b-%Y").date().isoformat()
    except ValueError as error:
        raise ValueError(f"Unrecognized NSE bulk-deal table date: {value!r}") from error


def _text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected {field} to be text, got {value!r}")
    return value.strip() or None


def _numeric(value: Any, field: str) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"Expected {field} to be numeric, got {value!r}")
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError as error:
        raise ValueError(f"Expected {field} to be numeric, got {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"Expected finite {field}, got {value!r}")
    return int(number) if number.is_integer() else number


def normalize_deal(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "deal_date": parse_table_date(row.get("date")),
        "symbol": _text(row.get("symbol"), "symbol"),
        "company_name": _text(row.get("name"), "company name"),
        "client_name": _text(row.get("clientName"), "client name"),
        "buy_sell": _text(row.get("buySell"), "buy/sell"),
        "quantity": _numeric(row.get("qty"), "quantity"),
        "weighted_average_trade_price": _numeric(row.get("watp"), "weighted average trade price"),
        "remarks": _text(row.get("remarks"), "remarks"),
    }


def collect_snapshots(
    payload: dict[str, Any], now: datetime | None = None
) -> list[dict[str, Any]]:
    rows = payload.get("BULK_DEALS_DATA")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("NSE response did not contain a valid bulk-deals table")

    captured_at = now.astimezone(TIMEZONE) if now else datetime.now(TIMEZONE)
    daily_deals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        deal = normalize_deal(row)
        daily_deals[deal["deal_date"]].append(deal)

    return [
        {
            "deal_date": deal_date,
            "captured_at": captured_at.isoformat(timespec="seconds"),
            "source_url": PAGE_URL,
            "count": len(deals),
            "deals": deals,
        }
        for deal_date, deals in sorted(daily_deals.items())
    ]


def empty_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "NSE India",
        "source_url": PAGE_URL,
        "timezone": "Asia/Kolkata",
        "retention": {
            "dates": RETENTION_DATES,
            "policy": "Keep the 15 most recent dates reported in the bulk-deals table.",
        },
        "updated_at": None,
        "data": [],
    }


def merge_snapshots(
    document: dict[str, Any], snapshots: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str], list[str]]:
    records = document.get("data")
    if not isinstance(records, list):
        raise ValueError("Existing NSE data file has an invalid 'data' field")

    by_date: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("deal_date"), str):
            raise ValueError("Existing NSE data file contains an invalid daily record")
        datetime.strptime(record["deal_date"], "%Y-%m-%d")
        by_date[record["deal_date"]] = record

    changed_dates: list[str] = []
    skipped_dates: list[str] = []
    for snapshot in snapshots:
        deal_date = snapshot.get("deal_date")
        if not isinstance(deal_date, str):
            raise ValueError("NSE snapshot is missing its table deal date")
        datetime.strptime(deal_date, "%Y-%m-%d")
        existing = by_date.get(deal_date)
        if existing is not None and existing.get("deals") == snapshot.get("deals"):
            skipped_dates.append(deal_date)
            continue
        by_date[deal_date] = snapshot
        changed_dates.append(deal_date)

    ordered_records = [by_date[date] for date in sorted(by_date)[-RETENTION_DATES:]]
    updated = {**document, "data": ordered_records}
    if changed_dates:
        updated["updated_at"] = max(
            snapshot["captured_at"]
            for snapshot in snapshots
            if snapshot.get("deal_date") in changed_dates
        )
    return updated, changed_dates, skipped_dates


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
    snapshots = collect_snapshots(fetch_bulk_deals())
    document = empty_document()
    if DATA_FILE.exists():
        with DATA_FILE.open(encoding="utf-8") as data_file:
            document = json.load(data_file)
        if not isinstance(document, dict):
            raise ValueError("Existing NSE data file must contain a JSON object")

    updated, changed_dates, skipped_dates = merge_snapshots(document, snapshots)
    if not changed_dates and updated == document:
        if skipped_dates:
            print(f"Skipped duplicate NSE bulk-deal table date(s): {', '.join(skipped_dates)}")
        else:
            print("No bulk-deal rows returned by NSE; no data saved")
        return

    write_json_atomically(DATA_FILE, updated)
    if changed_dates:
        print(f"Saved NSE bulk-deal data for date(s): {', '.join(changed_dates)}")
    if skipped_dates:
        print(f"Skipped duplicate NSE bulk-deal date(s): {', '.join(skipped_dates)}")


if __name__ == "__main__":
    main()