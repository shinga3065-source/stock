# Stock Report Automation

매일 한국시간 오후 4시에 미국 정규장 기준 저가주 거래량 Top 20 보고서를 생성합니다.

## Output

- 웹사이트 시작점: `index.html`
- Markdown 보고서: `reports/us_low_price_volume/YYYY-MM-DD.md`
- 웹사이트: `site/index.html`

## Manual Run

```bash
scripts/run_daily_us_stock_report.sh
```

## Scheduled Run

```bash
scripts/install_launchd_job.sh
```

## GitHub Daily Automation

GitHub Actions also runs the report every day at 07:00 UTC, which is 16:00 in Korea.

- Workflow: `.github/workflows/daily-report.yml`
- Manual run: GitHub → Actions → `Daily stock report` → `Run workflow`
- Output committed back to the repo:
  - `reports/us_low_price_volume/YYYY-MM-DD.md`
  - `site/index.html`
  - `site/reports/YYYY-MM-DD.html`

### Korean Auto Translation

For automatic Korean translation, add this repository secret:

- `OPENAI_API_KEY`

Optional repository variable:

- `OPENAI_TRANSLATION_MODEL` defaults to `gpt-4o-mini`

If `OPENAI_API_KEY` is missing, the workflow still runs. Company descriptions fall back to a short Korean sector/industry summary, and SEC filings still receive Korean form-type explanations.
