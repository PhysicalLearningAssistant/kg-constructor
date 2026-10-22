"""把候选节点组装成符合《知识图谱文件格式规范 v1.0》的 draft 图谱。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote

from .extract import Candidate
from .ids import node_id, normalize_name
from .readers import LoadedText
from .segment import Segmentation


@dataclass
class Node:
    id: str
    name: str
    type: str
    description: str
    chapter: str
    aliases: list[str]
    formula_latex: str | None
    conditions: list[str]
    evidence_ids: list[str]
    section_index: int
    section_title: str
    quote: str
    page_start: int | None
    page_end: int | None


@dataclass
class EdgeDraft:
    source: str
    target: str
    relation: str
    description: str
    evidence_ids: list[str] = field(default_factory=list)


def _pending_review() -> dict:
    return {"status": "pending", "reviewer_id": None, "reviewed_at": None, "note": None}


def _clean_aliases(name: str, aliases: list[str]) -> list[str]:
    normalized_name = normalize_name(name)
    result: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        alias = alias.strip()
        if not alias:
            continue
        key = normalize_name(alias)
        if key == normalized_name or key in seen:
            continue
        seen.add(key)
        result.append(alias)
    return result


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _has_path(adjacency: dict[str, set[str]], start: str, goal: str) -> bool:
    if start == goal:
        return True
    stack = [start]
    visited = {start}
    while stack:
        current = stack.pop()
        for nxt in adjacency.get(current, ()):
            if nxt == goal:
                return True
            if nxt not in visited:
                visited.add(nxt)
                stack.append(nxt)
    return False


def _reachable(adjacency: dict[str, set[str]], start: str, goal: str) -> bool:
    return _has_path(adjacency, start, goal)


def _build_nodes(candidates: list[Candidate], evidence_prefix: str = "ev") -> tuple[list[Node], list[dict]]:
    used_ids: set[str] = set()
    nodes: list[Node] = []
    evidence: list[dict] = []

    for index, candidate in enumerate(candidates, start=1):
        identifier = node_id(candidate.name, used_ids)
        evidence_id = f"{evidence_prefix}_{index:04d}"
        quote = (candidate.quote or candidate.description or candidate.name).strip()[:4000]
        section = candidate.section
        evidence.append(
            {
                "id": evidence_id,
                "source_id": "src_textbook",
                "locator": {
                    "section": section.chapter_path or section.title,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                    "anchor": f"sec_{section.index:03d}_kp_{index:03d}",
                },
                "quote": quote,
                "rag_ref": None,
            }
        )
        nodes.append(
            Node(
                id=identifier,
                name=candidate.name,
                type=candidate.type,
                description=(candidate.description or quote or candidate.name)[:8000],
                chapter=section.chapter_id,
                aliases=_clean_aliases(candidate.name, candidate.aliases),
                formula_latex=candidate.formula_latex if candidate.type == "formula" else None,
                conditions=_unique(candidate.conditions),
                evidence_ids=[evidence_id],
                section_index=section.index,
                section_title=section.chapter_path,
                quote=quote,
                page_start=section.page_start,
                page_end=section.page_end,
            )
        )
    return nodes, evidence


def _node_index(nodes: list[Node]) -> tuple[dict[str, Node], dict[int, list[Node]]]:
    by_name = {node.name: node for node in nodes}
    by_section: dict[int, list[Node]] = {}
    for node in nodes:
        by_section.setdefault(node.section_index, []).append(node)
    return by_name, by_section


def _append_edge(
    edges: list[EdgeDraft],
    seen: set[tuple[str, str, str]],
    source: Node,
    target: Node,
    relation: str,
    description: str,
) -> None:
    if source.id == target.id:
        return
    if relation == "related_to":
        first, second = sorted((source.id, target.id))
        key = ("related_to", first, second)
        source_id, target_id = first, second
    else:
        key = (relation, source.id, target.id)
        source_id, target_id = source.id, target.id
    if key in seen:
        return
    seen.add(key)
    evidence_id = target.evidence_ids[0] if target.evidence_ids else source.evidence_ids[0]
    edges.append(
        EdgeDraft(
            source=source_id,
            target=target_id,
            relation=relation,
            description=description,
            evidence_ids=[evidence_id],
        )
    )


def _candidate_edges(nodes: list[Node]) -> list[EdgeDraft]:
    by_name, by_section = _node_index(nodes)
    edges: list[EdgeDraft] = []
    seen: set[tuple[str, str, str]] = set()

    # 1) 公式节点：由同节的定律推导出来
    for node in nodes:
        if node.type != "formula":
            continue
        laws = [
            law
            for law in nodes
            if law.type == "law"
            and law.section_index == node.section_index
            and law.name in (node.name or "")
        ]
        if not laws:
            laws = [
                law
                for law in nodes
                if law.type == "law" and law.section_index <= node.section_index
            ][-1:]
        for law in laws:
            _append_edge(
                edges,
                seen,
                law,
                node,
                "derives",
                f"{node.name}由{law.name}导出。",
            )

    # 2) 描述中提到的节点 → 先修关系
    for target in nodes:
        if target.type == "formula":
            continue
        for source in nodes:
            if source.id == target.id or source.name == target.name:
                continue
            if source.name and source.name in target.description:
                _append_edge(
                    edges,
                    seen,
                    source,
                    target,
                    "prerequisite",
                    f"{source.name}是学习{target.name}的先修知识。",
                )

    # 3) 同句共现 → 一般关联
    by_quote: dict[tuple[int, str], list[Node]] = {}
    for node in nodes:
        by_quote.setdefault((node.section_index, node.quote), []).append(node)
    for group in by_quote.values():
        for i, first in enumerate(group):
            for second in group[i + 1 :]:
                if (
                    first.name
                    and second.name
                    and first.name in first.quote
                    and second.name in first.quote
                ):
                    _append_edge(
                        edges,
                        seen,
                        first,
                        second,
                        "related_to",
                        f"{first.name}与{second.name}在教材同一句中共同出现。",
                    )

    # 4) 避免孤立节点：同节内连一条 related_to，实在没有就找最近的节点
    degree: dict[str, int] = {node.id: 0 for node in nodes}
    for edge in edges:
        degree[edge.source] = degree.get(edge.source, 0) + 1
        degree[edge.target] = degree.get(edge.target, 0) + 1

    for node in nodes:
        if degree.get(node.id, 0) > 0:
            continue
        siblings = [item for item in by_section.get(node.section_index, []) if item.id != node.id]
        if not siblings:
            siblings = [item for item in nodes if item.id != node.id]
        if not siblings:
            continue
        nearest = min(siblings, key=lambda item: abs(item.section_index - node.section_index))
        _append_edge(
            edges,
            seen,
            node,
            nearest,
            "related_to",
            f"{node.name}与{nearest.name}在教材中相邻出现。",
        )
        degree[node.id] = degree.get(node.id, 0) + 1
        degree[nearest.id] = degree.get(nearest.id, 0) + 1

    return edges


def _prune_prerequisite(edges: list[EdgeDraft]) -> list[EdgeDraft]:
    """先修子图去环 + 传递归约。"""

    prerequisite = [edge for edge in edges if edge.relation == "prerequisite"]
    others = [edge for edge in edges if edge.relation != "prerequisite"]

    adjacency: dict[str, set[str]] = {}
    accepted: list[EdgeDraft] = []
    for edge in prerequisite:
        # 加边前判断是否成环
        if _has_path(adjacency, edge.target, edge.source):
            continue
        adjacency.setdefault(edge.source, set()).add(edge.target)
        accepted.append(edge)

    # 传递归约：若去掉某条边仍能从 source 到达 target，则删除
    final: list[EdgeDraft] = []
    for edge in accepted:
        adjacency[edge.source].discard(edge.target)
        if not _reachable(adjacency, edge.source, edge.target):
            final.append(edge)
        adjacency[edge.source].add(edge.target)

    return final + others


def build_graph(
    loaded: LoadedText,
    segmentation: Segmentation,
    candidates: list[Candidate],
    *,
    course_name: str | None = None,
    graph_id: str = "electromagnetism_university",
    version: str = "0.1.0",
) -> dict:
    nodes, evidence = _build_nodes(candidates)
    edges = _prune_prerequisite(_candidate_edges(nodes))

    if not nodes:
        raise ValueError("没有从教材中抽到任何候选知识点，请检查教材内容或标题格式")

    source_uri = "asset://kg-constructor/" + quote(loaded.path.name)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    node_dicts = [
        {
            "id": node.id,
            "name": node.name,
            "type": node.type,
            "description": node.description,
            "chapter": node.chapter,
            "aliases": node.aliases,
            "formula_latex": node.formula_latex,
            "conditions": node.conditions,
            "evidence_ids": node.evidence_ids,
            "review": _pending_review(),
            "extensions": {},
        }
        for node in nodes
    ]

    edge_dicts = [
        {
            "id": f"edge_{index:04d}",
            "source": edge.source,
            "target": edge.target,
            "relation": edge.relation,
            "description": edge.description[:2000],
            "evidence_ids": edge.evidence_ids,
            "review": _pending_review(),
            "extensions": {},
        }
        for index, edge in enumerate(edges, start=1)
    ]

    return {
        "schema_version": "1.0.0",
        "graph_id": graph_id,
        "version": version,
        "status": "draft",
        "created_at": created_at,
        "course": {
            "id": "university_electromagnetism",
            "name": course_name or "大学电磁学",
            "language": "zh-CN",
        },
        "chapters": [chapter.as_dict() for chapter in segmentation.chapters],
        "sources": [
            {
                "id": "src_textbook",
                "title": loaded.title,
                "edition": "未注明",
                "source_type": loaded.source_type,
                "uri": source_uri,
                "sha256": loaded.sha256,
            }
        ],
        "evidence": evidence,
        "nodes": node_dicts,
        "edges": edge_dicts,
        "item_mappings": [],
        "redirects": {},
        "extensions": {"kg.constructor": "heuristic-v0.1"},
    }
