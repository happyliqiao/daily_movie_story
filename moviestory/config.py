"""配置加载：从项目根目录的 .env 读取，全部使用标准库实现。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def _parse_env(path: Path) -> dict[str, str]:
    """极简 .env 解析：KEY=VALUE，忽略注释与空行，保留值里的反斜杠。"""
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        # 去掉成对引号
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key] = value
    return data


@dataclass
class Config:
    api_key: str
    api_base: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    output_dir: Path = PROJECT_ROOT / "output"
    catalog_path: Path = PROJECT_ROOT / "data" / "catalog.tsv"
    state_path: Path = PROJECT_ROOT / "data" / "state.json"
    log_dir: Path = PROJECT_ROOT / "logs"

    # 分段规则
    movie_segment_minutes: int = 10      # 电影：每 10 分钟一段
    movie_segment_min: int = 6
    movie_segment_max: int = 20
    tv_segments_per_episode: int = 2     # 电视剧：每集 2 段
    tv_segments_per_episode_long: int = 3  # 单集超过 long_episode_minutes 时用 3 段
    long_episode_minutes: int = 50

    # 生成参数
    batch_size_movie: int = 8
    batch_size_tv: int = 6
    temperature: float = 0.65
    max_tokens: int = 8000
    timeout: int = 180
    max_retries: int = 4

    extra: dict[str, str] = field(default_factory=dict)

    @property
    def env_files(self) -> list[Path]:
        return [ENV_PATH]


def _to_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_float(value: str | None, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def load_config() -> Config:
    env = _parse_env(ENV_PATH)
    # 环境变量优先级高于 .env，方便临时覆盖
    def pick(key: str, default: str = "") -> str:
        return os.environ.get(key) or env.get(key, default)

    api_key = pick("MOVIE_API_KEY") or pick("AI_NEWS_API_KEY")
    api_base = pick("MOVIE_API_BASE") or pick("AI_NEWS_API_BASE") or "https://api.deepseek.com"
    model = pick("MOVIE_MODEL") or pick("AI_NEWS_MODEL") or "deepseek-chat"

    output_dir = pick("MOVIE_OUTPUT_DIR") or str(PROJECT_ROOT / "output")
    catalog_path = pick("MOVIE_CATALOG") or str(PROJECT_ROOT / "data" / "catalog.tsv")

    return Config(
        api_key=api_key,
        api_base=api_base.rstrip("/"),
        model=model,
        output_dir=Path(output_dir).expanduser(),
        catalog_path=Path(catalog_path).expanduser(),
        state_path=PROJECT_ROOT / "data" / "state.json",
        log_dir=PROJECT_ROOT / "logs",
        movie_segment_minutes=_to_int(env.get("MOVIE_SEGMENT_MINUTES"), 10),
        tv_segments_per_episode=_to_int(env.get("TV_SEGMENTS_PER_EPISODE"), 2),
        batch_size_movie=_to_int(env.get("MOVIE_BATCH_SIZE"), 8),
        batch_size_tv=_to_int(env.get("TV_BATCH_SIZE"), 6),
        temperature=_to_float(env.get("MOVIE_TEMPERATURE"), 0.65),
        timeout=_to_int(env.get("MOVIE_TIMEOUT"), 180),
        max_retries=_to_int(env.get("MOVIE_MAX_RETRIES"), 4),
        extra=env,
    )
