# cronjobs
Cron jobs for various use cases 

## Groww NIFTY 500 market snapshot

`stock_market/scraper/top_gainer_looser_from_groww.py` collects Groww's top
gainers, top losers, 52-week highs, and 52-week lows for the NIFTY 500. It
reads the server-rendered stock data and writes a dated snapshot to
[`stock_market/data/top_gainers_loosers_from_groww.json`](stock_market/data/top_gainers_loosers_from_groww.json).
Each record includes source URLs, capture time, rank, stock identifiers, prices,
day change and percentage, market cap, volume, and 52-week range where provided
by Groww. The JSON retains the current date and the previous 14 calendar dates;
a rerun on the same day replaces that day's snapshot. A snapshot whose index
and category data exactly match any stored snapshot is skipped (timestamps and
dates do not affect the comparison), avoiding entries for market holidays or
other unchanged trading data.

The scraper uses only the Python standard library. Run it manually with:

```sh
python3 stock_market/scraper/top_gainer_looser_from_groww.py
```

To schedule it Monday through Friday at 4:00 PM India time, replace the
repository path in `stock_market/crontab`, then install those entries with
`crontab stock_market/crontab`. The schedule uses `CRON_TZ=Asia/Kolkata`;
scraper output and errors are appended to
`stock_market/scraper/groww_scraper.log`. The host must have cron enabled and
network access to Groww.

The [Stock market scrapers GitHub Actions workflow](.github/workflows/stock-market-scrapers.yml)
runs all three scrapers on the same weekday 4:00 PM India schedule
(10:30 UTC), commits changed JSON data, and can also be started manually from
the Actions tab. Repository Actions must be enabled, and the workflow's
`GITHUB_TOKEN` must be allowed to write contents for its data commits.

## NSE bulk-deal history

`stock_market/scraper/bulk_deals_from_nse.py` reads the bulk-deals JSON feed
used by NSE's [Large Deals](https://www.nseindia.com/market-data/large-deals)
page and writes normalized table rows to
[`stock_market/data/bulk_deals_from_nse.json`](stock_market/data/bulk_deals_from_nse.json).
Rows are grouped by their table date, not the scraper's run date. It keeps the
15 most recent dates in the table, skips an existing date when its deal rows
are identical, and replaces that date's entry if NSE publishes corrected rows.
An empty table adds no entry.

Run it manually with:

```sh
python3 stock_market/scraper/bulk_deals_from_nse.py
```

The weekday 4:00 PM Asia/Kolkata cron entry is in `stock_market/crontab` and
logs to `stock_market/scraper/nse_bulk_deals_scraper.log`. NSE access may be
rate-limited; HTTP and payload errors are reported rather than written as
successful empty data.

## NSE financial-results event history

`stock_market/scraper/financial_results_from_nse.py` collects equity and SME
events mentioning financial results from NSE's
[Corporate Filings Event Calendar](https://www.nseindia.com/companies-listing/corporate-filings-event-calendar)
and stores them in
[`stock_market/data/financial_results_from_nse.json`](stock_market/data/financial_results_from_nse.json).
Each entry preserves the event date from NSE, company/symbol, purpose, event
details, market segment, and available SME filing metadata. The JSON history is
unlimited: exact duplicate events are ignored (collection timestamps do not
cause duplicates), and entries remain date-sortable for historical use.

Run it manually with:

```sh
python3 stock_market/scraper/financial_results_from_nse.py
```

Its weekday 4:00 PM Asia/Kolkata cron entry is in `stock_market/crontab` and
logs to `stock_market/scraper/nse_financial_results_scraper.log`.
