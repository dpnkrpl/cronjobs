#!/usr/bin/env python3
"""Render the repository README from the saved stock-market JSON snapshots."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "stock_market" / "data"
README_FILE = ROOT_DIR / "README.md"
TIMEZONE = ZoneInfo("Asia/Kolkata")
TOP_COUNT = 10


def load_document(filename: str) -> dict[str, Any]:
    path = DATA_DIR / filename
    if not path.exists():
        return {"data": [], "updated_at": None}
    with path.open(encoding="utf-8") as data_file:
        document = json.load(data_file)
    if not isinstance(document, dict) or not isinstance(document.get("data", []), list):
        raise ValueError(f"Invalid stock-market data document: {path}")
    if any(not isinstance(record, dict) for record in document.get("data", [])):
        raise ValueError(f"Invalid record in stock-market data document: {path}")
    return document


def latest_record(records: list[dict[str, Any]], date_field: str) -> dict[str, Any] | None:
    dated_records = [record for record in records if isinstance(record.get(date_field), str)]
    return max(dated_records, key=lambda record: record[date_field]) if dated_records else None


def format_percent(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "N/A"
    marker = ":green_circle: " if value > 0 else ":red_circle: " if value < 0 else ""
    return f"{marker}{value:+.2f}%"


def format_number(value: Any, decimals: int = 2) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "N/A"
    if decimals == 0:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def markdown_cell(value: Any) -> str:
    return " ".join(str(value if value is not None else "N/A").replace("|", "\\|").split())


def latest_snapshot_label(record: dict[str, Any] | None, date_field: str) -> str:
    return record.get(date_field, "no snapshot") if record else "no snapshot"


def latest_fetch_label(documents: list[dict[str, Any]]) -> str:
    fetch_times = []
    for document in documents:
        value = document.get("updated_at")
        if not isinstance(value, str):
            continue
        try:
            fetched_at = datetime.fromisoformat(value)
        except ValueError:
            continue
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=TIMEZONE)
        fetch_times.append(fetched_at.astimezone(TIMEZONE))
    if not fetch_times:
        return "unavailable"
    return max(fetch_times).strftime("%Y-%m-%d %H:%M:%S IST")


def market_values(
    records: list[dict[str, Any]],
    items_field: str,
    name_field: str,
    change_field: str,
    *,
    limit: int | None = None,
) -> list[tuple[str, dict[str, float]]]:
    snapshots = []
    for record in sorted(records, key=lambda item: item.get("date", "")):
        date = record.get("date")
        items = record.get(items_field)
        if not isinstance(date, str) or not isinstance(items, list):
            continue
        values: dict[str, float] = {}
        for item in items[:limit] if limit is not None else items:
            if not isinstance(item, dict):
                continue
            name = item.get(name_field)
            change = item.get(change_field)
            if (
                isinstance(name, str)
                and name
                and isinstance(change, (int, float))
                and not isinstance(change, bool)
            ):
                values[name] = float(change)
        snapshots.append((date, values))
    return snapshots


def find_streaks(
    snapshots: list[tuple[str, dict[str, float]]],
) -> list[dict[str, Any]]:
    active: dict[str, list[tuple[str, float]]] = {}
    streaks: list[dict[str, Any]] = []

    def finish_streak(symbol: str, run: list[tuple[str, float]]) -> None:
        if len(run) < 2:
            return
        total_multiplier = 1.0
        for _, change in run:
            total_multiplier *= 1 + change / 100
        streaks.append(
            {
                "symbol": symbol,
                "snapshots": len(run),
                "start": run[0][0],
                "end": run[-1][0],
                "change_percent": (total_multiplier - 1) * 100,
            }
        )

    for date, values in sorted(snapshots, key=lambda snapshot: snapshot[0]):
        next_active: dict[str, list[tuple[str, float]]] = {}
        for symbol, change in values.items():
            run = active.get(symbol, [])
            next_active[symbol] = [*run, (date, change)]
        for next_symbol, run in active.items():
            if next_symbol not in next_active:
                finish_streak(next_symbol, run)
        active = next_active

    for next_symbol, run in active.items():
        finish_streak(next_symbol, run)
    return streaks


def render_streaks(
    snapshots: list[tuple[str, dict[str, float]]],
    *,
    reverse_return: bool = True,
) -> str:
    streaks = find_streaks(snapshots)
    streaks.sort(
        key=lambda streak: (
            -streak["snapshots"],
            -streak["change_percent"] if reverse_return else streak["change_percent"],
            streak["symbol"],
        )
    )
    if not streaks:
        return "No multi-snapshot streaks found in the available history."

    lines = [
        f"- `{streak['symbol']}`: {streak['snapshots']} consecutive snapshots "
        f"({streak['start']} to {streak['end']}), "
        f"{format_percent(streak['change_percent'])} compounded."
        for streak in streaks[:TOP_COUNT]
    ]
    return "\n".join(lines)


def render_bulk_deals(records: list[dict[str, Any]]) -> str:
    latest = latest_record(records, "deal_date")
    if latest is None:
        return "No bulk-deal snapshot is available."

    deals = latest.get("deals", [])
    if not isinstance(deals, list):
        raise ValueError("Bulk-deal snapshot has an invalid deals list")
    deals = sorted(
        (deal for deal in deals if isinstance(deal, dict)),
        key=lambda deal: deal.get("quantity") if isinstance(deal.get("quantity"), (int, float)) else -1,
        reverse=True,
    )
    count = latest.get("count", len(deals))
    lines = [
        f"Latest available snapshot: **{latest_snapshot_label(latest, 'deal_date')}**, "
        f"with {count} reported deal rows. Showing the {min(TOP_COUNT, len(deals))} "
        "largest rows by quantity.",
        "",
        "| Symbol | Side | Quantity | Avg. price | Client |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for deal in deals[:TOP_COUNT]:
        lines.append(
            "| "
            + " | ".join(
                (
                    markdown_cell(deal.get("symbol")),
                    {"BUY": ":green_circle:", "SELL": ":red_circle:"}.get(
                        deal.get("buy_sell"), markdown_cell(deal.get("buy_sell"))
                    ),
                    format_number(deal.get("quantity"), 0),
                    format_number(deal.get("weighted_average_trade_price")),
                    markdown_cell(deal.get("client_name")),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def render_results(records: list[dict[str, Any]], today: str) -> str:
    by_date: dict[str, set[str]] = {}
    for record in records:
        event_date = record.get("event_date")
        symbol = record.get("symbol")
        if isinstance(event_date, str) and event_date >= today and isinstance(symbol, str) and symbol:
            by_date.setdefault(event_date, set()).add(symbol)

    if not by_date:
        return f"No results events from **{today}** onward are in the saved calendar."

    lines = [
        f"NSE financial-result symbols from **{today}** onward, grouped by event date.",
        "",
    ]
    for event_date in sorted(by_date):
        symbols = sorted(by_date[event_date])
        formatted_symbols = " ".join(f"`{symbol}`" for symbol in symbols)
        symbol_label = "symbol" if len(symbols) == 1 else "symbols"
        lines.append(f"- **{event_date} ({len(symbols)} {symbol_label}):** {formatted_symbols}")
    return "\n".join(lines)


def render_sectors(records: list[dict[str, Any]]) -> str:
    latest = latest_record(records, "date")
    if latest is None:
        table = "No trending-sector snapshot is available."
        streaks = "No multi-snapshot streaks found in the available history."
    else:
        sectors = latest.get("sectors", [])
        if not isinstance(sectors, list):
            raise ValueError("Trending-sector snapshot has an invalid sectors list")
        sectors = [sector for sector in sectors if isinstance(sector, dict)]
        sectors.sort(key=lambda sector: sector.get("rank", float("inf")))
        table_lines = [
            f"Latest available snapshot: **{latest_snapshot_label(latest, 'date')}**. "
            "Top 10 sectors by reported rank; breadth is positive stocks / total stocks.",
            "",
            "| Rank | Sector | Day change | Positive breadth |",
            "| ---: | --- | ---: | ---: |",
        ]
        for sector in sectors[:TOP_COUNT]:
            table_lines.append(
                f"| {markdown_cell(sector.get('rank'))} | {markdown_cell(sector.get('name'))} "
                f"| {format_percent(sector.get('day_change_percent'))} "
                f"| {format_number(sector.get('positive_stocks'), 0)} / "
                f"{format_number(sector.get('total_stocks'), 0)} |"
            )
        table = "\n".join(table_lines)
        sector_history = []
        for record in records:
            sectors_in_record = record.get("sectors", [])
            if isinstance(sectors_in_record, list):
                sectors_in_record = sorted(
                    (sector for sector in sectors_in_record if isinstance(sector, dict)),
                    key=lambda sector: sector.get("rank", float("inf")),
                )[:TOP_COUNT]
            sector_history.append({**record, "sectors": sectors_in_record})
        streaks = render_streaks(
            market_values(sector_history, "sectors", "name", "day_change_percent")
        )

    return (
        f"{table}\n\n**Multi-day sector streaks:** Consecutive appearances in the daily top 10; "
        f"returns are compounded.\n\n{streaks}"
    )


def render_movers(records: list[dict[str, Any]]) -> str:
    latest = latest_record(records, "date")
    if latest is None:
        table = "No gainer/loser snapshot is available."
        gain_streaks = lose_streaks = "No multi-snapshot streaks found in the available history."
    else:
        categories = latest.get("categories", {})
        if not isinstance(categories, dict):
            raise ValueError("Gainer/loser snapshot has invalid categories")
        gainers = categories.get("top_gainers", {}).get("stocks", [])
        losers = categories.get("top_losers", {}).get("stocks", [])
        if not isinstance(gainers, list) or not isinstance(losers, list):
            raise ValueError("Gainer/loser snapshot has an invalid stock list")
        gainers = [stock for stock in gainers if isinstance(stock, dict)][:TOP_COUNT]
        losers = [stock for stock in losers if isinstance(stock, dict)][:TOP_COUNT]
        table_lines = [
            f"Latest available snapshot: **{latest_snapshot_label(latest, 'date')}** "
            f"({markdown_cell(latest.get('index', {}).get('name', 'market index'))}). "
            "Top 10 in each category by daily percentage change.",
            "",
            "| Top gainers | Change | Top losers | Change |",
            "| --- | ---: | --- | ---: |",
        ]
        for index in range(max(len(gainers), len(losers))):
            gainer = gainers[index] if index < len(gainers) else {}
            loser = losers[index] if index < len(losers) else {}
            table_lines.append(
                f"| {markdown_cell(gainer.get('symbol', ''))} "
                f"| {format_percent(gainer.get('change_percent'))} "
                f"| {markdown_cell(loser.get('symbol', ''))} "
                f"| {format_percent(loser.get('change_percent'))} |"
            )
        table = "\n".join(table_lines)

        gain_history = []
        lose_history = []
        for record in records:
            categories = record.get("categories", {})
            if not isinstance(categories, dict):
                continue
            gainers = categories.get("top_gainers", {}).get("stocks", [])
            losers = categories.get("top_losers", {}).get("stocks", [])
            gain_history.append({**record, "stocks": gainers if isinstance(gainers, list) else []})
            lose_history.append({**record, "stocks": losers if isinstance(losers, list) else []})
        gain_streaks = render_streaks(
            market_values(gain_history, "stocks", "symbol", "change_percent"),
        )
        lose_streaks = render_streaks(
            market_values(lose_history, "stocks", "symbol", "change_percent"),
            reverse_return=False,
        )

    return (
        f"{table}\n\n**Multi-day gainers:** Consecutive appearances in the saved top-100 "
        f"gainer snapshots; returns are compounded.\n\n{gain_streaks}\n\n"
        f"**Multi-day losers:** Consecutive appearances in the saved top-100 "
        f"loser snapshots; returns are compounded.\n\n{lose_streaks}"
    )


def build_readme(today: str | None = None) -> str:
    today = today or datetime.now(TIMEZONE).date().isoformat()
    bulk_document = load_document("bulk_deals_from_nse.json")
    results_document = load_document("financial_results_from_nse.json")
    sector_document = load_document("trending_sectors_from_groww.json")
    movers_document = load_document("top_gainers_loosers_from_groww.json")

    snapshot_dates = (
        f"bulk deals: {latest_snapshot_label(latest_record(bulk_document['data'], 'deal_date'), 'deal_date')}; "
        f"sectors: {latest_snapshot_label(latest_record(sector_document['data'], 'date'), 'date')}; "
        f"gainers/losers: {latest_snapshot_label(latest_record(movers_document['data'], 'date'), 'date')}"
    )
    results_updated = results_document.get("updated_at") or "unknown"
    last_fetch = latest_fetch_label(
        [bulk_document, results_document, sector_document, movers_document]
    )
    sections = [
        "# Stock Market Snapshot",
        "",
        f"**Last data fetch (IST):** {last_fetch}",
        "",
        "Generated from the saved JSON files in [`stock_market/data`](stock_market/data). "
        f"Market snapshots are not synchronized: {snapshot_dates} (IST). "
        f"Financial-results calendar last updated: {results_updated}.",
        "",
        "## Today's Bulk Deal",
        "",
        render_bulk_deals(bulk_document["data"]),
        "",
        "## Today's and Upcoming Results",
        "",
        render_results(results_document["data"], today),
        "",
        "## Trending Sectors Today",
        "",
        render_sectors(sector_document["data"]),
        "",
        "## Today's Gainers and Losers",
        "",
        render_movers(movers_document["data"]),
        "",
    ]
    return "\n".join(sections)


def write_readme(content: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=README_FILE.parent,
            prefix=f".{README_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, README_FILE)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    write_readme(build_readme())
    print(f"Updated {README_FILE}")


if __name__ == "__main__":
    main()