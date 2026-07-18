from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "blog_workflow.py"
SPEC = importlib.util.spec_from_file_location("blog_workflow", SCRIPT_PATH)
assert SPEC and SPEC.loader
workflow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)


class BlogWorkflowWritingProfilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.topic_config = workflow.load_topic_config()
        cls.profiles = workflow.load_writing_profiles(cls.topic_config)

    def test_profiles_cover_exactly_17_categories_and_12_types(self) -> None:
        topic_names = {item["name"] for item in self.topic_config["categories"]}
        self.assertEqual(topic_names, set(self.profiles["categories"]))
        self.assertEqual(17, len(topic_names))
        self.assertEqual(set(workflow.ARTICLE_TYPES), set(self.profiles["article_types"]))
        self.assertEqual(12, len(workflow.ARTICLE_TYPES))

    def test_article_type_default_length_ranges(self) -> None:
        expected = {
            "news-analysis": (1200, 2000),
            "faq-knowledge": (1800, 3000),
            "listicle": (2000, 3200),
            "product-review": (2000, 3200),
            "roundup": (2000, 3200),
            "case-study": (2200, 3500),
            "comparison": (2200, 3500),
            "thought-leadership": (2200, 3800),
            "how-to-guide": (2500, 4000),
            "tutorial": (2800, 4500),
            "data-research": (2800, 4500),
            "pillar-page": (3500, 6000),
        }
        actual = {
            name: (profile["minimum_length"], profile["recommended_max_length"])
            for name, profile in self.profiles["article_types"].items()
        }
        self.assertEqual(expected, actual)
        self.assertTrue(all(0 < minimum <= maximum for minimum, maximum in actual.values()))

    def test_all_article_types_can_be_explicitly_selected(self) -> None:
        for article_type in workflow.ARTICLE_TYPES:
            with self.subTest(article_type=article_type):
                result = workflow.resolve_article_type("任意主题", "任意角度", "互联网与科技趋势", article_type)
                self.assertEqual(article_type, result.name)
                self.assertTrue(result.explicit)
                self.assertEqual(1.0, result.confidence)

        with self.assertRaises(ValueError):
            workflow.resolve_article_type("任意主题", "任意角度", "互联网与科技趋势", "unknown")

    def test_article_type_inference_covers_all_12_types(self) -> None:
        cases = {
            "A vs B 对比": "comparison",
            "一个创业案例复盘": "case-study",
            "最佳 7 个写作工具": "listicle",
            "本周 AI 观点合集": "roundup",
            "新工具深度评测": "product-review",
            "Python API 部署实践": "tutorial",
            "如何建立个人工作流": "how-to-guide",
            "公司宣布新的监管政策": "news-analysis",
            "一项 arXiv 论文研究": "data-research",
            "什么是上下文工程": "faq-knowledge",
            "AI 学习知识体系": "pillar-page",
            "下一代产品组织的结构性变化": "thought-leadership",
        }
        for topic, expected in cases.items():
            with self.subTest(topic=topic):
                result = workflow.resolve_article_type(topic, "趋势观察", "互联网与科技趋势")
                self.assertEqual(expected, result.name)
                self.assertFalse(result.explicit)
                self.assertTrue(result.reason)

    def build_packet(
        self,
        category: str,
        article_type: str,
        items=None,
        minimum_length: int | None = None,
        maximum_length: int | None = None,
    ):
        category_info = next(item for item in self.topic_config["categories"] if item["name"] == category)
        resolution = workflow.CategoryResolution(category, 1.0, True, [])
        with tempfile.TemporaryDirectory() as tmp:
            return workflow.build_agent_writing_packet(
                "测试主题",
                resolution,
                category_info,
                [],
                items or [],
                workflow.now_local(),
                "zh-CN",
                self.profiles,
                article_type,
                Path(tmp),
                minimum_length,
                maximum_length,
            )

    def test_same_category_different_types_produce_different_outlines(self) -> None:
        tutorial = self.build_packet("AI与智能体相关", "tutorial")
        thought = self.build_packet("AI与智能体相关", "thought-leadership")
        self.assertNotEqual(tutorial["type_specific_outline"], thought["type_specific_outline"])
        self.assertEqual(tutorial["category_profile"], thought["category_profile"])
        self.assertTrue(Path(tutorial["template_path"]).exists())

    def test_agent_packet_requires_humanizer_stage(self) -> None:
        packet = self.build_packet("AI与智能体相关", "thought-leadership")
        humanizer = packet["humanizer"]
        self.assertTrue(humanizer["enabled"])
        self.assertEqual("humanizer-zh", humanizer["skill"])
        self.assertTrue(Path(humanizer["skill_path"]).exists())
        self.assertNotIn("minimum_score", humanizer)
        self.assertIn("after_initial_draft_before_validation", humanizer["stage"])
        self.assertEqual(4, len(humanizer["review_schema"]["fact_checklist"]))
        self.assertTrue(any("humanizer.skill_path" in item for item in packet["agent_handoff"]["instructions"]))

    def test_agent_packet_includes_default_and_overridden_length_requirements(self) -> None:
        default_packet = self.build_packet("AI与智能体相关", "news-analysis")
        self.assertEqual(1200, default_packet["length_requirement"]["minimum"])
        self.assertEqual(2000, default_packet["length_requirement"]["recommended_maximum"])
        self.assertEqual("article_type_default", default_packet["length_requirement"]["source"])
        override_packet = self.build_packet(
            "AI与智能体相关", "news-analysis", minimum_length=900, maximum_length=1500
        )
        self.assertEqual(900, override_packet["length_requirement"]["minimum"])
        self.assertEqual(1500, override_packet["length_requirement"]["recommended_maximum"])
        self.assertEqual("cli_override", override_packet["length_requirement"]["source"])

    def test_length_override_validation(self) -> None:
        self.assertEqual((1000, 1800), workflow.validate_length_override(1000, 1800, "agent-packet"))
        for minimum, maximum, writer in [
            (1000, None, "agent-packet"),
            (None, 1800, "agent-packet"),
            (0, 1800, "agent-packet"),
            (-1, 1800, "agent-packet"),
            (2000, 1000, "agent-packet"),
        ]:
            with self.subTest(minimum=minimum, maximum=maximum, writer=writer):
                with self.assertRaises(ValueError):
                    workflow.validate_length_override(minimum, maximum, writer)

    def test_invalid_cli_length_stops_before_collection(self) -> None:
        with mock.patch.object(workflow, "collect_items") as collector:
            with redirect_stderr(io.StringIO()):
                exit_code = workflow.main(
                    ["--topic", "测试", "--writer", "agent-packet", "--min-length", "1000"]
                )
        self.assertEqual(2, exit_code)
        collector.assert_not_called()

    def test_effective_length_excludes_non_body_material(self) -> None:
        article = """---
title: 不计
---
# 标题

正文 AI 2026。
[链接文字](https://example.com/path)
`内联代码`

```python
不计 code 99
```

[IMAGE: 不计]
<!-- 不计 -->

## 小节

表格内容 | data

## 来源记录

来源文字 English 123
"""
        counts = workflow.count_effective_article_length(article)
        self.assertEqual(14, counts["cjk_characters"])
        self.assertEqual(2, counts["english_words"])
        self.assertEqual(1, counts["number_sequences"])
        self.assertEqual(17, counts["effective_length"])

    def test_length_below_minimum_needs_work_and_above_maximum_is_informational(self) -> None:
        below_packet = self.build_packet(
            "AI与智能体相关", "news-analysis", minimum_length=50, maximum_length=100
        )
        _, below_meta = workflow.render_writing_compliance_report("# 短文\n\n内容有限。", below_packet, Path("article.md"))
        self.assertEqual("needs_work", below_meta["length"]["minimum_status"])
        self.assertIn("minimum_length", below_meta["failed"])

        above_packet = self.build_packet(
            "AI与智能体相关", "news-analysis", minimum_length=2, maximum_length=3
        )
        _, above_meta = workflow.render_writing_compliance_report(
            "# 标题\n\n正文内容已经超过建议上限。", above_packet, Path("article.md")
        )
        self.assertEqual("above_recommended_maximum", above_meta["length"]["position"])
        self.assertEqual("passed", above_meta["length"]["minimum_status"])
        self.assertNotIn("recommended_maximum", above_meta["failed"])

    def test_same_type_different_categories_produce_different_profiles(self) -> None:
        technical = self.build_packet("技术分享", "tutorial")
        investment = self.build_packet("投资相关", "tutorial")
        self.assertEqual(technical["type_specific_outline"], investment["type_specific_outline"])
        self.assertNotEqual(technical["category_profile"], investment["category_profile"])
        self.assertIn("环境", technical["category_profile"]["required_moves"][0])
        self.assertIn("投资建议", investment["category_profile"]["risk_disclosure"])

    def test_evidence_gaps_are_report_only(self) -> None:
        packet = self.build_packet("AI与智能体相关", "thought-leadership")
        article = """# 测试文章

截至 2026年7月12日，[来源一](https://one.example)与[来源二](https://two.example)提供了信号，[来源三](https://three.example)补充了背景。

## 中心论点
这是中心论点。

## 主流观点
这是主流观点。

## 关键证据
这是证据。

## 独立解释
这是解释。

## 最强反方
反方指出能力边界和采用阻力仍然存在。

## 影响与观察点
下一步继续观察。
"""
        _, meta = workflow.render_writing_compliance_report(article, packet, Path("article.md"))
        self.assertEqual("needs_work", meta["status"])
        self.assertIn("primary_technical", meta["failed"])
        self.assertIn("product_or_community", meta["failed"])

    def test_technical_article_without_environment_or_version_needs_work(self) -> None:
        packet = self.build_packet("技术分享", "tutorial")
        article = """# 技术文章

截至 2026-07-12，[一](https://one.example)、[二](https://two.example)和[三](https://three.example)描述了实现。

## 完成效果
可以运行。
## 架构原理
说明原理。
## 逐步实现
给出代码。
## 运行
运行命令。
## 排错
说明限制与错误。
## 生产注意事项
说明风险。
"""
        _, meta = workflow.render_writing_compliance_report(article, packet, Path("article.md"))
        self.assertIn("environment_version", meta["failed"])

    def test_investment_article_without_disclosure_needs_work(self) -> None:
        packet = self.build_packet("投资相关", "thought-leadership")
        article = """# 投资观察

截至 2026-07-12，[一](https://one.example)、[二](https://two.example)和[三](https://three.example)形成线索。

## 中心论点
概率判断。
## 主流观点
市场观点。
## 关键证据
数据。
## 独立解释
解释。
## 最强反方
限制存在。
## 影响与观察点
继续观察。
"""
        _, meta = workflow.render_writing_compliance_report(article, packet, Path("article.md"))
        self.assertIn("not_financial_advice", meta["failed"])
        self.assertIn("risk", meta["failed"])

    def test_default_writer_is_agent_packet(self) -> None:
        args = workflow.parse_args(["--topic", "测试"])
        self.assertEqual("agent-packet", args.writer)

    def test_validate_run_is_non_blocking_for_compliance_failures(self) -> None:
        packet = self.build_packet("技术分享", "tutorial")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            final_article = "# 短文\n\n2026-07-12 有一个限制，但没有完整结构。\n"
            (run_dir / "article.md").write_text(final_article, encoding="utf-8")
            (run_dir / "writing_packet.json").write_text(
                json.dumps(packet, ensure_ascii=False), encoding="utf-8"
            )
            (run_dir / "sources.json").write_text("[]", encoding="utf-8")
            with mock.patch.object(workflow, "run_analyze_check", return_value={"status": "skipped"}):
                with redirect_stdout(io.StringIO()):
                    exit_code = workflow.validate_existing_run(run_dir, 1.0, False)
            self.assertEqual(0, exit_code)
            metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual("needs_work", metadata["quality_checks"]["writing_compliance"]["status"])
            length = metadata["quality_checks"]["writing_compliance"]["length"]
            self.assertEqual(
                workflow.count_effective_article_length(final_article)["effective_length"],
                length["effective_length"],
            )
            self.assertEqual("humanizer", length["count_after_stage"])
            self.assertEqual("needs_work", metadata["quality_checks"]["humanizer"]["status"])
            self.assertTrue((run_dir / "quality" / "humanizer-check.md").exists())

    def test_humanizer_review_with_clean_article_passes(self) -> None:
        packet = self.build_packet("社会观察", "thought-leadership")
        article = """# 一次具体观察

2026年7月12日，[资料一](https://one.example)记录了变化。[资料二](https://two.example)给出另一组样本，[资料三](https://three.example)补充了背景。

样本来自两个平台，不能代表所有人。这里保留这个限制，也不急着替读者下结论。
"""
        with tempfile.TemporaryDirectory() as tmp:
            article_path = Path(tmp) / "article.md"
            article_path.write_text(article, encoding="utf-8")
            quality_dir = article_path.parent / "quality"
            quality_dir.mkdir()
            (quality_dir / "humanizer-review.md").write_text(
                """# Humanizer Review

状态: completed

## 主要修改

- 删除填充语并调整句子节奏。

## 事实保护

- [x] 链接未改变
- [x] 数字和日期未改变
- [x] 引语和代码未改变
- [x] 未虚构个人经历
""",
                encoding="utf-8",
            )
            _, meta = workflow.render_humanizer_check_report(article, packet, article_path)
            self.assertEqual("passed", meta["status"])
            self.assertTrue(meta["change_summary"])
            self.assertTrue(all(meta["fact_checklist"].values()))

    def test_humanizer_pattern_scan_flags_ai_style_even_with_review(self) -> None:
        packet = self.build_packet("商业与创业", "thought-leadership")
        article = (
            "# 🚀 关键性的变化\n\n"
            "当然！此外，这不仅仅是一次更新，而是行业不断演变的格局中的关键性转折。"
            "专家认为它至关重要，展示了公司持续追求卓越。——它令人叹为观止——也充满活力。\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            article_path = Path(tmp) / "article.md"
            article_path.write_text(article, encoding="utf-8")
            quality_dir = article_path.parent / "quality"
            quality_dir.mkdir()
            (quality_dir / "humanizer-review.md").write_text(
                """状态: completed

## 主要修改

- 删除部分套话。

## 事实保护

- [x] 链接未改变
- [x] 数字和日期未改变
- [x] 引语和代码未改变
- [x] 未虚构个人经历
""",
                encoding="utf-8",
            )
            _, meta = workflow.render_humanizer_check_report(article, packet, article_path)
            self.assertEqual("needs_work", meta["status"])
            finding_ids = {item["id"] for item in meta["findings"]}
            self.assertIn("chat_trace", finding_ids)
            self.assertIn("emoji_heading", finding_ids)
            self.assertIn("promotional_language", finding_ids)

    def test_humanizer_review_requires_complete_fact_checklist(self) -> None:
        packet = self.build_packet("社会观察", "thought-leadership")
        article = "2026年7月12日，样本有局限。"
        with tempfile.TemporaryDirectory() as tmp:
            article_path = Path(tmp) / "article.md"
            article_path.write_text(article, encoding="utf-8")
            quality_dir = article_path.parent / "quality"
            quality_dir.mkdir()
            (quality_dir / "humanizer-review.md").write_text(
                """状态: completed

## 主要修改

- 删除套话。

## 事实保护

- [x] 链接未改变
- [x] 数字和日期未改变
- [ ] 引语和代码未改变
- [x] 未虚构个人经历
""",
                encoding="utf-8",
            )
            _, meta = workflow.render_humanizer_check_report(article, packet, article_path)
            self.assertEqual("needs_work", meta["status"])
            self.assertIn("fact_preservation", meta["failed"])

    def test_strict_delivery_remains_blocking_when_explicit(self) -> None:
        packet = self.build_packet("技术分享", "tutorial")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "article.md").write_text("# 文章\n", encoding="utf-8")
            (run_dir / "writing_packet.json").write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
            (run_dir / "sources.json").write_text("[]", encoding="utf-8")
            with mock.patch.object(workflow, "run_quality_checks", return_value={}), mock.patch.object(
                workflow, "run_strict_delivery", return_value={"status": "blocked", "reason": "test"}
            ):
                with redirect_stdout(io.StringIO()):
                    exit_code = workflow.validate_existing_run(run_dir, 1.0, True)
            self.assertEqual(1, exit_code)

    def test_agent_packet_cli_creates_distinct_ai_tutorial_and_thought_handoffs(self) -> None:
        items = [
            workflow.EvidenceItem(
                source="arxiv",
                title="Primary paper",
                url="https://example.com/paper",
                labels=["primary", "research"],
                score=10,
            ),
            workflow.EvidenceItem(
                source="hackernews",
                title="Community discussion",
                url="https://example.com/community",
                labels=["community"],
                score=8,
            ),
        ]
        collector_result = ("topic", items, [], [], [], [], ["AI agent"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tutorial_dir = root / "tutorial"
            thought_dir = root / "thought"
            with mock.patch.object(workflow, "collect_items", return_value=collector_result):
                with redirect_stdout(io.StringIO()):
                    tutorial_exit = workflow.main(
                        [
                            "--topic",
                            "AI agent implementation",
                            "--category",
                            "AI与智能体相关",
                            "--writer",
                            "agent-packet",
                            "--article-type",
                            "tutorial",
                            "--min-length",
                            "100",
                            "--max-length",
                            "200",
                            "--output-dir",
                            str(tutorial_dir),
                        ]
                    )
                    thought_exit = workflow.main(
                        [
                            "--topic",
                            "AI agent adoption",
                            "--category",
                            "AI与智能体相关",
                            "--writer",
                            "agent-packet",
                            "--article-type",
                            "thought-leadership",
                            "--output-dir",
                            str(thought_dir),
                        ]
                    )
            self.assertEqual(0, tutorial_exit)
            self.assertEqual(0, thought_exit)
            tutorial_packet = json.loads((tutorial_dir / "writing_packet.json").read_text(encoding="utf-8"))
            thought_packet = json.loads((thought_dir / "writing_packet.json").read_text(encoding="utf-8"))
            self.assertNotEqual(tutorial_packet["type_specific_outline"], thought_packet["type_specific_outline"])
            self.assertEqual("cli_override", tutorial_packet["length_requirement"]["source"])
            self.assertEqual(100, tutorial_packet["length_requirement"]["minimum"])
            tutorial_metadata = json.loads((tutorial_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(tutorial_packet["length_requirement"], tutorial_metadata["length_requirement"])
            self.assertFalse((tutorial_dir / "article.md").exists())
            self.assertFalse((thought_dir / "article.md").exists())


if __name__ == "__main__":
    unittest.main()
