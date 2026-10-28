"""命令行入口：每天生成一篇影视分段故事梗概。"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from . import catalog, render, store
from .config import Config, load_config
from .generator import StoryDoc, generate
from .llm import LLMClient, LLMError
from .mailer import MailError, send_email

log = logging.getLogger("moviestory")


def send_story_email(doc: StoryDoc, run_date: date, cfg: Config,
                     attachments: list[Path]) -> bool:
    """把当天生成的梗概发到邮箱。返回是否发送成功。"""
    if not cfg.smtp_host or not cfg.smtp_user or not cfg.smtp_pass:
        log.warning("未配置 SMTP，跳过邮件发送（.env 里补 MOVIE_SMTP_* 即可）")
        return True
    subject = f"【每日影视故事梗概】《{doc.item.title}》{run_date.isoformat()}｜共 {len(doc.segments)} 段"
    try:
        send_email(
            smtp_host=cfg.smtp_host,
            smtp_port=cfg.smtp_port,
            smtp_user=cfg.smtp_user,
            smtp_pass=cfg.smtp_pass,
            recipient=cfg.smtp_to or cfg.smtp_user,
            subject=subject,
            html_body=render.render_email_html(doc, run_date),
            text_body=render.render_email_text(doc, run_date),
            attachments=attachments,
            use_ssl=cfg.smtp_ssl,
        )
    except MailError as exc:
        log.error("邮件发送失败：%s", exc)
        log.error("  正文已保存，可稍后用 --resend 重发")
        return False
    return True


def _runtime_label() -> str:
    """区分云端 / 本机，方便在告警里判断是哪个链路出的问题。"""
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        return "GitHub Actions（云端）"
    return "本机计划任务"


def _advice_for(reason: str) -> list[str]:
    """按失败原因给出可执行的下一步。"""
    low = reason.lower()
    if "余额不足" in reason or "insufficient_balance" in low or "402" in reason:
        return [
            "模型账户余额不足，先充值：DeepSeek 后台 platform.deepseek.com → 充值。",
            "充值后立刻手动补跑今天的：在本机执行 python run.py。",
            "云端用的也是同一个 key，充值后云端会自动恢复，不需要改配置。",
        ]
    if "401" in reason or "unauthorized" in low or "invalid api key" in low:
        return [
            "API Key 无效或已失效，检查 .env 里的 MOVIE_API_KEY。",
            "如果刚轮换过密钥，记得同步更新 GitHub 仓库的 Secrets（MOVIE_API_KEY）。",
            "改完执行 python run.py 补跑今天的。",
        ]
    if "429" in reason or "rate limit" in low:
        return [
            "触发接口频率或额度限制，等一段时间再跑。",
            "在本机执行 python run.py 补跑今天的。",
        ]
    if "timeout" in low or "超时" in reason or "网络" in reason:
        return [
            "网络或接口超时，通常重跑即可。",
            "在本机执行 python run.py 补跑今天的；云端可在 Actions 页面点 Run workflow。",
        ]
    return [
        "先看本机日志：logs\\<日期>.log，里面有完整堆栈。",
        "在本机执行 python run.py 补跑今天的。",
        "如果连续失败，把日志发我，我来看。",
    ]


def send_alert_email(cfg: Config, *, title: str, stage: str, reason: str,
                     run_date: date) -> bool:
    """生成失败时发一封告警邮件，避免整条链路静默失败。"""
    if not cfg.smtp_host or not cfg.smtp_user or not cfg.smtp_pass:
        log.warning("未配置 SMTP，无法发送失败告警（仅写日志）")
        return False
    advice = _advice_for(reason)
    where = _runtime_label()
    try:
        send_email(
            smtp_host=cfg.smtp_host,
            smtp_port=cfg.smtp_port,
            smtp_user=cfg.smtp_user,
            smtp_pass=cfg.smtp_pass,
            recipient=cfg.smtp_to or cfg.smtp_user,
            subject=f"【失败告警】每日影视故事梗概 {run_date.isoformat()}｜{stage}",
            html_body=render.render_alert_html(
                title=title, stage=stage, reason=reason, advice=advice,
                run_date=run_date, where=where),
            text_body=render.render_alert_text(
                title=title, stage=stage, reason=reason, advice=advice,
                run_date=run_date, where=where),
            attachments=[],
            use_ssl=cfg.smtp_ssl,
        )
    except MailError as exc:
        log.error("失败告警邮件也没发出去：%s", exc)
        return False
    return True


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
    p.add_argument("--no-email", action="store_true", help="生成后不发送邮件")
    p.add_argument("--no-alert", action="store_true", help="生成失败时不发告警邮件")
    p.add_argument("--resend", action="store_true",
                   help="不重新生成，用上次的结果直接重发邮件")
    p.add_argument("--verbose", "-v", action="store_true", help="输出调试日志")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    log_file = setup_logging(cfg.log_dir, args.verbose)

    # 重发邮件：不调用接口，直接用快照重发
    if args.resend:
        path = store.find_snapshot(cfg.snapshot_dir, args.title)
        if not path:
            log.error("找不到可重发的快照（目录：%s）", cfg.snapshot_dir)
            return 2
        try:
            doc = store.load_snapshot(path)
        except (OSError, ValueError, KeyError) as exc:
            log.error("快照读取失败：%s", exc)
            return 2
        snap_date = datetime.strptime(path.stem.split("_")[0], "%Y-%m-%d").date()
        atts = [p for p in (cfg.output_dir / f"{path.stem}.md",
                            cfg.output_dir / f"{path.stem}.html") if p.exists()]
        log.info("重发《%s》的邮件（%s）", doc.item.title, snap_date)
        return 0 if send_story_email(doc, snap_date, cfg, atts) else 3

    if not args.list and not cfg.api_key:
        msg = "未配置 API Key，请检查 .env 里的 MOVIE_API_KEY"
        log.error("%s（%s）", msg, cfg.log_dir.parent / ".env")
        if not args.no_email and not args.no_alert:
            send_alert_email(cfg, title="", stage="检查配置", reason=msg,
                             run_date=date.today())
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

    # 文件名只依赖片名和日期，可以在生成前判断是否已存在，避免白白消耗接口额度
    md_name = f"{run_date.isoformat()}_{render.safe_filename(item.title)}.md"
    html_name = f"{run_date.isoformat()}_{render.safe_filename(item.title)}.html"
    md_path = cfg.output_dir / md_name
    html_path = cfg.output_dir / html_name

    if md_path.exists() and not args.force:
        log.warning("文件已存在，跳过：%s（如需覆盖加 --force）", md_path)
        # 仍要记录轮播进度，否则片库会一直卡在这一部
        if not args.title:
            catalog.record_usage(state, item, run_date, [], override=False)
            state.save(cfg.state_path)
        return 0

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
        if not args.no_email and not args.no_alert:
            send_alert_email(cfg, title=item.title, stage="调用模型生成梗概",
                             reason=str(exc), run_date=run_date)
        return 1
    except Exception as exc:  # noqa: BLE001
        log.error("生成过程异常：%s", exc)
        log.debug(traceback.format_exc())
        if not args.no_email and not args.no_alert:
            send_alert_email(cfg, title=item.title, stage="生成过程异常",
                             reason=f"{type(exc).__name__}: {exc}", run_date=run_date)
        return 1

    md_name = render.build_filename(doc, run_date, "md")
    html_name = render.build_filename(doc, run_date, "html")
    md_path = cfg.output_dir / md_name
    html_path = cfg.output_dir / html_name

    write_atomic(md_path, render.render_markdown(doc, run_date))
    write_atomic(html_path, render.render_html(doc, run_date))

    if not args.no_index:
        try:
            render.render_index(cfg.output_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("索引页更新失败（不影响正文）：%s", exc)

    try:
        store.save_snapshot(doc, cfg.snapshot_dir, run_date.isoformat())
    except OSError as exc:
        log.warning("快照保存失败（不影响正文）：%s", exc)

    catalog.record_usage(state, item, run_date, [md_name, html_name], bool(args.title))
    state.save(cfg.state_path)

    log.info("完成 ✅ 共 %s 段", len(doc.segments))
    log.info("  Markdown：%s", md_path)
    log.info("  HTML    ：%s", html_path)
    log.info("  日志    ：%s", log_file)
    print(f"\n{html_path}")

    if not args.no_email:
        if not send_story_email(doc, run_date, cfg, [md_path, html_path]):
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
