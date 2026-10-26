"""离线自测：不调用大模型接口，验证核心逻辑。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moviestory import catalog, render  # noqa: E402
from moviestory.config import Config  # noqa: E402
from moviestory.generator import Outline, build_plan  # noqa: E402
from moviestory.llm import parse_json  # noqa: E402


def make_cfg(**kwargs) -> Config:
    return Config(api_key="test", **kwargs)


class TestSegmentPlan(unittest.TestCase):
    def test_movie_120min_gets_12_segments(self):
        item = catalog.Title(title="测试电影", kind="电影")
        outline = Outline(logline="x", runtime_minutes=120, episodes=None, episode_minutes=None,
                          characters=[], acts=[], turning_points=[], themes=[], ending="")
        slots, rule = build_plan(item, outline, make_cfg())
        self.assertEqual(len(slots), 12)
        self.assertEqual(slots[0].label, "00:00–00:10")
        self.assertEqual(slots[-1].label, "01:50–02:00")
        self.assertIn("12 段", rule)

    def test_movie_171min(self):
        item = catalog.Title(title="霸王别姬", kind="电影")
        outline = Outline(logline="x", runtime_minutes=171, episodes=None, episode_minutes=None,
                          characters=[], acts=[], turning_points=[], themes=[], ending="")
        slots, _ = build_plan(item, outline, make_cfg())
        self.assertEqual(len(slots), 17)
        self.assertEqual(slots[-1].label.split("–")[-1], "02:51")

    def test_movie_segment_count_clamped(self):
        item = catalog.Title(title="短片", kind="电影")
        outline = Outline(logline="x", runtime_minutes=20, episodes=None, episode_minutes=None,
                          characters=[], acts=[], turning_points=[], themes=[], ending="")
        slots, _ = build_plan(item, outline, make_cfg())
        self.assertEqual(len(slots), 6)  # 下限 6 段

    def test_tv_two_segments_per_episode(self):
        item = catalog.Title(title="测试剧", kind="电视剧", episodes="12")
        outline = Outline(logline="x", runtime_minutes=None, episodes=12, episode_minutes=45,
                          characters=[], acts=[], turning_points=[], themes=[], ending="")
        slots, rule = build_plan(item, outline, make_cfg())
        self.assertEqual(len(slots), 24)
        self.assertEqual(slots[0].label, "第1集·上")
        self.assertEqual(slots[1].label, "第1集·下")
        self.assertEqual(slots[-1].label, "第12集·下")
        self.assertIn("12 集", rule)

    def test_tv_long_episode_three_segments(self):
        item = catalog.Title(title="长剧", kind="电视剧", episodes="8")
        outline = Outline(logline="x", runtime_minutes=None, episodes=8, episode_minutes=55,
                          characters=[], acts=[], turning_points=[], themes=[], ending="")
        slots, _ = build_plan(item, outline, make_cfg())
        self.assertEqual(len(slots), 24)
        self.assertEqual(slots[2].label, "第1集·后")


class TestCatalog(unittest.TestCase):
    def test_load_and_rotate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.tsv"
            path.write_text(
                "title\tcountry\ttype\tyear\tgenre\tepisodes\tsynopsis\n"
                "甲\t中国\t电影\t2000\t剧情\t\t甲的故事\n"
                "乙\t中国\t电视剧\t2001\t悬疑\t10\t乙的故事\n",
                encoding="utf-8",
            )
            items = catalog.load_catalog(path)
            self.assertEqual([i.title for i in items], ["甲", "乙"])
            self.assertTrue(items[1].is_tv)
            self.assertEqual(items[1].episode_count, 10)

            state = catalog.State()
            self.assertEqual(catalog.pick_today(items, state).title, "甲")
            state.used.append("甲")
            self.assertEqual(catalog.pick_today(items, state).title, "乙")
            state.used.append("乙")
            self.assertEqual(catalog.pick_today(items, state).title, "甲")  # 轮完重置

    def test_pick_by_name(self):
        items = [catalog.Title(title="霸王别姬"), catalog.Title(title="活着")]
        state = catalog.State()
        self.assertEqual(catalog.pick_today(items, state, "活着").title, "活着")
        self.assertEqual(catalog.pick_today(items, state, "霸王").title, "霸王别姬")
        with self.assertRaises(LookupError):
            catalog.pick_today(items, state, "不存在的片")

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = catalog.State(used=["甲"])
            state.save(path)
            self.assertEqual(catalog.State.load(path).used, ["甲"])


class TestJsonParsing(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_json('{"a": 1}')["a"], 1)

    def test_code_fence(self):
        self.assertEqual(parse_json('```json\n{"a": 2}\n```')["a"], 2)

    def test_noise_around(self):
        text = '好的，结果如下：\n{"segments": [{"index": 1}]}\n希望有帮助'
        self.assertEqual(parse_json(text)["segments"][0]["index"], 1)

    def test_trailing_comma(self):
        self.assertEqual(parse_json('{"a": 1,}')["a"], 1)

    def test_nested_braces_in_string(self):
        data = parse_json('{"a": "含 } 花括号"}')
        self.assertEqual(data["a"], "含 } 花括号")

    def test_invalid_raises(self):
        from moviestory.llm import LLMError

        with self.assertRaises(LLMError):
            parse_json("完全不是 JSON")


class TestRender(unittest.TestCase):
    def test_safe_filename(self):
        self.assertEqual(render.safe_filename('a/b:c*d?"e"'), "a_b_c_d__e_")

    def test_index_built_from_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "2026-01-01_测试片.md").write_text(
                '<!-- meta: {"title":"测试片","date":"2026-01-01","kind":"电影","segments":12} -->\n# 测试片\n',
                encoding="utf-8",
            )
            entries = render.collect_entries(out)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["segments"], 12)
            md_path, html_path = render.render_index(out)
            self.assertTrue(md_path.exists() and html_path.exists())
            self.assertIn("测试片", md_path.read_text(encoding="utf-8"))
            # 索引页自身不应被计入
            self.assertEqual(len(render.collect_entries(out)), 1)


if __name__ == "__main__":
    unittest.main()
