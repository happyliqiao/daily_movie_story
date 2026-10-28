"""故事梗概生成：先出全片大纲，再按批次写分段梗概。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from .catalog import Title
from .config import Config
from .llm import LLMClient, LLMError

log = logging.getLogger("moviestory.generator")

SYSTEM_PROMPT = """你是一位资深影视解说编剧，专门把电影和电视剧的完整剧情拆成"分段故事梗概"。

硬性要求：
1. 只依据该作品的真实剧情写作。不虚构人物、不编造情节、不把不同作品的情节混在一起。
   对记不准确的具体细节（某句台词、某个人物的结局、某场戏的先后顺序），宁可用概括性表述，也不要编造具体细节来填满字数。
2. 中文平实叙述，信息密度高。不要用"这一段""接下来""话说""让我们"这类口水话开头。
3. 只写剧情本身：谁做了什么、遇到什么阻碍、结果如何、人物关系和局势怎么变化。不评价演技、不写镜头和配乐、不写观后感、不用营销腔。
4. 严格按用户指定的 JSON 结构输出，不要输出任何解释文字或 markdown 代码块以外的内容。"""

# 单段字数下限：低于这个值的段落会被要求重写
MIN_SUMMARY_CHARS = 150

# 长度参照示例。
# 弱模型（如免费的 GLM-4-Flash）不吃「不少于 N 字」这类抽象指令，但会模仿示例篇幅：
# 实测同一段内容，无示例 93 字、带示例 156 字。这里给一段与任何作品无关的写法示范，
# 只让它学「篇幅和信息密度」，并明确要求不要照抄内容。
LENGTH_REFERENCE = """「一九二七年秋，沈砚之带着一封推荐信到省城报到，被分到城南的测绘队。队里人手不足，他白天跟着老测量员跑野外，晚上在油灯下整理图纸。第一次独立出任务时，他把两处标高记反，导致图纸返工，被队长当众训了半个钟头。他不服气，连着三天重测那一段，把误差压到最小，队长没再说什么，只是把他调去负责更难的河堤断面。同屋的赵霖劝他别太较真，他嘴上应着，第二天照旧天不亮就出门。入冬后河面结冰，队里停工，他借来几本旧教材自学，把落下的几何补上。」"""


@dataclass
class Segment:
    index: int
    range: str
    title: str
    summary: str
    events: list[str] = field(default_factory=list)


@dataclass
class Outline:
    logline: str
    runtime_minutes: int | None
    episodes: int | None
    episode_minutes: int | None
    characters: list[dict]
    acts: list[dict]
    turning_points: list[dict]
    themes: list[str]
    ending: str
    setting: str = ""


@dataclass
class StoryDoc:
    item: Title
    outline: Outline
    segments: list[Segment]
    segment_rule: str
    generated_at: datetime
    model: str


# ---------------------------------------------------------------- 工具函数

def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _mmss(minutes: float) -> str:
    """把分钟数格式化为 时:分（HH:MM），超过 60 分钟也正确，如 110 分钟 -> 01:50。"""
    total = int(round(minutes))
    return f"{total // 60:02d}:{total % 60:02d}"


def _safe_str(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return "、".join(_safe_str(v) for v in value if v)
    return str(value).strip()


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


# ---------------------------------------------------------------- 分段计划

@dataclass
class PlanSlot:
    index: int
    label: str
    hint: str  # 给模型的定位提示，如 "第 3 集前段"


def build_plan(item: Title, outline: Outline, cfg: Config) -> tuple[list[PlanSlot], str]:
    """根据作品类型算出分段计划，返回 (段落列表, 规则说明)。"""
    if item.is_tv or (outline.episodes and outline.episodes > 1):
        episodes = item.episode_count or outline.episodes or 12
        per_ep = cfg.tv_segments_per_episode
        ep_minutes = outline.episode_minutes or 45
        if ep_minutes > cfg.long_episode_minutes:
            per_ep = cfg.tv_segments_per_episode_long
        slots: list[PlanSlot] = []
        for ep in range(1, episodes + 1):
            for part in range(per_ep):
                slots.append(PlanSlot(
                    index=len(slots) + 1,
                    label=f"第{ep}集·{_part_label(part, per_ep)}",
                    hint=f"第 {ep} 集（全剧共 {episodes} 集）的第 {part + 1}/{per_ep} 部分",
                ))
        rule = (f"电视剧共 {episodes} 集，单集约 {ep_minutes} 分钟，"
                f"每集拆 {per_ep} 段，全剧共 {len(slots)} 段")
        return slots, rule

    runtime = item.duration_minutes or outline.runtime_minutes or 120
    total = _clamp(int(round(runtime / cfg.movie_segment_minutes)),
                   cfg.movie_segment_min, cfg.movie_segment_max)
    boundaries = [round(i * runtime / total) for i in range(total + 1)]
    boundaries[-1] = runtime
    slots = []
    for i in range(total):
        start, end = boundaries[i], boundaries[i + 1]
        slots.append(PlanSlot(
            index=i + 1,
            label=f"{_mmss(start)}–{_mmss(end)}",
            hint=f"片长 {runtime} 分钟中的第 {start}–{end} 分钟",
        ))
    rule = (f"电影片长约 {runtime} 分钟，按每 {cfg.movie_segment_minutes} 分钟一段切分，"
            f"共 {total} 段")
    return slots, rule


def _part_label(part: int, total: int) -> str:
    if total == 1:
        return "全"
    if total == 2:
        return ["上", "下"][part]
    if total == 3:
        return ["前", "中", "后"][part]
    return f"第{part + 1}部分"


# ---------------------------------------------------------------- 生成器

class StoryGenerator:
    def __init__(self, client: LLMClient, cfg: Config) -> None:
        self.client = client
        self.cfg = cfg

    # ---- 第一步：大纲 ----
    def make_outline(self, item: Title) -> Outline:
        prompt = f"""请为下面这部作品生成一份用于分段解说的结构大纲。

{item.as_context()}

输出 JSON，字段如下：
{{
  "logline": "一句话故事，40-70字，讲清主角、目标和最大阻碍",
  "runtime_minutes": 电影的真实片长（整数，分钟）；电视剧填每集平均时长,
  "episodes": 电影填 null；电视剧填总集数,
  "setting": "故事发生的时代与地点，20字内",
  "characters": [{{"name": "人物名", "role": "主角/对手/关键配角", "desc": "20字内的身份与动机"}}],
  "acts": [{{"name": "故事阶段名，如'少年学戏'", "desc": "30字内概括这一阶段"}}],
  "turning_points": [{{"at": "约第30分钟 或 第12集", "event": "30字内的关键转折"}}],
  "themes": ["2-4个主题词"],
  "ending": "结尾最终走向，60字内，允许剧透"
}}

要求：
- characters 给 4-8 位真正推动剧情的人物，按重要性排序。
- acts 给 3-5 个阶段，覆盖完整故事线。
- turning_points 给 4-6 个，位置要具体。
- 全部基于该作品的真实剧情，宁缺毋滥。"""

        data = self.client.chat_json(SYSTEM_PROMPT, prompt)

        characters = []
        for raw in _as_list(data.get("characters"))[:10]:
            if isinstance(raw, dict) and _safe_str(raw.get("name")):
                characters.append({
                    "name": _safe_str(raw.get("name")),
                    "role": _safe_str(raw.get("role"), "配角"),
                    "desc": _safe_str(raw.get("desc")),
                })

        acts = []
        for raw in _as_list(data.get("acts"))[:6]:
            if isinstance(raw, dict):
                acts.append({
                    "name": _safe_str(raw.get("name")),
                    "desc": _safe_str(raw.get("desc")),
                })
            elif _safe_str(raw):
                acts.append({"name": _safe_str(raw), "desc": ""})

        turning = []
        for raw in _as_list(data.get("turning_points"))[:8]:
            if isinstance(raw, dict):
                turning.append({
                    "at": _safe_str(raw.get("at")),
                    "event": _safe_str(raw.get("event")),
                })

        outline = Outline(
            logline=_safe_str(data.get("logline")),
            runtime_minutes=_to_int(data.get("runtime_minutes")),
            episodes=_to_int(data.get("episodes")),
            episode_minutes=_to_int(data.get("episode_minutes")),
            characters=characters,
            acts=acts,
            turning_points=turning,
            themes=[_safe_str(t) for t in _as_list(data.get("themes")) if _safe_str(t)][:5],
            ending=_safe_str(data.get("ending")),
            setting=_safe_str(data.get("setting")),
        )
        # 电视剧的 runtime_minutes 语义是单集时长
        if (item.is_tv or outline.episodes) and not outline.episode_minutes:
            outline.episode_minutes = outline.runtime_minutes
            outline.runtime_minutes = None

        if not outline.logline:
            raise LLMError("大纲缺少 logline，生成中止")
        return outline

    # ---- 第二步：分批写分段 ----
    def write_segments(self, item: Title, outline: Outline,
                       slots: list[PlanSlot]) -> list[Segment]:
        batch_size = self.cfg.batch_size_tv if item.is_tv else self.cfg.batch_size_movie
        total = len(slots)
        done: dict[int, Segment] = {}

        for start in range(0, total, batch_size):
            batch = slots[start : start + batch_size]
            log.info("  生成第 %s–%s 段 / 共 %s 段", batch[0].index, batch[-1].index, total)
            segments = self._write_batch(item, outline, batch, total, done)
            for seg in segments:
                done[seg.index] = seg

        missing = [slot for slot in slots if slot.index not in done]
        if missing:
            log.warning("  有 %s 段缺失，逐段补写", len(missing))
            for slot in missing:
                try:
                    segs = self._write_batch(item, outline, [slot], total, done, strict=False)
                    for seg in segs:
                        done[seg.index] = seg
                except LLMError as exc:
                    log.error("  第 %s 段补写失败：%s", slot.index, exc)
                    done[slot.index] = Segment(
                        index=slot.index,
                        range=slot.label,
                        title="待补充",
                        summary=f"该段内容生成失败（{exc}）。可稍后重新运行并加 --force 覆盖重生成。",
                        events=[],
                    )

        # 质检：字数偏短的段落重写一次
        floor = self.cfg.min_summary_chars
        thin = [seg for seg in done.values() if len(seg.summary) < floor]
        if thin:
            log.info("  质检：%s 段字数不足 %s，重写补足", len(thin), floor)
            slot_map = {slot.index: slot for slot in slots}
            # 重写目标比下限高一点，留出波动余量
            target = min(240, floor + 30)
            for seg in thin:
                try:
                    segs = self._write_batch(item, outline, [slot_map[seg.index]], total,
                                             done, strict=False, min_chars=target)
                except LLMError as exc:
                    log.warning("  第 %s 段重写失败，保留原稿：%s", seg.index, exc)
                    continue
                for new_seg in segs:
                    if len(new_seg.summary) > len(seg.summary):
                        done[new_seg.index] = new_seg

        return [done[slot.index] for slot in slots if slot.index in done]

    def _write_batch(self, item: Title, outline: Outline, batch: list[PlanSlot],
                     total: int, done: dict[int, Segment], strict: bool = True,
                     min_chars: int = 160) -> list[Segment]:
        outline_brief = {
            "title": item.title,
            "year": item.year,
            "type": item.kind,
            "logline": outline.logline,
            "setting": outline.setting,
            "characters": outline.characters,
            "acts": outline.acts,
            "turning_points": outline.turning_points,
            "ending": outline.ending,
        }

        prev = [done[i] for i in sorted(done) if i < batch[0].index][-3:]
        if prev:
            prev_text = "\n".join(
                f"第{s.index}段（{s.range}）{s.title}：{s.summary[:80]}" for s in prev
            )
        else:
            prev_text = "（这是开头的段落，没有前情）"

        slot_lines = "\n".join(
            f"第{s.index}段｜{s.label}｜{s.hint}" for s in batch
        )

        prompt = f"""《{item.title}》分段故事梗概，本次写第 {batch[0].index}–{batch[-1].index} 段（全套共 {total} 段）。

【作品大纲】
{outline_brief}

【本次要写的段落】
{slot_lines}

【前情提要】
{prev_text}

【写作要求】
1. 每段 summary 写 {min_chars}-240 字（不少于 {min_chars} 字），只写该时间范围内真正发生的事，按时间顺序推进，段内要有具体的动作、冲突和结果。
2. 段与段之间必须向前推进，不能重复前情提要里已经写过的事件。
3. 只写原作中确实发生的情节。细节记不准时用概括表述，不要为了凑字数编造台词、人物结局或子虚乌有的场面。
4. title 给 6-12 个字的小标题，要具体（如"蝶衣被母亲送进戏班"），不要"开端""发展""高潮"这类空词。
5. events 给 2-4 条该段最关键的具体事件，每条不超过 15 字。
6. range 字段原样照抄上面给的段落标签，不要改动。
7. 必须输出 {len(batch)} 段，index 从 {batch[0].index} 连续到 {batch[-1].index}，不得缺漏。

【长度参照】
下面这段与本部作品无关，只用来参照「篇幅和信息密度」，绝对不要照抄它的内容、人名或情节：
{LENGTH_REFERENCE}
你写的每一段，篇幅都要和上面这段相当；明显短于它就视为不合格，需要补充具体细节写够。

【输出格式】
{{"segments":[{{"index":{batch[0].index},"range":"{batch[0].label}","title":"小标题","summary":"{min_chars}-240字的梗概","events":["事件1","事件2"]}}]}}"""

        try:
            data = self.client.chat_json(SYSTEM_PROMPT, prompt)
        except LLMError:
            if not strict:
                raise
            log.warning("  本批生成失败，拆成单段重试")
            out: list[Segment] = []
            for slot in batch:
                try:
                    out.extend(self._write_batch(item, outline, [slot], total, done, strict=False))
                except LLMError as exc:
                    log.error("  第 %s 段失败：%s", slot.index, exc)
            return out

        segments: list[Segment] = []
        expected = {slot.index: slot for slot in batch}
        for raw in _as_list(data.get("segments")):
            if not isinstance(raw, dict):
                continue
            idx = _to_int(raw.get("index"))
            if idx is None or idx not in expected:
                continue
            slot = expected[idx]
            summary = _safe_str(raw.get("summary"))
            if not summary:
                continue
            segments.append(Segment(
                index=idx,
                range=slot.label,
                title=_safe_str(raw.get("title"), f"第{idx}段")[:24],
                summary=summary,
                events=[_safe_str(e)[:30] for e in _as_list(raw.get("events")) if _safe_str(e)][:4],
            ))
        return segments


def generate(item: Title, cfg: Config, client: LLMClient) -> StoryDoc:
    gen = StoryGenerator(client, cfg)
    log.info("① 生成故事大纲…")
    outline = gen.make_outline(item)
    log.info("  片长/集数：%s / %s，人物 %s 位",
             outline.runtime_minutes, outline.episodes, len(outline.characters))

    slots, rule = build_plan(item, outline, cfg)
    log.info("② 分段计划：%s", rule)

    log.info("③ 开始写分段梗概…")
    segments = gen.write_segments(item, outline, slots)
    log.info("  完成 %s 段", len(segments))

    return StoryDoc(
        item=item,
        outline=outline,
        segments=segments,
        segment_rule=rule,
        generated_at=datetime.now(),
        model=cfg.model,
    )
