#!/usr/bin/env python3
"""从一致性状态和显式 Block 判定生成 Graphviz Block 差异图。"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


OPERATIONS = {"KEEP", "ADD", "MODIFY", "DELETE", "UNRESOLVED"}
COLORS = {
    "KEEP": ("#E8F0FE", "#5F6368"),
    "ADD": ("#D9F7E8", "#188038"),
    "MODIFY": ("#FFF4CE", "#B06000"),
    "DELETE": ("#FCE8E6", "#C5221F"),
    "UNRESOLVED": ("#F1F3F4", "#80868B"),
}
CN = {"KEEP": "保留", "ADD": "新增", "MODIFY": "变更", "DELETE": "删除", "UNRESOLVED": "待确认"}


def load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def esc(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def normalize_operation(value: Any) -> str:
    aliases = {"新增": "ADD", "增加": "ADD", "变更": "MODIFY", "修改": "MODIFY", "删除": "DELETE", "保留": "KEEP", "待确认": "UNRESOLVED"}
    operation = aliases.get(str(value or "").strip(), str(value or "").strip().upper())
    if operation not in OPERATIONS:
        raise ValueError(f"不支持的 Block 操作：{value}")
    return operation


def normalize(state: dict[str, Any], decisions: Any | None) -> dict[str, Any]:
    target = state.get("target") or {}
    raw = decisions or {}
    if isinstance(raw, list):
        raw = {"blocks": raw}
    if not isinstance(raw, dict):
        raise ValueError("Block 差异判定必须是对象或数组")
    explicit: dict[str, dict[str, Any]] = {}
    for item in raw.get("blocks") or []:
        block_id = str(item.get("block_id") or "")
        if not block_id or block_id not in target.get("blocks", {}):
            raise ValueError(f"Block 差异引用了不存在的当前框图 Block：{block_id}")
        if block_id in explicit:
            raise ValueError(f"Block 差异重复：{block_id}")
        explicit[block_id] = item

    blocks = []
    for block_id in target.get("ordered_blocks") or target.get("blocks", {}).keys():
        block = target["blocks"][str(block_id)]
        selected = block.get("selected") or {}
        item = explicit.get(str(block_id), {})
        hinted = item.get("operation") or selected.get("operation") or selected.get("change_type")
        operation = normalize_operation(hinted) if hinted else ("KEEP" if block.get("status") == "SELECTED" else "UNRESOLVED")
        if operation in {"ADD", "MODIFY"} and not (item.get("reason") or selected.get("difference_reason")):
            raise ValueError(f"Block {block_id} 的 {operation} 判定缺少 reason")
        evidence = item.get("evidence") or selected.get("evidence") or []
        if operation in {"ADD", "MODIFY"} and not evidence:
            raise ValueError(f"Block {block_id} 的 {operation} 判定缺少 evidence")
        blocks.append({
            "node_id": f"block:{block_id}", "block_id": str(block_id),
            "block_identity": f"{target.get('graph_id')}-{block_id}",
            "name": str(block.get("name") or ""), "code": str(block.get("business_code") or ""),
            "operation": operation,
            "refdes": str(item.get("refdes") or selected.get("refdes") or selected.get("cbb_id") or ""),
            "reason": str(item.get("reason") or selected.get("difference_reason") or ""),
            "evidence": list(evidence), "origin": "TARGET_DIAGRAM",
        })

    for item in raw.get("legacy_blocks") or []:
        operation = normalize_operation(item.get("operation"))
        if operation != "DELETE":
            raise ValueError("legacy_blocks 只用于表达旧原理图中确认删除的功能块")
        if item.get("confirmed_functional_removal") is not True:
            raise ValueError("旧原理图功能块删除必须 confirmed_functional_removal=true")
        legacy_id = str(item.get("legacy_id") or item.get("refdes") or "")
        if not legacy_id or not item.get("reason") or not item.get("evidence"):
            raise ValueError("删除 Block 必须包含 legacy_id/refdes、reason 和 evidence")
        blocks.append({
            "node_id": f"legacy:{legacy_id}", "block_id": "", "block_identity": legacy_id,
            "name": str(item.get("name") or legacy_id), "code": str(item.get("code") or ""),
            "operation": "DELETE", "refdes": str(item.get("refdes") or ""),
            "reason": str(item["reason"]), "evidence": list(item["evidence"]),
            "origin": "OLD_SCHEMATIC_ONLY",
        })

    by_block = {item["block_id"]: item for item in blocks if item["block_id"]}
    edge_explicit = {str(item.get("edge_id")): item for item in raw.get("edges") or []}
    edges = []
    for edge_id, edge in target.get("edges", {}).items():
        source_port = target.get("ports", {}).get(str(edge.get("source_port_id")), {})
        target_port = target.get("ports", {}).get(str(edge.get("target_port_id")), {})
        source_block = str(source_port.get("block_id") or "")
        target_block = str(target_port.get("block_id") or "")
        if source_block not in by_block or target_block not in by_block:
            continue
        item = edge_explicit.get(str(edge_id), {})
        if item.get("operation"):
            operation = normalize_operation(item["operation"])
        elif edge.get("status") == "VERIFIED":
            operation = "KEEP"
        elif edge.get("status") == "CONNECTION_MISSING":
            operation = "ADD"
        else:
            operation = "UNRESOLVED"
        edges.append({
            "edge_id": str(edge_id), "source_block_id": source_block, "target_block_id": target_block,
            "source_port": str(source_port.get("name") or ""), "target_port": str(target_port.get("name") or ""),
            "operation": operation, "verification_status": str(edge.get("status") or ""),
        })
    return {
        "schema_version": 1, "analysis_id": state.get("analysis_id"),
        "graph_id": target.get("graph_id"), "graph_name": target.get("graph_name") or "",
        "blocks": blocks, "edges": edges,
        "counts": {op: sum(item["operation"] == op for item in blocks) for op in OPERATIONS},
    }


def make_dot(model: dict[str, Any]) -> str:
    lines = [
        "digraph block_diff {", "  graph [rankdir=LR, bgcolor=\"white\", pad=0.25, nodesep=0.55, ranksep=0.8];",
        "  node [shape=box, style=\"rounded,filled\", fontname=\"Microsoft YaHei\", fontsize=11, margin=\"0.12,0.08\"];",
        "  edge [fontname=\"Microsoft YaHei\", fontsize=9, arrowsize=0.7];",
        f'  label="{esc(model.get("graph_name") or "Block 拓扑差异")}\\n绿色=新增  黄色=变更  红色=删除  灰色=待确认";',
        "  labelloc=t; fontsize=14;",
    ]
    ids: dict[str, str] = {}
    for index, block in enumerate(model["blocks"], 1):
        dot_id = f"n{index}"
        ids[block["node_id"]] = dot_id
        fill, stroke = COLORS[block["operation"]]
        detail = [block["name"], block["block_identity"], CN[block["operation"]]]
        if block.get("refdes"):
            detail.append(block["refdes"])
        if block.get("code"):
            detail.append(block["code"])
        style = "rounded,filled,dashed" if block["operation"] == "DELETE" else "rounded,filled"
        node_label = esc("\n".join(detail))
        lines.append(f'  {dot_id} [label="{node_label}", fillcolor="{fill}", color="{stroke}", fontcolor="{stroke}", style="{style}"];')
    for edge in model["edges"]:
        source = ids.get(f"block:{edge['source_block_id']}")
        target = ids.get(f"block:{edge['target_block_id']}")
        if not source or not target:
            continue
        _, color = COLORS[edge["operation"]]
        style = "solid" if edge["operation"] == "KEEP" else "dashed"
        label = f"{edge['source_port']} → {edge['target_port']}\\n{CN[edge['operation']]}"
        lines.append(f'  {source} -> {target} [label="{esc(label)}", color="{color}", fontcolor="{color}", style="{style}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render(dot_path: Path, output_path: Path, fmt: str) -> None:
    executable = shutil.which("dot")
    if not executable:
        raise ValueError("未找到 Graphviz dot；已生成 .dot，但不能声称完成了 Graphviz 渲染")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [executable, f"-T{fmt}", str(dot_path), "-o", str(output_path)],
        text=True, capture_output=True, check=False,
    )
    if completed.returncode:
        raise ValueError(f"Graphviz 渲染失败：{completed.stderr.strip()}")


def self_test() -> None:
    state = {"analysis_id": "T", "target": {"graph_id": 0, "graph_name": "Test",
        "ordered_blocks": ["1", "2"],
        "blocks": {"1": {"id": "1", "name": "MCU", "business_code": "A", "status": "SELECTED", "selected": {"refdes": "U1"}},
                   "2": {"id": "2", "name": "Sensor", "business_code": "B", "status": "SELECTED", "selected": {"refdes": "U2"}}},
        "ports": {"11": {"block_id": "1", "name": "I2C"}, "21": {"block_id": "2", "name": "I2C"}},
        "edges": {"31": {"source_port_id": "11", "target_port_id": "21", "status": "CONNECTION_MISSING"}}}}
    decisions = {"blocks": [{"block_id": "2", "operation": "MODIFY", "reason": "型号变化", "evidence": ["review:1"]}]}
    model = normalize(state, decisions)
    assert model["counts"]["MODIFY"] == 1 and model["counts"]["KEEP"] == 1
    dot = make_dot(model)
    assert "digraph block_diff" in dot and "绿色=新增" in dot
    assert model["edges"][0]["operation"] == "ADD"
    try:
        normalize(state, {"legacy_blocks": [{"legacy_id": "U9", "operation": "DELETE", "reason": "移除", "evidence": ["x"]}]})
    except ValueError:
        pass
    else:
        raise AssertionError("未确认的删除不应通过")
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "diff.dot"
        path.write_text(dot, encoding="utf-8")
        if shutil.which("dot"):
            render(path, Path(temp) / "diff.svg", "svg")
    print(json.dumps({"self_test": "PASS", "tests": 4, "graphviz_available": bool(shutil.which('dot'))}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "self-test"])
    parser.add_argument("--state")
    parser.add_argument("--decisions")
    parser.add_argument("--json-output")
    parser.add_argument("--dot-output")
    parser.add_argument("--svg-output")
    parser.add_argument("--png-output")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return 0
        if not (args.state and args.json_output and args.dot_output):
            raise ValueError("build 需要 --state、--json-output 和 --dot-output")
        model = normalize(load(args.state), load(args.decisions) if args.decisions else None)
        write_json(args.json_output, model)
        dot_path = Path(args.dot_output)
        dot_path.parent.mkdir(parents=True, exist_ok=True)
        dot_path.write_text(make_dot(model), encoding="utf-8")
        if args.svg_output:
            render(dot_path, Path(args.svg_output), "svg")
        if args.png_output:
            render(dot_path, Path(args.png_output), "png")
        print(json.dumps({"json": args.json_output, "dot": args.dot_output, "svg": args.svg_output, "png": args.png_output}, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
