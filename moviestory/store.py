"""生成结果快照：把 StoryDoc 存成 JSON，便于日后重发邮件而不用重新调用接口。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .catalog import Title
from .generator import Outline, Segment, StoryDoc


def _safe(name: str) -> str:
    from .render import safe_filename

    return safe_filename(name)


def snapshot_path(snapshot_dir: Path, run_date: str, title: str) -> Path:
    return snapshot_dir / f"{run_date}_{_safe(title)}.json"


def save_snapshot(doc: StoryDoc, snapshot_dir: Path, run_date: str) -> Path:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(snapshot_dir, run_date, doc.item.title)
    payload = {
        "generated_at": doc.generated_at.isoformat(timespec="seconds"),
        "model": doc.model,
        "segment_rule": doc.segment_rule,
        "item": asdict(doc.item),
        "outline": asdict(doc.outline),
        "segments": [asdict(s) for s in doc.segments],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_snapshot(path: Path) -> StoryDoc:
    from datetime import datetime

    raw = json.loads(path.read_text(encoding="utf-8"))
    item = Title(**raw["item"])
    outline = Outline(**raw["outline"])
    segments = [Segment(**s) for s in raw["segments"]]
    return StoryDoc(
        item=item,
        outline=outline,
        segments=segments,
        segment_rule=raw["segment_rule"],
        generated_at=datetime.fromisoformat(raw["generated_at"]),
        model=raw["model"],
    )


def find_snapshot(snapshot_dir: Path, title: str | None = None) -> Path | None:
    """找指定作品的快照；没指定则取最新的一个。"""
    if not snapshot_dir.exists():
        return None
    files = sorted(snapshot_dir.glob("*.json"), reverse=True)
    if not files:
        return None
    if title:
        for path in files:
            if title in path.stem:
                return path
        return None
    return files[0]
