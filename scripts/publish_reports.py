"""
发布分析报告到 stock-theme-assistant 网站

功能：
  1. 扫描本地标的分析目录中的 HTML 报告
  2. 复制到 stock-theme-assistant 的 www/reports/ 目录
  3. 自动更新 www/reports.html 研报列表页

用法：
  python scripts/publish_reports.py

配置：
  修改下方的 STOCK_THEME_ASSISTANT_DIR 指向正确的路径
"""

import os
import re
import shutil
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from urllib.parse import quote

# ═══════════════════════════════════════════
# 配置区（按需修改）
# ═══════════════════════════════════════════
# stock-theme-assistant 项目路径
STOCK_THEME_ASSISTANT_DIR = Path(
    os.environ.get("STOCK_THEME_ASSISTANT_DIR")
    or r"D:\ai\stock-theme-assistant"
)
# 来源目录（本站点分析报告存放路径）
SOURCE_DIR = Path(__file__).parent.parent / "01-价值投资" / "标的分析"
# 目标目录（stock-theme-assistant 中的 www/reports）
TARGET_DIR = STOCK_THEME_ASSISTANT_DIR / "www" / "reports"


# ═══════════════════════════════════════════
# 报告解析
# ═══════════════════════════════════════════

REPORT_PATTERN = re.compile(
    r"(?P<code>\d{5,6}(?:\.\w+)?)[-－](?P<name>.+?)-(?P<date>\d{4}-\d{2}-\d{2})\.html$"
)


def parse_rating(html_path: Path) -> str:
    """从 HTML 内容中提取评级标签。

    支持多种格式：
      - B版: class="badge buy"           (拓普集团原版)
      - A版: class="v-big buy"            (华新建材新版)
      - A版: verdict-box + "买入"/"观察"  (百济神州/泡泡玛特原版)
    """
    content = html_path.read_text("utf-8", errors="ignore")

    # Method 1: 精确匹配 badge/v-big 元素上的 class（最可靠）
    m = re.search(r'class="(?:badge|v-big)\s+(buy|watch|avoid)"', content)
    if m:
        return m.group(1)

    # Method 2: 在 verdict-box 容器内匹配评级文本
    vb = re.search(r'class="verdict-box[^"]*".*?class="(?:big|v-big)"[^>]*>.*?(买入|观察|回避)', content, re.DOTALL)
    if vb:
        txt = vb.group(1)
        if '买入' in txt:
            return "buy"
        if '观察' in txt:
            return "watch"
        return "avoid"

    # Method 3: 匹配 badge 元素内的评级文本（旧版 fallback）
    if re.search(r'class="badge[^"]*"[^>]*>.*?买入', content):
        return "buy"
    if re.search(r'class="badge[^"]*"[^>]*>.*?观察', content):
        return "watch"
    if 'rating-avoid' in content or '回避' in content:
        return "avoid"

    return "watch"


def parse_stock_code(filename: str) -> tuple[str, str]:
    """从文件名中提取股票代码和名称。"""
    m = REPORT_PATTERN.search(filename)
    if m:
        return m.group("code"), m.group("name")
    return "", ""


def parse_title_and_desc(html_path: Path) -> tuple[str, str, str, list[str]]:
    """从 HTML 中提取标题、描述、市场和标签。"""
    content = html_path.read_text("utf-8", errors="ignore")

    # 提取标题
    title_match = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.DOTALL)
    title = title_match.group(1).strip() if title_match else html_path.stem
    # 清理 HTML 标签
    title = re.sub(r'<[^>]+>', '', title)

    # 提取描述（第一个 key-insight 或 meta-bar 附近内容）
    desc_match = re.search(
        r'class="desc"[^>]*>(.*?)</div>', content, re.DOTALL
    )
    desc = desc_match.group(1).strip() if desc_match else ""
    desc = re.sub(r'<[^>]+>', '', desc).strip()

    # 提取股票代码和标签
    codes = re.findall(r'\d{5,6}\.(?:SH|SZ|HK|US)', content)
    tags = []
    for c in codes:
        if c.endswith(".HK"):
            tags.append("港股")
        elif c.endswith(".SH"):
            tags.append("A股")
        elif c.endswith(".SZ"):
            tags.append("A股")
        elif c.endswith(".US"):
            tags.append("美股")
        else:
            tags.append("股票")

    # 从 meta-bar 提取行业
    industry_match = re.search(r'行业[：:]\s*(.+?)(?:\s*<|$)', content)
    if industry_match:
        industry = industry_match.group(1).strip()
        # 拆分行业标签
        for seg in re.split(r'[·/、,，]', industry):
            seg = seg.strip()
            if seg and len(seg) <= 8:
                tags.append(seg)

    # 去重
    seen = set()
    tags = [t for t in tags if not (t in seen or seen.add(t))]

    return title, desc, str(html_path.stem), tags


def collect_reports() -> list[dict]:
    """扫描 SOURCE_DIR 并返回报告信息列表（按日期倒序）。"""
    reports = []
    if not SOURCE_DIR.exists():
        print(f"⚠ 来源目录不存在: {SOURCE_DIR}")
        return reports

    for f in sorted(SOURCE_DIR.glob("*.html"), reverse=True):
        code, name = parse_stock_code(f.name)
        if not code:
            continue
        rating = parse_rating(f)
        title, desc, stem, tags = parse_title_and_desc(f)

        # 从文件中提取 3-4 个关键句作为摘要
        report_date = stem[-10:] if len(stem) >= 10 else ""

        reports.append({
            "filename": f.name,
            "code": code,
            "name": name,
            "title": title,
            "description": desc,
            "date": report_date,
            "rating": rating,
            "tags": tags,
        })

    return reports


# ═══════════════════════════════════════════
# 文件复制
# ═══════════════════════════════════════════

def copy_reports(reports: list[dict]) -> list[str]:
    """将报告 HTML 复制到 TARGET_DIR。"""
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    for r in reports:
        src = SOURCE_DIR / r["filename"]
        dst = TARGET_DIR / r["filename"]
        shutil.copy2(src, dst)
        copied.append(r["filename"])
    return copied


# ═══════════════════════════════════════════
# 生成研报列表页
# ═══════════════════════════════════════════

RATING_MAP = {
    "buy": ("✅ 买入", "rating-buy"),
    "watch": ("⚡ 观察", "rating-watch"),
    "avoid": ("❌ 回避", "rating-avoid"),
}

TAG_COLOR = ["tag-blue", "tag-green", "tag-yellow"]


def _get_week_range(iso_year: int, iso_week: int) -> tuple[str, str]:
    """返回 ISO 周的周一和周日日期字符串（中文格式）。"""
    # ISO week 1 = 包含该年第一个周四的那一周
    jan4 = date(iso_year, 1, 4)
    # 周一到周日
    monday = jan4 + timedelta(days=-jan4.isoweekday() + 1 + (iso_week - 1) * 7)
    sunday = monday + timedelta(days=6)

    def fmt(d: date) -> str:
        return f"{d.month}月{d.day}日"

    return fmt(monday), fmt(sunday)


def _get_today_week() -> tuple[int, int]:
    """返回今天的 ISO 年份和周数。"""
    today = date.today()
    return today.isocalendar()[0], today.isocalendar()[1]


def generate_reports_html(reports: list[dict]) -> str:
    """生成 www/reports.html 内容（按周分组）。"""
    # ── 按 ISO 周分组 ──
    reports_by_week: dict[tuple[int, int], list] = {}  # (iso_year, iso_week) -> [...]
    for r in reports:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
            iso = d.isocalendar()
            key = (iso[0], iso[1])
        except (ValueError, IndexError):
            key = (9999, 0)  # 未知日期排最后
        reports_by_week.setdefault(key, []).append(r)

    today_year, today_week = _get_today_week()

    cards_html = ""
    for (iso_year, iso_week) in sorted(reports_by_week.keys(), reverse=True):
        reports_in_week = reports_by_week[(iso_year, iso_week)]
        n = len(reports_in_week)

        # 周范围标签
        monday_str, sunday_str = _get_week_range(iso_year, iso_week)

        # 判断是否本周
        is_current = (iso_year == today_year and iso_week == today_week)

        # 周分组头部
        section_class = 'week-section is-current' if is_current else 'week-section'
        now_badge = f'<span class="week-head__now">本周</span>' if is_current else ''
        cards_html += f'''
  <div class="{section_class}">
    <div class="week-head">
      <span class="week-head__num">第{iso_week}周</span>
      <span class="week-head__range">{monday_str} — {sunday_str}</span>
      <span class="week-head__count">{n} 篇</span>
      {now_badge}
    </div>'''

        for r in reports_in_week:
            rating_label, rating_class = RATING_MAP.get(
                r["rating"], ("⚡ 观察", "rating-watch")
            )

            tags_html = ""
            for i, tag in enumerate(r["tags"][:4]):
                tc = TAG_COLOR[i % len(TAG_COLOR)]
                tags_html += f'\n        <span class="tag {tc}">{tag}</span>'

            cards_html += f'''
    <a class="report-card" href="/reports/{quote(r["filename"], safe="-./")}">
      <div class="tag-box"><span class="rating {rating_class}">{rating_label}</span></div>
      <div class="info">
        <h3>{r["title"]}</h3>
        <div class="meta">
          <span>{r["date"]}</span>
          <span>{r["code"]}</span>
        </div>
        <div class="desc">
          {r["description"]}
        </div>
        <div class="tags">{tags_html}
        </div>
      </div>
      <div class="arrow">→</div>
    </a>'''

        cards_html += '\n  </div><!-- /.week-section -->'

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="index, follow" />
<title>深度研报 - 先机 ForeEdge</title>
<meta name="description" content="价值投资深度分析报告，基于巴菲特/段永平投资思想，覆盖A股/港股优质标的。" />
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />
<link rel="canonical" href="https://stock.futuretime.site/reports.html" />
<meta property="og:title" content="深度研报 - 先机 ForeEdge" />
<meta property="og:description" content="价值投资深度分析报告，基于巴菲特/段永平投资思想。" />
<meta property="og:url" content="https://stock.futuretime.site/reports.html" />
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebPage","name":"深度研报 - 先机 ForeEdge","description":"价值投资深度分析报告"}}</script>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-BJSQJ8DPH4"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','G-BJSQJ8DPH4');</script>
<script src="https://analytics.ahrefs.com/analytics.js" data-key="Nq/2xuSZW/DWTiQyhGqLcQ" async></script>
<style>
  :root {{
    --bg: #0a0e17; --card: #111827; --card-hover: #1a2332; --border: #1e293b;
    --text: #e5e7eb; --muted: #9ca3af; --accent: #6366f1; --accent-hover: #818cf8;
    --emerald: #34d399; --amber: #fbbf24; --rose: #f43f5e;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.7;
    min-height: 100vh; padding-top: 56px;
    background-image: radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99,102,241,0.08), transparent);
  }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}

  .topnav {{
    position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
    background: rgba(10,14,23,0.88); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid rgba(99,102,241,0.12);
    padding: 0 1.25rem; height: 52px;
    display: flex; align-items: center; justify-content: space-between;
  }}
  .topnav .brand {{ font-size: 1.15rem; font-weight: 800; color: #e2e8f0; text-decoration: none; letter-spacing: -0.5px; }}
  .topnav .brand span {{ color: var(--accent); }}
  .topnav .nav-links {{ display: flex; gap: 0.25rem; }}
  .topnav .nav-links a {{
    color: #94a3b8; text-decoration: none; padding: 6px 14px; border-radius: 8px;
    font-size: 0.82rem; font-weight: 500; transition: all 0.15s;
  }}
  .topnav .nav-links a:hover, .topnav .nav-links a.active {{ color: #e2e8f0; background: rgba(99,102,241,0.12); }}
  .topnav .nav-right {{ display: flex; align-items: center; gap: 0.5rem; }}
  .topnav .nav-right a {{
    color: #94a3b8; text-decoration: none; font-size: 0.75rem;
    padding: 5px 12px; border-radius: 6px; border: 1px solid rgba(99,102,241,0.2); transition: all 0.15s;
  }}
  .topnav .nav-right a:hover {{ color: #e2e8f0; background: rgba(99,102,241,0.1); border-color: rgba(99,102,241,0.4); }}
  @media(max-width:768px) {{ .topnav .nav-links {{ display: none; }} .topnav .menu-btn {{ display: flex; }} }}
  .topnav .menu-btn {{
    display: none; width: 36px; height: 36px; border-radius: 8px;
    align-items: center; justify-content: center; cursor: pointer;
    background: transparent; border: 1px solid rgba(99,102,241,0.2);
    color: #94a3b8; font-size: 1.1rem; transition: all 0.15s;
  }}
  .topnav .menu-btn:hover {{ background: rgba(99,102,241,0.1); color: #e2e8f0; }}
  .mobile-menu {{
    display: none; position: fixed; top: 48px; left: 0; right: 0; z-index: 999;
    background: rgba(10,14,23,0.96); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border-bottom: 1px solid rgba(99,102,241,0.15);
    padding: 0.75rem 1rem; flex-direction: column; gap: 0.25rem;
  }}
  .mobile-menu.show {{ display: flex; }}
  .mobile-menu a {{
    display: block; padding: 0.75rem 1rem; border-radius: 0.5rem;
    color: #94a3b8; text-decoration: none; font-size: 0.88rem; font-weight: 500;
    transition: all 0.15s;
  }}
  .mobile-menu a:hover, .mobile-menu a.active {{ color: #e2e8f0; background: rgba(99,102,241,0.1); }}

  .page-header {{ padding: 2.5rem 0 1.5rem; text-align: center; }}
  .page-header h1 {{ font-size: 2rem; font-weight: 800; }}
  .page-header h1 span {{ color: var(--accent); }}
  .page-header p {{ color: var(--muted); margin-top: 0.5rem; font-size: 0.95rem; max-width: 560px; margin-left: auto; margin-right: auto; }}

  .report-card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 1.5rem; margin-bottom: 1rem;
    display: flex; gap: 1.5rem; align-items: flex-start;
    transition: all 0.2s; cursor: pointer;
    text-decoration: none; color: inherit;
  }}
  .report-card:hover {{ background: var(--card-hover); border-color: rgba(99,102,241,0.3); transform: translateY(-1px); }}
  .report-card .tag-box {{ flex: 0 0 80px; text-align: center; }}
  .report-card .tag-box .rating {{
    display: inline-block; padding: 4px 12px; border-radius: 6px;
    font-size: 0.78rem; font-weight: 700;
  }}
  .rating-buy {{ background: rgba(52,211,153,0.15); color: var(--emerald); border: 1px solid var(--emerald); }}
  .rating-watch {{ background: rgba(251,191,36,0.15); color: var(--amber); border: 1px solid var(--amber); }}
  .rating-avoid {{ background: rgba(244,63,94,0.15); color: var(--rose); border: 1px solid var(--rose); }}
  .report-card .info {{ flex: 1; }}
  .report-card .info h3 {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 4px; }}
  .report-card .info .meta {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 6px; display: flex; gap: 12px; flex-wrap: wrap; }}
  .report-card .info .desc {{ font-size: 0.88rem; color: #cbd5e1; line-height: 1.6; }}
  .report-card .info .tags {{ margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }}
  .tag {{ display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }}
  .tag-green {{ background: rgba(52,211,153,0.12); color: var(--emerald); }}
  .tag-yellow {{ background: rgba(251,191,36,0.12); color: var(--amber); }}
  .tag-blue {{ background: rgba(99,102,241,0.12); color: var(--accent-hover); }}
  .report-card .arrow {{ flex: 0 0 24px; font-size: 1.2rem; color: var(--muted); align-self: center; }}

  @media(max-width:600px) {{
    .report-card {{ flex-direction: column; gap: 0.75rem; }}
    .report-card .tag-box {{ flex: 0 0 auto; text-align: left; }}
    .report-card .arrow {{ display: none; }}
  }}

  .section-title {{ font-size: 1.1rem; color: var(--muted); margin: 2rem 0 1rem; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; }}

  /* ── 周分组 ── */
  .week-section {{
    margin-bottom: 2.5rem;
  }}
  .week-section.is-current {{
    background: linear-gradient(135deg, rgba(52,211,153,0.04) 0%, rgba(52,211,153,0.01) 100%);
    border: 1px solid rgba(52,211,153,0.12);
    border-radius: 14px;
    padding: 1.25rem 1.25rem 0.25rem;
    margin-left: -1.25rem; margin-right: -1.25rem;
  }}
  .week-head {{
    display: flex; align-items: baseline; gap: 14px;
    padding-bottom: 0.75rem; margin-bottom: 0.25rem;
    border-bottom: 2px solid rgba(99,102,241,0.18);
  }}
  .week-section.is-current .week-head {{
    border-bottom-color: rgba(52,211,153,0.3);
  }}
  .week-head__num {{
    font-size: 1.05rem; font-weight: 800; color: var(--accent-hover);
    letter-spacing: -0.3px;
  }}
  .week-section.is-current .week-head__num {{
    color: var(--emerald);
  }}
  .week-head__range {{
    font-size: 0.85rem; color: var(--muted); flex: 1;
  }}
  .week-head__count {{
    font-size: 0.78rem; color: var(--accent);
    background: rgba(99,102,241,0.14); padding: 3px 12px;
    border-radius: 20px; font-weight: 600;
  }}
  .week-head__now {{
    font-size: 0.75rem; font-weight: 700; padding: 3px 10px;
    border-radius: 5px; background: rgba(52,211,153,0.2);
    color: var(--emerald); border: 1px solid rgba(52,211,153,0.3);
  }}
  @media(max-width:600px) {{
    .week-section.is-current {{
      margin-left: -0.5rem; margin-right: -0.5rem;
      padding: 1rem 0.5rem 0.25rem;
    }}
    .week-head {{ gap: 8px; }}
    .week-head__num {{ font-size: 0.9rem; }}
    .week-head__range {{ font-size: 0.75rem; }}
  }}

  footer {{
    text-align: center; padding: 2.5rem 0;
    border-top: 1px solid var(--border); color: var(--muted); font-size: 0.82rem;
    max-width: 960px; margin: 0 auto;
  }}
  footer a {{ color: var(--accent-hover); text-decoration: none; }}
  footer a:hover {{ text-decoration: underline; }}
  footer .disclaimer {{ color: var(--rose); font-weight: 500; margin-top: 0.3rem; }}
</style>
</head>
<body>

<nav class="topnav">
  <a href="/" class="brand">先机</a>
  <div class="nav-links">
    <a href="/">首页</a>
    <a href="/events.html">事件日历</a>
    <a href="/backtest.html">回溯实验室</a>
    <a href="/knowledge.html">知识库</a>
    <a href="/reports.html" class="active">📖 研报</a>
    <a href="/app/discover">题材雷达</a>
  </div>
  <div class="nav-right">
    <a href="/app/discover" style="background:#4f46e5;color:#fff;padding:.4rem .85rem;border-radius:.6rem;font-weight:700;font-size:.85rem;text-decoration:none">进入 App</a>
    <a href="/en/">EN</a>
    <button class="menu-btn" onclick="toggleMobileMenu()" aria-label="菜单">☰</button>
  </div>
</nav>
<div class="mobile-menu" id="mobileMenu">
  <a href="/">首页</a>
  <a href="/events.html">事件日历</a>
  <a href="/backtest.html">回溯实验室</a>
  <a href="/knowledge.html">知识库</a>
  <a href="/reports.html" class="active">📖 研报</a>
  <a href="/app/discover">题材雷达 App</a>
</div>

<div class="wrap">

  <div class="page-header">
    <h1>📖 深度<span>研报</span></h1>
    <p>价值投资分析报告，基于巴菲特/段永平投资思想。好生意 + 好管理 + 好价格 = 好投资。</p>
  </div>

  {cards_html}

</div>

<footer>
  <p>先机 · 快人一步</p>
  <p class="disclaimer">⚠️ 免责声明：仅供分析参考，不构成投资建议。市场有风险，投资需谨慎。</p>
  <p style="margin-top:0.5rem"><a href="/events.html">事件日历</a> · <a href="/backtest.html">回溯实验室</a> · <a href="/knowledge.html">知识库</a> · <a href="/reports.html">深度研报</a> · <a href="/cards/">每日卡片</a></p>
  <p style="margin-top:0.5rem;color:var(--muted)">© 2026 先机 · <a href="mailto:contact@futuretime.site">contact@futuretime.site</a></p>
</footer>

<script>
function toggleMobileMenu() {{
  document.getElementById('mobileMenu').classList.toggle('show');
}}
</script>
</body>
</html>'''


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════

def main():
    print("=" * 50)
    print("[Publish] analysis reports -> stock-theme-assistant")
    print("=" * 50)
    print(f"\nSource: {SOURCE_DIR}")
    print(f"Target: {TARGET_DIR}")

    # 1. Check stock-theme-assistant dir exists
    if not STOCK_THEME_ASSISTANT_DIR.exists():
        print(f"\n[ERROR] stock-theme-assistant dir not found")
        print(f"   Set STOCK_THEME_ASSISTANT_DIR env var or edit script config")
        sys.exit(1)

    if not (STOCK_THEME_ASSISTANT_DIR / "www").exists():
        print(f"\n[ERROR] {STOCK_THEME_ASSISTANT_DIR} is not a valid project dir (missing www/)")
        sys.exit(1)

    # 2. Collect reports
    reports = collect_reports()
    if not reports:
        print(f"\n[WARN] No reports found in {SOURCE_DIR}")
        sys.exit(0)

    print(f"\n[Scan] Found {len(reports)} report(s):")
    for r in reports:
        rating_icon = {"buy": "[BUY]", "watch": "[WATCH]", "avoid": "[AVOID]"}.get(r["rating"], "[WATCH]")
        title_clean = re.sub(r'[^\x20-\x7E一-鿿　-〿＀-￯]', '', r['title'])
        print(f"   {rating_icon} {r['code']} {title_clean[:40]} ({r['date']})")

    # 3. Copy files
    copied = copy_reports(reports)
    print(f"\n[Copy] {len(copied)} file(s) -> {TARGET_DIR}")

    # 4. Generate report listing page
    html = generate_reports_html(reports)
    reports_page = STOCK_THEME_ASSISTANT_DIR / "www" / "reports.html"
    reports_page.write_text(html, encoding="utf-8")
    print(f"[Page] Updated: {reports_page}")

    print(f"\n[Done] Publish success!")
    print(f"   https://stock.futuretime.site/reports.html")
    print()
    print("═" * 50)
    print(">> 下一步: 部署到生产服务器 <<")
    print("═" * 50)
    print("git push 后还需在 CVM 上执行：")
    print()
    print("   # 登录服务器")
    print("   ssh root@124.156.154.129")
    print()
    print("   # 拉取最新文件 + 重启服务")
    print("   cd /opt/stock_1")
    print("   git pull")
    print("   systemctl restart theme-assistant")
    print()
    print("   或通过腾讯云 OrcaTerm 网页终端操作：")
    print("   https://orcaterm.cloud.tencent.com/terminal?type=cvm&instanceId=ins-clv3bkp2&region=ap-hongkong")


if __name__ == "__main__":
    main()
