#!/usr/bin/env python3
"""Collect NSE financial-result events from the corporate event calendar."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo


BASE_URL = "https://www.nseindia.com"
PAGE_URL = f"{BASE_URL}/companies-listing/corporate-filings-event-calendar"
API_URL = f"{BASE_URL}/api/event-calendar"
TIMEZONE = ZoneInfo("Asia/Kolkata")
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "financial_results_from_nse.json"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _headers(*, api: bool = False) -> dict[str, str]:
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


def _read_json(opener: Any, url: str, timeout: int) -> Any:
    with opener.open(Request(url, headers=_headers(api=True)), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_event_calendars(timeout: int = 30) -> dict[str, list[dict[str, Any]]]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(Request(PAGE_URL, headers=_headers()), timeout=timeout) as response:
        response.read()

    feeds = {
        "equity": _read_json(opener, API_URL, timeout),
        "sme": _read_json(opener, f"{API_URL}?index=sme", timeout),
    }
    for market_segment, rows in feeds.items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"NSE returned an invalid {market_segment} event-calendar response")
    return feeds


def _text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected {field} to be text, got {value!r}")
    return value.strip() or None


def _event_date(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Financial-result event has an invalid date: {value!r}")
    try:
        return datetime.strptime(value.strip(), "%d-%b-%Y").date().isoformat()
    except ValueError as error:
        raise ValueError(f"Unrecognized NSE event date: {value!r}") from error


def _is_financial_result(row: dict[str, Any], market_segment: str) -> bool:
    purpose_key = "purpose" if market_segment == "equity" else "bm_purpose"
    details_key = "bm_desc"
    purpose = row.get(purpose_key)
    details = row.get(details_key)
    searchable_text = " ".join(
        value.casefold() for value in (purpose, details) if isinstance(value, str)
    )
    return "financial result" in searchable_text


def normalize_event(row: dict[str, Any], market_segment: str) -> dict[str, Any]:
    is_sme = market_segment == "sme"
    event = {
        "event_date": _event_date(row.get("bm_date" if is_sme else "date")),
        "market_segment": market_segment,
        "symbol": _text(row.get("bm_symbol" if is_sme else "symbol"), "symbol"),
        "company_name": _text(row.get("sm_name" if is_sme else "company"), "company name"),
        "purpose": _text(row.get("bm_purpose" if is_sme else "purpose"), "purpose"),
        "details": _text(row.get("bm_desc"), "event details"),
    }
    if is_sme:
        event.update(
            {
                "announcement_timestamp": _text(row.get("bm_timestamp"), "announcement timestamp"),
                "isin": _text(row.get("sm_isin"), "ISIN"),
                "attachment_url": _text(row.get("attachment"), "attachment URL"),
                "ixbrl_url": _text(row.get("ixbrl"), "iXBRL URL"),
            }
        )
    return event


def collect_events(
    feeds: dict[str, list[dict[str, Any]]], now: datetime | None = None
) -> list[dict[str, Any]]:
    captured_at = now.astimezone(TIMEZONE) if now else datetime.now(TIMEZONE)
    captured_at_text = captured_at.isoformat(timespec="seconds")
    events = []
    for market_segment, rows in feeds.items():
        if market_segment not in {"equity", "sme"}:
            raise ValueError(f"Unexpected NSE market segment: {market_segment}")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"Invalid event-calendar rows for {market_segment}")
        for row in rows:
            if _is_financial_result(row, market_segment):
                event = normalize_event(row, market_segment)
                event["captured_at"] = captured_at_text
                events.append(event)

    events.sort(
        key=lambda event: (
            event["event_date"],
            event["market_segment"],
            event["symbol"] or "",
            event["purpose"] or "",
            event["details"] or "",
        )
    )
    return events


def empty_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "NSE India",
        "source_url": PAGE_URL,
        "timezone": "Asia/Kolkata",
        "retention": "unlimited",
        "updated_at": None,
        "data": [],
    }


def _event_identity(event: dict[str, Any]) -> str:
    stable_content = {key: value for key, value in event.items() if key != "captured_at"}
    return json.dumps(stable_content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def add_new_events(
    document: dict[str, Any], events: list[dict[str, Any]]
) -> tuple[dict[str, Any], int]:
    records = document.get("data")
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError("Existing NSE financial-results file has an invalid 'data' field")

    known_events = {_event_identity(record) for record in records}
    new_events = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("NSE financial-results collection contains an invalid event")
        identity = _event_identity(event)
        if identity not in known_events:
            known_events.add(identity)
            new_events.append(event)

    if not new_events:
        return document, 0

    combined = [*records, *new_events]
    combined.sort(
        key=lambda event: (
            event.get("event_date", ""),
            event.get("market_segment", ""),
            event.get("symbol") or "",
            event.get("purpose") or "",
            event.get("details") or "",
        )
    )
    updated = {
        **document,
        "data": combined,
        "updated_at": max(event["captured_at"] for event in new_events),
    }
    return updated, len(new_events)


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
    events = collect_events(fetch_event_calendars())
    document = empty_document()
    if DATA_FILE.exists():
        with DATA_FILE.open(encoding="utf-8") as data_file:
            document = json.load(data_file)
        if not isinstance(document, dict):
            raise ValueError("Existing NSE financial-results file must contain a JSON object")

    updated, added_count = add_new_events(document, events)
    if not added_count:
        print(f"No new financial-result events ({len(events)} currently listed by NSE)")
        return

    write_json_atomically(DATA_FILE, updated)
    print(f"Added {added_count} financial-result events to {DATA_FILE} (unlimited history)")


if __name__ == "__main__":
    main()