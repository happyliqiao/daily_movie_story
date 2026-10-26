"""片库读取与每日选片轮播。"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Title:
    title: str
    country: str = ""
    kind: str = "电影"          # 电影 / 电视剧
    year: str = ""
    genre: str = ""
    episodes: str = ""
    synopsis: str = ""
    duration: str = ""          # 可选：电影片长（分钟）

    @property
    def is_tv(self) -> bool:
        if self.kind and "剧" in self.kind:
            return True
        return bool(self.episodes.strip())

    @property
    def episode_count(self) -> int | None:
        raw = self.episodes.strip()
        if not raw:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        return int(digits) if digits else None

    @property
    def duration_minutes(self) -> int | None:
        raw = self.duration.strip()
        if not raw:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        return int(digits) if digits else None

    def as_context(self) -> str:
        bits = [f"片名：{self.title}"]
        if self.year:
            bits.append(f"年份：{self.year}")
        if self.country:
            bits.append(f"国家/地区：{self.country}")
        if self.kind:
            bits.append(f"类型：{self.kind}")
        if self.genre:
            bits.append(f"题材：{self.genre}")
        if self.is_tv and self.episode_count:
            bits.append(f"集数：{self.episode_count}")
        if self.synopsis:
            bits.append(f"已有剧情参考：{self.synopsis}")
        return "\n".join(bits)


def load_catalog(path: Path) -> list[Title]:
    if not path.exists():
        raise FileNotFoundError(f"片库文件不存在：{path}")
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines(), delimiter="\t")
    items: list[Title] = []
    for row in reader:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        items.append(
            Title(
                title=title,
                country=(row.get("country") or "").strip(),
                kind=(row.get("type") or "电影").strip(),
                year=(row.get("year") or "").strip(),
                genre=(row.get("genre") or "").strip(),
                episodes=(row.get("episodes") or "").strip(),
                synopsis=(row.get("synopsis") or "").strip(),
                duration=(row.get("duration") or "").strip(),
            )
        )
    if not items:
        raise ValueError(f"片库为空：{path}")
    return items


@dataclass
class State:
    used: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls(
            used=list(raw.get("used") or []),
            history=list(raw.get("history") or []),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"used": self.used, "history": self.history[-400:]}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def pick_today(items: list[Title], state: State, override: str | None = None) -> Title:
    """按片库顺序轮播：优先取还没生成过的第一部；全部用过则从头再来。"""
    if override:
        for item in items:
            if item.title == override:
                return item
        lowered = override.lower()
        for item in items:
            if lowered in item.title.lower():
                return item
        raise LookupError(f"片库里找不到《{override}》，可用 --list 查看全部片名")

    used = set(state.used)
    for item in items:
        if item.title not in used:
            return item
    # 全片库已轮完，重置使用记录
    state.used = []
    return items[0]


def record_usage(state: State, item: Title, run_date: date, files: list[str], override: bool) -> None:
    if not override and item.title not in state.used:
        state.used.append(item.title)
    state.history.append(
        {
            "date": run_date.isoformat(),
            "title": item.title,
            "files": files,
            "override": override,
        }
    )
