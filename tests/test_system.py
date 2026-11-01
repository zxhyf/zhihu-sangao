# -*- coding: utf-8 -*-
"""自动化回归测试（仅用标准库 unittest，不依赖 pytest）。

运行：
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import db
from agent import intent, orchestrator, safety
from agent.rag import get_kb
from tools import (interactions, measurements, medications, plan as plan_tool,
                   profile as profile_tool, registry, reports, risks, tasks, trends)

TEST_USER = "u_test_automation"


def setUpModule():
    db.init_db()
    profile_tool.ensure_profile(TEST_USER)
    db.reset_user_data(TEST_USER)
    get_kb().build()


def tearDownModule():
    db.reset_user_data(TEST_USER)


class TestIntent(unittest.TestCase):
    def test_bp(self):
        ms = intent.parse_measurements("今天血压 150/95")
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0]["kind"], "bp")
        self.assertEqual((ms[0]["val1"], ms[0]["val2"]), (150.0, 95.0))

    def test_bp_gaoya_diya(self):
        ms = intent.parse_measurements("高压 158 低压 96")
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0]["val2"], 96.0)

    def test_glucose_subkinds(self):
        self.assertEqual(intent.parse_measurements("空腹血糖 7.2")[0]["sub_kind"], "fasting")
        self.assertEqual(intent.parse_measurements("餐后血糖 9.8")[0]["sub_kind"], "postprandial")
        self.assertEqual(intent.parse_measurements("血糖 6.5")[0]["sub_kind"], "random")

    def test_lipid(self):
        ms = intent.parse_measurements("低密度脂蛋白 3.9，甘油三酯 2.4")
        subs = {m["sub_kind"] for m in ms}
        self.assertIn("ldl", subs)
        self.assertIn("tg", subs)

    def test_weight_jin(self):
        ms = intent.parse_measurements("体重 140 斤")
        self.assertEqual(ms[0]["val1"], 70.0)

    def test_time_yesterday(self):
        ms = intent.parse_measurements("昨天晚上血压 145/92")
        ts = datetime.strptime(ms[0]["measured_at"], "%Y-%m-%d %H:%M:%S")
        self.assertEqual(ts.date(), (datetime.now() - timedelta(days=1)).date())
        self.assertEqual(ts.hour, 19)

    def test_intent_detect(self):
        self.assertEqual(intent.detect_intent("今天血压 150/95")[0], "record")
        self.assertEqual(intent.detect_intent("我最近血压怎么样")[0], "query_trend")
        self.assertEqual(intent.detect_intent("给我一份 7 天方案")[0], "plan")
        self.assertEqual(intent.detect_intent("帮我生成本周报告")[0], "report")


class TestSafety(unittest.TestCase):
    def test_chest_pain(self):
        r = safety.evaluate("我胸口疼得厉害，还出冷汗")
        self.assertEqual(r["level"], "emergency")
        self.assertIn("120", r["actions"])

    def test_stroke(self):
        r = safety.evaluate("我爸突然说话不清，一侧胳膊抬不起来")
        self.assertEqual(r["level"], "emergency")

    def test_bp_180_110(self):
        r = safety.evaluate("今天血压 185/110")
        self.assertEqual(r["level"], "emergency")

    def test_high_glucose(self):
        r = safety.evaluate("血糖 18.2")
        self.assertEqual(r["level"], "emergency")

    def test_hypoglycemia(self):
        r = safety.evaluate("血糖 3.2")
        self.assertEqual(r["level"], "urgent")

    def test_prescription(self):
        for text in ["我能不能把氨氯地平停掉", "能不能减半片", "不吃药了行不行"]:
            self.assertEqual(safety.check_prescription(text)["level"], "prescription", text)

    def test_normal_not_blocked(self):
        self.assertEqual(safety.evaluate("今天血压 135/85")["level"], "none")


class TestRiskClassification(unittest.TestCase):
    def test_bp_levels(self):
        self.assertEqual(risks.classify_bp(120, 78)["level"], "normal")
        self.assertEqual(risks.classify_bp(145, 92)["level"], "watch")
        self.assertEqual(risks.classify_bp(165, 102)["level"], "danger")
        self.assertEqual(risks.classify_bp(182, 112)["level"], "emergency")

    def test_glucose_levels(self):
        self.assertEqual(risks.classify_glucose(5.2, "fasting")["level"], "normal")
        self.assertEqual(risks.classify_glucose(6.5, "fasting")["level"], "watch")
        self.assertEqual(risks.classify_glucose(7.4, "fasting")["level"], "danger")
        self.assertEqual(risks.classify_glucose(3.2, "random")["level"], "emergency")

    def test_lipid_tg_pancreatitis(self):
        self.assertEqual(risks.classify_lipid(6.1, "tg")["level"], "emergency")

    def test_bmi(self):
        r = risks.classify_weight(78, 170)
        self.assertEqual(r["level"], "watch")


class TestMeasurementStore(unittest.TestCase):
    def test_reject_impossible(self):
        bad = measurements.record(TEST_USER, "bp", None, 1500, 95)
        self.assertFalse(bad["ok"])
        bad2 = measurements.record(TEST_USER, "bp", None, 80, 120)
        self.assertFalse(bad2["ok"], "收缩压低于舒张压应被拒绝")

    def test_record_and_trend(self):
        for i in range(5):
            day = datetime.now() - timedelta(days=4 - i)
            measurements.record(TEST_USER, "bp", None, 150 - i, 95 - i,
                                measured_at=day.strftime("%Y-%m-%d %H:%M:%S"))
        t = trends.analyze(TEST_USER, "bp", None, days=30, min_points=3)
        self.assertTrue(t["ok"])
        self.assertEqual(t["count"], 5)
        self.assertIn("下降", t["stats"]["direction"])

    def test_trend_insufficient(self):
        t = trends.analyze(TEST_USER, "lipid", "ldl", days=30, min_points=3)
        self.assertFalse(t["ok"])
        self.assertIn("不足", t["message"])


class TestMedicationInteractions(unittest.TestCase):
    def test_beta_blocker_masks_hypoglycemia(self):
        res = interactions.check(["美托洛尔", "格列美脲"], include_current=False)
        titles = " ".join(i["title"] for i in res["interactions"])
        self.assertIn("低血糖", titles)
        self.assertTrue(any(i["level"] == "high" for i in res["interactions"]))

    def test_statin_fibrate(self):
        res = interactions.check(["阿托伐他汀", "非诺贝特"], include_current=False)
        self.assertTrue(any("贝特" in i["title"] for i in res["interactions"]))

    def test_alias_resolution(self):
        self.assertEqual(interactions.resolve("倍他乐克")["id"], "metoprolol")

    def test_rules_loaded(self):
        st = interactions.stats()
        self.assertGreaterEqual(st["drug_count"], 30)
        self.assertGreaterEqual(st["rule_count"], 25)


class TestPlanAndReport(unittest.TestCase):
    def test_plan_structure(self):
        p = plan_tool.generate(TEST_USER, days=7)
        self.assertEqual(len(p["days"]), 7)
        items = p["days"][0]["items"]
        self.assertTrue(all("time" in i and "content" in i for i in items))
        self.assertTrue(any(i["category"] == "meal" for i in items))
        self.assertTrue(any(i["category"] == "measure" for i in items))
        self.assertGreater(len(p["tips"]), 0)

    def test_report_sections(self):
        r = reports.weekly(TEST_USER, 7)
        titles = [s["title"] for s in r["sections"]]
        self.assertTrue(any("血压" in t for t in titles))
        self.assertIn("本建议不构成诊疗意见", r["disclaimer"])


class TestRAG(unittest.TestCase):
    def test_search_returns_guideline(self):
        hits = get_kb().search("三高人群每天能吃多少盐", 3)
        self.assertTrue(hits)
        joined = " ".join(h["title"] for h in hits)
        self.assertIn("膳食", joined)

    def test_emergency_doc(self):
        hits = get_kb().search("中风怎么识别", 3)
        self.assertTrue(any("急症" in h["title"] for h in hits))

    def test_add_and_remove_doc(self):
        kb = get_kb()
        before = len(kb.docs)
        name = kb.add_document("_test_temp.md",
                               "---\ntitle: 临时测试文档\n---\n# 测试\n临时内容：每日食盐不超过 5 克。")
        self.assertTrue(name.endswith(".md"))
        self.assertEqual(len(kb.docs), before + 1)
        self.assertTrue(kb.remove_document("_test_temp"))
        self.assertEqual(len(kb.docs), before)


class TestOrchestrator(unittest.TestCase):
    def test_emergency_blocks_generation(self):
        r = orchestrator.handle("我胸口疼，喘不上气", user_id=TEST_USER, use_llm=False, save=False)
        self.assertEqual(r["mode"], "safety")
        self.assertEqual(r["intent"], "emergency")
        self.assertIn("120", r["reply"])
        self.assertTrue(any(b["type"] == "alert" for b in r["blocks"]))

    def test_prescription_blocks(self):
        # 问“能不能停”属于医疗决策 → 处方红线
        r = orchestrator.handle("我能不能把二甲双胍停掉", user_id=TEST_USER, use_llm=False, save=False)
        self.assertEqual(r["mode"], "safety")
        self.assertEqual(r["intent"], "prescription")

    def test_stop_request_becomes_plan_change(self):
        # 陈述“我想停掉X” → 当作清单变更，但仍要求确认并提示遵医嘱
        r = orchestrator.handle("我想把二甲双胍停掉", user_id=TEST_USER, use_llm=False, save=False)
        self.assertEqual(r["intent"], "med_plan")
        self.assertTrue(any(b["type"] == "med_change" and b["action"] == "stop" for b in r["blocks"]))
        self.assertIn("不要自行停药", r["reply"])

    def test_record_flow_offline(self):
        r = orchestrator.handle("今天血压 148/94", user_id=TEST_USER, use_llm=False, save=False)
        self.assertEqual(r["intent"], "record")
        self.assertEqual(r["mode"], "local")
        types = [b["type"] for b in r["blocks"]]
        self.assertIn("metric", types)
        self.assertTrue(r["disclaimer"])

    def test_trend_flow(self):
        r = orchestrator.handle("我最近血压怎么样", user_id=TEST_USER, use_llm=False, save=False)
        self.assertEqual(r["intent"], "query_trend")
        types = [b["type"] for b in r["blocks"]]
        self.assertIn("chart", types)

    def test_plan_flow(self):
        r = orchestrator.handle("给我一份 7 天方案", user_id=TEST_USER, use_llm=False, save=False)
        self.assertEqual(r["intent"], "plan")
        self.assertTrue(any(b["type"] == "plan" for b in r["blocks"]))

    def test_kb_answer_has_sources(self):
        r = orchestrator.handle("血压高的人每天能吃多少盐", user_id=TEST_USER, use_llm=False, save=False)
        self.assertTrue(r["sources"], "知识问答必须附带可溯源来源")

    def test_trace_ordered(self):
        r = orchestrator.handle("今天血压 146/92", user_id=TEST_USER, use_llm=False, save=False)
        labels = [t["step"] for t in r["trace"]]
        self.assertEqual(labels[0], "safety")
        self.assertLess(labels.index("intent"), labels.index("llm") if "llm" in labels else len(labels))


class TestLabReport(unittest.TestCase):
    def test_parse_sample_all_items(self):
        from tools import lab_report
        r = lab_report.parse_text(lab_report.SAMPLE)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["items"]), 6)
        labels = [i["label"] for i in r["items"]]
        self.assertIn("糖化血红蛋白", labels)
        self.assertEqual(r["date_text"], "2026-10-30")

    def test_two_indicators_in_one_line(self):
        from tools import lab_report
        r = lab_report.parse_text("总胆固醇 5.6 甘油三酯 2.31")
        self.assertEqual(len(r["items"]), 2)
        values = {i["label"]: i["value"] for i in r["items"]}
        self.assertEqual(values["总胆固醇"], 5.6)
        self.assertEqual(values["甘油三酯"], 2.31)

    def test_abbreviation_not_parsed_as_number(self):
        from tools import lab_report
        r = lab_report.parse_text("糖化血红蛋白(HbA1c) 7.5 %")
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["value"], 7.5)

    def test_out_of_range_line_skipped(self):
        from tools import lab_report
        r = lab_report.parse_text("空腹血糖 168")
        self.assertFalse(r["ok"])

    def test_commit_writes_measurements(self):
        from tools import lab_report
        r = lab_report.parse_text("空腹血糖 6.8\n甘油三酯 2.31")
        res = lab_report.commit(TEST_USER, r["items"], r["measured_at"])
        self.assertEqual(res["count"], 2)
        self.assertGreaterEqual(measurements.count(TEST_USER), 2)

    def test_chat_lab_intent_returns_card(self):
        from tools import lab_report
        r = orchestrator.handle(lab_report.SAMPLE, user_id=TEST_USER, use_llm=False, save=False)
        self.assertEqual(r["intent"], "lab")
        self.assertTrue(any(b["type"] == "lab" for b in r["blocks"]))

    def test_chat_medication_dose_and_time(self):
        r = orchestrator.handle("今天早上吃了一片氨氯地平", user_id=TEST_USER, use_llm=False, save=False)
        self.assertEqual(r["intent"], "med_record")
        self.assertEqual(r["mode"], "local")


class TestSecurityHardening(unittest.TestCase):
    """对应评审意见 P1–P9：权限、打卡去重、未知药物、档案校验、急症同义词。"""

    def test_unknown_drug_rejected(self):
        res = medications.log_dose(TEST_USER, "不存在的药")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "unknown_med")

    def test_duplicate_checkin_blocked(self):
        medications.add_med(TEST_USER, "测试药甲", "5 mg", times=["08:00"])
        first = medications.log_dose(TEST_USER, "测试药甲")
        self.assertTrue(first["ok"])
        second = medications.log_dose(TEST_USER, "测试药甲")
        self.assertFalse(second["ok"])
        self.assertEqual(second["code"], "already_done")

    def test_multi_slot_requires_each_slot(self):
        medications.add_med(TEST_USER, "测试药乙", "5 mg", times=["08:00", "18:00"])
        r1 = medications.log_dose(TEST_USER, "测试药乙")
        r2 = medications.log_dose(TEST_USER, "测试药乙")
        self.assertEqual({r1["slot"], r2["slot"]}, {"08:00", "18:00"})
        self.assertFalse(medications.log_dose(TEST_USER, "测试药乙")["ok"])

    def test_adherence_never_exceeds_100(self):
        for _ in range(8):
            medications.log_dose(TEST_USER, "测试药甲")
        a = medications.adherence(TEST_USER, 7)
        self.assertLessEqual(a["rate"], 100)
        for name, v in a["by_med"].items():
            self.assertLessEqual(v["rate"], 100, name)

    def test_profile_field_validation(self):
        self.assertFalse(profile_tool.update_profile_checked(TEST_USER, {"height_cm": 500})["ok"])
        self.assertFalse(profile_tool.update_profile_checked(TEST_USER, {"birth_year": 1800})["ok"])
        self.assertFalse(profile_tool.update_profile_checked(TEST_USER, {"wake_time": "25:99"})["ok"])
        self.assertFalse(profile_tool.update_profile_checked(TEST_USER, {"name": "x" * 30})["ok"])
        self.assertTrue(profile_tool.update_profile_checked(TEST_USER, {"height_cm": 171})["ok"])

    def test_red_flag_synonyms(self):
        for text in ["我爸嘴歪了，说话含糊", "突然一侧手麻，抬不起胳膊", "气短得厉害，上不来气"]:
            self.assertEqual(safety.evaluate(text)["level"], "emergency", text)

    def test_no_false_positive_on_mild_complaints(self):
        for text in ["我今天有点累", "昨晚没睡好", "血压 128/78", "最近走路有点慢"]:
            self.assertEqual(safety.evaluate(text)["level"], "none", text)

    def test_session_lifecycle(self):
        from agent import auth
        token = auth.STORE.create("u_session_test")
        self.assertIsNotNone(auth.STORE.get(token))
        self.assertEqual(auth.STORE.get(token)["user_id"], "u_session_test")
        auth.STORE.revoke(token)
        self.assertIsNone(auth.STORE.get(token))

    def test_session_expiry(self):
        from agent import auth
        token = auth.STORE.create("u_session_test")
        auth.STORE._sessions[token]["created"] -= auth.SESSION_TTL + 10
        self.assertIsNone(auth.STORE.get(token))

    def test_garbage_input_does_not_crash(self):
        r = orchestrator.handle("血压" + "9" * 3000, user_id=TEST_USER, use_llm=False, save=False)
        self.assertTrue(r["ok"])
        r2 = orchestrator.handle("！！！", user_id=TEST_USER, use_llm=False, save=False)
        self.assertTrue(r2["ok"])


class TestMedPlanChange(unittest.TestCase):
    """用药计划变更：写入/移除都要先确认，确认前不得写库。"""

    def test_parse_new_schedule(self):
        plan = intent.parse_med_plan("我每天早上8点吃一片氨氯地平")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "upsert")
        self.assertEqual(plan["items"][0]["name"], "氨氯地平")
        self.assertEqual(plan["items"][0]["times"], ["08:00"])

    def test_parse_per_drug_schedule(self):
        plan = intent.parse_med_plan("每天早上8点吃一片氨氯地平，晚上9点吃阿托伐他汀20mg")
        times = {i["name"]: i["times"] for i in plan["items"]}
        self.assertEqual(times["氨氯地平"], ["08:00"])
        self.assertEqual(times["阿托伐他汀"], ["21:00"])

    def test_parse_twice_daily(self):
        plan = intent.parse_med_plan("二甲双胍改成一天两次，早晚各一次")
        self.assertEqual(plan["items"][0]["times"], ["08:00", "19:00"])

    def test_parse_stop(self):
        plan = intent.parse_med_plan("把阿托伐他汀从打卡里删掉")
        self.assertEqual(plan["action"], "stop")
        self.assertEqual(plan["items"][0]["name"], "阿托伐他汀")

    def test_advice_question_is_not_plan(self):
        # “能不能停药”属于医疗决策，走处方红线，不当作计划变更
        self.assertIsNone(intent.parse_med_plan("我能不能把氨氯地平停掉"))

    def test_no_write_before_confirm(self):
        before = len(medications.list_meds(TEST_USER))
        r = orchestrator.handle("我每天早上8点吃一片氨氯地平", user_id=TEST_USER,
                                use_llm=False, save=False)
        after = len(medications.list_meds(TEST_USER))
        self.assertEqual(before, after, "确认前不得写入用药计划")
        self.assertTrue(any(b["type"] == "med_change" for b in r["blocks"]))
        self.assertEqual(r["mode"], "rule")

    def test_confirm_then_write(self):
        medications.add_med(TEST_USER, "计划药", "5 mg", times=["08:00"])
        meds = {m["name"]: m for m in medications.list_meds(TEST_USER)}
        self.assertIn("计划药", meds)
        self.assertTrue(medications.stop_med(TEST_USER, "计划药"))
        meds = {m["name"]: m for m in medications.list_meds(TEST_USER)}
        self.assertNotIn("计划药", meds)

    def test_add_vs_update_is_distinguished(self):
        # 清单里没有 → 新增
        r = orchestrator.handle("我每天中午12点吃一片氯沙坦", user_id=TEST_USER,
                                use_llm=False, save=False)
        card = next(b for b in r["blocks"] if b["type"] == "med_change")
        self.assertEqual(card["mode"], "add")
        self.assertEqual(card["title"], "新增用药计划")
        self.assertEqual(card["items"][0]["change"], "add")

        # 已存在 → 变更
        medications.add_med(TEST_USER, "氯沙坦", "50 mg", times=["12:00"])
        r2 = orchestrator.handle("氯沙坦改成晚上8点", user_id=TEST_USER, use_llm=False, save=False)
        card2 = next(b for b in r2["blocks"] if b["type"] == "med_change")
        self.assertEqual(card2["mode"], "update")
        self.assertEqual(card2["title"], "变更用药计划")
        self.assertEqual(card2["items"][0]["change"], "update")
        self.assertEqual(card2["items"][0]["times"], ["20:00"])

    def test_noop_when_identical(self):
        medications.add_med(TEST_USER, "氯沙坦", "50 mg", times=["12:00"])
        r = orchestrator.handle("每天12点吃氯沙坦", user_id=TEST_USER, use_llm=False, save=False)
        self.assertFalse(any(b["type"] == "med_change" for b in r["blocks"]))
        self.assertIn("不用修改", r["reply"])

    def test_more_than_four_slots(self):
        plan = intent.parse_med_plan("每天8点、10点、12点、15点、18点、21点吃二甲双胍")
        self.assertEqual(plan["items"][0]["times"],
                         ["08:00", "10:00", "12:00", "15:00", "18:00", "21:00"])

    def test_mixed_period_word_not_dropped(self):
        # 「睡前」没有钟点，不能被前面几个时间点挤掉
        plan = intent.parse_med_plan("每天8点、12点、18点、21点、睡前吃一片二甲双胍")
        self.assertEqual(plan["items"][0]["times"],
                         ["08:00", "12:00", "18:00", "21:00", "22:00"])

    def test_colon_format_times(self):
        times, _ = intent.parse_schedule("每天8:00、12:30、18:00、21:00")
        self.assertEqual(times, ["08:00", "12:30", "18:00", "21:00"])

    def test_merge_adds_only_new_times(self):
        """默认是合并去重：新时段补进去，原有安排保留。"""
        medications.add_med(TEST_USER, "缬沙坦", "80 mg", times=["08:00", "12:00"])
        r = orchestrator.handle("我每天18点吃缬沙坦", user_id=TEST_USER, use_llm=False, save=False)
        it = next(b for b in r["blocks"] if b["type"] == "med_change")["items"][0]
        self.assertEqual(it["change"], "append")
        self.assertEqual(it["final_times"], ["08:00", "12:00", "18:00"])
        self.assertEqual(it["added_times"], ["18:00"])
        # 确认前不写库
        meds = {m["name"]: m for m in medications.list_meds(TEST_USER)}
        self.assertEqual(meds["缬沙坦"]["times"], ["08:00", "12:00"])

    def test_duplicate_time_is_not_added_twice(self):
        medications.add_med(TEST_USER, "格列美脲", "2 mg", times=["08:00", "12:00"])
        r = orchestrator.handle("我每天8点吃格列美脲", user_id=TEST_USER, use_llm=False, save=False)
        self.assertFalse(any(b["type"] == "med_change" for b in r["blocks"]))
        self.assertIn("不用修改", r["reply"])

    def test_explicit_change_replaces(self):
        medications.add_med(TEST_USER, "阿卡波糖", "50 mg", times=["08:00", "12:00"])
        r = orchestrator.handle("阿卡波糖改成一天两次，早晚各一次", user_id=TEST_USER,
                                use_llm=False, save=False)
        it = next(b for b in r["blocks"] if b["type"] == "med_change")["items"][0]
        self.assertEqual(it["change"], "update")
        self.assertEqual(it["final_times"], ["08:00", "19:00"])

    def test_upsert_times_merges_by_default(self):
        """界面上的「添加」也必须去重合并，不能覆盖。"""
        medications.add_med(TEST_USER, "界面药", "5 mg", times=["08:00", "18:00"])
        r = medications.upsert_times(TEST_USER, "界面药", "", ["12:00"])
        self.assertEqual(r["mode"], "append")
        self.assertEqual(r["times"], ["08:00", "12:00", "18:00"])
        # 再加一次重复的 → 不修改
        r2 = medications.upsert_times(TEST_USER, "界面药", "", ["12:00"])
        self.assertEqual(r2["mode"], "none")
        self.assertEqual(r2["times"], ["08:00", "12:00", "18:00"])
        # 显式 replace 才整体覆盖
        r3 = medications.upsert_times(TEST_USER, "界面药", "", ["09:00"], op="replace")
        self.assertEqual(r3["mode"], "update")
        self.assertEqual(r3["times"], ["09:00"])

    def test_update_keeps_dose_when_omitted(self):
        medications.add_med(TEST_USER, "保剂量药", "10 mg", times=["08:00"])
        medications.add_med(TEST_USER, "保剂量药", "", times=["08:00", "19:00"])
        meds = {m["name"]: m for m in medications.list_meds(TEST_USER)}
        self.assertEqual(meds["保剂量药"]["dose"], "10 mg")
        self.assertEqual(meds["保剂量药"]["times"], ["08:00", "19:00"])


class TestToolWhitelist(unittest.TestCase):
    def test_unknown_tool_rejected(self):
        res = registry.call("shell.exec", cmd="rm -rf /")
        self.assertFalse(res["ok"])
        self.assertIn("未注册", res["error"])

    def test_registered_tool(self):
        res = registry.call("profile.get", user_id=TEST_USER)
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"]["user_id"], TEST_USER)


if __name__ == "__main__":
    unittest.main(verbosity=2)
