# Daily US Low-Price Volume Report Workflow

## Goal

Every day at 16:00 Asia/Seoul time, create a Markdown report for the most recent completed US regular trading session.

The report ranks US-listed stocks by regular-session volume, filtered to closing prices from USD 1.00 through USD 10.00, and includes the top 20 companies.

## Output

Write one report per trading date:

`reports/us_low_price_volume/YYYY-MM-DD.md`

Also rebuild the static website after each report:

- `site/index.html`
- `site/reports/YYYY-MM-DD.html`

## Selection Rules

1. Use the most recent completed US regular trading session from the current Asia/Seoul execution time.
2. Include stocks with close price >= 1.00 and <= 10.00.
3. Sort by regular-session volume descending.
4. Keep the top 20 companies.

## Required Sections

1. Report header with trading date, generation time, and selection criteria.
2. Top 20 summary table with rank, ticker, company, close, volume, percent change, news count, and recent earnings/filing flag.
3. Company sections with:
   - Company overview
   - Market data
   - News from the last 5 calendar days, including publication date
   - Recent earnings releases or earnings-related SEC filings

## Data Sources

Use free sources first:

- Yahoo Finance unofficial endpoints for screener, quote, and company profile data.
- Google News RSS for recent news discovery.
- SEC EDGAR public JSON endpoints for company ticker mapping and recent filings.

If a source fails, keep building the report and mark the failing field as unavailable. Do not hide failures.

## Failure Handling

- A single-symbol failure must not stop the full report.
- Log source errors to stderr.
- In the report, show "수집 실패" or "최근 5일 내 확인된 실적 발표/관련 공시 없음" where appropriate.
- Do not store secrets in code or workflow files.

## Manual Run

```bash
scripts/run_daily_us_stock_report.sh
```

Open the website locally from:

`site/index.html`

## Scheduled Run

Use the launchd plist in:

`launchd/com.codex.us-low-price-volume-report.plist`

The job writes logs to:

- `.tmp/daily_us_stock_report.out.log`
- `.tmp/daily_us_stock_report.err.log`

## GitHub Scheduled Run

The GitHub Actions workflow `.github/workflows/daily-report.yml` runs daily at 07:00 UTC, which is 16:00 Asia/Seoul.

The workflow:

1. Checks out the repository.
2. Runs `scripts/run_daily_us_stock_report.sh`.
3. Rebuilds the Markdown report and static website.
4. Commits changed report/site files back to `main`.

For automatic Korean translation of company descriptions and news summaries, set the repository secret `OPENAI_API_KEY`. If it is not set, the report still runs and includes Korean fallback summaries plus Korean explanations of SEC filing types.
