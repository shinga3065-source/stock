#!/usr/bin/env python3
"""Create a daily US low-price, high-volume stock report.

The tool intentionally keeps each data source isolated. Free web endpoints can
change without notice, so failures are recorded per source instead of stopping
the entire report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "us_low_price_volume"
TMP_DIR = ROOT / ".tmp"

SEOUL = ZoneInfo("Asia/Seoul")
NEW_YORK = ZoneInfo("America/New_York")

USER_AGENT = os.environ.get(
    "STOCK_REPORT_USER_AGENT",
    "codex-daily-stock-report/1.0 contact: local-user@example.com",
)

EARNINGS_KEYWORDS = (
    "earnings",
    "quarterly results",
    "financial results",
    "results of operations",
    "10-q",
    "10-k",
    "8-k",
)


@dataclass
class StockCandidate:
    symbol: str
    company: str
    close: Optional[float]
    previous_close: Optional[float]
    volume: Optional[int]
    exchange: str = ""
    currency: str = "USD"
    sector: str = ""
    industry: str = ""

    @property
    def change_pct(self) -> Optional[float]:
        if self.close is None or not self.previous_close:
            return None
        return ((self.close - self.previous_close) / self.previous_close) * 100


@dataclass
class CompanyProfile:
    sector: str = "수집 실패"
    industry: str = "수집 실패"
    summary: str = "수집 실패"
    website: str = ""


@dataclass
class NewsItem:
    title: str
    publisher: str
    published: Optional[dt.datetime]
    summary: str
    link: str


@dataclass
class FilingItem:
    filed_at: str
    form: str
    title: str
    link: str
    summary: str = ""


@dataclass
class StockReportItem:
    stock: StockCandidate
    profile: CompanyProfile = field(default_factory=CompanyProfile)
    news: List[NewsItem] = field(default_factory=list)
    filings: List[FilingItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def http_get_json(url: str, *, timeout: int = 25) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent_for_url(url),
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_post_json(url: str, payload: Dict[str, Any], *, timeout: int = 25) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "User-Agent": user_agent_for_url(url),
            "Content-Type": "application/json",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_get_text(url: str, *, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent_for_url(url),
            "Accept": "application/rss+xml,application/xml,text/xml,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def user_agent_for_url(url: str) -> str:
    if "sec.gov" in url:
        return USER_AGENT
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def most_recent_completed_us_session(now: Optional[dt.datetime] = None) -> dt.date:
    """Return the most recent regular US session date.

    This handles weekends and the normal 16:00 ET close. It does not include a
    full exchange holiday calendar; if a free quote source has no data for a
    market holiday, the report still records the source failure.
    """

    now = now or dt.datetime.now(SEOUL)
    ny_now = now.astimezone(NEW_YORK)
    session = ny_now.date()
    market_close = dt.datetime.combine(session, dt.time(16, 0), NEW_YORK)
    if ny_now < market_close:
        session -= dt.timedelta(days=1)
    while session.weekday() >= 5:
        session -= dt.timedelta(days=1)
    return session


def nasdaq_screener_candidates(limit: int) -> List[StockCandidate]:
    """Fetch all Nasdaq screener rows, then filter and sort locally."""

    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true"
    data = http_get_json(url)
    rows = data.get("data", {}).get("rows", [])
    candidates: List[StockCandidate] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        name = clean_company_name(str(row.get("name") or symbol))
        if not symbol or not is_common_equity(symbol, name):
            continue
        close = parse_money(row.get("lastsale"))
        volume = as_int(str(row.get("volume") or "").replace(",", ""))
        net_change = as_float(str(row.get("netchange") or "").replace(",", ""))
        if close is None or volume is None:
            continue
        if not (1 <= close <= 10):
            continue
        previous_close = close - net_change if net_change is not None else None
        candidates.append(
            StockCandidate(
                symbol=symbol,
                company=name,
                close=close,
                previous_close=previous_close,
                volume=volume,
                exchange="US listed",
                currency="USD",
                sector=clean_text(str(row.get("sector") or "")),
                industry=clean_text(str(row.get("industry") or "")),
            )
        )
    return sorted(candidates, key=lambda item: item.volume or 0, reverse=True)[:limit]


def yahoo_screener_candidates(limit: int) -> List[StockCandidate]:
    """Fallback low-priced stock screener from Yahoo Finance."""

    url = "https://query1.finance.yahoo.com/v1/finance/screener"
    payload = {
        "offset": 0,
        "size": max(limit * 3, 60),
        "sortField": "regularMarketVolume",
        "sortType": "DESC",
        "quoteType": "EQUITY",
        "query": {
            "operator": "and",
            "operands": [
                {
                    "operator": "eq",
                    "operands": ["region", "us"],
                },
                {
                    "operator": "gte",
                    "operands": ["regularMarketPrice", 1],
                },
                {
                    "operator": "lte",
                    "operands": ["regularMarketPrice", 10],
                },
                {
                    "operator": "gt",
                    "operands": ["regularMarketVolume", 0],
                },
            ],
        },
    }
    data = http_post_json(url, payload)
    quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
    candidates: List[StockCandidate] = []
    for quote in quotes:
        close = as_float(quote.get("regularMarketPrice"))
        volume = as_int(quote.get("regularMarketVolume"))
        if close is None or volume is None:
            continue
        if not (1 <= close <= 10):
            continue
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol or "." in symbol or "-" in symbol:
            continue
        candidates.append(
            StockCandidate(
                symbol=symbol,
                company=str(quote.get("shortName") or quote.get("longName") or symbol),
                close=close,
                previous_close=as_float(quote.get("regularMarketPreviousClose")),
                volume=volume,
                exchange=str(quote.get("fullExchangeName") or quote.get("exchange") or ""),
                currency=str(quote.get("currency") or "USD"),
            )
        )
    return sorted(candidates, key=lambda item: item.volume or 0, reverse=True)[:limit]


def company_profile(stock: StockCandidate) -> CompanyProfile:
    try:
        return nasdaq_company_profile(stock)
    except Exception as nasdaq_exc:
        log(f"{stock.symbol}: Nasdaq profile failed: {nasdaq_exc}")
    try:
        return yahoo_quote_summary(stock.symbol)
    except Exception as yahoo_exc:
        log(f"{stock.symbol}: Yahoo profile failed: {yahoo_exc}")
    summary = f"{stock.company}의 회사 설명을 무료 소스에서 수집하지 못했습니다."
    return CompanyProfile(
        sector=stock.sector or "수집 실패",
        industry=stock.industry or "수집 실패",
        summary=summary,
    )


def translated_profile(stock: StockCandidate, profile: CompanyProfile) -> CompanyProfile:
    if not should_translate():
        return profile
    translated = translate_to_korean(
        profile.summary,
        f"{stock.company} 회사 개요를 한국 투자자가 이해하기 쉽게 2~3문장으로 번역/요약",
    )
    if not translated:
        translated = fallback_company_summary(stock, profile)
    return CompanyProfile(
        sector=profile.sector,
        industry=profile.industry,
        summary=translated,
        website=profile.website,
    )


def nasdaq_company_profile(stock: StockCandidate) -> CompanyProfile:
    url = f"https://api.nasdaq.com/api/company/{urllib.parse.quote(stock.symbol)}/company-profile"
    data = http_get_json(url)
    profile = data.get("data") or {}
    return CompanyProfile(
        sector=value_from_nasdaq_field(profile.get("Sector")) or stock.sector or "수집 실패",
        industry=value_from_nasdaq_field(profile.get("Industry")) or stock.industry or "수집 실패",
        summary=value_from_nasdaq_field(profile.get("CompanyDescription")) or "수집 실패",
        website=value_from_nasdaq_field(profile.get("CompanyUrl")) or "",
    )


def yahoo_quote_summary(symbol: str) -> CompanyProfile:
    modules = "assetProfile,price"
    url = (
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
        f"{urllib.parse.quote(symbol)}?modules={modules}"
    )
    data = http_get_json(url)
    result = data.get("quoteSummary", {}).get("result") or []
    if not result:
        raise ValueError("Yahoo quote summary returned no result")
    asset = result[0].get("assetProfile") or {}
    summary = clean_text(str(asset.get("longBusinessSummary") or "수집 실패"))
    return CompanyProfile(
        sector=str(asset.get("sector") or "수집 실패"),
        industry=str(asset.get("industry") or "수집 실패"),
        summary=summary,
        website=str(asset.get("website") or ""),
    )


def google_news(symbol: str, company: str, days: int) -> List[NewsItem]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    query = f'"{symbol}" "{company}" stock OR shares'
    params = urllib.parse.urlencode(
        {
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
    )
    xml_text = http_get_text(f"https://news.google.com/rss/search?{params}")
    root = ET.fromstring(xml_text)
    items: List[NewsItem] = []
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title") or "")
        link = item.findtext("link") or ""
        source_el = item.find("source")
        publisher = clean_text(source_el.text if source_el is not None else "Google News")
        published = parse_rss_date(item.findtext("pubDate") or "")
        if published and published.astimezone(dt.timezone.utc) < cutoff:
            continue
        summary = summarize_news_title(title, company)
        items.append(NewsItem(title=title, publisher=publisher, published=published, summary=summary, link=link))
        if len(items) >= 4:
            break
    return items


def load_sec_ticker_map() -> Dict[str, str]:
    cache_file = TMP_DIR / "sec_company_tickers.json"
    cache_max_age = dt.timedelta(days=7)
    if cache_file.exists():
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromtimestamp(cache_file.stat().st_mtime, dt.timezone.utc)
        if age < cache_max_age:
            return parse_sec_ticker_map(json.loads(cache_file.read_text(encoding="utf-8")))
    data = http_get_json("https://www.sec.gov/files/company_tickers.json")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return parse_sec_ticker_map(data)


def parse_sec_ticker_map(data: Dict[str, Any]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for row in data.values():
        ticker = str(row.get("ticker") or "").upper()
        cik = str(row.get("cik_str") or "").zfill(10)
        if ticker and cik:
            mapping[ticker] = cik
    return mapping


def sec_recent_filings(symbol: str, ticker_map: Dict[str, str], days: int) -> List[FilingItem]:
    cik = ticker_map.get(symbol.upper())
    if not cik:
        return []
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = http_get_json(url)
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])
    cutoff = most_recent_completed_us_session() - dt.timedelta(days=days)
    filings: List[FilingItem] = []
    for form, filed_at, accession, doc, description in zip(forms, dates, accessions, primary_docs, descriptions):
        if not filed_at:
            continue
        try:
            filed_date = dt.date.fromisoformat(filed_at)
        except ValueError:
            continue
        if filed_date < cutoff:
            continue
        title = clean_text(str(description or form or "SEC filing"))
        searchable = f"{form} {title}".lower()
        if form not in {"8-K", "10-Q", "10-K"} and not any(keyword in searchable for keyword in EARNINGS_KEYWORDS):
            continue
        accession_clean = str(accession).replace("-", "")
        link = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{doc}"
        form_text = str(form)
        filings.append(
            FilingItem(
                filed_at=filed_at,
                form=form_text,
                title=title,
                link=link,
                summary=filing_summary_ko(form_text, title),
            )
        )
        if len(filings) >= 3:
            break
    return filings


def build_report(limit: int, days: int, output_dir: Path, session_date: Optional[dt.date] = None) -> Path:
    generated_at = dt.datetime.now(SEOUL)
    session_date = session_date or most_recent_completed_us_session(generated_at)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        candidates = nasdaq_screener_candidates(limit)
    except Exception as nasdaq_exc:
        log(f"Nasdaq screener failed, trying Yahoo fallback: {nasdaq_exc}")
        candidates = yahoo_screener_candidates(limit)
    if not candidates:
        raise RuntimeError("No candidates returned by free screeners")

    try:
        ticker_map = load_sec_ticker_map()
    except Exception as exc:
        ticker_map = {}
        log(f"SEC ticker map failed: {exc}")

    report_items: List[StockReportItem] = []
    for stock in candidates:
        item = StockReportItem(stock=stock)
        try:
            item.profile = translated_profile(stock, company_profile(stock))
        except Exception as exc:
            message = f"profile failed: {exc}"
            item.errors.append(message)
            log(f"{stock.symbol}: {message}")
        try:
            item.news = google_news(stock.symbol, stock.company, days)
            if should_translate():
                for news in item.news:
                    translated_summary = translate_to_korean(
                        news.title,
                        f"{stock.company} 관련 뉴스 제목을 한국어로 한 문장 요약",
                    )
                    if translated_summary:
                        news.summary = translated_summary
        except Exception as exc:
            message = f"news failed: {exc}"
            item.errors.append(message)
            log(f"{stock.symbol}: {message}")
        try:
            item.filings = sec_recent_filings(stock.symbol, ticker_map, days)
        except Exception as exc:
            message = f"SEC filings failed: {exc}"
            item.errors.append(message)
            log(f"{stock.symbol}: {message}")
        report_items.append(item)
        time.sleep(0.2)

    markdown = render_markdown(report_items, session_date, generated_at, limit, days)
    output_path = output_dir / f"{session_date.isoformat()}.md"
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


def render_markdown(
    items: List[StockReportItem],
    session_date: dt.date,
    generated_at: dt.datetime,
    limit: int,
    days: int,
) -> str:
    lines: List[str] = []
    lines.append(f"# 미국 저가주 거래량 Top {limit} 뉴스·공시 보고서")
    lines.append("")
    lines.append(f"- 기준 거래일: {session_date.isoformat()}")
    lines.append(f"- 생성 시각: {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append("- 선정 기준: 미국 정규장 종가 1달러 이상 10달러 이하, 거래량 많은 순")
    lines.append(f"- 뉴스/공시 조회 범위: 최근 {days}일")
    lines.append("")
    lines.append(f"## Top {limit} 요약")
    lines.append("")
    lines.append("| 순위 | 티커 | 회사 | 종가 | 거래량 | 변동률 | 최근 뉴스 | 실적/공시 |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---|")
    for idx, item in enumerate(items, 1):
        stock = item.stock
        lines.append(
            "| {rank} | {symbol} | {company} | {close} | {volume} | {change} | {news_count} | {filing_flag} |".format(
                rank=idx,
                symbol=md_escape(stock.symbol),
                company=md_escape(stock.company),
                close=format_money(stock.close),
                volume=format_int(stock.volume),
                change=format_pct(stock.change_pct),
                news_count=len(item.news),
                filing_flag="있음" if item.filings else "없음",
            )
        )
    lines.append("")
    lines.append("## 회사별 상세")
    lines.append("")
    for idx, item in enumerate(items, 1):
        stock = item.stock
        profile = item.profile
        lines.append(f"### {idx}. {md_escape(stock.company)} ({md_escape(stock.symbol)})")
        lines.append("")
        lines.append(f"- 거래소: {md_escape(stock.exchange or '수집 실패')}")
        lines.append(f"- 섹터/산업: {md_escape(profile.sector)} / {md_escape(profile.industry)}")
        lines.append(f"- 종가: {format_money(stock.close)}")
        lines.append(f"- 거래량: {format_int(stock.volume)}")
        lines.append(f"- 변동률: {format_pct(stock.change_pct)}")
        if profile.website:
            lines.append(f"- 웹사이트: {profile.website}")
        if item.errors:
            lines.append(f"- 수집 참고: {md_escape('; '.join(item.errors))}")
        lines.append("")
        lines.append("**회사 개요**")
        lines.append("")
        lines.append(wrap_paragraph(profile.summary))
        lines.append("")
        lines.append("**최근 5일 뉴스**")
        lines.append("")
        if item.news:
            for news in item.news:
                pub_date = news.published.astimezone(SEOUL).strftime("%Y-%m-%d %H:%M") if news.published else "발행일 수집 실패"
                lines.append(f"- {pub_date} | {md_escape(news.publisher)} | [{md_escape(news.title)}]({news.link})")
                lines.append(f"  - 요약: {md_escape(news.summary)}")
        else:
            lines.append("- 최근 5일 내 확인된 뉴스 없음 또는 뉴스 수집 실패")
        lines.append("")
        lines.append("**최근 공시/실적 발표**")
        lines.append("")
        if item.filings:
            for filing in item.filings:
                lines.append(
                    f"- {filing.filed_at} | {md_escape(filing.form)} | "
                    f"[{md_escape(filing.title)}]({filing.link})"
                )
                if filing.summary:
                    lines.append(f"  - 요약: {md_escape(filing.summary)}")
        else:
            lines.append("- 최근 5일 내 확인된 실적 발표/관련 공시 없음")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_money(value: Any) -> Optional[float]:
    if value is None:
        return None
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    if cleaned in {"", "N/A", "nan"}:
        return None
    return as_float(cleaned)


def as_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def should_translate() -> bool:
    return os.environ.get("STOCK_TRANSLATE_KO", "1") != "0"


def translate_to_korean(text: str, instruction: str) -> str:
    text = clean_text(text)
    if not text or text == "수집 실패" or contains_korean(text):
        return text
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ""
    payload = {
        "model": os.environ.get("OPENAI_TRANSLATION_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": "You translate and summarize financial report text into clear Korean. Return only Korean text.",
            },
            {
                "role": "user",
                "content": f"{instruction}\n\n{textwrap.shorten(text, width=1800, placeholder='...')}",
            },
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        return clean_text(data["choices"][0]["message"]["content"])
    except Exception as exc:
        log(f"translation failed: {exc}")
        return ""


def fallback_company_summary(stock: StockCandidate, profile: CompanyProfile) -> str:
    sector = profile.sector if profile.sector != "수집 실패" else stock.sector or "미분류"
    industry = profile.industry if profile.industry != "수집 실패" else stock.industry or "미분류"
    return (
        f"{stock.company}는 {sector} 섹터의 {industry} 업종에 속한 미국 상장 기업입니다. "
        "자동 번역 API 키가 없어 원문 회사 설명 전체 번역은 생략됐지만, 보고서 생성은 정상 진행됐습니다."
    )


def contains_korean(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text))


def filing_summary_ko(form: str, title: str) -> str:
    normalized = form.upper()
    title_ko = translate_to_korean(title, "SEC 공시 제목을 한국어로 짧게 번역")
    if normalized == "10-Q":
        base = "분기 실적과 재무상태, 현금흐름, 주요 리스크를 담은 정기 보고서입니다."
    elif normalized == "10-K":
        base = "연간 실적과 사업 현황, 재무상태, 주요 리스크를 담은 정기 보고서입니다."
    elif normalized.startswith("8-K"):
        base = "실적 발표, 경영진 변경, 자금 조달, 계약 등 투자자가 알아야 할 주요 사건을 알리는 수시 공시입니다."
    else:
        base = "SEC에 제출된 회사 공시입니다."
    if title_ko and title_ko != title:
        return f"{base} 공시 제목 요약: {title_ko}"
    return base


def clean_company_name(value: str) -> str:
    value = clean_text(value)
    suffixes = (
        " Common Stock",
        " Class A Common Stock",
        " Class B Common Stock",
        " Ordinary Shares",
        " American Depositary Shares",
        " American Depository Shares",
    )
    for suffix in suffixes:
        value = value.replace(suffix, "")
    return clean_text(value)


def is_common_equity(symbol: str, name: str) -> bool:
    if any(char in symbol for char in ("^", "/", "=")):
        return False
    lowered = name.lower()
    excluded_terms = (
        "warrant",
        "rights",
        "unit",
        "preferred",
        "preference",
        "notes due",
        "bond",
        "etf",
        "fund",
        "trust units",
    )
    return not any(term in lowered for term in excluded_terms)


def value_from_nasdaq_field(field: Any) -> str:
    if isinstance(field, dict):
        return clean_text(str(field.get("value") or ""))
    return clean_text(str(field or ""))


def parse_rss_date(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def summarize_news_title(title: str, company: str) -> str:
    cleaned = clean_text(title)
    if not cleaned:
        return "뉴스 제목 수집 실패"
    title_without_source = re.sub(r"\s+-\s+[^-]+$", "", cleaned)
    return f"{company} 관련 보도: {title_without_source}"


def wrap_paragraph(text: str) -> str:
    text = clean_text(text)
    if len(text) <= 900:
        return text
    return textwrap.shorten(text, width=900, placeholder="...")


def md_escape(value: str) -> str:
    return str(value).replace("|", "\\|")


def format_money(value: Optional[float]) -> str:
    return "수집 실패" if value is None else f"${value:,.2f}"


def format_int(value: Optional[int]) -> str:
    return "수집 실패" if value is None else f"{value:,}"


def format_pct(value: Optional[float]) -> str:
    return "수집 실패" if value is None else f"{value:+.2f}%"


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the daily US low-price volume report.")
    parser.add_argument("--limit", type=int, default=20, help="Number of stocks to include.")
    parser.add_argument("--news-days", type=int, default=5, help="Recent news and filing lookback window.")
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR, help="Report output directory.")
    parser.add_argument("--session-date", type=dt.date.fromisoformat, help="Override session date YYYY-MM-DD.")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    try:
        output_path = build_report(
            limit=args.limit,
            days=args.news_days,
            output_dir=args.output_dir,
            session_date=args.session_date,
        )
    except Exception as exc:
        log(f"Report failed: {exc}")
        return 1
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
