"""渲染输出：Markdown、单文件 HTML，以及总索引页。"""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from pathlib import Path

from .generator import StoryDoc

INVALID_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
META_RE = re.compile(r"<!--\s*meta:\s*(\{.*?\})\s*-->", re.S)


def safe_filename(name: str) -> str:
    cleaned = INVALID_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "未命名"


def build_filename(doc: StoryDoc, run_date: date, suffix: str) -> str:
    return f"{run_date.isoformat()}_{safe_filename(doc.item.title)}.{suffix}"


# ---------------------------------------------------------------- Markdown

def render_markdown(doc: StoryDoc, run_date: date) -> str:
    item, outline = doc.item, doc.outline
    meta = {
        "title": item.title,
        "date": run_date.isoformat(),
        "kind": item.kind,
        "year": item.year,
        "country": item.country,
        "genre": item.genre,
        "segments": len(doc.segments),
        "rule": doc.segment_rule,
    }

    meta_bits = [run_date.isoformat(), item.kind or "影视"]
    for value in (item.country, item.genre, item.year):
        if value:
            meta_bits.append(value)
    meta_bits.append(doc.segment_rule)

    lines: list[str] = []
    lines.append(f"<!-- meta: {json.dumps(meta, ensure_ascii=False)} -->")
    lines.append("")
    lines.append(f"# {item.title}")
    lines.append("")
    lines.append("> " + " · ".join(meta_bits))
    lines.append("")

    if outline.logline:
        lines.append("## 一句话故事")
        lines.append("")
        lines.append(f"**{outline.logline}**")
        lines.append("")

    if outline.setting:
        lines.append(f"**时代背景**：{outline.setting}")
        lines.append("")

    if outline.characters:
        lines.append("## 主要人物")
        lines.append("")
        lines.append("| 人物 | 身份 | 简介 |")
        lines.append("| --- | --- | --- |")
        for ch in outline.characters:
            lines.append(f"| {_md(ch['name'])} | {_md(ch['role'])} | {_md(ch['desc'])} |")
        lines.append("")

    if outline.acts:
        lines.append("## 故事脉络")
        lines.append("")
        for idx, act in enumerate(outline.acts, 1):
            name = _md(act["name"])
            desc = _md(act["desc"])
            lines.append(f"{idx}. **{name}**" + (f" —— {desc}" if desc else ""))
        lines.append("")

    lines.append(f"## 分段梗概（共 {len(doc.segments)} 段）")
    lines.append("")
    for seg in doc.segments:
        lines.append(f"### 第 {seg.index} 段 · {seg.range} · {seg.title}")
        lines.append("")
        lines.append(seg.summary)
        lines.append("")
        if seg.events:
            lines.append("**关键事件**：" + " ｜ ".join(seg.events))
            lines.append("")

    if outline.turning_points:
        lines.append("## 关键转折")
        lines.append("")
        lines.append("| 位置 | 转折 |")
        lines.append("| --- | --- |")
        for tp in outline.turning_points:
            lines.append(f"| {_md(tp['at'])} | {_md(tp['event'])} |")
        lines.append("")

    if outline.themes:
        lines.append("## 主题关键词")
        lines.append("")
        lines.append(" · ".join(f"`{_md(t)}`" for t in outline.themes))
        lines.append("")

    if outline.ending:
        lines.append("## 结局走向")
        lines.append("")
        lines.append(outline.ending)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"*生成时间：{doc.generated_at:%Y-%m-%d %H:%M} ｜ 模型：{doc.model} ｜ "
        f"内容由 AI 依据作品公开剧情整理，仅作阅读参考*"
    )
    lines.append("")
    return "\n".join(lines)


def _md(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------- HTML

CSS = """
:root{
  --bg:#f6f7f9; --panel:#ffffff; --text:#1b1f24; --muted:#666f7a;
  --line:#e3e7ec; --accent:#b4262b; --accent-soft:#fdf1f1; --chip:#eef1f5;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.05);
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#14171c; --panel:#1b1f26; --text:#e8ecf1; --muted:#9aa4b1;
    --line:#2b313a; --accent:#e2565b; --accent-soft:#2a1d1f; --chip:#242a33;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);
  }
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--text);
  font-family:"Microsoft YaHei","PingFang SC","Hiragino Sans GB","Noto Sans SC",system-ui,sans-serif;
  font-size:16px; line-height:1.85; -webkit-font-smoothing:antialiased;
}
a{color:inherit}
.wrap{max-width:1180px; margin:0 auto; padding:0 20px 80px}
header.top{padding:56px 0 28px; border-bottom:1px solid var(--line)}
h1{margin:0 0 14px; font-size:34px; line-height:1.25; letter-spacing:.5px}
h1 .year{color:var(--muted); font-size:20px; font-weight:400; margin-left:8px}
.chips{display:flex; flex-wrap:wrap; gap:8px; margin-top:6px}
.chip{
  background:var(--chip); color:var(--muted); border-radius:999px;
  padding:3px 12px; font-size:13px; line-height:1.7;
}
.chip.hot{background:var(--accent-soft); color:var(--accent)}
.logline{
  margin:30px 0 8px; padding:22px 26px; background:var(--panel); border-radius:14px;
  border-left:4px solid var(--accent); box-shadow:var(--shadow); font-size:18px; line-height:1.9;
}
.layout{display:grid; grid-template-columns:230px minmax(0,1fr); gap:36px; margin-top:34px; align-items:start}
nav.toc{position:sticky; top:24px; max-height:calc(100vh - 60px); overflow:auto; padding-right:6px}
nav.toc h2{font-size:12px; letter-spacing:1.6px; color:var(--muted); text-transform:uppercase; margin:0 0 12px}
nav.toc ol{list-style:none; margin:0; padding:0; counter-reset:seg}
nav.toc li{counter-increment:seg; margin:0}
nav.toc a{
  display:block; padding:6px 10px 6px 34px; position:relative; border-radius:8px;
  font-size:13.5px; color:var(--muted); text-decoration:none; line-height:1.5;
  border-left:2px solid transparent;
}
nav.toc a::before{
  content:counter(seg); position:absolute; left:10px; top:6px;
  font-size:11px; color:var(--muted); opacity:.7; font-variant-numeric:tabular-nums;
}
nav.toc a:hover{background:var(--chip); color:var(--text)}
nav.toc a.active{background:var(--accent-soft); color:var(--accent); border-left-color:var(--accent)}
main{min-width:0}
section{margin-bottom:44px}
h2.sec{
  font-size:15px; letter-spacing:2px; color:var(--muted); font-weight:600;
  margin:0 0 18px; padding-bottom:10px; border-bottom:1px solid var(--line);
}
table{width:100%; border-collapse:collapse; font-size:14.5px; background:var(--panel);
  border-radius:12px; overflow:hidden; box-shadow:var(--shadow)}
th,td{padding:11px 14px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top}
th{background:var(--chip); font-weight:600; font-size:13px; color:var(--muted); letter-spacing:.5px}
tr:last-child td{border-bottom:none}
.cards{display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:12px}
.person{background:var(--panel); border-radius:12px; padding:14px 16px; box-shadow:var(--shadow)}
.person .n{font-weight:600}
.person .r{font-size:12px; color:var(--accent); margin-left:6px}
.person .d{font-size:13.5px; color:var(--muted); margin-top:4px; line-height:1.6}
.acts{counter-reset:act; display:grid; gap:10px}
.act{display:flex; gap:14px; align-items:baseline; background:var(--panel);
  border-radius:10px; padding:12px 16px; box-shadow:var(--shadow)}
.act .idx{font-size:12px; color:var(--accent); font-weight:700; letter-spacing:1px; min-width:22px}
.act .nm{font-weight:600; min-width:110px}
.act .ds{color:var(--muted); font-size:14px}
.seg{
  background:var(--panel); border-radius:14px; padding:20px 24px; margin-bottom:14px;
  box-shadow:var(--shadow); scroll-margin-top:20px; border:1px solid transparent;
}
.seg:target{border-color:var(--accent)}
.seg .head{display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:10px}
.seg .no{
  background:var(--accent); color:#fff; border-radius:6px; font-size:12px;
  padding:1px 8px; font-weight:600; letter-spacing:.5px; font-variant-numeric:tabular-nums;
}
.seg .tm{font-size:12.5px; color:var(--muted); font-variant-numeric:tabular-nums}
.seg h3{margin:0; font-size:17.5px; line-height:1.5}
.seg p{margin:0; font-size:15.5px; line-height:1.95; color:var(--text)}
.events{display:flex; flex-wrap:wrap; gap:7px; margin-top:12px}
.ev{background:var(--chip); color:var(--muted); border-radius:6px; padding:3px 10px; font-size:12.5px}
.themes{display:flex; flex-wrap:wrap; gap:8px}
.theme{background:var(--accent-soft); color:var(--accent); border-radius:999px; padding:4px 14px; font-size:13.5px}
.ending{background:var(--panel); border-radius:12px; padding:18px 22px; box-shadow:var(--shadow); line-height:1.95}
footer{margin-top:60px; padding-top:20px; border-top:1px solid var(--line); color:var(--muted); font-size:13px}
@media (max-width:900px){
  .layout{grid-template-columns:1fr; gap:20px}
  nav.toc{position:static; max-height:none; display:none}
  h1{font-size:26px}
  .wrap{padding:0 16px 60px}
  header.top{padding:34px 0 20px}
  .seg{padding:16px 18px}
}
@media print{
  nav.toc{display:none} .layout{grid-template-columns:1fr}
  body{background:#fff} .seg,.logline,.person,.act,.ending,table{box-shadow:none; border:1px solid #ddd}
}
"""

JS = """
(function(){
  var links = Array.prototype.slice.call(document.querySelectorAll('nav.toc a'));
  if(!links.length || !('IntersectionObserver' in window)) return;
  var map = {};
  links.forEach(function(a){ map[a.getAttribute('href').slice(1)] = a; });
  var current = null;
  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(e.isIntersecting){
        if(current) current.classList.remove('active');
        current = map[e.target.id];
        if(current) current.classList.add('active');
      }
    });
  }, {rootMargin:'-10% 0px -75% 0px', threshold:0});
  document.querySelectorAll('section.seg').forEach(function(s){ io.observe(s); });
})();
"""


def _e(text: str) -> str:
    return html.escape(text or "", quote=True)


def render_html(doc: StoryDoc, run_date: date) -> str:
    item, outline = doc.item, doc.outline

    chips = [f'<span class="chip hot">{_e(run_date.isoformat())}</span>']
    for label in (item.kind, item.country, item.genre, item.year):
        if label:
            chips.append(f'<span class="chip">{_e(label)}</span>')
    chips.append(f'<span class="chip">{_e(doc.segment_rule)}</span>')

    toc_items = "\n".join(
        f'<li><a href="#seg{seg.index}">{_e(seg.title)}</a></li>' for seg in doc.segments
    )

    people = "\n".join(
        f'<div class="person"><div><span class="n">{_e(ch["name"])}</span>'
        f'<span class="r">{_e(ch["role"])}</span></div>'
        f'<div class="d">{_e(ch["desc"])}</div></div>'
        for ch in outline.characters
    )

    acts = "\n".join(
        f'<div class="act"><span class="idx">{i:02d}</span>'
        f'<span class="nm">{_e(a["name"])}</span>'
        f'<span class="ds">{_e(a["desc"])}</span></div>'
        for i, a in enumerate(outline.acts, 1)
    )

    segs = []
    for seg in doc.segments:
        events = ""
        if seg.events:
            events = '<div class="events">' + "".join(
                f'<span class="ev">{_e(e)}</span>' for e in seg.events
            ) + "</div>"
        segs.append(f"""
<section class="seg" id="seg{seg.index}">
  <div class="head">
    <span class="no">第 {seg.index} 段</span>
    <span class="tm">{_e(seg.range)}</span>
    <h3>{_e(seg.title)}</h3>
  </div>
  <p>{_e(seg.summary)}</p>
  {events}
</section>""")
    seg_html = "\n".join(segs)

    turning = ""
    if outline.turning_points:
        rows = "".join(
            f"<tr><td>{_e(tp['at'])}</td><td>{_e(tp['event'])}</td></tr>"
            for tp in outline.turning_points
        )
        turning = f"""
<section>
  <h2 class="sec">关键转折</h2>
  <table><thead><tr><th style="width:150px">位置</th><th>转折</th></tr></thead>
  <tbody>{rows}</tbody></table>
</section>"""

    themes = ""
    if outline.themes:
        themes = '<section><h2 class="sec">主题关键词</h2><div class="themes">' + "".join(
            f'<span class="theme">{_e(t)}</span>' for t in outline.themes
        ) + "</div></section>"

    ending = ""
    if outline.ending:
        ending = f'<section><h2 class="sec">结局走向</h2><div class="ending">{_e(outline.ending)}</div></section>'

    setting = f'<span class="chip">{_e(outline.setting)}</span>' if outline.setting else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(item.title)} · 分段故事梗概 · {run_date.isoformat()}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>{_e(item.title)}<span class="year">{_e(item.year)}</span></h1>
    <div class="chips">{''.join(chips)}{setting}</div>
    <div class="logline">{_e(outline.logline)}</div>
  </header>

  <div class="layout">
    <nav class="toc">
      <h2>分段导航 · {len(doc.segments)} 段</h2>
      <ol>{toc_items}</ol>
    </nav>
    <main>
      {'<section><h2 class="sec">主要人物</h2><div class="cards">' + people + '</div></section>' if people else ''}
      {'<section><h2 class="sec">故事脉络</h2><div class="acts">' + acts + '</div></section>' if acts else ''}
      <section>
        <h2 class="sec">分段梗概</h2>
        {seg_html}
      </section>
      {turning}
      {themes}
      {ending}
    </main>
  </div>

  <footer>
    生成时间 {doc.generated_at:%Y-%m-%d %H:%M} · 模型 {_e(doc.model)} · 共 {len(doc.segments)} 段<br>
    内容由 AI 依据作品公开剧情整理，仅作阅读参考。
  </footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------- 邮件版

EMAIL_TMPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title></head>
<body style="margin:0;padding:0;background:#f4f5f7;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="680" cellpadding="0" cellspacing="0" style="width:680px;max-width:96%;background:#ffffff;border-radius:10px;overflow:hidden;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;color:#1b1f24;line-height:1.85;">
<tr><td style="padding:28px 32px 20px;border-bottom:1px solid #e6e9ed;">
<h1 style="margin:0 0 8px;font-size:26px;line-height:1.3;font-weight:700;">{title}<span style="font-size:16px;color:#8a929c;font-weight:400;"> {year}</span></h1>
<div style="font-size:13px;color:#8a929c;">{meta}</div>
</td></tr>

<tr><td style="padding:24px 32px 8px;">
<div style="padding:16px 18px;background:#fdf3f3;border-left:4px solid #b4262b;border-radius:6px;font-size:16px;line-height:1.85;">{logline}</div>
</td></tr>

{people}
{acts}

<tr><td style="padding:12px 32px 0;">
<h2 style="margin:0 0 14px;font-size:13px;letter-spacing:2px;color:#8a929c;border-bottom:1px solid #e6e9ed;padding-bottom:8px;">分段梗概（共 {seg_count} 段）</h2>
</td></tr>

{segments}

{turning}
{themes}
{ending}

<tr><td style="padding:26px 32px 30px;border-top:1px solid #e6e9ed;margin-top:20px;">
<div style="font-size:12.5px;color:#8a929c;line-height:1.8;">
生成时间 {generated} ｜ 模型 {model}<br>
内容由 AI 依据作品公开剧情整理，仅作阅读参考。完整文件见附件。
</div>
</td></tr>
</table>
</td></tr></table>
</body></html>"""

EMAIL_PEOPLE_TMPL = """
<tr><td style="padding:16px 32px 0;">
<h2 style="margin:0 0 12px;font-size:13px;letter-spacing:2px;color:#8a929c;border-bottom:1px solid #e6e9ed;padding-bottom:8px;">主要人物</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;font-size:14px;">
{person_rows}
</table>
</td></tr>
"""

EMAIL_ACTS_TMPL = """
<tr><td style="padding:16px 32px 0;">
<h2 style="margin:0 0 12px;font-size:13px;letter-spacing:2px;color:#8a929c;border-bottom:1px solid #e6e9ed;padding-bottom:8px;">故事脉络</h2>
{act_rows}
</td></tr>
"""

EMAIL_SEG_TMPL = """
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;margin:0 0 12px;">
<tr><td style="background:#fafbfc;border:1px solid #e6e9ed;border-radius:8px;padding:16px 18px;">
<div style="margin-bottom:8px;">
<span style="display:inline-block;background:#b4262b;color:#ffffff;font-size:11px;padding:2px 8px;border-radius:4px;">第 {index} 段</span>
<span style="font-size:12.5px;color:#8a929c;margin-left:8px;">{range}</span>
<span style="font-size:16px;font-weight:600;margin-left:10px;">{seg_title}</span>
</div>
<div style="font-size:14.5px;line-height:1.9;color:#1b1f24;">{summary}</div>
{events}
</td></tr></table>
"""

EMAIL_EVENTS_TMPL = """<div style="margin-top:10px;">{event_chips}</div>"""

EMAIL_EVENT_CHIP = """<span style="display:inline-block;background:#eef1f5;color:#6b7480;font-size:12px;padding:2px 9px;border-radius:4px;margin:0 6px 6px 0;">{text}</span>"""

EMAIL_TABLE_TMPL = """
<tr><td style="padding:16px 32px 0;">
<h2 style="margin:0 0 12px;font-size:13px;letter-spacing:2px;color:#8a929c;border-bottom:1px solid #e6e9ed;padding-bottom:8px;">{heading}</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;font-size:14px;">
{rows}
</table>
</td></tr>
"""

EMAIL_THEMES_TMPL = """
<tr><td style="padding:16px 32px 0;">
<h2 style="margin:0 0 12px;font-size:13px;letter-spacing:2px;color:#8a929c;border-bottom:1px solid #e6e9ed;padding-bottom:8px;">主题关键词</h2>
<div>{chips}</div>
</td></tr>
"""

EMAIL_ENDING_TMPL = """
<tr><td style="padding:16px 32px 0;">
<h2 style="margin:0 0 12px;font-size:13px;letter-spacing:2px;color:#8a929c;border-bottom:1px solid #e6e9ed;padding-bottom:8px;">结局走向</h2>
<div style="padding:14px 16px;background:#f7f8fa;border-radius:6px;font-size:14.5px;line-height:1.9;">{ending}</div>
</td></tr>
"""


def render_email_html(doc: StoryDoc, run_date: date) -> str:
    item, outline = doc.item, doc.outline

    meta_bits = [run_date.isoformat(), item.kind or "影视"]
    for value in (item.country, item.genre, item.year):
        if value:
            meta_bits.append(value)
    meta_bits.append(doc.segment_rule)

    people = ""
    if outline.characters:
        rows = "".join(
            '<tr>'
            f'<td style="padding:9px 10px;border-bottom:1px solid #eef1f5;white-space:nowrap;">'
            f'<b>{_e(ch["name"])}</b></td>'
            f'<td style="padding:9px 10px;border-bottom:1px solid #eef1f5;color:#b4262b;font-size:13px;white-space:nowrap;">{_e(ch["role"])}</td>'
            f'<td style="padding:9px 10px;border-bottom:1px solid #eef1f5;color:#5a626c;">{_e(ch["desc"])}</td>'
            '</tr>'
            for ch in outline.characters
        )
        people = EMAIL_PEOPLE_TMPL.format(person_rows=rows)

    acts = ""
    if outline.acts:
        rows = "".join(
            '<div style="margin:0 0 8px;font-size:14.5px;">'
            f'<b style="color:#b4262b;">{i:02d}</b> '
            f'<b style="margin:0 8px;">{_e(a["name"])}</b>'
            f'<span style="color:#5a626c;">{_e(a["desc"])}</span></div>'
            for i, a in enumerate(outline.acts, 1)
        )
        acts = EMAIL_ACTS_TMPL.format(act_rows=rows)

    seg_parts = []
    for seg in doc.segments:
        events = ""
        if seg.events:
            chips = "".join(
                EMAIL_EVENT_CHIP.format(text=_e(e)) for e in seg.events
            )
            events = EMAIL_EVENTS_TMPL.format(event_chips=chips)
        seg_parts.append(EMAIL_SEG_TMPL.format(
            index=seg.index,
            range=_e(seg.range),
            seg_title=_e(seg.title),
            summary=_e(seg.summary),
            events=events,
        ))

    turning = ""
    if outline.turning_points:
        rows = "".join(
            f'<tr><td style="padding:9px 10px;border-bottom:1px solid #eef1f5;color:#8a929c;white-space:nowrap;">{_e(tp["at"])}</td>'
            f'<td style="padding:9px 10px;border-bottom:1px solid #eef1f5;">{_e(tp["event"])}</td></tr>'
            for tp in outline.turning_points
        )
        turning = EMAIL_TABLE_TMPL.format(heading="关键转折", rows=rows)

    themes = ""
    if outline.themes:
        chips = "".join(
            f'<span style="display:inline-block;background:#fdf3f3;color:#b4262b;font-size:13px;padding:3px 12px;border-radius:12px;margin:0 8px 8px 0;">{_e(t)}</span>'
            for t in outline.themes
        )
        themes = EMAIL_THEMES_TMPL.format(chips=chips)

    ending = ""
    if outline.ending:
        ending = EMAIL_ENDING_TMPL.format(ending=_e(outline.ending))

    return EMAIL_TMPL.format(
        title=_e(item.title),
        year=_e(item.year),
        meta=_e(" · ".join(meta_bits)),
        logline=_e(outline.logline),
        people=people,
        acts=acts,
        seg_count=len(doc.segments),
        segments="".join(seg_parts),
        turning=turning,
        themes=themes,
        ending=ending,
        generated=f"{doc.generated_at:%Y-%m-%d %H:%M}",
        model=_e(doc.model),
    )


def render_email_text(doc: StoryDoc, run_date: date) -> str:
    """纯文本版，作为 HTML 的替代内容。"""
    item, outline = doc.item, doc.outline
    lines = [
        f"《{item.title}》{('（' + item.year + '）') if item.year else ''}",
        f"日期：{run_date.isoformat()} ｜ {item.kind} ｜ {item.genre} ｜ {doc.segment_rule}",
        "",
        "【一句话故事】",
        outline.logline,
        "",
    ]
    if outline.characters:
        lines.append("【主要人物】")
        for ch in outline.characters:
            lines.append(f"  · {ch['name']}（{ch['role']}）—— {ch['desc']}")
        lines.append("")
    if outline.acts:
        lines.append("【故事脉络】")
        for i, act in enumerate(outline.acts, 1):
            lines.append(f"  {i}. {act['name']} —— {act['desc']}")
        lines.append("")
    lines.append(f"【分段梗概（共 {len(doc.segments)} 段）】")
    for seg in doc.segments:
        lines.append("")
        lines.append(f"第 {seg.index} 段 · {seg.range} · {seg.title}")
        lines.append(seg.summary)
        if seg.events:
            lines.append("关键事件：" + " ｜ ".join(seg.events))
    if outline.ending:
        lines.extend(["", "【结局走向】", outline.ending])
    lines.extend([
        "",
        f"生成时间 {doc.generated_at:%Y-%m-%d %H:%M} ｜ 模型 {doc.model}",
        "内容由 AI 依据作品公开剧情整理，仅作阅读参考。",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------- 失败告警邮件


def render_alert_html(*, title: str, stage: str, reason: str,
                      advice: list[str], run_date: date,
                      where: str = "") -> str:
    """生成任务失败时的告警邮件正文（内联样式，兼容邮件客户端）。"""
    cells = [
        ("日期", run_date.isoformat()),
        ("作品", title or "（未确定）"),
        ("失败环节", stage),
        ("运行环境", where or "未知"),
    ]
    rows = "".join(
        f'<tr>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #eee;color:#666;'
        f'font-size:13px;white-space:nowrap;vertical-align:top;">{_e(k)}</td>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #eee;color:#111;'
        f'font-size:14px;">{_e(v)}</td>'
        f'</tr>'
        for k, v in cells
    )
    tips = "".join(
        f'<li style="margin:6px 0;color:#333;font-size:14px;line-height:1.7;">{_e(a)}</li>'
        for a in advice
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f7;">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;
     font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',
     'Microsoft YaHei',sans-serif;">
  <div style="background:#fff;border-radius:12px;overflow:hidden;
       box-shadow:0 2px 12px rgba(0,0,0,.06);">
    <div style="background:#c0392b;padding:20px 24px;">
      <div style="color:#fff;font-size:18px;font-weight:600;">今日梗概生成失败</div>
      <div style="color:rgba(255,255,255,.85);font-size:13px;margin-top:4px;">
        每日影视故事梗概 · 自动告警
      </div>
    </div>
    <div style="padding:20px 24px;">
      <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">{rows}</table>
      <div style="background:#fdf2f2;border-left:3px solid #c0392b;border-radius:4px;
           padding:12px 14px;margin-bottom:18px;">
        <div style="color:#8b1e12;font-size:13px;font-weight:600;margin-bottom:6px;">失败原因</div>
        <div style="color:#5a1410;font-size:14px;line-height:1.7;word-break:break-word;">
          {_e(reason)}
        </div>
      </div>
      <div style="color:#111;font-size:14px;font-weight:600;margin-bottom:8px;">怎么处理</div>
      <ol style="margin:0;padding-left:22px;">{tips}</ol>
    </div>
    <div style="padding:14px 24px;background:#fafafa;border-top:1px solid #eee;
         color:#999;font-size:12px;line-height:1.6;">
      这封邮件由程序自动发出。修好之后可以手动补跑今天的：<br>
      <code style="color:#555;">python run.py</code>（本机）或到 GitHub Actions 页面点 Run workflow（云端）。
    </div>
  </div>
</div>
</body></html>"""


def render_alert_text(*, title: str, stage: str, reason: str,
                      advice: list[str], run_date: date, where: str = "") -> str:
    lines = [
        "【每日影视故事梗概】今日生成失败",
        "",
        f"日期：{run_date.isoformat()}",
        f"作品：{title or '（未确定）'}",
        f"失败环节：{stage}",
        f"运行环境：{where or '未知'}",
        "",
        "失败原因：",
        reason,
        "",
        "怎么处理：",
    ]
    lines += [f"  {i}. {a}" for i, a in enumerate(advice, 1)]
    lines += [
        "",
        "修好之后可以手动补跑今天的：python run.py（本机）",
        "或到 GitHub Actions 页面点 Run workflow（云端）。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 索引页

def collect_entries(output_dir: Path) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(output_dir.glob("*.md")):
        if path.name.startswith("索引"):
            continue
        try:
            head = path.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        match = META_RE.search(head)
        if not match:
            continue
        try:
            meta = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        meta["stem"] = path.stem
        meta["has_html"] = path.with_suffix(".html").exists()
        entries.append(meta)
    entries.sort(key=lambda m: (m.get("date", ""), m.get("title", "")), reverse=True)
    return entries


def render_index(output_dir: Path) -> tuple[Path, Path]:
    entries = collect_entries(output_dir)
    total_segments = sum(int(e.get("segments") or 0) for e in entries)

    md = ["# 每日影视故事梗概 · 总索引", ""]
    md.append(f"共 {len(entries)} 部作品，累计 {total_segments} 段梗概。")
    md.append("")
    md.append("| 日期 | 作品 | 类型 | 段数 | 文件 |")
    md.append("| --- | --- | --- | --- | --- |")
    for e in entries:
        link = f"[{e.get('title','')}]({e['stem']}.md)"
        html_link = f"[网页版]({e['stem']}.html)" if e.get("has_html") else ""
        md.append(
            f"| {e.get('date','')} | {link} | {e.get('kind','')} | "
            f"{e.get('segments','')} | {html_link} |"
        )
    md.append("")
    md_path = output_dir / "索引.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    rows = []
    for e in entries:
        target = f"{e['stem']}.html" if e.get("has_html") else f"{e['stem']}.md"
        rows.append(
            f'<a class="row" href="{_e(target)}">'
            f'<span class="d">{_e(e.get("date",""))}</span>'
            f'<span class="t">{_e(e.get("title",""))}</span>'
            f'<span class="k">{_e(e.get("kind",""))}</span>'
            f'<span class="s">{e.get("segments","")} 段</span></a>'
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日影视故事梗概 · 总索引</title>
<style>
:root{{--bg:#f6f7f9;--panel:#fff;--text:#1b1f24;--muted:#666f7a;--line:#e3e7ec;--accent:#b4262b;--chip:#eef1f5;
--shadow:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.05)}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171c;--panel:#1b1f26;--text:#e8ecf1;--muted:#9aa4b1;
--line:#2b313a;--accent:#e2565b;--chip:#242a33;--shadow:0 1px 2px rgba(0,0,0,.3)}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;line-height:1.8}}
.wrap{{max-width:860px;margin:0 auto;padding:56px 20px 80px}}
h1{{font-size:30px;margin:0 0 10px}}
.sub{{color:var(--muted);margin-bottom:32px;font-size:15px}}
.list{{display:flex;flex-direction:column;gap:8px}}
.row{{display:grid;grid-template-columns:110px 1fr 70px 70px;gap:12px;align-items:center;
background:var(--panel);border-radius:10px;padding:13px 18px;text-decoration:none;color:inherit;box-shadow:var(--shadow)}}
.row:hover{{outline:1px solid var(--accent)}}
.row .d{{color:var(--muted);font-size:13.5px;font-variant-numeric:tabular-nums}}
.row .t{{font-weight:600}}
.row .k,.row .s{{color:var(--muted);font-size:13px;text-align:right}}
@media(max-width:600px){{.row{{grid-template-columns:1fr auto}}.row .k{{display:none}}}}
</style></head><body><div class="wrap">
<h1>每日影视故事梗概</h1>
<div class="sub">共 {len(entries)} 部作品 · 累计 {total_segments} 段梗概</div>
<div class="list">{''.join(rows)}</div>
</div></body></html>"""
    html_path = output_dir / "索引.html"
    html_path.write_text(html_doc, encoding="utf-8")
    return md_path, html_path
