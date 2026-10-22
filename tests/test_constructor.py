"""构建器回归测试：教材 → 分块 → 粗筛 → 合法 graph.json。"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import validate_graph as vg  # noqa: E402

from kg_constructor.build import build_graph  # noqa: E402
from kg_constructor.extract import extract_candidates  # noqa: E402
from kg_constructor.readers import read_textbook  # noqa: E402
from kg_constructor.segment import segment  # noqa: E402

EXAMPLE = ROOT / "examples" / "sample_electromagnetism.md"
SCHEMA = ROOT / "graph.schema.json"


class ConstructorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loaded = read_textbook(EXAMPLE, title="大学电磁学")
        cls.segmentation = segment(cls.loaded.text, fallback_title=cls.loaded.title)
        cls.candidates = extract_candidates(cls.segmentation.sections, max_per_section=10)
        cls.graph = build_graph(cls.loaded, cls.segmentation, cls.candidates)
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def messages(self, graph: dict) -> list[str]:
        validator = vg.Draft202012Validator(
            self.schema,
            format_checker=vg.Draft202012Validator.FORMAT_CHECKER,
        )
        issues = vg.schema_issues(validator, graph)
        issues += vg.SemanticChecker(graph).run()
        return [f"{issue.pointer}: {issue.message}" for issue in issues]

    def test_graph_is_valid(self) -> None:
        self.assertEqual(self.messages(self.graph), [])

    def test_chapters_are_recognized(self) -> None:
        titles = {chapter["title"] for chapter in self.graph["chapters"]}
        self.assertIn("静电场", titles)
        self.assertIn("恒定磁场", titles)
        self.assertIn("电磁感应", titles)

    def test_core_nodes_are_extracted(self) -> None:
        names = {node["name"] for node in self.graph["nodes"]}
        for expected in ["库仑定律", "电场强度", "电通量", "高斯定理", "高斯面法", "法拉第电磁感应定律"]:
            self.assertIn(expected, names)

    def test_no_sentence_fragments(self) -> None:
        names = [node["name"] for node in self.graph["nodes"]]
        forbidden = ["当带电体", "这种现象", "置于电场中", "种现象"]
        for fragment in forbidden:
            self.assertFalse(
                any(fragment in name for name in names),
                msg=f"抽到了句子碎片：{fragment}；实际节点：{names}",
            )

    def test_evidence_is_attached(self) -> None:
        evidence_ids = {item["id"] for item in self.graph["evidence"]}
        for node in self.graph["nodes"]:
            self.assertTrue(node["evidence_ids"])
            self.assertTrue(set(node["evidence_ids"]) <= evidence_ids)
        for edge in self.graph["edges"]:
            self.assertTrue(edge["evidence_ids"])
            self.assertTrue(set(edge["evidence_ids"]) <= evidence_ids)

    def test_formula_nodes_have_latex(self) -> None:
        formulas = [node for node in self.graph["nodes"] if node["type"] == "formula"]
        self.assertTrue(formulas)
        for node in formulas:
            self.assertTrue(node["formula_latex"])
            self.assertNotIn("$", node["formula_latex"])

    def test_no_isolated_nodes(self) -> None:
        endpoints = set()
        for edge in self.graph["edges"]:
            endpoints.add(edge["source"])
            endpoints.add(edge["target"])
        isolated = [node["id"] for node in self.graph["nodes"] if node["id"] not in endpoints]
        self.assertEqual(isolated, [])

    def test_relations_cover_three_types(self) -> None:
        relations = {edge["relation"] for edge in self.graph["edges"]}
        self.assertEqual(relations, {"prerequisite", "derives", "related_to"})

    def test_duplicate_id_is_caught_by_validator(self) -> None:
        graph = copy.deepcopy(self.graph)
        graph["nodes"][1]["id"] = graph["nodes"][0]["id"]
        self.assertTrue(any("重复" in message for message in self.messages(graph)))


if __name__ == "__main__":
    unittest.main()
