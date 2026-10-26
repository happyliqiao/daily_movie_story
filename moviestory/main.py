"""命令行入口：每天生成一篇影视分段故事梗概。"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from . import catalog, render
from .config import load_config
from .generator import generate
from .llm import LLMClient, LLMError

log = logging.getLogger("moviestory")


def setup_logging(log_dir: Path, verbose: bool) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(ch)
    return log_file


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moviestory",
        description="每天自动生成一篇电影/电视剧的分段故事梗概",
    )
    p.add_argument("--title", "-t", help="指定作品名（默认按片库轮播）")
    p.add_argument("--date", "-d", help="指定日期 YYYY-MM-DD（默认今天，影响文件命名）")
    p.add_argument("--force", "-f", action="store_true", help="已存在也重新生成并覆盖")
    p.add_argument("--list", "-l", action="store_true", help="列出片库并退出")
    p.add_argument("--dry-run", action="store_true", help="只生成大纲并打印分段计划，不落盘")
    p.add_argument("--no-index", action="store_true", help="不更新总索引页")
    p.add_argument("--verbose", "-v", action="store_true", help="输出调试日志")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    log_file = setup_logging(cfg.log_dir, args.verbose)

    if not args.list and not cfg.api_key:
        log.error("未配置 API Key。请在 %s 里设置 MOVIE_API_KEY", cfg.log_dir.parent / ".env")
        return 2

    try:
        items = catalog.load_catalog(cfg.catalog_path)
    except (FileNotFoundError, ValueError) as exc:
        log.error("片库读取失败：%s", exc)
        return 2

    if args.list:
        print(f"片库共 {len(items)} 部：\n")
        for i, item in enumerate(items, 1):
            extra = f"{item.episodes}集" if item.is_tv and item.episodes else (item.year or "")
            print(f"{i:>3}. {item.title:<22} {item.kind:<4} {extra:<8} {item.genre}")
        return 0

    run_date = date.today()
    if args.date:
        try:
            run_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            log.error("日期格式应为 YYYY-MM-DD，收到：%s", args.date)
            return 2

    state = catalog.State.load(cfg.state_path)
    try:
        item = catalog.pick_today(items, state, args.title)
    except LookupError as exc:
        log.error("%s", exc)
        return 2

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    log.info("今日作品：《%s》（%s%s）", item.title, item.kind, f" · {item.year}" if item.year else "")

    client = LLMClient(
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        model=cfg.model,
        timeout=cfg.timeout,
        max_retries=cfg.max_retries,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )

    if args.dry_run:
        from .generator import StoryGenerator, build_plan

        gen = StoryGenerator(client, cfg)
        outline = gen.make_outline(item)
        slots, rule = build_plan(item, outline, cfg)
        print("\n一句话故事：", outline.logline)
        print("分段规则：", rule)
        print(f"人物 {len(outline.characters)} 位 / 阶段 {len(outline.acts)} 个 / "
              f"转折 {len(outline.turning_points)} 处")
        print("\n分段计划：")
        for slot in slots:
            print(f"  {slot.index:>3}. {slot.label}")
        return 0

    try:
        doc = generate(item, cfg, client)
    except LLMError as exc:
        log.error("生成失败：%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        log.error("生成过程异常：%s", exc)
        log.debug(traceback.format_exc())
        return 1

    md_name = render.build_filename(doc, run_date, "md")
    html_name = render.build_filename(doc, run_date, "html")
    md_path = cfg.output_dir / md_name
    html_path = cfg.output_dir / html_name

    if md_path.exists() and not args.force:
        log.warning("文件已存在，跳过：%s（如需覆盖加 --force）", md_path)
        return 0

    write_atomic(md_path, render.render_markdown(doc, run_date))
    write_atomic(html_path, render.render_html(doc, run_date))

    if not args.no_index:
        try:
            render.render_index(cfg.output_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("索引页更新失败（不影响正文）：%s", exc)

    catalog.record_usage(state, item, run_date, [md_name, html_name], bool(args.title))
    state.save(cfg.state_path)

    log.info("完成 ✅ 共 %s 段", len(doc.segments))
    log.info("  Markdown：%s", md_path)
    log.info("  HTML    ：%s", html_path)
    log.info("  日志    ：%s", log_file)
    print(f"\n{html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
