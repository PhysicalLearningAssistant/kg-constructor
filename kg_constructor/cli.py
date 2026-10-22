"""命令行入口：python -m kg_constructor build 教材.md -o graph.json"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .build import build_graph
from .extract import extract_candidates
from .readers import read_textbook
from .segment import segment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kg_constructor",
        description="从教材粗筛电磁学知识图谱（输出符合规范 v1.0 的 draft graph.json）。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="读取教材并生成初抽图谱")
    build.add_argument("textbook", type=Path, help="教材文件（.md/.txt/.docx/.pdf）")
    build.add_argument("-o", "--output", type=Path, default=Path("graph.json"), help="输出 graph.json 路径")
    build.add_argument("--title", default=None, help="教材标题（默认取文件名）")
    build.add_argument("--course-name", default=None, help="课程名称，默认“大学电磁学”")
    build.add_argument("--graph-id", default="electromagnetism_university", help="图谱系列 ID")
    build.add_argument("--version", default="0.1.0", help="图谱数据版本")
    build.add_argument("--max-per-section", type=int, default=10, help="每节最多抽取的候选节点数")
    build.add_argument("--max-nodes", type=int, default=150, help="整本教材最多节点数")
    build.add_argument("--validate", action="store_true", help="生成后调用 validate_graph.py 校验")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "build":
        return 2

    try:
        loaded = read_textbook(args.textbook, title=args.title)
        segmentation = segment(loaded.text, fallback_title=loaded.title)
        candidates = extract_candidates(segmentation.sections, max_per_section=args.max_per_section)
        candidates = candidates[: args.max_nodes]
        graph = build_graph(
            loaded,
            segmentation,
            candidates,
            course_name=args.course_name,
            graph_id=args.graph_id,
            version=args.version,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"[OK] {output}：{len(graph['nodes'])} 个节点 / {len(graph['edges'])} 条关系 / "
        f"{len(graph['chapters'])} 个章节"
    )

    if args.validate:
        validator = Path(__file__).resolve().parents[1] / "validate_graph.py"
        if not validator.exists():
            print("[WARN] 未找到 validate_graph.py，跳过校验", file=sys.stderr)
            return 0
        result = subprocess.run([sys.executable, str(validator), str(output)], check=False)
        return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
