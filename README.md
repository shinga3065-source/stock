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
