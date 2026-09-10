#!/usr/bin/env python3
"""把分析结果拆分为四类可审计中间产物，并生成完整性清单。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any


def load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path, required: bool = True) -> dict[str, Any]:
    exists = path.is_file() and path.stat().st_size > 0
    return {
        "path": str(path), "required": required,
        "status": "READY" if exists else "MISSING",
        "bytes": path.stat().st_size if exists else 0,
        "sha256": sha256(path) if exists else None,
    }


def flatten_original(answer: dict[str, Any], block_diff: dict[str, Any]) -> list[dict[str, Any]]:
    changed_refdes = {
        str(item.get("refdes") or "")
        for item in block_diff.get("blocks", [])
        if item.get("operation") in {"MODIFY", "DELETE"} and item.get("refdes")
    }
    referenced_ids = {
        str(item.get("original_interface_id"))
        for item in answer.get("signal_deltas", [])
        if item.get("action") in {"MODIFY", "DELETE", "UNRESOLVED"} and item.get("original_interface_id")
    }
    rows = []
    for item in answer.get("original_interfaces", []):
        if str(item.get("refdes") or "") not in changed_refdes and str(item.get("interface_id") or "") not in referenced_ids:
            continue
        pins = item.get("pins") or []
        rows.append({
            "interface_id": item.get("interface_id", ""), "refdes": item.get("refdes", ""),
            "pin_names": ",".join(str(pin.get("name") or "") for pin in pins),
            "pin_numbers": ",".join(str(pin.get("number") or pin.get("pin_number") or "") for pin in pins),
            "net_name": item.get("net_name", ""), "category": item.get("category", ""),
            "scope_class": item.get("scope_class", ""), "status": item.get("status", ""),
            "verified_chain": item.get("verified_chain", ""),
            "remote_endpoints": json.dumps(item.get("remote_endpoints") or [], ensure_ascii=False),
            "evidence_level": item.get("evidence_level", ""),
        })
    return rows


def mapping_rows(answer: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in answer.get("signal_deltas", []):
        source = item.get("source") or {}
        destination = item.get("destination") or {}
        source_score = source.get("mapping_score")
        destination_score = destination.get("mapping_score")
        known_scores = [float(value) for value in (source_score, destination_score) if isinstance(value, (int, float))]
        confidence = min(known_scores) if known_scores else None
        rows.append({
            "delta_id": item.get("delta_id", ""), "operation": item.get("action", ""),
            "source_block_id": source.get("block_id", ""), "source_block_name": source.get("block_name", ""),
            "source_port": source.get("port_name", ""),
            "destination_block_id": destination.get("block_id", ""), "destination_block_name": destination.get("block_name", ""),
            "destination_port": destination.get("port_name", ""),
            "schematic_source_pin_name": item.get("source_pin_name", ""),
            "original_net_name": item.get("original_net_name", ""),
            "target_net_name": item.get("target_net_name", ""),
            "connection_change": item.get("connection_change") or item.get("action", ""),
            "mapping_confidence": confidence if confidence is not None else "",
            "analysis": item.get("reason", ""),
            "evidence": json.dumps(item.get("evidence") or [], ensure_ascii=False),
            "requires_connection_mapping": bool(item.get("requires_connection_mapping")),
        })
    return rows


def target_rows(answer: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for row in mapping_rows(answer):
        if row["operation"] == "DELETE":
            continue
        result.append({
            "source_block_id": row["source_block_id"], "source_block_name": row["source_block_name"],
            "source_port": row["source_port"], "destination_block_id": row["destination_block_id"],
            "destination_block_name": row["destination_block_name"], "destination_port": row["destination_port"],
            "schematic_source_pin_name": row["schematic_source_pin_name"],
            "analysis": row["analysis"], "mapping_confidence": row["mapping_confidence"],
            "network_name": row["target_net_name"] or row["original_net_name"],
            "network_operation": row["operation"], "status": "PROPOSED" if row["operation"] in {"ADD", "MODIFY"} else row["operation"],
            "evidence": row["evidence"],
        })
    return result


def mapping_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Port—Pin 映射与连接关系变化", "",
        "| 操作 | 源Block/Port | 目的Block/Port | 原理图源端Pin名称 | 原网络 | 目标网络 | 置信度 | 分析 |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        source = f"{row['source_block_id']} {row['source_block_name']}/{row['source_port']}".strip(" /") or "-"
        destination = f"{row['destination_block_id']} {row['destination_block_name']}/{row['destination_port']}".strip(" /") or "-"
        lines.append(
            f"| {row['operation']} | {source} | {destination} | {row['schematic_source_pin_name'] or '-'} | "
            f"{row['original_net_name'] or '-'} | {row['target_net_name'] or '-'} | {row['mapping_confidence'] or '-'} | {row['analysis']} |"
        )
    lines += ["", "说明：表中的原理图 Pin 只展示源端 Pin 名称；物理脚号、目的端 Pin 和完整链路保留在 JSON 证据中。", ""]
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    state = load(args.consistency_state)
    answer = load(args.answer)
    block_diff = load(args.block_diff_json)
    if answer.get("analysis_id") != state.get("analysis_id") or block_diff.get("analysis_id") != state.get("analysis_id"):
        raise ValueError("输入文件的 analysis_id 不一致")
    output = Path(args.output_dir)
    stage2 = output / "02_changed_block_original_networks"
    stage3 = output / "03_port_pin_connection_changes"
    stage4 = output / "04_modified_signal_interfaces"
    originals = flatten_original(answer, block_diff)
    mappings = mapping_rows(answer)
    targets = target_rows(answer)

    original_json = stage2 / "changed-block-original-networks.json"
    original_csv = stage2 / "changed-block-original-networks.csv"
    mapping_json = stage3 / "port-pin-connection-changes.json"
    mapping_md = stage3 / "port-pin-connection-changes.md"
    target_json = stage4 / "modified-signal-interface-list.json"
    target_csv = stage4 / "modified-signal-interface-list.csv"
    write_json(original_json, {"analysis_id": state["analysis_id"], "interfaces": originals})
    write_csv(original_csv, originals, ["interface_id", "refdes", "pin_names", "pin_numbers", "net_name", "category", "scope_class", "status", "verified_chain", "remote_endpoints", "evidence_level"])
    write_json(mapping_json, {"analysis_id": state["analysis_id"], "connections": mappings})
    mapping_md.write_text(mapping_markdown(mappings), encoding="utf-8")
    write_json(target_json, {"analysis_id": state["analysis_id"], "interfaces": targets})
    write_csv(target_csv, targets, ["source_block_id", "source_block_name", "source_port", "destination_block_id", "destination_block_name", "destination_port", "schematic_source_pin_name", "analysis", "mapping_confidence", "network_name", "network_operation", "status", "evidence"])

    paths = [
        artifact(Path(args.block_diff_json)), artifact(Path(args.block_diff_dot)), artifact(Path(args.block_diff_svg)),
        artifact(original_json), artifact(original_csv), artifact(mapping_json), artifact(mapping_md), artifact(target_json), artifact(target_csv),
    ]
    if args.original_xlsx:
        paths.append(artifact(Path(args.original_xlsx)))
    elif args.require_xlsx:
        paths.append({"path": "原始信号接口.xlsx", "required": True, "status": "MISSING", "bytes": 0, "sha256": None})
    if args.modified_xlsx:
        paths.append(artifact(Path(args.modified_xlsx)))
    elif args.require_xlsx:
        paths.append({"path": "修改后信号接口.xlsx", "required": True, "status": "MISSING", "bytes": 0, "sha256": None})
    complete = all(not item["required"] or item["status"] == "READY" for item in paths)
    manifest = {
        "schema_version": 1, "analysis_id": state["analysis_id"], "complete": complete,
        "counts": {"changed_block_original_networks": len(originals), "mapping_rows": len(mappings), "modified_interfaces": len(targets)},
        "artifacts": paths,
    }
    write_json(output / "middleware-manifest.json", manifest)
    if args.require_xlsx and not complete:
        raise ValueError("中间产物未完成：Graphviz SVG 或两份 Excel 缺失；详见 middleware-manifest.json")
    return manifest


def self_test() -> None:
    state = {"analysis_id": "T"}
    block = {"analysis_id": "T", "blocks": [{"block_id": "1", "operation": "MODIFY", "refdes": "U1"}]}
    answer = {"analysis_id": "T", "original_interfaces": [
        {"interface_id": "I1", "refdes": "U1", "pins": [{"name": "SCK", "number": "1"}], "net_name": "SPI_CLK", "category": "DATA", "status": "VERIFIED"},
        {"interface_id": "I2", "refdes": "U9", "pins": [{"name": "X"}], "net_name": "X"}],
        "signal_deltas": [{"delta_id": "D1", "action": "MODIFY", "original_interface_id": "I1",
            "source": {"block_id": "0-1", "block_name": "MCU", "port_name": "SPI", "mapping_score": 0.9},
            "destination": {"block_id": "0-2", "block_name": "Flash", "port_name": "SPI", "mapping_score": 0.8},
            "source_pin_name": "SCK", "original_net_name": "SPI_CLK", "target_net_name": "SPI1_CLK", "reason": "实例变化", "evidence": ["E3"]}]}
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for name, payload in (("state.json", state), ("answer.json", answer), ("block.json", block)):
            write_json(root / name, payload)
        (root / "block.dot").write_text("digraph{}", encoding="utf-8")
        (root / "block.svg").write_text("<svg/>", encoding="utf-8")
        args = argparse.Namespace(consistency_state=str(root / "state.json"), answer=str(root / "answer.json"),
            block_diff_json=str(root / "block.json"), block_diff_dot=str(root / "block.dot"), block_diff_svg=str(root / "block.svg"),
            output_dir=str(root / "out"), original_xlsx=None, modified_xlsx=None, require_xlsx=False)
        manifest = build(args)
        assert manifest["complete"] and manifest["counts"]["changed_block_original_networks"] == 1
        assert manifest["counts"]["mapping_rows"] == 1 and manifest["counts"]["modified_interfaces"] == 1
        mapping = load(root / "out" / "03_port_pin_connection_changes" / "port-pin-connection-changes.json")
        assert mapping["connections"][0]["schematic_source_pin_name"] == "SCK"
    print(json.dumps({"self_test": "PASS", "tests": 4}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "self-test"])
    parser.add_argument("--consistency-state")
    parser.add_argument("--answer")
    parser.add_argument("--block-diff-json")
    parser.add_argument("--block-diff-dot")
    parser.add_argument("--block-diff-svg")
    parser.add_argument("--output-dir")
    parser.add_argument("--original-xlsx")
    parser.add_argument("--modified-xlsx")
    parser.add_argument("--require-xlsx", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return 0
        required = [args.consistency_state, args.answer, args.block_diff_json, args.block_diff_dot, args.block_diff_svg, args.output_dir]
        if not all(required):
            raise ValueError("build 缺少必要输入或输出目录")
        manifest = build(args)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
