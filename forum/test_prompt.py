#!/usr/bin/env python3
"""论坛生成管线的持久回归护栏（unittest，纯逻辑、零 LLM 调用）。

运行（解释器需含 openai/dotenv，如 Any-Award-Backend/.venv；注意 PYTHONUTF8
会破坏该 venv 探测，见 HANDOFF §10）：
  cd forum && env -u PYTHONUTF8 ../Any-Award-Backend/.venv/bin/python -m unittest test_prompt -v

背景：2026-11-15~16 两轮共 ~1300 行改动全部靠"跑完即丢"的内联脚本验收，
一次 mock 签名错（mt vs max_tokens）排查了最久——有本文件这类护栏，该类
错误分钟级定位。改 prompt/记忆/关系任何一处，先跑这里。
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import relations
import memory
import generate
import audit
from lexicon import BANNED_WORDS, COMPILED_FRAMES, banned_prompt_line


def _fake_chat(calls, body="蹲", point=""):
    def chat(client, model, system, user, temperature, max_tokens):
        calls.append(user)
        if "发一帖" in user:
            return {"title": "测试帖", "body": "正文而已。"}
        return {"point": point, "body": body, "reply_to": "楼主"}
    return chat


class TestLexicon(unittest.TestCase):
    def test_prompt_line_逐字一致(self):
        expect = ("禁用词：综上所述/总的来说/总而言之/说白了/本质上/换句话说/值得注意的是/"
                  "不难发现/众所周知/毋庸置疑/这意味着/由此可见/那么问题来了/你可能会问/"
                  "首先其次最后/一方面另一方面/不得不说。")
        self.assertEqual(banned_prompt_line(), expect)

    def test_帧级命中与放行(self):
        hits = [r"\s*".join([])]  # 占位防误删
        pats = [p.pattern for p in COMPILED_FRAMES]
        joined = "|".join(pats)
        # 必须命中
        for t in ("与其干等着生气，不如直接点名", "这不叫干预，叫自救",
                  "不是简单的打钱问题，而是", "所以问题来了", "作为一个AI"):
            self.assertTrue(any(p.search(t) for p in COMPILED_FRAMES), t)
        # 必须放行（真人高频/口语建议——历史基线误伤教训）
        for t in ("不如来操场跑两圈", "考不上就考不上吧 服了", "十一点了 桌面还是昨晚那摊"):
            self.assertFalse(any(p.search(t) for p in COMPILED_FRAMES), t)


class TestViolations(unittest.TestCase):
    def test_违规与放行(self):
        V = generate._violations
        self.assertTrue(V("综上所述我觉得不行", None, None))
        self.assertTrue(V("首先你说一,其次我说二", None, None))
        self.assertTrue(V("哥不去,蚌化了,哥累了", 80, {"catchphrase": ["哥", "蚌"]}))
        self.assertTrue(V("字" * 150, 80, None))
        self.assertFalse(V("水没了能打,奖没评上呢", 80, None))
        self.assertFalse(V("哥 练完了", 80, {"catchphrase": ["哥"]}))

    def test_insight_金句过滤(self):
        f = generate._insight_is_slop
        self.assertTrue(f("与其干等着生气，不如直接点名"))
        self.assertTrue(f("公告是死的——脑补是活的"))
        self.assertFalse(f("今天组会被导师批了 改第三版"))
        self.assertFalse(f(""))


class TestPersonas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate.load_personas()
        cls.rules = cls.data["rules"]
        cls.by = {p["nickname"]: p for p in cls.data["personas"]}

    def test_动机池无抽象立场(self):
        for name in ("_MOTIVES", "_REPLY_MOTIVES", "_THREAD_MOTIVES"):
            for m in getattr(generate, name):
                for w in ("不同意", "感同身受", "反驳", "怼一下", "补充"):
                    self.assertNotIn(w, m, f"{name}: {m}")

    def test_人设无表态残根(self):
        blob = json.dumps(self.data, ensure_ascii=False)
        for w in ("先夸一句", "各有利弊", "两面看", "先肯定再反驳"):
            self.assertNotIn(w, blob, w)

    def test_flaw_boundary已回注(self):
        sys_text = generate.persona_system(self.by["老蔡不姓蔡"], self.rules)
        self.assertIn("表达缺陷", sys_text)
        self.assertIn("边界", sys_text)

    def test_玩家拿不到关系行(self):
        # hint_line 对未知昵称(玩家)返回空——防玩家路径每条刷「不熟」噪音
        self.assertEqual(relations.hint_line("阿穹", "匿名玩家甲"), "")


class TestRelations(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._old = relations.REL_PATH
        relations.REL_PATH = self.tmp / "r.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        relations.REL_PATH = self._old

    def test_种子幂等且方向正确(self):
        n1 = relations.seed_from_personas()
        n2 = relations.seed_from_personas()
        self.assertGreater(n1, 0)
        self.assertEqual(n2, 0)
        mf = relations.get("梗先知", "食堂干饭王")
        self.assertEqual((mf["kind"], mf["strength"]), ("饭搭子", 58))
        dq = relations.get("梗先知", "体育生大壮")
        self.assertEqual((dq["kind"], dq["strength"]), ("互怼之交", 48))

    def test_阻尼与阶段(self):
        e = relations.ensure("老蔡不姓蔡", "阿穹", strength=48)
        self.assertEqual(relations.stage_of(48)[0], "熟络")
        e = relations.update("老蔡不姓蔡", "阿穹", -3)   # 高位减半
        self.assertEqual(e["strength"], 47)
        e = relations.update("老蔡不姓蔡", "阿穹", -3)   # 当日连负再减
        self.assertEqual(e["strength"], 46)
        e = relations.update("老蔡不姓蔡", "阿穹", +2)   # 正向重置连击
        self.assertEqual(e["neg"], {})
        self.assertEqual(relations.hint_line("老蔡不姓蔡", "阿穹")[:3], "（你和")


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._old = memory.MEMORY_DIR
        memory.MEMORY_DIR = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        memory.MEMORY_DIR = self._old

    def _thread(self):
        return {"id": "t1", "title": "测试帖",
                "author": {"kind": "ai", "nickname": "阿穹"}, "body": "楼主正文",
                "comments": [
                    {"id": "c1", "author": {"kind": "ai", "nickname": "老蔡"},
                     "body": "老蔡的评论", "reply_to": None},
                    {"id": "c2", "author": {"kind": "ai", "nickname": "阿穹"},
                     "body": "阿穹怼老蔡:你这数不对", "reply_to": "c1"},
                    {"id": "c3", "author": {"kind": "player", "nickname": "路人"},
                     "body": "玩家插嘴", "reply_to": "c1"},
                ]}

    def test_见闻记忆与玩家跳过(self):
        th = self._thread()
        for c in th["comments"]:
            memory.record_comment(th, c)
        aq, lc = memory.recent("阿穹"), memory.recent("老蔡")
        self.assertTrue(any(e["kind"] == "received" and e["from"] == "老蔡" for e in aq))
        self.assertTrue(any(e["kind"] == "received" and e["from"] == "阿穹" for e in lc))
        self.assertEqual(memory.recent("路人"), [])

    def test_混合配额保互动(self):
        th = self._thread()
        for c in th["comments"]:
            memory.record_comment(th, c)
        for i in range(6):
            memory.append("老蔡", {"at": f"2026-11-16T0{i}:00", "kind": "thread",
                                   "thread_title": f"自帖{i}", "body": f"内容{i}"})
        fp = memory.footprints(["老蔡"], k=3)
        self.assertIn("发帖《", fp)
        self.assertIn("对我说", fp)

    def test_has_interaction(self):
        th = self._thread()
        for c in th["comments"]:
            memory.record_comment(th, c)
        self.assertTrue(memory.has_interaction("老蔡", "阿穹"))
        self.assertFalse(memory.has_interaction("老蔡", "路人"))


class TestAudit(unittest.TestCase):
    def test_双向率合成数据(self):
        tmp = Path(tempfile.mkdtemp())
        old = audit.HERE
        try:
            (tmp / "data" / "memory").mkdir(parents=True)
            audit.HERE = tmp
            (tmp / "data" / "memory" / "a.json").write_text(json.dumps([
                {"kind": "comment", "body": "x", "reply_to_nick": "b"}], ensure_ascii=False), encoding="utf-8")
            (tmp / "data" / "memory" / "b.json").write_text(json.dumps([
                {"kind": "received", "body": "x", "from": "a"}], ensure_ascii=False), encoding="utf-8")
            out = audit.memory_two_way()
            self.assertIn("100%", out)
        finally:
            audit.HERE = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
