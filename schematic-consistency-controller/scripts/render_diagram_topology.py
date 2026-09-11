#!/usr/bin/env python3
"""把已规范化的当前框图拓扑使用 Graphviz 渲染为 DOT 和 SVG。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def esc(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def port_text(port: dict[str, Any]) -> str:
    direction = str(port.get("direction") or "UNKNOWN")
    name = str(port.get("name") or "(未命名)")
    protocol = str(port.get("protocol") or "")
    suffix = f" [{direction}]"
    if protocol:
        suffix += f" {protocol}"
    return name + suffix


def make_dot(state: dict[str, Any]) -> str:
    target = state.get("target") or {}
    lines = [
        "digraph diagram_topology {",
        "  graph [rankdir=LR, bgcolor=\"white\", pad=0.25, nodesep=0.55, ranksep=0.9, splines=ortho];",
        "  node [shape=box, style=\"rounded,filled\", fillcolor=\"#E8F0FE\", color=\"#5F6368\", fontname=\"Microsoft YaHei\", fontsize=10, margin=\"0.14,0.10\"];",
        "  edge [color=\"#5F6368\", fontcolor=\"#3C4043\", fontname=\"Microsoft YaHei\", fontsize=9, arrowsize=0.7];",
        f'  label="{esc(target.get("graph_name") or "当前框图拓扑")}\\nGraph {esc(target.get("graph_id"))}";',
        "  labelloc=t; fontsize=14;",
    ]
    node_ids: dict[str, str] = {}
    for index, block_id in enumerate(target.get("ordered_blocks") or target.get("blocks", {}).keys(), 1):
        block = target.get("blocks", {}).get(str(block_id), {})
        node_id = f"b{index}"
        node_ids[str(block_id)] = node_id
        label = [str(block.get("name") or "(未命名Block)"), f"ID: {target.get('graph_id')}-{block_id}"]
        if block.get("model"):
            label.append(f"Model: {block['model']}")
        if block.get("business_code"):
            label.append(f"Code: {block['business_code']}")
        ports = [target.get("ports", {}).get(str(pid), {}) for pid in block.get("ports") or []]
        label.extend(port_text(port) for port in ports)
        warning = any(
            issue.get("block_id") == str(block_id)
            or str(issue.get("object_id") or "") in {str(pid) for pid in block.get("ports") or []}
            for issue in target.get("issues") or []
        )
        fill = "#FFF4CE" if warning else "#E8F0FE"
        stroke = "#B06000" if warning else "#5F6368"
        node_label = esc("\n".join(label))
        lines.append(f'  {node_id} [label="{node_label}", fillcolor="{fill}", color="{stroke}"];')

    for edge_id, edge in target.get("edges", {}).items():
        source_port = target.get("ports", {}).get(str(edge.get("source_port_id")), {})
        target_port = target.get("ports", {}).get(str(edge.get("target_port_id")), {})
        source = node_ids.get(str(source_port.get("block_id") or ""))
        destination = node_ids.get(str(target_port.get("block_id") or ""))
        if not source or not destination:
            continue
        valid = edge.get("status") != "INVALID_TARGET"
        color = "#5F6368" if valid else "#C5221F"
        style = "solid" if valid else "dashed"
        label = f"{source_port.get('name') or '?'} → {target_port.get('name') or '?'}"
        if edge.get("name"):
            label += f"\n{edge['name']}"
        lines.append(f'  {source} -> {destination} [label="{esc(label)}", color="{color}", fontcolor="{color}", style="{style}", tooltip="wire:{esc(edge_id)}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render(dot_path: Path, svg_path: Path) -> str:
    executable = shutil.which("dot")
    if not executable:
        raise ValueError("未找到 Graphviz dot，不能完成框图拓扑 SVG 渲染")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [executable, "-Tsvg", str(dot_path), "-o", str(svg_path)],
        text=True, capture_output=True, check=False,
    )
    if completed.returncode:
        raise ValueError(f"Graphviz 渲染失败：{completed.stderr.strip()}")
    if not svg_path.is_file() or "<svg" not in svg_path.read_text(encoding="utf-8", errors="ignore")[:4096]:
        raise ValueError("Graphviz 未生成有效 SVG")
    return executable


def build(args: argparse.Namespace) -> dict[str, Any]:
    state = load(args.state)
    if not state.get("target") or not state.get("analysis_id"):
        raise ValueError("状态文件缺少已规范化的框图拓扑")
    dot_path = Path(args.dot_output).resolve()
    svg_path = Path(args.svg_output).resolve()
    dot_path.parent.mkdir(parents=True, exist_ok=True)
    dot_path.write_text(make_dot(state), encoding="utf-8")
    executable = render(dot_path, svg_path)
    target = state["target"]
    result = {
        "schema_version": 1,
        "analysis_id": state["analysis_id"],
        "diagram_sha256": state.get("diagram_sha256"),
        "renderer": "graphviz-dot",
        "renderer_executable": executable,
        "dot_file": str(dot_path),
        "svg_file": str(svg_path),
        "dot_sha256": digest(dot_path),
        "svg_sha256": digest(svg_path),
        "counts": {
            "blocks": len(target.get("blocks", {})),
            "ports": len(target.get("ports", {})),
            "edges": len(target.get("edges", {})),
            "issues": len(target.get("issues", [])),
        },
    }
    write_json(args.result_output, result)
    return result


def self_test() -> None:
    state = {"analysis_id": "T", "diagram_sha256": "abc", "target": {
        "graph_id": 0, "graph_name": "Demo", "ordered_blocks": ["1", "2"],
        "blocks": {
            "1": {"name": "MCU", "model": "MCU", "business_code": "A", "ports": ["11"]},
            "2": {"name": "Sensor", "model": "SENSOR", "business_code": "B", "ports": ["21"]},
        },
        "ports": {
            "11": {"name": "I2C", "direction": "OUT", "protocol": "I2C", "block_id": "1"},
            "21": {"name": "I2C", "direction": "IN", "protocol": "I2C", "block_id": "2"},
        },
        "edges": {"31": {"source_port_id": "11", "target_port_id": "21", "name": "I2C", "status": "PENDING"}},
        "issues": [],
    }}
    dot = make_dot(state)
    assert "digraph diagram_topology" in dot
    assert "MCU" in dot and "Sensor" in dot and "I2C → I2C" in dot
    assert dot.count(" -> ") == 1
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "topology.dot"
        path.write_text(dot, encoding="utf-8")
        assert path.stat().st_size > 0
    print(json.dumps({"self_test": "PASS", "tests": 4, "graphviz_available": bool(shutil.which('dot'))}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "self-test"])
    parser.add_argument("--state")
    parser.add_argument("--dot-output")
    parser.add_argument("--svg-output")
    parser.add_argument("--result-output")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return 0
        if not all([args.state, args.dot_output, args.svg_output, args.result_output]):
            raise ValueError("build 需要 --state、--dot-output、--svg-output 和 --result-output")
        print(json.dumps(build(args), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
