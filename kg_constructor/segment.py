"""教材分块：识别标题层级，产出章节树与文本段。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .ids import chapter_id
from .readers import PAGE_MARKER

PAGE_RE = re.compile(r"\[\[PAGE:(\d+)\]\]")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百零〇\d]+[章节]\s*(.+?)\s*$")
NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+(.+?)\s*$")
SECTION_RE = re.compile(r"^第[一二三四五六七八九十百零〇\d]+节\s*(.+?)\s*$")


@dataclass
class Section:
    index: int
    chapter_id: str
    chapter_path: str
    title: str
    text: str
    page_start: int | None
    page_end: int | None
    order: int


@dataclass
class Chapter:
    id: str
    title: str
    parent_id: str | None
    order: int
    level: int
    path: str
    children: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "parent_id": self.parent_id,
            "order": self.order,
        }


@dataclass
class Segmentation:
    chapters: list[Chapter]
    sections: list[Section]


def _heading_of(line: str) -> tuple[int, str] | None:
    match = MD_HEADING_RE.match(line)
    if match:
        level = len(match.group(1))
        title = match.group(2).strip()
        chapter_match = re.match(r"^第[一二三四五六七八九十百零〇\d]+章\s*(.+)$", title)
        section_match = re.match(r"^第[一二三四五六七八九十百零〇\d]+节\s*(.+)$", title)
        if chapter_match:
            title = chapter_match.group(1).strip()
        elif section_match:
            title = section_match.group(1).strip()
        return level, title
    match = CHAPTER_RE.match(line)
    if match and len(line) <= 60:
        return 1, match.group(1).strip()
    match = SECTION_RE.match(line)
    if match and len(line) <= 60:
        return 2, match.group(1).strip()
    match = NUMBERED_RE.match(line)
    if match and len(line) <= 80:
        title = f"{match.group(1)} {match.group(2)}".strip()
        level = min(6, match.group(1).count(".") + 1)
        return level, title
    return None


def segment(text: str, fallback_title: str = "全文") -> Segmentation:
    lines = text.split("\n")
    chapters: list[Chapter] = []
    sections: list[Section] = []
    used_ids: set[str] = set()

    stack: list[Chapter] = []
    counters: dict[str | None, int] = {}
    current: Chapter | None = None
    buffer: list[str] = []
    buffer_pages: list[int] = []
    current_page: int | None = None
    section_index = 0

    def flush() -> None:
        nonlocal buffer, buffer_pages, section_index
        body = "\n".join(buffer).strip()
        buffer = []
        pages = buffer_pages
        buffer_pages = []
        if not body or current is None:
            return
        section_index += 1
        sections.append(
            Section(
                index=section_index,
                chapter_id=current.id,
                chapter_path=current.path,
                title=current.title,
                text=body,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                order=len([item for item in sections if item.chapter_id == current.id]),
            )
        )

    def open_chapter(level: int, title: str) -> Chapter:
        nonlocal stack
        while stack and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        parent_key = parent.id if parent else None
        order = counters.get(parent_key, 0)
        counters[parent_key] = order + 1
        identifier = chapter_id(title, parent.id if parent else None, order, used_ids)
        path = f"{parent.path} / {title}" if parent else title
        chapter = Chapter(identifier, title, parent.id if parent else None, order, level, path)
        chapters.append(chapter)
        if parent:
            parent.children.append(identifier)
        stack.append(chapter)
        return chapter

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        page_match = PAGE_RE.search(line)
        if page_match:
            current_page = int(page_match.group(1))
            line = PAGE_RE.sub("", line).strip()

        heading = _heading_of(line) if line.strip() else None
        if heading:
            flush()
            current = open_chapter(*heading)
            if current_page is not None:
                buffer_pages.append(current_page)
            continue

        if not line.strip():
            if buffer:
                buffer.append("")
            continue

        buffer.append(line)
        if current_page is not None:
            buffer_pages.append(current_page)

    flush()

    if not chapters:
        current = open_chapter(1, fallback_title)
        # 没有标题时，flush 已经在循环末尾执行过，这里单独造一个全文段
        body = text.strip()
        if body:
            sections.append(
                Section(
                    index=1,
                    chapter_id=current.id,
                    chapter_path=current.path,
                    title=current.title,
                    text=body,
                    page_start=None,
                    page_end=None,
                    order=0,
                )
            )

    if not sections:
        # 标题存在但正文为空：至少保留一个空段，避免下游空图
        chapter = chapters[0]
        sections.append(
            Section(
                index=1,
                chapter_id=chapter.id,
                chapter_path=chapter.path,
                title=chapter.title,
                text="（未识别到正文内容）",
                page_start=None,
                page_end=None,
                order=0,
            )
        )

    return Segmentation(chapters=chapters, sections=sections)
