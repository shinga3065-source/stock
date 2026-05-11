#!/usr/bin/env python3
"""Build a static website from generated Markdown stock reports."""

from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "us_low_price_volume"
SITE_DIR = ROOT / "site"


@dataclass
class ReportPage:
    date: str
    title: str
    source_path: Path
    html_name: str
    generated_at: str = ""
    trading_date: str = ""


def discover_reports(report_dir: Path) -> List[ReportPage]:
    reports: List[ReportPage] = []
    for path in sorted(report_dir.glob("*.md"), reverse=True):
        text = path.read_text(encoding="utf-8")
        title = first_heading(text) or f"미국 저가주 보고서 {path.stem}"
        reports.append(
            ReportPage(
                date=path.stem,
                title=title,
                source_path=path,
                html_name=f"{path.stem}.html",
                generated_at=find_meta(text, "생성 시각"),
                trading_date=find_meta(text, "기준 거래일") or path.stem,
            )
        )
    return reports


def build_site(report_dir: Path, site_dir: Path) -> Path:
    reports = discover_reports(report_dir)
    if not reports:
        raise RuntimeError(f"No Markdown reports found in {report_dir}")

    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "reports").mkdir(parents=True, exist_ok=True)

    for report in reports:
        markdown = report.source_path.read_text(encoding="utf-8")
        report_html = render_report_page(report, markdown, reports)
        (site_dir / "reports" / report.html_name).write_text(report_html, encoding="utf-8")

    index_html = render_index_page(reports)
    index_path = site_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    return index_path


def render_index_page(reports: List[ReportPage]) -> str:
    latest = reports[0]
    rows = "\n".join(
        f"""
        <a class="report-row" href="reports/{html.escape(report.html_name)}">
          <span>
            <strong>{html.escape(report.trading_date)}</strong>
            <small>{html.escape(report.generated_at or "생성 시각 없음")}</small>
          </span>
          <span class="open-link">열기</span>
        </a>
        """.strip()
        for report in reports
    )
    return page_shell(
        title="미국 저가주 거래량 보고서",
        body=f"""
        <section class="hero">
          <div>
            <p class="eyebrow">Daily US Market Report</p>
            <h1>미국 저가주 거래량 Top 20</h1>
            <p class="lead">종가 1~10달러 종목을 거래량 순으로 추려 회사 개요, 최근 뉴스, 실적 발표 및 SEC 공시를 한 화면에서 확인합니다.</p>
          </div>
          <div class="hero-panel">
            <span class="panel-label">최신 보고서</span>
            <strong>{html.escape(latest.trading_date)}</strong>
            <a class="primary-link" href="reports/{html.escape(latest.html_name)}">보고서 보기</a>
          </div>
        </section>
        <section class="content-band">
          <div class="section-heading">
            <h2>보고서 목록</h2>
            <p>매일 오후 4시 자동 생성된 보고서가 날짜별로 쌓입니다.</p>
          </div>
          <div class="report-list">{rows}</div>
        </section>
        """,
    )


def render_report_page(report: ReportPage, markdown: str, reports: List[ReportPage]) -> str:
    nav = "\n".join(
        f'<a class="{ "active" if other.html_name == report.html_name else "" }" href="{html.escape(other.html_name)}">{html.escape(other.trading_date)}</a>'
        for other in reports
    )
    content = markdown_to_html(markdown)
    return page_shell(
        title=report.title,
        body=f"""
        <section class="report-layout">
          <aside class="report-nav">
            <a class="back-link" href="../index.html">전체 목록</a>
            <h2>보고서 날짜</h2>
            <nav>{nav}</nav>
          </aside>
          <article class="report-document">
            {content}
          </article>
        </section>
        """,
        report_page=True,
    )


def page_shell(title: str, body: str, report_page: bool = False) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f7f8fb;
      --surface: #ffffff;
      --ink: #141922;
      --muted: #5f6b7a;
      --line: #dfe4ec;
      --accent: #0f766e;
      --accent-strong: #0b4f4a;
      --gain: #047857;
      --loss: #b91c1c;
      --shadow: 0 18px 45px rgba(20, 25, 34, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.55;
    }}
    a {{ color: var(--accent-strong); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .hero {{
      min-height: 72vh;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 300px;
      gap: 32px;
      align-items: end;
      padding: 72px max(24px, calc((100vw - 1120px) / 2)) 56px;
      background:
        linear-gradient(135deg, rgba(15, 118, 110, 0.9), rgba(20, 25, 34, 0.86)),
        url("https://images.unsplash.com/photo-1642790551116-18e150f248e3?auto=format&fit=crop&w=1600&q=80");
      background-size: cover;
      background-position: center;
      color: #fff;
    }}
    .eyebrow {{
      margin: 0 0 12px;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
      opacity: 0.82;
    }}
    h1 {{
      margin: 0;
      font-size: 52px;
      line-height: 1.04;
      letter-spacing: 0;
    }}
    .lead {{
      max-width: 680px;
      margin: 20px 0 0;
      font-size: 18px;
      color: rgba(255, 255, 255, 0.86);
    }}
    .hero-panel {{
      background: rgba(255, 255, 255, 0.95);
      color: var(--ink);
      border: 1px solid rgba(255, 255, 255, 0.7);
      border-radius: 8px;
      padding: 22px;
      box-shadow: var(--shadow);
    }}
    .panel-label {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .hero-panel strong {{
      display: block;
      font-size: 30px;
      margin-bottom: 18px;
    }}
    .primary-link {{
      display: inline-flex;
      min-height: 42px;
      align-items: center;
      padding: 0 16px;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
    }}
    .content-band {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 44px 24px 72px;
    }}
    .section-heading {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 18px;
    }}
    .section-heading h2, .report-nav h2 {{
      margin: 0;
      font-size: 24px;
      letter-spacing: 0;
    }}
    .section-heading p {{
      margin: 0;
      color: var(--muted);
    }}
    .report-list {{
      display: grid;
      gap: 10px;
    }}
    .report-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-height: 72px;
      padding: 14px 18px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(20, 25, 34, 0.04);
    }}
    .report-row small {{
      display: block;
      color: var(--muted);
      margin-top: 2px;
    }}
    .open-link {{
      color: var(--accent-strong);
      font-weight: 700;
      white-space: nowrap;
    }}
    .report-layout {{
      display: grid;
      grid-template-columns: 250px minmax(0, 1fr);
      gap: 26px;
      max-width: 1320px;
      margin: 0 auto;
      padding: 24px;
    }}
    .report-nav {{
      position: sticky;
      top: 24px;
      align-self: start;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      box-shadow: 0 8px 24px rgba(20, 25, 34, 0.04);
    }}
    .back-link {{
      display: inline-block;
      margin-bottom: 18px;
      font-weight: 700;
    }}
    .report-nav nav {{
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }}
    .report-nav nav a {{
      display: block;
      padding: 9px 10px;
      border-radius: 6px;
      color: var(--muted);
    }}
    .report-nav nav a.active {{
      background: #e7f4f2;
      color: var(--accent-strong);
      font-weight: 700;
    }}
    .report-document {{
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 34px;
      box-shadow: var(--shadow);
    }}
    .report-document h1 {{
      color: var(--ink);
      font-size: 34px;
      line-height: 1.15;
      margin-bottom: 18px;
    }}
    .report-document h2 {{
      margin-top: 38px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
      font-size: 24px;
    }}
    .report-document h3 {{
      margin-top: 34px;
      font-size: 20px;
    }}
    .report-document p, .report-document li {{
      color: #273140;
    }}
    .report-document table {{
      width: 100%;
      border-collapse: collapse;
      margin: 18px 0 28px;
      font-size: 14px;
    }}
    .report-document th, .report-document td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 9px;
      text-align: left;
      vertical-align: top;
    }}
    .report-document th {{
      position: sticky;
      top: 0;
      background: #eef5f4;
      color: #25313d;
      font-weight: 800;
    }}
    .report-document code {{
      background: #f0f3f7;
      padding: 2px 5px;
      border-radius: 4px;
    }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .table-wrap table {{
      margin: 0;
      min-width: 860px;
    }}
    @media (max-width: 820px) {{
      .hero {{
        min-height: auto;
        grid-template-columns: 1fr;
        padding-top: 52px;
      }}
      h1 {{ font-size: 38px; }}
      .section-heading {{ display: block; }}
      .report-layout {{
        grid-template-columns: 1fr;
        padding: 12px;
      }}
      .report-nav {{
        position: static;
      }}
      .report-document {{
        padding: 22px 16px;
      }}
    }}
  </style>
</head>
<body class="{ "report-page" if report_page else "home-page" }">
  {body}
</body>
</html>
"""


def markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    html_lines: List[str] = []
    paragraph: List[str] = []
    list_open = False
    i = 0

    def flush_paragraph() -> None:
        if paragraph:
            html_lines.append(f"<p>{parse_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            html_lines.append("</ul>")
            list_open = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            close_list()
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            flush_paragraph()
            close_list()
            table_lines = [stripped, lines[i + 1].strip()]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            html_lines.append(markdown_table_to_html(table_lines))
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            close_list()
            level = min(len(stripped) - len(stripped.lstrip("#")), 3)
            text = stripped[level:].strip()
            html_lines.append(f"<h{level}>{parse_inline(text)}</h{level}>")
            i += 1
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            if not list_open:
                html_lines.append("<ul>")
                list_open = True
            html_lines.append(f"<li>{parse_inline(stripped[2:].strip())}</li>")
            i += 1
            continue
        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    close_list()
    return "\n".join(html_lines)


def markdown_table_to_html(lines: List[str]) -> str:
    headers = split_table_row(lines[0])
    rows = [split_table_row(line) for line in lines[2:]]
    thead = "".join(f"<th>{parse_inline(cell)}</th>" for cell in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{parse_inline(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{thead}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def split_table_row(line: str) -> List[str]:
    line = line.strip().strip("|")
    cells = re.split(r"(?<!\\)\|", line)
    return [cell.replace("\\|", "|").strip() for cell in cells]


def is_table_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", line))


def parse_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    escaped = re.sub(
        r"\[((?:[^\[\]]|\[[^\]]*\])+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        escaped,
    )
    return escaped


def first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def find_meta(markdown: str, key: str) -> str:
    pattern = re.compile(rf"^-\s*{re.escape(key)}:\s*(.+)$")
    for line in markdown.splitlines():
        match = pattern.match(line.strip())
        if match:
            return match.group(1).strip()
    return ""


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static HTML pages for stock reports.")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--site-dir", type=Path, default=SITE_DIR)
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    index_path = build_site(args.report_dir, args.site_dir)
    print(index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
