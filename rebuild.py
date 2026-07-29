#!/usr/bin/env python3
"""
Rebuild weekly_news_rep: generate missing weekly HTML, clean duplicates,
rewrite index.html with multi-week accordion layout.
Each calendar week gets its own independent accordion section.
"""
import html
import re
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

ROOT = Path("/home/jojo/projects/weekly_news_rep")
WEEKLY_DIR = ROOT / "weekly"
BRIEFINGS = Path("/home/jojo/projects/au-renewables-agent/briefings")

# ── CSS shared across all pages ──
BASE_CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
       background: #f8fafc; color: #1e293b; line-height: 1.7; }
.wrap { max-width: 860px; margin: 0 auto; padding: 24px 16px 64px; }
header.hero { background: #fff; border-radius: 16px; padding: 24px 24px 16px;
              margin-bottom: 24px; text-align: center;
              border-top: 5px solid #16a34a;
              box-shadow: 0 1px 3px rgba(0,0,0,.06); }
header.hero img.logo { height: 160px; margin-bottom: 8px; }
header.hero h1 { font-size: 24px; color: #166534; margin-bottom: 6px; }
header.hero .sub { font-size: 14px; color: #64748b; }
nav.toc { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
          padding: 12px 16px; margin-bottom: 24px; font-size: 14px;
          display: flex; flex-wrap: wrap; gap: 4px 14px; }
nav.toc a { color: #2563eb; text-decoration: none; white-space: nowrap; }
h2.sec { font-size: 18px; margin: 32px 0 12px; padding-left: 12px; border-left: 5px solid #16a34a; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 14px 18px; margin-bottom: 12px; }
.card .title { font-weight: 600; font-size: 16px; margin-bottom: 4px; }
.card .meta { font-size: 13px; color: #64748b; margin-bottom: 6px; }
.card .meta a { color: #2563eb; text-decoration: none; word-break: break-all; }
.card .point { font-size: 14.5px; }
footer.src { margin-top: 40px; font-size: 13px; color: #64748b; }
footer.src li { margin-left: 20px; }
a.back { color: #2563eb; text-decoration: none; font-size: 14px; }

/* ── list items (index page) ── */
.list-item { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:16px 20px;
             margin-bottom:12px; display:block; text-decoration:none; color:inherit;
             cursor:pointer; position: relative; overflow: hidden; }
.list-item:hover { border-color:#16a34a; }
.list-item .d { font-weight:600; font-size:17px; }
.list-item .c { font-size:13px; color:#64748b; }
.badge-new { position: absolute; top: 8px; right: 8px; background: #dc2626; color: #fff;
  font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px;
  text-transform: uppercase; letter-spacing: .5px; }

/* ── accordion ── */
.week-toggle { cursor: pointer; user-select: none; }
.week-toggle .arrow { display: inline-block; transition: transform 0.2s; margin-right: 4px; }
.week-toggle.open .arrow { transform: rotate(90deg); }
.week-body { display: none; padding: 8px 0 0 0; }
.week-body.open { display: block; }
.week-body .sub-item { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 10px;
  padding: 12px 16px; margin-bottom: 8px; display: block; text-decoration: none; color: inherit; }
.week-body .sub-item:hover { border-color: #16a34a; background: #fff; }
.week-body .sub-item .sd { font-weight: 600; font-size: 15px; }
.week-body .sub-item .sc { font-size: 12px; color: #64748b; margin-top: 2px; }
.week-body .weekly-card { background: #f0fdf4; border: 1.5px solid #16a34a; border-radius: 10px; }
.week-body .weekly-card:hover { background: #dcfce7; }
.week-separator { font-size: 13px; color: #94a3b8; text-transform: uppercase;
  letter-spacing: .5px; margin: 28px 0 8px; padding-left: 4px; }
.week-separator:first-of-type { margin-top: 0; }

/* ── lang toggle ── */
.lang-toggle { display: flex; justify-content: center; gap: 0; margin-bottom: 24px; }
.lang-toggle button { border: 1px solid #d1d5db; background: #fff; color: #64748b;
  padding: 8px 24px; cursor: pointer; font-size: 14px; font-weight: 500;
  transition: all .15s; }
.lang-toggle button:first-child { border-radius: 8px 0 0 8px; }
.lang-toggle button:last-child { border-radius: 0 8px 8px 0; }
.lang-toggle button.active { background: #16a34a; color: #fff; border-color: #16a34a; }
.lang-section h3 { font-size: 14px; color: #94a3b8; text-transform: uppercase;
  letter-spacing: .5px; margin-bottom: 10px; }
"""


def parse_weekly_md(text: str, is_cn: bool = False):
    """Parse weekly markdown (English or Chinese format)."""
    src_label = "来源" if is_cn else "Source"
    point_label = "要点" if is_cn else "Key point"
    title = ""
    sections = []  # (name, [{title, meta, point}])
    cur = None
    item = None
    for line in text.splitlines():
        stripped = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            name = line[3:].strip()
            cur = {"name": name, "items": []}
            sections.append(cur)
            item = None
        elif cur is not None and stripped.startswith("- ") and not stripped.startswith("- Source") and not stripped.startswith("- " + src_label) and not stripped.startswith("- Key point") and not stripped.startswith("- " + point_label):
            # new item title
            item = {"title": stripped[2:].strip(), "meta": "", "point": ""}
            cur["items"].append(item)
        elif item is not None:
            if stripped.startswith(f"- {src_label}:") or stripped.startswith(f"- {src_label}："):
                item["meta"] = stripped[2:].strip()
            elif stripped.startswith(f"- {point_label}:") or stripped.startswith(f"- {point_label}："):
                item["point"] = stripped[2:].strip()
    return title, sections


def render_weekly_html(md_path: Path, is_cn: bool = False) -> str:
    """Generate a standalone weekly briefing HTML page."""
    text = md_path.read_text(encoding="utf-8")
    title, sections = parse_weekly_md(text, is_cn)
    date_slug = md_path.stem

    toc = "".join(
        f'<a href="#s{i}">{html.escape(s["name"])}</a>'
        for i, s in enumerate(sections)
    )
    body_parts = []
    for i, s in enumerate(sections):
        body_parts.append(
            f'<h2 class="sec" id="s{i}">{html.escape(s["name"])}</h2>'
        )
        for it in s["items"]:
            meta_html = ""
            if it["meta"]:
                clean = re.sub(r'^(来源：|来源:|Source:|Source：)\s*', '', it["meta"])
                parts = [p.strip() for p in clean.split("|")]
                meta_segments = []
                for p in parts:
                    if p.startswith("http"):
                        esc = html.escape(p)
                        meta_segments.append(
                            f'<a href="{esc}" target="_blank" rel="noopener">原文链接</a>'
                        )
                    else:
                        meta_segments.append(html.escape(p))
                meta_html = '<div class="meta">' + " · ".join(meta_segments) + "</div>"

            body_parts.append(
                '<div class="card">'
                f'<div class="title">{html.escape(it["title"])}</div>'
                f'{meta_html}'
                f'<div class="point">{html.escape(it["point"])}</div>'
                "</div>"
            )

    n = sum(len(s["items"]) for s in sections)
    favicon = "../wiseway_logo.png"
    logo = "../gcgf_logo.png"
    back = "../index.html"

    return f"""<!DOCTYPE html>
<html lang="{'zh-CN' if is_cn else 'en'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/png" href="{favicon}">
<title>Renewable Energy News in AU – {date_slug}</title><style>{BASE_CSS}</style></head>
<body><div class="wrap">
<a class="back" href="{back}">← All Briefings</a>
<header class="hero">
  <img class="logo" src="{logo}" alt="GCGF Logo">
  <h1>{html.escape(title)}</h1>
  <div class="sub">{date_slug} · {n} items</div>
</header>
<nav class="toc">{toc}</nav>
{"".join(body_parts)}
<footer class="src" style="margin-top:40px;font-size:13px;color:#64748b">
<p>由 au-renewables-agent 自动生成</p></footer>
</div></body></html>"""


def monday_of_week(d: date) -> date:
    """Return the Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


def build_index(weeks_data, weekly_map_cn, weekly_map_en):
    """Build index.html with multi-week accordion layout.

    weeks_data: OrderedDict of week_key -> list of (date_str, cn_count, en_count)
               Sorted newest first.
    weekly_map_cn: week_key -> (slug, count) or None
    weekly_map_en: week_key -> (slug, count) or None
    """
    today = date.today().strftime("%Y-%m-%d")
    week_keys = list(weeks_data.keys())
    is_first = True

    cn_sections = []
    en_sections = []

    for wk in week_keys:
        dailies = weeks_data[wk]  # already sorted newest first within week

        # --- Compute week label: Monday ~ Friday of that week ---
        monday = date.fromisoformat(wk)
        friday = monday + timedelta(days=4)
        wk_label = f"{monday.strftime('%Y-%m-%d')} ~ {friday.strftime('%Y-%m-%d')}"
        # count total items
        total_cn = sum(cn for _, cn, _ in dailies)
        total_en = sum(en for _, _, en in dailies)

        # NEW badge only on latest week
        badge = '<span class="badge-new">NEW</span>' if is_first else ''
        is_first = False

        # Weekly report lookup
        wk_cn = weekly_map_cn.get(wk)
        wk_en = weekly_map_en.get(wk)

        # --- Chinese section ---
        cn_weekly_cn_count = wk_cn[1] if wk_cn else 0
        cn_desc = f"{total_cn} 条日报" if total_cn > 0 else ""
        if cn_weekly_cn_count:
            cn_desc = f"{cn_weekly_cn_count} 条周报 + {total_cn} 条日报" if total_cn else f"{cn_weekly_cn_count} 条周报"

        cn_section = f"""<div class="week-toggle list-item" onclick="toggleWeek(this)" style="position:relative;overflow:hidden">
{badge}<span class="arrow">▶</span> <span class="d">📅 {wk_label}</span>
<div class="c">{cn_desc} · 点击展开/收起</div>
</div>
<div class="week-body">
"""
        if wk_cn:
            slug, count = wk_cn
            cn_section += f"""<a class="sub-item weekly-card" href="weekly/{slug}.html">
  <div class="sd">📋 本周精选周报</div>
  <div class="sc">{count} 条要闻 · 点击阅读完整周报</div>
</a>
"""

        for d, cn, en in dailies:
            cn_section += f'<a class="sub-item" href="weekly/{d}.html"><div class="sd">📅 {d}</div><div class="sc">{cn} 条信息 · 点击查看日简报</div></a>\n'

        cn_section += "</div>"
        cn_sections.append(cn_section)

        # --- English section ---
        en_weekly_en_count = wk_en[1] if wk_en else 0
        en_desc = f"{total_en} dailies" if total_en > 0 else "No dailies"
        if en_weekly_en_count:
            en_desc = f"{en_weekly_en_count} weekly + {total_en} dailies" if total_en else f"{en_weekly_en_count} weekly"

        en_section = f"""<div class="week-toggle list-item" onclick="toggleWeek(this)" style="position:relative;overflow:hidden">
{badge}<span class="arrow">▶</span> <span class="d">📅 {wk_label}</span>
<div class="c">{en_desc} · Click to expand/collapse</div>
</div>
<div class="week-body">
"""
        if wk_en:
            slug, count = wk_en
            en_section += f"""<a class="sub-item weekly-card" href="weekly/{slug}.html">
  <div class="sd">📋 Weekly Highlights</div>
  <div class="sc">{count} items · Read full weekly report</div>
</a>
"""

        for d, cn, en in dailies:
            en_section += f'<a class="sub-item" href="weekly/{d}_en.html"><div class="sd">📅 {d}</div><div class="sc">{en} items · Daily Briefing</div></a>\n'

        en_section += "</div>"
        en_sections.append(en_section)

    # ── JS for accordion + lang switch ──
    js = """<script>
function toggleWeek(el) {
  el.classList.toggle('open');
  var body = el.nextElementSibling;
  body.classList.toggle('open');
}
function switchLang(lang) {
  document.getElementById('btn-cn').classList.toggle('active', lang==='cn');
  document.getElementById('btn-en').classList.toggle('active', lang==='en');
  document.getElementById('section-cn').style.display = lang==='cn' ? '' : 'none';
  document.getElementById('section-en').style.display = lang==='en' ? '' : 'none';
}
</script>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/png" href="wiseway_logo.png">
<title>Renewable Energy News in AU</title><style>{BASE_CSS}</style></head>
<body><div class="wrap">
<header class="hero">
  <img class="logo" src="gcgf_logo.png" alt="GCGF Logo">
  <h1>Renewable Energy News in AU</h1>
  <div class="sub">Last modified: {today}</div>
</header>

<div class="lang-toggle">
  <button id="btn-cn" class="active" onclick="switchLang('cn')">中文</button>
  <button id="btn-en" onclick="switchLang('en')">EN</button>
</div>
<div id="section-cn" class="lang-section">
{"".join(cn_sections)}
</div>
<div id="section-en" class="lang-section" style="display:none">
{"".join(en_sections)}
</div>
<footer style="margin-top:40px;text-align:center;font-size:13px;color:#94a3b8">
  powered by <a href="https://wiseway.ai" style="color:#2563eb;text-decoration:none">Wiseway.ai</a>
</footer>
</div>
{js}
</body></html>"""


def parse_weekly_slug(slug: str):
    """Parse weekly slug like 'weekly-2026-07-20_2026-07-25'
    Returns (start_date, end_date) or None."""
    m = re.match(r'weekly-(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})', slug)
    if m:
        return date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
    return None


def main():
    # ── 1. Auto-discover weekly markdowns, generate HTML ──
    weekly_mds = sorted(BRIEFINGS.glob("weekly-*.md"), reverse=True)
    for md_path in weekly_mds:
        is_cn = md_path.stem.endswith("_cn")
        html_name = md_path.stem + ".html"
        html_path = WEEKLY_DIR / html_name
        html_content = render_weekly_html(md_path, is_cn=is_cn)
        html_path.write_text(html_content, encoding="utf-8")
        print(f"Generated: {html_name}")

    # ── 2. Remove stale weekly HTMLs without matching .md ──
    for html_path in WEEKLY_DIR.glob("weekly-*.html"):
        md_stem = html_path.stem
        if not (BRIEFINGS / f"{md_stem}.md").exists():
            html_path.unlink()
            print(f"Removed stale: {html_path.name}")

    # ── 3. Auto-discover daily briefing HTMLs ──
    daily_files = sorted(
        [p.stem for p in WEEKLY_DIR.glob("20*.html")
         if not p.stem.startswith("weekly") and not p.stem.endswith("_en")],
        reverse=True
    )
    daily_entries = []
    for d in daily_files:
        cn_path = WEEKLY_DIR / f"{d}.html"
        en_path = WEEKLY_DIR / f"{d}_en.html"
        cn_count = cn_path.read_text(encoding="utf-8").count('<div class="card">') if cn_path.exists() else 0
        en_count = en_path.read_text(encoding="utf-8").count('<div class="card">') if en_path.exists() else 0
        daily_entries.append((d, cn_count, en_count))
        print(f"  {d}: CN={cn_count}, EN={en_count}")

    # ── 4. Group dailies by calendar week (Monday as week start) ──
    weeks_data = defaultdict(list)
    for d_str, cn, en in daily_entries:
        d = date.fromisoformat(d_str)
        monday = monday_of_week(d)
        week_key = monday.strftime("%Y-%m-%d")
        weeks_data[week_key].append((d_str, cn, en))

    # Sort week keys newest first; within each week keep newest-first order
    from collections import OrderedDict
    sorted_weeks = OrderedDict()
    for wk in sorted(weeks_data.keys(), reverse=True):
        sorted_weeks[wk] = weeks_data[wk]

    # ── 5. Map weekly reports to their week keys ──
    weekly_map_cn = {}
    weekly_map_en = {}
    wk_entries = sorted(WEEKLY_DIR.glob("weekly-*.html"), reverse=True)
    for p in wk_entries:
        slug = p.stem
        parsed = parse_weekly_slug(slug)
        if parsed is None:
            continue
        start_date, end_date = parsed
        week_key = monday_of_week(start_date).strftime("%Y-%m-%d")
        count = p.read_text(encoding="utf-8").count('<div class="card">')

        if slug.endswith("_cn"):
            weekly_map_cn[week_key] = (slug, count)
            print(f"  Weekly CN: {slug} -> week {week_key} ({count} items)")
        else:
            weekly_map_en[week_key] = (slug, count)
            print(f"  Weekly EN: {slug} -> week {week_key} ({count} items)")

    # ── 6. Build new index.html ──
    index_html = build_index(sorted_weeks, weekly_map_cn, weekly_map_en)
    (ROOT / "index.html").write_text(index_html, encoding="utf-8")

    print("\n✅ index.html rebuilt with multi-week accordion layout")
    print(f"   Weeks: {len(sorted_weeks)}")
    for wk, entries in sorted_weeks.items():
        wk_cn = weekly_map_cn.get(wk)
        wk_en = weekly_map_en.get(wk)
        cn_wk = f" + 周报({wk_cn[1]}条)" if wk_cn else ""
        en_wk = f" + weekly({wk_en[1]} items)" if wk_en else ""
        print(f"     {wk}: {len(entries)} dailies{cn_wk}{en_wk}")


if __name__ == "__main__":
    main()
