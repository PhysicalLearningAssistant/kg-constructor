"""validate_graph.py 的回归测试。

运行：
    python -m unittest discover -s tests -v
（在仓库根目录执行；依赖 jsonschema>=4.18,<5）
"""

from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import validate_graph as vg  # noqa: E402

EXAMPLE_PATH = ROOT / "example.graph.json"
SCHEMA_PATH = ROOT / "graph.schema.json"


class GraphTestCase(unittest.TestCase):
    """所有用例都从同一个合法示例出发，只改动被测规则涉及的部分。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def graph(self) -> dict:
        return copy.deepcopy(self.example)

    def messages(self, document: dict, *, release: bool = False) -> list[str]:
        validator = vg.Draft202012Validator(
            self.schema,
            format_checker=vg.Draft202012Validator.FORMAT_CHECKER,
        )
        issues = vg.schema_issues(validator, document)
        issues += vg.SemanticChecker(document, require_release=release).run()
        return [f"{issue.pointer}: {issue.message}" for issue in issues]

    def assert_issue(self, document: dict, needle: str, *, release: bool = False) -> None:
        messages = self.messages(document, release=release)
        self.assertTrue(
            any(needle in message for message in messages),
            msg=f"未找到包含 {needle!r} 的问题；实际结果：{messages}",
        )

    def approve_all(self, document: dict) -> None:
        for collection in ("nodes", "edges", "item_mappings"):
            for item in document[collection]:
                item["review"] = {
                    "status": "approved",
                    "reviewer_id": "reviewer_test",
                    "reviewed_at": "2026-10-15T00:00:00Z",
                    "note": None,
                }

    # ------------------------------------------------------------ 正例

    def test_example_passes(self) -> None:
        self.assertEqual(self.messages(self.graph()), [])

    def test_released_example_passes(self) -> None:
        document = self.graph()
        document["status"] = "released"
        self.approve_all(document)
        self.assertEqual(self.messages(document), [])
        self.assertEqual(self.messages(document, release=True), [])

    def test_cli_pass_and_release_fail(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(vg.main([str(EXAMPLE_PATH)]), 0)
        self.assertIn("[PASS]", buffer.getvalue())

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(vg.main([str(EXAMPLE_PATH), "--release"]), 1)
        self.assertIn("--release", buffer.getvalue())

    # ------------------------------------------------------------ 解析层

    def test_duplicate_json_key_rejected(self) -> None:
        with self.assertRaises(vg.InputError) as context:
            vg.parse_document('{"a": 1, "a": 2}'.encode("utf-8"))
        self.assertIn("重复键", str(context.exception))

    def test_bom_rejected(self) -> None:
        with self.assertRaises(vg.InputError) as context:
            vg.parse_document(b"\xef\xbb\xbf{}")
        self.assertIn("BOM", str(context.exception))

    def test_nan_rejected(self) -> None:
        with self.assertRaises(vg.InputError) as context:
            vg.parse_document('{"value": NaN}'.encode("utf-8"))
        self.assertIn("NaN", str(context.exception))

    # ------------------------------------------------------------ 结构与引用

    def test_duplicate_node_id(self) -> None:
        document = self.graph()
        document["nodes"][1]["id"] = document["nodes"][0]["id"]
        self.assert_issue(document, "重复")

    def test_missing_chapter(self) -> None:
        document = self.graph()
        document["nodes"][0]["chapter"] = "ch_missing"
        self.assert_issue(document, "ch_missing")

    def test_missing_evidence(self) -> None:
        document = self.graph()
        document["nodes"][0]["evidence_ids"][0] = "ev_missing"
        self.assert_issue(document, "ev_missing")

    def test_missing_skill(self) -> None:
        document = self.graph()
        document["item_mappings"][0]["skill_ids"][0] = "skill_missing"
        self.assert_issue(document, "skill_missing")

    def test_unknown_field_rejected(self) -> None:
        document = self.graph()
        document["nodes"][0]["extra"] = 1
        self.assert_issue(document, "Additional properties are not allowed")

    def test_extension_key_needs_namespace(self) -> None:
        document = self.graph()
        document["extensions"]["plain"] = 1
        self.assert_issue(document, "does not match")

    def test_extension_key_allows_unicode_namespace(self) -> None:
        document = self.graph()
        document["extensions"] = {"团队.难度": 3}
        self.assertEqual(self.messages(document), [])

    def test_asset_uri_needs_authority(self) -> None:
        document = self.graph()
        document["sources"][0]["uri"] = "asset:///course-library/em.pdf"
        self.assert_issue(document, "authority")

    def test_rag_ref_needs_both_ids(self) -> None:
        document = self.graph()
        document["evidence"][0]["rag_ref"] = {"file_id": "only_file_id"}
        self.assert_issue(document, "required property")

    def test_page_range_invalid(self) -> None:
        document = self.graph()
        document["evidence"][0]["locator"]["page_start"] = 90
        document["evidence"][0]["locator"]["page_end"] = 80
        self.assert_issue(document, "页码范围无效")

    def test_web_source_requires_https(self) -> None:
        document = self.graph()
        document["sources"][2]["uri"] = "http://ocw.example.edu/course"
        self.assert_issue(document, "/sources/2/uri")

    def test_uri_credentials_rejected(self) -> None:
        document = self.graph()
        document["sources"][2]["uri"] = "https://ocw.example.edu/course?token=abc"
        self.assert_issue(document, "疑似包含访问密钥")

    def test_asset_uri_private_path_rejected(self) -> None:
        document = self.graph()
        document["sources"][0]["uri"] = "asset://C:/Users/lenovo/secret.pdf"
        self.assert_issue(document, "私有绝对路径")

    def test_created_at_second_out_of_range(self) -> None:
        document = self.graph()
        document["created_at"] = "2026-10-16T08:00:60Z"
        self.assert_issue(document, "/created_at")

    def test_utc_offset_zero_accepted(self) -> None:
        document = self.graph()
        document["created_at"] = "2026-10-16T08:00:00+00:00"
        self.assertEqual(self.messages(document), [])

    def test_non_utc_offset_rejected(self) -> None:
        document = self.graph()
        document["created_at"] = "2026-10-16T16:00:00+08:00"
        self.assert_issue(document, "/created_at")

    def test_formula_latex_rejects_dollar_delimiters(self) -> None:
        document = self.graph()
        document["nodes"][3]["formula_latex"] = "$E = F/q$"
        self.assert_issue(document, "定界符")

    def test_file_source_requires_sha256(self) -> None:
        document = self.graph()
        document["sources"][0]["sha256"] = None
        self.assert_issue(document, "sha256")

    # ------------------------------------------------------------ 节点

    def test_alias_collision_after_normalization(self) -> None:
        document = self.graph()
        document["nodes"][0]["aliases"] = ["电场", "电场"]
        self.assert_issue(document, "规范化后与")

    def test_alias_equals_name(self) -> None:
        document = self.graph()
        document["nodes"][0]["aliases"] = ["电场强度"]
        self.assert_issue(document, "与主名称相同")

    def test_duplicate_condition(self) -> None:
        document = self.graph()
        document["nodes"][2]["conditions"].append("静电场")
        self.assert_issue(document, "conditions 存在重复元素")

    def test_formula_node_requires_latex(self) -> None:
        document = self.graph()
        document["nodes"][3]["formula_latex"] = None
        self.assert_issue(document, "/nodes/3/formula_latex")

    def test_non_formula_node_must_have_null_latex(self) -> None:
        document = self.graph()
        document["nodes"][0]["formula_latex"] = "E = F/q"
        self.assert_issue(document, "/nodes/0/formula_latex")

    # ------------------------------------------------------------ 章节

    def test_chapter_cycle(self) -> None:
        document = self.graph()
        document["chapters"][0]["parent_id"] = "ch_electric_field"
        self.assert_issue(document, "章节层级成环")

    def test_sibling_order_duplicate(self) -> None:
        document = self.graph()
        document["chapters"][2]["order"] = 0
        self.assert_issue(document, "order=0")

    # ------------------------------------------------------------ 关系

    def test_prerequisite_cycle(self) -> None:
        document = self.graph()
        document["edges"].append(
            {
                "id": "edge_back_to_field",
                "source": "electric_flux",
                "target": "electric_field",
                "relation": "prerequisite",
                "description": "制造环的测试边。",
                "evidence_ids": ["ev_lecture_flux"],
                "review": {
                    "status": "approved",
                    "reviewer_id": "reviewer_test",
                    "reviewed_at": "2026-10-15T00:00:00Z",
                    "note": None,
                },
                "extensions": {},
            }
        )
        self.assert_issue(document, "prerequisite 子图存在环")

    def test_redundant_prerequisite_edge(self) -> None:
        document = self.graph()
        document["edges"].append(
            {
                "id": "edge_field_to_gauss",
                "source": "electric_field",
                "target": "gauss_law",
                "relation": "prerequisite",
                "description": "已被 electric_field→electric_flux→gauss_law 覆盖。",
                "evidence_ids": ["ev_textbook_gauss"],
                "review": {
                    "status": "approved",
                    "reviewer_id": "reviewer_test",
                    "reviewed_at": "2026-10-15T00:00:00Z",
                    "note": None,
                },
                "extensions": {},
            }
        )
        self.assert_issue(document, "冗余直接边")

    def test_related_to_reverse_duplicate(self) -> None:
        document = self.graph()
        document["edges"].append(
            {
                "id": "edge_ampere_gauss_reversed",
                "source": "gauss_law",
                "target": "ampere_circuital_law",
                "relation": "related_to",
                "description": "反向重复记录，应被识别为重复。",
                "evidence_ids": ["ev_textbook_gauss"],
                "review": {
                    "status": "approved",
                    "reviewer_id": "reviewer_test",
                    "reviewed_at": "2026-10-15T00:00:00Z",
                    "note": None,
                },
                "extensions": {},
            }
        )
        self.assert_issue(document, "重复")

    def test_related_to_order(self) -> None:
        document = self.graph()
        for edge in document["edges"]:
            if edge["id"] == "edge_field_shielding":
                edge["source"], edge["target"] = edge["target"], edge["source"]
        self.assert_issue(document, "ASCII ID 升序")

    def test_edge_self_loop(self) -> None:
        document = self.graph()
        document["edges"][0]["target"] = document["edges"][0]["source"]
        self.assert_issue(document, "不得相同")

    # ------------------------------------------------------------ 审核

    def test_pending_with_reviewer(self) -> None:
        document = self.graph()
        pending = next(node for node in document["nodes"] if node["review"]["status"] == "pending")
        pending["review"]["reviewer_id"] = "reviewer_x"
        self.assert_issue(document, "pending 状态下 reviewer_id 必须为 null")

    def test_review_time_after_created_at(self) -> None:
        document = self.graph()
        document["nodes"][0]["review"]["reviewed_at"] = "2026-10-17T00:00:00Z"
        self.assert_issue(document, "不得晚于顶层 created_at")

    def test_rejected_requires_note(self) -> None:
        document = self.graph()
        document["nodes"][0]["review"] = {
            "status": "rejected",
            "reviewer_id": "reviewer_test",
            "reviewed_at": "2026-10-10T00:00:00Z",
            "note": None,
        }
        self.assert_issue(document, "rejected 状态的 note 必须非空")

    # ------------------------------------------------------------ redirects

    def test_redirect_chain(self) -> None:
        document = self.graph()
        document["redirects"]["gauss_old"] = "gauss_theorem"
        self.assert_issue(document, "不得成链")

    def test_redirect_target_missing(self) -> None:
        document = self.graph()
        document["redirects"]["gauss_theorem"] = "gauss_missing"
        self.assert_issue(document, "重定向目标")

    def test_redirect_old_id_still_a_node(self) -> None:
        document = self.graph()
        document["redirects"]["gauss_law"] = "gauss_law_integral"
        self.assert_issue(document, "不得同时存在于 nodes")

    # ------------------------------------------------------------ released

    def test_released_requires_approved(self) -> None:
        document = self.graph()
        document["status"] = "released"
        # 保持示例中的 pending 节点不变
        self.assert_issue(document, "必须全部为 approved")

    def test_released_forbids_isolated_node(self) -> None:
        document = self.graph()
        document["status"] = "released"
        self.approve_all(document)
        document["edges"] = []
        self.assert_issue(document, "孤立节点")


if __name__ == "__main__":
    unittest.main()
