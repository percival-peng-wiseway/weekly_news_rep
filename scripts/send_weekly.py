#!/usr/bin/env python3
"""构建并发送新能源周报邮件（基于网站当周周报 HTML）。

默认不发送（安全）：
  python scripts/send_weekly.py --weekly latest --dry-run

发送到订阅列表：
  python scripts/send_weekly.py --weekly latest --send

手动指定收件人并立即发送：
  python scripts/send_weekly.py --weekly latest --send --to percival@wiseway.ai
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Dict, List
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
WEEKLY_DIR = ROOT / "weekly"
SUBSCRIBERS = ROOT / "subscribers.csv"
TEMPLATE_PATH = ROOT / "scripts" / "templates" / "weekly_email_template_stable.html"
GOOGLE_API = Path("$HOME/.hermes/skills/productivity/google-workspace/scripts/google_api.py").expanduser()
SITE_URL = "https://weekly-au-news.wiseway.ai/"
LOGO_URL = SITE_URL + "gcgf_logo.png"
DEFAULT_RECIPIENTS = ["percival@wiseway.ai"]

SECTION_ORDER = [
    "Policy & Regulation",
    "Solar",
    "Battery Storage (BESS)",
    "Wind",
    "Company & Project Developments",
    "Sources",
]

SECTION_NORMALIZE_MAP = {
    "政策与监管": "Policy & Regulation",
    "政策与监管  ": "Policy & Regulation",
    "Policy": "Policy & Regulation",
    "Policy &amp; Regulation": "Policy & Regulation",
    "太阳能 Solar": "Solar",
    "solar": "Solar",
    "储能 BESS": "Battery Storage (BESS)",
    "Energy Storage (BESS)": "Battery Storage (BESS)",
    "风电 Wind": "Wind",
    "公司与项目动向": "Company & Project Developments",
    "Company & Project Developments": "Company & Project Developments",
    "Companies & Projects": "Company & Project Developments",
    "本期信息源": "Sources",
    "Sources": "Sources",
}

H2_RE = re.compile(r'<h2 class="sec" id="s\d+">(.*?)</h2>(.*?)(?=<h2 class="sec" id="s\d+"|<footer|$)', re.S)
CARD_RE = re.compile(
    r'<div class="card">\s*<div class="title">(.*?)</div>\s*(?:<div class="meta">(.*?)</div>\s*)?<div class="point">(.*?)</div>\s*</div>',
    re.S,
)

META_LINK_RE = re.compile(r'href="([^"]+)"', re.I)


def strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def norm(s: str) -> str:
    if not s:
        return s
    return html.unescape(s).strip()


def normalize_section(name: str) -> str:
    n = norm(name)
    n = n.replace("&amp;", "&")
    if n in SECTION_NORMALIZE_MAP:
        return SECTION_NORMALIZE_MAP[n]
    lowered = re.sub(r"\s+", " ", n.lower())
    for k, v in SECTION_NORMALIZE_MAP.items():
        if lowered == re.sub(r"\s+", " ", k.lower()):
            return v
    if "policy" in lowered:
        return "Policy & Regulation"
    if "solar" in lowered:
        return "Solar"
    if "storage" in lowered or "bess" in lowered:
        return "Battery Storage (BESS)"
    if "wind" in lowered:
        return "Wind"
    if "company" in lowered or "project" in lowered:
        return "Company & Project Developments"
    if "source" in lowered:
        return "Sources"
    return n


def parse_meta(meta_html: str) -> Dict[str, str]:
    meta_text = strip_html(meta_html)
    link_match = META_LINK_RE.search(meta_html or "")
    url = link_match.group(1).strip() if link_match else ""

    source = ""
    date = ""
    # 形如：ESD News · 2026-08-10 · Source
    if meta_text:
        # 去掉 Source 关键字
        meta_text = re.sub(r"^\s*(Source|来源)\s*:\s*", "", meta_text, flags=re.I)
        parts = [p.strip() for p in meta_text.split("·") if p.strip()]
        if parts:
            if re.search(r"https?://", parts[0], re.I):
                pass
            else:
                source = parts[0] if parts[0] not in {"Source", "来源", "Key point"} else ""
            if len(parts) > 1 and re.match(r"\d{4}-\d{2}-\d{2}", parts[1]):
                date = parts[1]

    if not source and url:
        source = urlparse(url).netloc.replace("www.", "")
    if source == "":
        source = "Unknown"

    return {"source": source, "date": date, "url": url}


def parse_weekly_html(html_path: Path) -> dict:
    raw = html_path.read_text(encoding="utf-8")

    title_match = re.search(r"<h1>(.*?)</h1>", raw, re.S)
    header_title = norm(strip_html(title_match.group(1))) if title_match else html_path.stem

    sections: Dict[str, List[Dict[str, str]]] = {name: [] for name in SECTION_ORDER}
    section_found = set()

    for sec_match in H2_RE.finditer(raw):
        sec_name_raw, sec_body = sec_match.group(1), sec_match.group(2)
        sec_name = normalize_section(sec_name_raw)
        if sec_name not in sections:
            sections[sec_name] = []

        cards = CARD_RE.findall(sec_body)
        for title_raw, meta_raw, point_raw in cards:
            item_title = norm(strip_html(title_raw))
            if not item_title:
                continue
            meta = parse_meta(meta_raw)
            point = norm(strip_html(point_raw))
            point = re.sub(r"^(Key point|要点)[:：]\s*", "", point)

            sections[sec_name].append(
                {
                    "title": item_title,
                    "source": meta["source"],
                    "date": meta["date"],
                    "url": meta["url"],
                    "point": point,
                }
            )
        section_found.add(sec_name)

    # 如果找不到 section（例如网页结构不标准）
    if not section_found:
        raise ValueError(f"failed to parse sections from {html_path}")

    # 过滤掉空的 Source（来源）section，避免发送空块
    if not sections["Sources"]:
        sections.pop("Sources", None)

    # 追加来源列表作为末尾“Sources”
    if "Sources" not in sections:
        sections["Sources"] = []
        source_set = []
        seen = set()
        for sec_name, items in sections.items():
            for item in items:
                src = item.get("source", "").strip()
                if src and src not in seen:
                    seen.add(src)
                    source_set.append(src)
        for src in source_set:
            sections["Sources"].append(
                {
                    "title": src,
                    "source": "",
                    "date": "",
                    "url": "",
                    "point": "",
                }
            )

    # 去重 section；保持顺序
    ordered_sections = {name: sections[name] for name in SECTION_ORDER if sections.get(name)}
    return {
        "title": header_title,
        "sections": ordered_sections,
        "path": str(html_path),
    }


def render_sections(sections: Dict[str, List[Dict[str, str]]]) -> str:
    chunks: List[str] = []
    for sec_name, items in sections.items():
        section_chunks: List[str] = [
            f'<div style="margin: 24px 0;">',
            f'<h2 style="font-size:18px;color:#166534;margin:0 0 10px;padding-left:12px;border-left:5px solid #16a34a;border-radius:2px;">{html.escape(sec_name)}</h2>',
            '<ul style="margin:0;padding-left:20px;">',
        ]

        if sec_name == "Sources":
            for item in items:
                section_chunks.append(
                    f'  <li style="margin:0 0 6px 0;list-style-type:disc;color:#0f172a;">'
                    f'<span style="font-size:14px;">{html.escape(item["title"])}</span></li>'
                )
        else:
            for item in items:
                source = item.get("source", "") or ""
                date = item.get("date", "") or ""
                url = item.get("url", "") or ""
                point = item.get("point", "") or ""

                source_html = ""
                if source or date or url:
                    source_fields = []
                    if source:
                        source_fields.append(html.escape(source))
                    if date:
                        source_fields.append(html.escape(date))
                    if url:
                        source_html = (
                            f'{" | ".join(source_fields)}'
                            + f' | <a href="{html.escape(url)}" style="color:#2563eb;word-break:break-all;" target="_blank" rel="noopener">{html.escape(url)}</a>'
                            if source_fields
                            else f'<a href="{html.escape(url)}" style="color:#2563eb;word-break:break-all;" target="_blank" rel="noopener">{html.escape(url)}</a>'
                        )
                    else:
                        source_html = " | ".join(source_fields)

                section_chunks.append('  <li style="margin:0 0 16px 0;list-style-type:disc;">')
                section_chunks.append(
                    f'    <div style="font-weight:700;font-size:1.06em;line-height:1.4;margin-bottom:4px;">{html.escape(item["title"])}</div>'
                )
                if source_html:
                    section_chunks.append(
                        f'    <div style="font-size:14px;color:#334155;margin-bottom:4px;">'
                        f'Source: {source_html}</div>'
                    )
                if point:
                    section_chunks.append(
                        f'    <div style="font-size:14px;color:#334155;">'
                        f'Key point: {html.escape(point)}</div>'
                    )
                section_chunks.append("  </li>")

        section_chunks.append("</ul>")
        section_chunks.append("</div>")
        chunks.append("\n".join(section_chunks))

    return "\n".join(chunks)


def get_latest_weekly(lang: str) -> Path:
    if lang == "cn":
        candidates = sorted(WEEKLY_DIR.glob("weekly-*_*_cn.html"))
    else:
        candidates = sorted(WEEKLY_DIR.glob("weekly-*.html"))
        candidates = [p for p in candidates if "_cn" not in p.stem]

    if not candidates:
        raise FileNotFoundError("No weekly files found for language " + lang)
    return candidates[-1]


def load_subscribers() -> List[str]:
    if not SUBSCRIBERS.exists():
        return DEFAULT_RECIPIENTS
    recipients = []
    with SUBSCRIBERS.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 2 and parts[1]:
                recipients.append(parts[1])
    return recipients or DEFAULT_RECIPIENTS


def build_subject(title: str) -> str:
    return title


def render_email(html_path: Path, subject_override: str | None = None) -> Dict[str, str]:
    parsed = parse_weekly_html(html_path)
    sections_html = render_sections(parsed["sections"])
    tpl = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))

    modified = datetime.now().strftime("%Y-%m-%d")
    email_subject = subject_override or build_subject(parsed["title"])

    body = tpl.safe_substitute(
        email_subject=email_subject,
        website_url=SITE_URL,
        logo_url=LOGO_URL,
        email_title=parsed["title"],
        last_modified=modified,
        sections_html=sections_html,
    )

    return {
        "subject": email_subject,
        "body": body,
        "path": parsed["path"],
        "title": parsed["title"],
        "sections": parsed["sections"],
    }


def send_one(to_addr: str, subject: str, body: str) -> Dict[str, object]:
    if not GOOGLE_API.exists():
        raise FileNotFoundError(f"google api script not found: {GOOGLE_API}")

    cmd = [
        "python",
        str(GOOGLE_API),
        "gmail",
        "send",
        "--to",
        to_addr,
        "--subject",
        subject,
        "--body",
        body,
        "--html",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stdout or "") + (result.stderr or "")
        raise RuntimeError(f"send failed for {to_addr}: {err.strip()}")

    out = (result.stdout or "").strip()
    status = ""
    sent_id = ""
    thread_id = ""
    try:
        payload = json.loads(out)
        status = payload.get("status", "")
        sent_id = payload.get("id", "") or payload.get("messageId", "")
        thread_id = payload.get("threadId", "")
    except Exception:
        # 非标准 JSON 输出也可输出为文本，但仍视作失败前提由状态码决定
        status = "sent" if "status\"" in out or "sent" in out else "unknown"

    return {
        "to": to_addr,
        "status": status,
        "id": sent_id,
        "threadId": thread_id,
        "stdout": out,
    }


def get_argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Send weekly report email based on weekly_news_rep HTML pages")
    p.add_argument("--weekly", default="latest", choices=["latest"], help="Keep default: latest")
    p.add_argument(
        "--lang",
        default="en",
        choices=["en", "cn"],
        help="Select weekly language source for newsletter content",
    )
    p.add_argument(
        "--send",
        action="store_true",
        help="Actually send mails; dry-run by default",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for preview-only execution (same as default)",
    )
    p.add_argument("--to", help="Comma-separated recipients override subscribers")
    p.add_argument("--subject", help="Custom email subject")
    p.add_argument("--output", help="Save rendered email HTML to this file")
    return p


def main() -> None:
    args = get_argument_parser().parse_args()
    weekly = get_latest_weekly(args.lang)

    rendered = render_email(weekly, subject_override=args.subject)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered["body"], encoding="utf-8")
        print(f"Rendered email preview: {out}")
    else:
        preview_path = Path("/tmp/au_renewables_weekly_email_preview.html")
        preview_path.write_text(rendered["body"], encoding="utf-8")
        print(f"Rendered email preview: {preview_path}")

    item_count = 0
    for items in rendered["sections"].values():
        item_count += len(items)
    print(f"Source: {weekly.name} | Items: {item_count}")

    if not args.send:
        print("Dry run mode. Use --send to actually deliver the mail.")
        return

    recipients = [x.strip() for x in args.to.split(",")] if args.to else load_subscribers()
    recipients = [x for x in recipients if x]
    if not recipients:
        raise ValueError("No recipients configured")

    results = []
    for to in recipients:
        result = send_one(to, rendered["subject"], rendered["body"])
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))

    ok = all(r.get("status") == "sent" for r in results)
    if not ok:
        raise RuntimeError(f"some emails were not sent: {results}")
    print("done")


if __name__ == "__main__":
    main()
