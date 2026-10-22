#!/usr/bin/env python3
"""校验电磁学课程知识图谱文件是否符合《知识图谱文件格式规范 v1.0》。

用法：
    python validate_graph.py graph.json
    python validate_graph.py graph.json --release

依赖：Python 3.11+，jsonschema>=4.18,<5。

校验分两层：
1. graph.schema.json 的字段结构与取值域（JSON Schema Draft 2020-12）；
2. 文件内部一致性：ID 唯一、跨集合引用、章节无环、先修关系无环及传递归约、
   审核状态时效、redirects 规则、released 定稿约束。

规范中无法由 JSON Schema 表达、由本工具补充的规则：
- 文本必须是 NFC、首尾无空白；
- 证据页码必须成对且 page_start <= page_end；
- 同一 URI 的 authority 有效且不含用户名/密码；
- 别名的规范化去重；
- 章节同级 order 唯一、章节层级无环；
- related_to 的 ASCII 升序存储与反向重复判定；
- prerequisite 子图无环、无冗余传递边；
- 审核时间不得晚于 created_at；
- released 文件不得有孤立节点（本工具按“未出现在任何 edge 的 source/target 中”判定，
  item_mappings 的引用不算连通）；
- redirects 不得成链、成环或自指。

本工具不验证来源文件哈希真实性、原文真实性、关系事实正确性或人工审核真实性。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qsl, urlsplit

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
except ModuleNotFoundError:  # pragma: no cover - 取决于运行环境
    print(
        "缺少依赖 jsonschema。请先安装：\n"
        "    python -m pip install 'jsonschema>=4.18,<5'\n"
        "（本工具需要 Python 3.11 及以上版本）",
        file=sys.stderr,
    )
    raise SystemExit(2)


FILE_SOURCE_TYPES = {"pdf", "docx", "markdown"}
MAX_ERRORS_SHOWN = 50
ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
CREDENTIAL_QUERY_KEYS = {
    "key",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "secret",
    "signature",
    "password",
    "passwd",
    "credential",
    "authorization",
}
WINDOWS_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


class InputError(Exception):
    """输入文件内容不合法（JSON 语法、编码、重复键等）。"""


class DuplicateKeyError(Exception):
    """JSON 对象中出现重复键。"""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


@dataclass(frozen=True)
class Issue:
    """一条校验问题。pointer 使用 JSON Pointer 风格路径。"""

    pointer: str
    message: str


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise DuplicateKeyError(key)
        seen.add(key)
    return dict(pairs)


def _reject_non_finite_constant(token: str) -> Any:
    raise ValueError(f"JSON 不允许 {token}；只允许有限数值")


def parse_document(raw: bytes) -> dict[str, Any]:
    """解析图谱文件字节流，拒绝 BOM、重复键、NaN/Infinity 等非法 JSON。"""

    if raw.startswith(b"\xef\xbb\xbf"):
        raise InputError("文件包含 UTF-8 BOM；规范要求 UTF-8 无 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"文件不是合法 UTF-8：{exc}") from exc
    if not text.strip():
        raise InputError("文件为空")

    try:
        document = json.loads(
            text,
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_non_finite_constant,
        )
    except DuplicateKeyError as exc:
        raise InputError(f"JSON 对象存在重复键 {exc.key!r}；规范不允许重复对象键") from exc
    except ValueError as exc:
        raise InputError(f"JSON 语法错误：{exc}") from exc

    if not isinstance(document, dict):
        raise InputError("顶层必须是 JSON 对象")
    return document


def load_document(path: Path) -> dict[str, Any]:
    """读取并解析图谱文件。"""

    return parse_document(path.read_bytes())


def walk(value: Any, pointer: str = "") -> Iterator[tuple[str, Any]]:
    """深度优先遍历 JSON 值，产出 (JSON Pointer, 值)。"""

    stack: list[tuple[str, Any]] = [(pointer, value)]
    while stack:
        current_pointer, current = stack.pop()
        yield current_pointer, current
        if isinstance(current, dict):
            for key, child in current.items():
                stack.append((f"{current_pointer}/{key}", child))
        elif isinstance(current, list):
            for index, child in enumerate(current):
                stack.append((f"{current_pointer}/{index}", child))


def parse_timestamp(value: str) -> datetime:
    """解析规范要求的 UTC RFC 3339 时间（Z 或 +00:00）。"""

    if value.endswith("Z"):
        text = value[:-1]
    else:
        text = value[:-6]  # 去掉 +00:00
    if "." in text:
        head, _, fraction = text.partition(".")
        text = f"{head}.{fraction[:6].ljust(6, '0')}"
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def normalize_label(value: str) -> str:
    """规范化名称/别名：NFC、去首尾空白、连续空白压为一个空格、ASCII A–Z 转小写。"""

    normalized = unicodedata.normalize("NFC", value)
    normalized = " ".join(normalized.split())
    return normalized.translate(ASCII_LOWER)


def _sorted_strings(values: Iterable[str]) -> str:
    return "、".join(sorted(values))


class SemanticChecker:
    """负责 JSON Schema 之外的全部一致性规则。"""

    def __init__(self, document: dict[str, Any], *, require_release: bool = False) -> None:
        self.doc = document
        self.require_release = require_release
        self.issues: list[Issue] = []

        self.chapters: list[dict[str, Any]] = list(document.get("chapters") or [])
        self.sources: list[dict[str, Any]] = list(document.get("sources") or [])
        self.evidence: list[dict[str, Any]] = list(document.get("evidence") or [])
        self.nodes: list[dict[str, Any]] = list(document.get("nodes") or [])
        self.edges: list[dict[str, Any]] = list(document.get("edges") or [])
        self.item_mappings: list[dict[str, Any]] = list(document.get("item_mappings") or [])

        self.chapter_ids = {item.get("id") for item in self.chapters}
        self.source_ids = {item.get("id") for item in self.sources}
        self.evidence_ids = {item.get("id") for item in self.evidence}
        self.node_ids = {item.get("id") for item in self.nodes}
        self.redirects: dict[str, str] = dict(document.get("redirects") or {})

    # ------------------------------------------------------------------ 工具

    def add(self, pointer: str, message: str) -> None:
        self.issues.append(Issue(pointer or "/", message))

    def _node_hint(self, identifier: Any) -> str:
        """节点 ID 不存在时，若它是 redirects 中的旧 ID，给出替换建议。"""

        if isinstance(identifier, str) and identifier in self.redirects:
            return f"（该 ID 是 redirects 中的旧 ID，应改用 {self.redirects[identifier]!r}）"
        return ""

    # ------------------------------------------------------------------ 检查

    def run(self) -> list[Issue]:
        self._check_text_and_numbers()
        self._check_id_uniqueness()
        self._check_chapters()
        self._check_sources()
        self._check_evidence()
        self._check_nodes()
        self._check_edges()
        self._check_item_mappings()
        self._check_redirects()
        self._check_reviews()
        self._check_release()

        unique: dict[tuple[str, str], Issue] = {}
        for issue in self.issues:
            unique.setdefault((issue.pointer, issue.message), issue)
        return sorted(unique.values(), key=lambda item: (item.pointer, item.message))

    def _check_text_and_numbers(self) -> None:
        for pointer, value in walk(self.doc):
            if isinstance(value, bool):
                continue
            if isinstance(value, float) and not math.isfinite(value):
                self.add(pointer, "数值必须是有限值，不允许 NaN/Infinity")
            if isinstance(value, str):
                if unicodedata.normalize("NFC", value) != value:
                    self.add(pointer, "文本必须是 Unicode NFC 形式")
                if value != value.strip():
                    self.add(pointer, "文本首尾不得含空白")

    def _check_id_uniqueness(self) -> None:
        collections = (
            ("chapters", self.chapters),
            ("sources", self.sources),
            ("evidence", self.evidence),
            ("nodes", self.nodes),
            ("edges", self.edges),
        )
        for name, items in collections:
            first_seen: dict[Any, int] = {}
            for index, item in enumerate(items):
                identifier = item.get("id")
                if identifier in first_seen:
                    first = first_seen[identifier]
                    self.add(
                        f"/{name}/{index}/id",
                        f"ID {identifier!r} 与 /{name}/{first}/id 重复；集合内 ID 必须唯一",
                    )
                else:
                    first_seen[identifier] = index

        first_seen: dict[Any, int] = {}
        for index, mapping in enumerate(self.item_mappings):
            identifier = mapping.get("item_id")
            if identifier in first_seen:
                first = first_seen[identifier]
                self.add(
                    f"/item_mappings/{index}/item_id",
                    f"item_id {identifier!r} 与 /item_mappings/{first}/item_id 重复；同版本内必须唯一",
                )
            else:
                first_seen[identifier] = index

    def _check_chapters(self) -> None:
        chapter_by_id = {chapter.get("id"): chapter for chapter in self.chapters}
        sibling_orders: dict[Any, dict[int, int]] = {}

        for index, chapter in enumerate(self.chapters):
            chapter_id = chapter.get("id")
            parent_id = chapter.get("parent_id")
            pointer = f"/chapters/{index}"

            if parent_id is not None:
                if parent_id == chapter_id:
                    self.add(f"{pointer}/parent_id", "章节不得以自身为上级")
                elif parent_id not in chapter_by_id:
                    self.add(f"{pointer}/parent_id", f"上级章节 {parent_id!r} 不存在")

            order = chapter.get("order")
            if isinstance(order, int) and not isinstance(order, bool):
                orders = sibling_orders.setdefault(parent_id, {})
                if order in orders:
                    first = orders[order]
                    self.add(
                        f"{pointer}/order",
                        f"同一上级下 order={order} 与 /chapters/{first}/order 重复",
                    )
                else:
                    orders[order] = index

            # 沿上级链检查是否成环
            seen = [chapter_id]
            parent = parent_id
            while parent is not None and parent in chapter_by_id:
                if parent in seen:
                    self.add(f"{pointer}/parent_id", "章节层级成环")
                    break
                seen.append(parent)
                parent = chapter_by_id[parent].get("parent_id")

    def _check_sources(self) -> None:
        for index, source in enumerate(self.sources):
            pointer = f"/sources/{index}"
            source_type = source.get("source_type")
            uri = source.get("uri")
            sha256 = source.get("sha256")

            if source_type in FILE_SOURCE_TYPES and sha256 is None:
                self.add(f"{pointer}/sha256", f"{source_type} 来源的 sha256 必须非空")
            if source_type == "web" and uri is None:
                self.add(f"{pointer}/uri", "web 来源的 uri 必须为 HTTPS 地址")

            if isinstance(uri, str):
                self._check_uri(pointer, uri)

    def _check_uri(self, pointer: str, uri: str) -> None:
        parts = urlsplit(uri)
        if parts.username is not None or parts.password is not None:
            self.add(f"{pointer}/uri", "URI 不得包含用户名或密码")

        credential_params = sorted(
            name for name, _value in parse_qsl(parts.query, keep_blank_values=True)
            if name.lower() in CREDENTIAL_QUERY_KEYS
        )
        if credential_params:
            self.add(
                f"{pointer}/uri",
                "URI 查询参数疑似包含访问密钥：" + "、".join(credential_params),
            )

        if parts.scheme == "https":
            if not parts.hostname:
                self.add(f"{pointer}/uri", "HTTPS 地址缺少有效 authority")
            return
        if parts.scheme == "asset":
            if not parts.netloc:
                self.add(f"{pointer}/uri", "asset:// 标识缺少有效 authority（资料库标识）")
            if (
                "\\" in parts.netloc + parts.path
                or WINDOWS_ABSOLUTE_PATH.match(parts.path)
                or re.match(r"^[A-Za-z]:", parts.netloc)
            ):
                self.add(f"{pointer}/uri", "asset:// 标识不得使用机器私有绝对路径")
            return
        self.add(f"{pointer}/uri", "uri 只允许 https:// 或 asset:// 形式")

    def _check_evidence(self) -> None:
        for index, item in enumerate(self.evidence):
            pointer = f"/evidence/{index}"
            source_id = item.get("source_id")
            if source_id not in self.source_ids:
                self.add(f"{pointer}/source_id", f"来源 {source_id!r} 不存在")

            locator = item.get("locator") or {}
            page_start = locator.get("page_start")
            page_end = locator.get("page_end")
            if isinstance(page_start, int) and isinstance(page_end, int) and page_start > page_end:
                self.add(
                    f"{pointer}/locator/page_start",
                    f"页码范围无效：page_start={page_start} 大于 page_end={page_end}",
                )

    def _check_nodes(self) -> None:
        for index, node in enumerate(self.nodes):
            pointer = f"/nodes/{index}"
            chapter_id = node.get("chapter")
            if chapter_id not in self.chapter_ids:
                self.add(f"{pointer}/chapter", f"章节 {chapter_id!r} 不存在")

            for evidence_index, evidence_id in enumerate(node.get("evidence_ids") or []):
                if evidence_id not in self.evidence_ids:
                    self.add(
                        f"{pointer}/evidence_ids/{evidence_index}",
                        f"证据 {evidence_id!r} 不存在",
                    )

            if node.get("type") == "formula":
                latex = node.get("formula_latex")
                if not latex:
                    self.add(f"{pointer}/formula_latex", "formula 节点必须提供 formula_latex")
                elif isinstance(latex, str) and (
                    latex.strip().startswith("$") or latex.strip().endswith("$")
                ):
                    self.add(
                        f"{pointer}/formula_latex",
                        "formula_latex 不得含 $ 或 $$ 外层定界符，只存公式本身",
                    )
            elif node.get("formula_latex") is not None:
                self.add(f"{pointer}/formula_latex", "非 formula 节点的 formula_latex 必须为 null")

            self._check_node_labels(pointer, node)

            conditions = list(node.get("conditions") or [])
            if len(set(conditions)) != len(conditions):
                duplicates = sorted({value for value in conditions if conditions.count(value) > 1})
                self.add(f"{pointer}/conditions", f"conditions 存在重复元素：{_sorted_strings(duplicates)}")

    def _check_node_labels(self, pointer: str, node: dict[str, Any]) -> None:
        name = node.get("name")
        aliases = list(node.get("aliases") or [])
        normalized_name = normalize_label(name) if isinstance(name, str) else ""
        seen: dict[str, int] = {}

        for index, alias in enumerate(aliases):
            normalized = normalize_label(alias)
            if normalized == normalized_name:
                self.add(f"{pointer}/aliases/{index}", "别名规范化后与主名称相同")
            elif normalized in seen:
                self.add(
                    f"{pointer}/aliases/{index}",
                    f"别名 {alias!r} 规范化后与 /aliases/{seen[normalized]} 重复",
                )
            else:
                seen[normalized] = index

    def _check_edges(self) -> None:
        relation_keys: dict[tuple[Any, str, str], int] = {}
        prerequisite_pairs: set[tuple[str, str]] = set()
        edge_id_by_pair: dict[tuple[str, str], Any] = {}

        for index, edge in enumerate(self.edges):
            pointer = f"/edges/{index}"
            source = edge.get("source")
            target = edge.get("target")
            relation = edge.get("relation")

            for field, value in (("source", source), ("target", target)):
                if value not in self.node_ids:
                    self.add(
                        f"{pointer}/{field}",
                        f"节点 {value!r} 不存在{self._node_hint(value)}",
                    )

            if source == target:
                self.add(f"{pointer}/target", "关系的 source 与 target 不得相同")

            for evidence_index, evidence_id in enumerate(edge.get("evidence_ids") or []):
                if evidence_id not in self.evidence_ids:
                    self.add(
                        f"{pointer}/evidence_ids/{evidence_index}",
                        f"证据 {evidence_id!r} 不存在",
                    )

            if relation == "related_to" and isinstance(source, str) and isinstance(target, str):
                if source > target:
                    self.add(
                        f"{pointer}/source",
                        "related_to 为无向关系，只存一条且必须按 ASCII ID 升序（source < target）；"
                        f"应写为 source={min(source, target)!r}、target={max(source, target)!r}",
                    )
                key = ("related_to", min(source, target), max(source, target))
            else:
                key = (relation, str(source), str(target))

            if key in relation_keys:
                self.add(
                    f"{pointer}",
                    f"(relation, source, target) 与 /edges/{relation_keys[key]} 重复",
                )
            else:
                relation_keys[key] = index

            if relation == "prerequisite" and isinstance(source, str) and isinstance(target, str):
                pair = (source, target)
                if pair in prerequisite_pairs:
                    self.add(f"{pointer}", f"先修关系 {source}→{target} 重复")
                prerequisite_pairs.add(pair)
                edge_id_by_pair.setdefault(pair, edge.get("id"))

        self._check_prerequisite_graph(prerequisite_pairs, edge_id_by_pair)

    def _check_prerequisite_graph(
        self,
        pairs: set[tuple[str, str]],
        edge_id_by_pair: dict[tuple[str, str], Any],
    ) -> None:
        adjacency: dict[str, set[str]] = {}
        for source, target in pairs:
            adjacency.setdefault(source, set()).add(target)

        # 1) 无环（Kahn 拓扑排序）
        # 节点集合以 nodes 与实际出现的端点的并集为准，避免重复 ID 等结构问题导致漏检或崩溃。
        all_ids = set(self.node_ids)
        for source, target in pairs:
            all_ids.add(source)
            all_ids.add(target)
        indegree = {node_id: 0 for node_id in all_ids}
        for _source, target in pairs:
            indegree[target] += 1
        queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
        processed = 0
        while queue:
            current = queue.popleft()
            processed += 1
            for nxt in adjacency.get(current, ()):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if processed < len(indegree):
            cycle_nodes = sorted(node_id for node_id, degree in indegree.items() if degree > 0)
            self.add(
                "/edges",
                "prerequisite 子图存在环，涉及节点："
                + "、".join(cycle_nodes[:10])
                + ("…" if len(cycle_nodes) > 10 else ""),
            )

        # 2) 无冗余传递边：A→C 已由 A→…→C 表达时，不得再存直接边
        for source, target in sorted(pairs):
            path = self._shortest_path(adjacency, source, target, banned=(source, target))
            if path is not None:
                edge_id = edge_id_by_pair.get((source, target))
                label = f"（edge id={edge_id!r}）" if edge_id else ""
                self.add(
                    "/edges",
                    f"先修关系 {source}→{target}{label} 是冗余直接边，已被路径 "
                    f"{' → '.join(path)} 表达",
                )

    @staticmethod
    def _shortest_path(
        adjacency: dict[str, set[str]],
        start: str,
        goal: str,
        *,
        banned: tuple[str, str] | None = None,
    ) -> list[str] | None:
        """返回 start 到 goal 的一条路径（不含被禁用的那条直接边）。"""

        parents: dict[str, str | None] = {start: None}
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            for nxt in adjacency.get(current, ()):
                if banned is not None and (current, nxt) == banned:
                    continue
                if nxt in parents:
                    continue
                parents[nxt] = current
                if nxt == goal:
                    path = [nxt]
                    cursor = current
                    while cursor is not None:
                        path.append(cursor)
                        cursor = parents[cursor]
                    return list(reversed(path))
                queue.append(nxt)
        return None

    def _check_item_mappings(self) -> None:
        for index, mapping in enumerate(self.item_mappings):
            pointer = f"/item_mappings/{index}"
            for skill_index, skill_id in enumerate(mapping.get("skill_ids") or []):
                if skill_id not in self.node_ids:
                    self.add(
                        f"{pointer}/skill_ids/{skill_index}",
                        f"节点 {skill_id!r} 不存在{self._node_hint(skill_id)}",
                    )
            for evidence_index, evidence_id in enumerate(mapping.get("evidence_ids") or []):
                if evidence_id not in self.evidence_ids:
                    self.add(
                        f"{pointer}/evidence_ids/{evidence_index}",
                        f"证据 {evidence_id!r} 不存在",
                    )

    def _check_redirects(self) -> None:
        for old_id, new_id in self.redirects.items():
            if old_id in self.node_ids:
                self.add("/redirects", f"旧 ID {old_id!r} 不得同时存在于 nodes 中")
            if old_id == new_id:
                self.add("/redirects", f"旧 ID {old_id!r} 不得重定向到自身")
            if new_id in self.redirects:
                self.add("/redirects", f"重定向不得成链：{old_id!r} → {new_id!r} → …")
            elif new_id not in self.node_ids:
                self.add("/redirects", f"重定向目标 {new_id!r} 不在 nodes 中")

    def _check_reviews(self) -> None:
        try:
            created_at = parse_timestamp(self.doc["created_at"])
        except (KeyError, TypeError, ValueError):
            self.add("/created_at", "无法解析 created_at 时间")
            return

        for pointer, review in self._iter_reviews():
            status = review.get("status")
            reviewer_id = review.get("reviewer_id")
            reviewed_at = review.get("reviewed_at")
            note = review.get("note")

            if status == "pending":
                if reviewer_id is not None:
                    self.add(f"{pointer}/reviewer_id", "pending 状态下 reviewer_id 必须为 null")
                if reviewed_at is not None:
                    self.add(f"{pointer}/reviewed_at", "pending 状态下 reviewed_at 必须为 null")
            else:
                if reviewer_id is None:
                    self.add(f"{pointer}/reviewer_id", f"{status} 状态下 reviewer_id 必须非空")
                if reviewed_at is None:
                    self.add(f"{pointer}/reviewed_at", f"{status} 状态下 reviewed_at 必须非空")
                else:
                    try:
                        reviewed = parse_timestamp(reviewed_at)
                    except ValueError:
                        self.add(f"{pointer}/reviewed_at", "无法解析 reviewed_at 时间")
                    else:
                        if reviewed > created_at:
                            self.add(f"{pointer}/reviewed_at", "审核时间不得晚于顶层 created_at")
                if status == "rejected" and not note:
                    self.add(f"{pointer}/note", "rejected 状态的 note 必须非空")

    def _iter_reviews(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for collection_name, collection in (
            ("nodes", self.nodes),
            ("edges", self.edges),
            ("item_mappings", self.item_mappings),
        ):
            for index, item in enumerate(collection):
                review = item.get("review")
                if isinstance(review, dict):
                    yield f"/{collection_name}/{index}/review", review

    def _check_release(self) -> None:
        status = self.doc.get("status")
        if self.require_release and status != "released":
            self.add("/status", f"文件 status 为 {status!r}；--release 仅接受 status=released 的定稿文件")
        if status != "released":
            return

        for pointer, review in self._iter_reviews():
            if review.get("status") != "approved":
                self.add(pointer, "released 文件的节点、关系和题目映射必须全部为 approved")

        endpoints: set[Any] = set()
        for edge in self.edges:
            endpoints.add(edge.get("source"))
            endpoints.add(edge.get("target"))
        for index, node in enumerate(self.nodes):
            if node.get("id") not in endpoints:
                self.add(f"/nodes/{index}", f"released 文件不得有孤立节点：{node.get('id')!r}")


def schema_issues(validator: Draft202012Validator, document: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    for error in validator.iter_errors(document):
        pointer = "/" + "/".join(str(part) for part in error.absolute_path)
        message = error.message
        if len(message) > 400:
            message = message[:397] + "…"
        issues.append(Issue(pointer, message))
    unique: dict[tuple[str, str], Issue] = {}
    for issue in issues:
        unique.setdefault((issue.pointer, issue.message), issue)
    return sorted(unique.values(), key=lambda item: (item.pointer, item.message))


def _print_issues(graph: Path, issues: list[Issue]) -> None:
    print(f"[FAIL] {graph}: 发现 {len(issues)} 处问题")
    for issue in issues[:MAX_ERRORS_SHOWN]:
        print(f"  {issue.pointer}: {issue.message}")
    if len(issues) > MAX_ERRORS_SHOWN:
        print(f"  … 另有 {len(issues) - MAX_ERRORS_SHOWN} 处未显示")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_graph.py",
        description="校验知识图谱文件是否符合《知识图谱文件格式规范 v1.0》。",
    )
    parser.add_argument("graph", type=Path, help="待校验的 graph.json")
    parser.add_argument(
        "--release",
        action="store_true",
        help="仅接受最终定稿状态（status=released），并检查 released 约束",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="graph.schema.json 路径；默认使用本脚本同目录下的文件",
    )
    parser.add_argument("--version", action="version", version="validate_graph.py 1.0.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    # 输出固定使用 UTF-8，避免在 Windows 重定向/CI 日志里按本地代码页编码导致乱码。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)

    schema_path = args.schema or Path(__file__).resolve().with_name("graph.schema.json")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"[ERROR] 无法读取 Schema 文件 {schema_path}: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Schema 文件不是合法 JSON: {exc}", file=sys.stderr)
        return 2

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        print(f"[ERROR] Schema 文件自身不合法: {exc.message}", file=sys.stderr)
        return 2

    validator = Draft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )

    try:
        document = load_document(args.graph)
    except OSError as exc:
        print(f"[ERROR] 无法读取文件 {args.graph}: {exc}", file=sys.stderr)
        return 2
    except InputError as exc:
        print(f"[FAIL] {args.graph}: {exc}")
        return 1

    issues = schema_issues(validator, document)
    if issues:
        _print_issues(args.graph, issues)
        return 1

    checker = SemanticChecker(document, require_release=args.release)
    issues = checker.run()
    if issues:
        _print_issues(args.graph, issues)
        return 1

    counts = (
        f"{len(checker.nodes)} 个节点 / {len(checker.edges)} 条关系 / "
        f"{len(checker.item_mappings)} 条题目映射"
    )
    print(f"[PASS] {args.graph}: {counts}, status={document.get('status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
