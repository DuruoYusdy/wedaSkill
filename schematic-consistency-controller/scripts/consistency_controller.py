#!/usr/bin/env python3
"""框图—原理图一致性分析的确定性状态控制器。

控制器不直接调用 MCP。它负责保存目标图、候选、动作队列、查询预算、
已访问状态和 chain_check 证据；模型只负责执行 next 返回的动作，并将
精简后的结构化证据提交回来。
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3
TERMINAL_BLOCK_STATES = {"SELECTED", "UNRESOLVED", "HARD_CONFLICT"}
TERMINAL_EDGE_STATES = {
    "VERIFIED",
    "INVALID_TARGET",
    "UNRESOLVED_ENDPOINT",
    "NOT_OBSERVED_WITHIN_SCOPE",
    "CONNECTION_MISSING",
    "UNVERIFIED_PATH",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False))


def load_json_file(path: str | Path) -> Any:
    if str(path) == "-":
        return json.load(sys.stdin)
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def parse_json_input(input_path: str | None, json_text: str | None) -> Any:
    if input_path:
        return load_json_file(input_path)
    if json_text:
        return json.loads(json_text)
    raise ValueError("必须提供 --input 或 --json")


def atomic_save(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(payload)
        temp_name = handle.name
    os.replace(temp_name, target)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state(path: str | Path) -> dict[str, Any]:
    state = load_json_file(path)
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"不支持的状态版本：{state.get('schema_version')}，期望 {SCHEMA_VERSION}"
        )
    return state


def touch(state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    state["state_revision"] = int(state.get("state_revision", 0)) + 1


def user_define_map(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(value, list):
        return result
    for entry in value:
        if isinstance(entry, list) and len(entry) >= 2:
            result[str(entry[0])] = entry[1]
    return result


def flatten_objects(root: Any) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    objects: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []

    def walk(obj: Any, path: str) -> None:
        if not isinstance(obj, dict):
            return
        object_id = obj.get("id")
        if object_id is not None:
            key = str(object_id)
            if key in objects:
                issues.append(
                    {
                        "type": "DUPLICATE_OBJECT_ID",
                        "object_id": object_id,
                        "path": path,
                        "severity": "ERROR",
                    }
                )
            else:
                copied = copy.deepcopy(obj)
                copied["_source_path"] = path
                objects[key] = copied
        for index, child in enumerate(obj.get("children") or []):
            walk(child, f"{path}.children[{index}]")

    walk(root, "graph")
    return objects, issues


def canonical_text(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[\s\-+/\\.#]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def extract_refdes_hints(text: Any) -> list[str]:
    if not text:
        return []
    return sorted(set(re.findall(r"\b[A-Z]{1,4}\d+[A-Z]?\b", str(text).upper())))


def block_priority(block: dict[str, Any], degree: int) -> int:
    score = 0
    if block.get("component_uuid"):
        score += 100
    if block.get("business_code"):
        score += 80
    if block.get("cbb_name"):
        score += 70
    if block.get("refdes_hints"):
        score += 65
    model = canonical_text(block.get("model"))
    if model and model not in {"GENERAL", "UNKNOWN"}:
        score += 45
    name = canonical_text(block.get("name"))
    if name and name not in {"BLOCK", "MODULE", "GENERAL", "模块", "功能模块"}:
        score += 25
    score += min(len(block.get("ports", [])), 10) * 2
    score += min(degree, 8) * 5
    return score


def normalize_diagram(document: dict[str, Any], scope_ids: set[str] | None) -> dict[str, Any]:
    graph = document.get("graph", document)
    if not isinstance(graph, dict):
        raise ValueError("输入中不存在有效 graph 对象")
    objects, issues = flatten_objects(graph)

    raw_blocks = {
        key: value for key, value in objects.items() if value.get("type") == "block"
    }
    raw_ports = {
        key: value for key, value in objects.items() if value.get("type") == "port"
    }
    raw_wires = {
        key: value for key, value in objects.items() if value.get("type") == "wire"
    }

    ports: dict[str, dict[str, Any]] = {}
    positions: dict[tuple[str, Any, Any], list[str]] = {}
    for key, port in raw_ports.items():
        business = port.get("business") or {}
        style = port.get("style") or {}
        parent_id = str(port.get("parentId"))
        entry = {
            "id": key,
            "source_id": port.get("id"),
            "block_id": parent_id,
            "name": port.get("name") or "",
            "canonical_name": canonical_text(port.get("name")),
            "direction": business.get("direction") or "UNKNOWN",
            "protocol": business.get("protocol") or "",
            "voltage": business.get("voltage") or "",
            "signal_function": business.get("signalFunction") or "",
            "pinlist": user_define_map(port.get("userDefine")).get("Pinlist", ""),
            "style": {"x": style.get("x"), "y": style.get("y")},
            "status": "UNMAPPED",
            "mapping": None,
        }
        ports[key] = entry
        if not entry["name"]:
            issues.append(
                {
                    "type": "UNNAMED_PORT",
                    "object_id": port.get("id"),
                    "severity": "WARNING",
                }
            )
        pos_key = (parent_id, style.get("x"), style.get("y"))
        positions.setdefault(pos_key, []).append(key)

    for (parent_id, x_value, y_value), port_ids in positions.items():
        if len(port_ids) > 1:
            issues.append(
                {
                    "type": "DUPLICATE_PORT_CANDIDATE",
                    "block_id": parent_id,
                    "port_ids": port_ids,
                    "position": {"x": x_value, "y": y_value},
                    "severity": "WARNING",
                }
            )

    edges: dict[str, dict[str, Any]] = {}
    degree: dict[str, int] = {key: 0 for key in raw_blocks}
    for key, wire in raw_wires.items():
        business = wire.get("business") or {}
        source_id = str(business.get("source")) if business.get("source") is not None else None
        target_id = str(business.get("target")) if business.get("target") is not None else None
        valid = source_id in ports and target_id in ports
        entry = {
            "id": key,
            "source_port_id": source_id,
            "target_port_id": target_id,
            "name": wire.get("name") or "",
            "status": "PENDING" if valid else "INVALID_TARGET",
            "trace_attempts": 0,
            "paths": [],
            "verified_path_id": None,
            "finding": None,
        }
        edges[key] = entry
        if not valid:
            issues.append(
                {
                    "type": "BROKEN_WIRE_REFERENCE",
                    "wire_id": wire.get("id"),
                    "source": business.get("source"),
                    "target": business.get("target"),
                    "severity": "ERROR",
                }
            )
        else:
            source_block = ports[source_id]["block_id"]
            target_block = ports[target_id]["block_id"]
            degree[source_block] = degree.get(source_block, 0) + 1
            degree[target_block] = degree.get(target_block, 0) + 1

    blocks: dict[str, dict[str, Any]] = {}
    for key, block in raw_blocks.items():
        if scope_ids and key not in scope_ids:
            continue
        business = block.get("business") or {}
        custom = user_define_map(block.get("userDefine"))
        block_ports = [port_id for port_id, port in ports.items() if port["block_id"] == key]
        pin_text = " ".join(str(ports[port_id].get("pinlist") or "") for port_id in block_ports)
        refdes_hints = extract_refdes_hints(pin_text)
        entry = {
            "id": key,
            "source_id": block.get("id"),
            "name": block.get("name") or "",
            "canonical_name": canonical_text(block.get("name")),
            "model": business.get("model") or "",
            "business_code": business.get("code") or "",
            "cbb_name": business.get("cbbName") or custom.get("partGroup") or "",
            "component_uuid": business.get("componentUuid") or "",
            "requirements": custom.get("DesignRequirements") or block.get("remarks") or "",
            "ports": block_ports,
            "refdes_hints": refdes_hints,
            "degree": degree.get(key, 0),
            "priority": 0,
            "status": "UNMAPPED",
            "round": 0,
            "candidates": [],
            "selected": None,
            "ports_submitted": False,
            "dependencies_status": "PENDING",
            "dependency_findings": [],
        }
        entry["priority"] = block_priority(entry, entry["degree"])
        blocks[key] = entry

    if scope_ids:
        allowed_ports = {port_id for block in blocks.values() for port_id in block["ports"]}
        ports = {key: value for key, value in ports.items() if key in allowed_ports}
        edges = {
            key: value
            for key, value in edges.items()
            if value["source_port_id"] in allowed_ports or value["target_port_id"] in allowed_ports
        }

    ordered_blocks = sorted(blocks, key=lambda item: (-blocks[item]["priority"], item))
    return {
        "format_version": document.get("version"),
        "graph_id": graph.get("id"),
        "graph_name": graph.get("name") or "",
        "blocks": blocks,
        "ports": ports,
        "edges": edges,
        "ordered_blocks": ordered_blocks,
        "issues": issues,
    }


def new_action(
    state: dict[str, Any],
    key: str,
    kind: str,
    subject: str,
    tool: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    existing_id = state["action_keys"].get(key)
    if existing_id:
        return state["actions"][existing_id]
    state["action_seq"] += 1
    action_id = f"A{state['action_seq']:05d}"
    action = {
        "id": action_id,
        "key": key,
        "kind": kind,
        "subject": subject,
        "tool": tool,
        "payload": payload,
        "status": "PENDING",
        "created_at": now_iso(),
        "completed_at": None,
    }
    state["actions"][action_id] = action
    state["action_keys"][key] = action_id
    return action


def complete_action_by_key(
    state: dict[str, Any], key: str, status: str = "DONE", note: str | None = None
) -> None:
    action_id = state["action_keys"].get(key)
    if not action_id:
        return
    action = state["actions"][action_id]
    if action["status"] in {"DONE", "FAILED", "SKIPPED"}:
        return
    action["status"] = status
    action["completed_at"] = now_iso()
    if note:
        action["note"] = note
    if action.get("tool"):
        state["budget"]["used"] += 1


def pending_actions(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [action for action in state["actions"].values() if action["status"] == "PENDING"]


def recommended_block_route(block: dict[str, Any], state: dict[str, Any]) -> list[str]:
    if block.get("refdes_hints"):
        return ["get_component_info_by_refdes", "get_component_pins"]
    if block.get("component_uuid"):
        return ["get_schematic_summary", "get_component_info_by_refdes", "get_component_pins"]
    if block.get("business_code") or block.get("cbb_name"):
        return ["list_cbbs", "get_cbb_info", "get_cbb_components", "get_cbb_topology"]
    mapped_neighbors = mapped_neighbor_blocks(block["id"], state)
    if mapped_neighbors:
        return ["get_component_pins", "trace_net", "get_component_info_by_refdes"]
    return ["list_sheets", "get_sheet_topology", "search_components"]


def mapped_neighbor_blocks(block_id: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    target = state["target"]
    result: list[dict[str, Any]] = []
    for edge in target["edges"].values():
        source_port = target["ports"].get(edge.get("source_port_id"))
        target_port = target["ports"].get(edge.get("target_port_id"))
        if not source_port or not target_port:
            continue
        pair = (source_port["block_id"], target_port["block_id"])
        if block_id == pair[0]:
            other = pair[1]
        elif block_id == pair[1]:
            other = pair[0]
        else:
            continue
        other_block = target["blocks"].get(other)
        if other_block and other_block.get("status") == "SELECTED":
            result.append(
                {
                    "target_block_id": other,
                    "target_block_name": other_block["name"],
                    "selected_implementation": other_block["selected"],
                }
            )
    return result


def determine_phase(state: dict[str, Any]) -> str:
    topology_render = state["diagram_topology_render"]
    if topology_render["status"] == "PENDING":
        return "RENDER_DIAGRAM_TOPOLOGY"
    if state["budget"]["used"] >= state["budget"]["max"]:
        return "STOPPED_BUDGET"
    overview = state["schematic_overview"]
    if overview["summary"]["status"] == "PENDING" or overview["sheets"]["status"] == "PENDING":
        return "SCHEMATIC_OVERVIEW"
    if any(block["status"] not in TERMINAL_BLOCK_STATES for block in state["target"]["blocks"].values()):
        return "MAP_BLOCKS"
    selected = [block for block in state["target"]["blocks"].values() if block["status"] == "SELECTED"]
    inventory = state["interface_inventory"]
    if selected and inventory["status"] not in {"COMPLETE", "PARTIAL"}:
        return "INVENTORY_SCHEMATIC_INTERFACES"
    if not selected and inventory["status"] == "PENDING":
        return "INVENTORY_SCHEMATIC_INTERFACES"
    if any(not block["ports_submitted"] for block in selected):
        return "MAP_PORTS"
    if any(edge["status"] not in TERMINAL_EDGE_STATES for edge in state["target"]["edges"].values()):
        return "VERIFY_EDGES"
    if any(block["dependencies_status"] == "PENDING" for block in selected):
        return "CHECK_DEPENDENCIES"
    return "DONE"


def schedule(state: dict[str, Any]) -> None:
    state["phase"] = determine_phase(state)
    if state["phase"] == "STOPPED_BUDGET":
        return

    if state["phase"] == "RENDER_DIAGRAM_TOPOLOGY":
        new_action(
            state,
            "diagram:topology-render",
            "RENDER_DIAGRAM_TOPOLOGY",
            "diagram:current-target",
            None,
            {
                "script": "scripts/render_diagram_topology.py",
                "renderer": "graphviz-dot",
                "required_outputs": ["diagram-topology.dot", "diagram-topology.svg", "diagram-topology-render.json"],
                "目的": "在任何原理图查询和 Block 映射前，把已解析的当前框图拓扑渲染为 Graphviz SVG",
                "提交命令": "record-topology-render",
            },
        )
        return

    if state["phase"] == "SCHEMATIC_OVERVIEW":
        if state["schematic_overview"]["summary"]["status"] == "PENDING":
            new_action(
                state,
                "overview:summary",
                "CALL_TOOL",
                "schematic",
                "get_schematic_summary",
                {"目的": "获取工程 UUID、板卡、图页、CBB 和器件数量概要"},
            )
        if state["schematic_overview"]["sheets"]["status"] == "PENDING":
            new_action(
                state,
                "overview:sheets",
                "CALL_TOOL",
                "schematic",
                "list_sheets",
                {"建议参数": {"depth": 1}, "目的": "获取浅层图页树"},
            )
        return

    if state["phase"] == "MAP_BLOCKS":
        for block_id in state["target"]["ordered_blocks"]:
            block = state["target"]["blocks"][block_id]
            if block["status"] in TERMINAL_BLOCK_STATES:
                continue
            key = f"block:{block_id}:round:{block['round'] + 1}"
            new_action(
                state,
                key,
                "DISCOVER_BLOCK_CANDIDATES",
                f"block:{block_id}",
                None,
                {
                    "目标Block": {
                        "id": block_id,
                        "name": block["name"],
                        "model": block["model"],
                        "business_code": block["business_code"],
                        "cbb_name": block["cbb_name"],
                        "component_uuid": block["component_uuid"],
                        "refdes_hints": block["refdes_hints"],
                        "ports": [state["target"]["ports"][pid] for pid in block["ports"]],
                    },
                    "已映射相邻Block": mapped_neighbor_blocks(block_id, state),
                    "推荐工具路径": recommended_block_route(block, state),
                    "提交命令": "submit-blocks",
                },
            )
            break
        return

    if state["phase"] == "INVENTORY_SCHEMATIC_INTERFACES":
        selected = [
            {
                "block_id": block["id"],
                "block_name": block["name"],
                "implementation": block["selected"],
            }
            for block in state["target"]["blocks"].values()
            if block["status"] == "SELECTED"
        ]
        new_action(
            state,
            "inventory:interfaces",
            "RUN_INTERFACE_INVENTORY",
            "schematic:all-selected-blocks",
            None,
            {
                "skill": "schematic-diff-interface-extractor",
                "scope": "ALL_SELECTED_BLOCK_IMPLEMENTATIONS",
                "include_all_selected": True,
                "selected_blocks": selected,
                "required_outputs": ["original-interfaces.json", "interface-coverage.json"],
                "目的": "在框图边差异判断前，逆向并冻结旧原理图的原始信号接口事实基线",
                "提交命令": "record-interface-inventory",
            },
        )
        return

    if state["phase"] == "MAP_PORTS":
        for block_id in state["target"]["ordered_blocks"]:
            block = state["target"]["blocks"][block_id]
            if block["status"] != "SELECTED" or block["ports_submitted"]:
                continue
            new_action(
                state,
                f"ports:{block_id}",
                "MAP_BLOCK_PORTS",
                f"block:{block_id}",
                "get_component_pins",
                {
                    "目标Block": {"id": block_id, "name": block["name"]},
                    "已选实现": block["selected"],
                    "目标Ports": [state["target"]["ports"][pid] for pid in block["ports"]],
                    "目的": "批量提交该 Block 的 Port→Pin/Net 映射",
                    "提交命令": "submit-ports",
                },
            )
            break
        return

    if state["phase"] == "VERIFY_EDGES":
        for edge_id, edge in state["target"]["edges"].items():
            if edge["status"] in TERMINAL_EDGE_STATES:
                continue
            source = state["target"]["ports"].get(edge.get("source_port_id"))
            target = state["target"]["ports"].get(edge.get("target_port_id"))
            if not source or not target:
                edge["status"] = "INVALID_TARGET"
                continue
            source_mapping = source.get("mapping")
            target_mapping = target.get("mapping")
            if not source_mapping or not target_mapping:
                edge["status"] = "UNRESOLVED_ENDPOINT"
                edge["finding"] = "至少一个目标 Port 没有可靠的原理图映射"
                continue
            unchecked = next((item for item in edge["paths"] if item["verified"] is None), None)
            if unchecked:
                new_action(
                    state,
                    f"chain:{edge_id}:{unchecked['id']}",
                    "VERIFY_CHAIN",
                    f"edge:{edge_id}",
                    "chain_check",
                    {
                        "chain": unchecked["chain"],
                        "path_id": unchecked["id"],
                        "目的": "验证精确电气链路",
                        "提交命令": "submit-chain",
                    },
                )
                return
            if edge["paths"] and all(item["verified"] is False for item in edge["paths"]):
                edge["status"] = "UNVERIFIED_PATH"
                edge["finding"] = "所有候选链路均未通过 chain_check"
                continue
            if edge["trace_attempts"] >= state["limits"]["max_edge_trace_rounds"]:
                edge["status"] = "NOT_OBSERVED_WITHIN_SCOPE"
                edge["finding"] = "达到局部追踪上限，未发现可验证链路"
                continue
            new_action(
                state,
                f"trace:{edge_id}:round:{edge['trace_attempts'] + 1}",
                "TRACE_TARGET_EDGE",
                f"edge:{edge_id}",
                "trace_connection",
                {
                    "source": source_mapping,
                    "target": target_mapping,
                    "目标边": edge_id,
                    "目的": "查找两个已映射端点之间的候选实现链路",
                    "提交命令": "submit-trace",
                },
            )
            return
        state["phase"] = determine_phase(state)
        return

    if state["phase"] == "CHECK_DEPENDENCIES":
        for block_id in state["target"]["ordered_blocks"]:
            block = state["target"]["blocks"][block_id]
            if block["status"] != "SELECTED" or block["dependencies_status"] != "PENDING":
                continue
            new_action(
                state,
                f"dependencies:{block_id}",
                "CHECK_LOCAL_DEPENDENCIES",
                f"block:{block_id}",
                None,
                {
                    "目标Block": {"id": block_id, "name": block["name"]},
                    "已选实现": block["selected"],
                    "目标要求": block["requirements"],
                    "检查项": ["电源/使能", "时钟", "复位", "Strap/配置", "必要外围"],
                    "推荐工具": ["get_component_pins", "trace_net", "chain_check"],
                    "提交命令": "submit-dependencies",
                },
            )
            break


def command_init(args: argparse.Namespace) -> None:
    diagram = load_json_file(args.diagram)
    scope_ids = set(filter(None, (args.scope_blocks or "").split(","))) or None
    target = normalize_diagram(diagram, scope_ids)
    raw_hash = hashlib.sha256(
        json.dumps(diagram, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    state = {
        "schema_version": SCHEMA_VERSION,
        "state_revision": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "analysis_id": args.analysis_id or f"analysis-{raw_hash[:12]}",
        "diagram_sha256": raw_hash,
        "context": {
            "solution_id": args.solution_id,
            "schematic_id": args.schematic_id,
            "board_id": args.board_id,
        },
        "phase": "SCHEMATIC_OVERVIEW",
        "limits": {
            "max_block_rounds": args.max_block_rounds,
            "max_edge_paths": args.max_edge_paths,
            "max_edge_trace_rounds": args.max_edge_trace_rounds,
            "select_threshold": args.select_threshold,
            "select_margin": args.select_margin,
        },
        "budget": {"max": args.query_budget, "used": 0},
        "schematic_overview": {
            "summary": {"status": "PENDING", "result": None},
            "sheets": {"status": "PENDING", "result": None},
        },
        "diagram_topology_render": {
            "status": "PENDING",
            "result": None,
        },
        "interface_inventory": {
            "status": "PENDING",
            "result": None,
        },
        "target": target,
        "actions": {},
        "action_keys": {},
        "action_seq": 0,
        "events": [],
    }
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit(state_summary(state))


def command_next(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    actions = pending_actions(state)[: args.limit]
    emit({"phase": state["phase"], "budget": state["budget"], "actions": actions})


def command_record_topology_render(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    result = parse_json_input(args.input, args.json)
    if not isinstance(result, dict):
        raise ValueError("拓扑渲染结果必须是 JSON 对象")
    if result.get("analysis_id") != state["analysis_id"]:
        raise ValueError("拓扑渲染结果的 analysis_id 与主状态不一致")
    if result.get("diagram_sha256") != state.get("diagram_sha256"):
        raise ValueError("拓扑渲染结果不是当前框图快照")
    if result.get("renderer") != "graphviz-dot":
        raise ValueError("框图拓扑必须由 Graphviz dot 渲染")
    dot_path = Path(str(result.get("dot_file") or ""))
    svg_path = Path(str(result.get("svg_file") or ""))
    if not dot_path.is_file() or not svg_path.is_file():
        raise ValueError("拓扑渲染缺少 .dot 或 .svg 文件")
    if dot_path.suffix.lower() != ".dot" or svg_path.suffix.lower() != ".svg":
        raise ValueError("拓扑渲染文件扩展名必须是 .dot 和 .svg")
    svg_head = svg_path.read_text(encoding="utf-8", errors="ignore")[:4096]
    if "<svg" not in svg_head:
        raise ValueError("拓扑渲染结果不是有效 SVG")
    actual_dot_hash = file_sha256(dot_path)
    actual_svg_hash = file_sha256(svg_path)
    if result.get("dot_sha256") != actual_dot_hash or result.get("svg_sha256") != actual_svg_hash:
        raise ValueError("拓扑渲染文件哈希与结果声明不一致")
    state["diagram_topology_render"] = {
        "status": "COMPLETE",
        "result": copy.deepcopy(result),
    }
    complete_action_by_key(state, "diagram:topology-render")
    state["events"].append(
        {"at": now_iso(), "type": "DIAGRAM_TOPOLOGY_RENDER", "status": "COMPLETE"}
    )
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit(state_summary(state))


def command_record_overview(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if state["diagram_topology_render"]["status"] != "COMPLETE":
        raise ValueError("必须先完成当前框图拓扑的 Graphviz 渲染")
    result = parse_json_input(args.input, args.json)
    key = "summary" if args.kind == "summary" else "sheets"
    state["schematic_overview"][key] = {"status": args.status, "result": result}
    complete_action_by_key(
        state,
        f"overview:{key}",
        "DONE" if args.status == "SUCCESS" else "FAILED",
    )
    state["events"].append({"at": now_iso(), "type": "OVERVIEW", "kind": key})
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit(state_summary(state))


def validate_score(value: Any, name: str) -> float:
    score = float(value)
    if score < 0 or score > 1:
        raise ValueError(f"{name} 必须在 0～1 之间")
    return score


def score_candidate(candidate: dict[str, Any]) -> float:
    identity = validate_score(candidate.get("identity_score", 0), "identity_score")
    capability = validate_score(candidate.get("capability_score", 0), "capability_score")
    port = validate_score(candidate.get("port_score", 0), "port_score")
    neighbor = validate_score(candidate.get("neighborhood_score", 0), "neighborhood_score")
    return round(0.35 * identity + 0.25 * capability + 0.25 * port + 0.15 * neighbor, 6)


def command_submit_blocks(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    block_id = str(args.block_id)
    block = state["target"]["blocks"].get(block_id)
    if not block:
        raise ValueError(f"不存在目标 Block：{block_id}")
    payload = parse_json_input(args.input, args.json)
    candidates = payload.get("candidates", payload) if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        raise ValueError("候选输入必须是数组，或包含 candidates 数组")
    normalized = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError("每个候选必须是对象")
        item = copy.deepcopy(candidate)
        item["id"] = str(item.get("id") or item.get("refdes") or item.get("cbb_id") or f"candidate-{index + 1}")
        item["hard_conflicts"] = list(item.get("hard_conflicts") or [])
        item["score"] = score_candidate(item)
        normalized.append(item)
    normalized.sort(key=lambda item: (-item["score"], item["id"]))
    block["round"] += 1
    block["candidates"] = normalized
    key = f"block:{block_id}:round:{block['round']}"
    complete_action_by_key(state, key)

    viable = [item for item in normalized if not item["hard_conflicts"]]
    top = viable[0] if viable else None
    second_score = viable[1]["score"] if len(viable) > 1 else 0.0
    threshold = state["limits"]["select_threshold"]
    margin = state["limits"]["select_margin"]
    if top and top["score"] >= threshold and top["score"] - second_score >= margin:
        block["status"] = "SELECTED"
        block["selected"] = top
    elif normalized and all(item["hard_conflicts"] for item in normalized):
        block["status"] = "HARD_CONFLICT"
    elif block["round"] >= state["limits"]["max_block_rounds"]:
        block["status"] = "UNRESOLVED"
    else:
        block["status"] = "AMBIGUOUS"

    state["events"].append(
        {
            "at": now_iso(),
            "type": "BLOCK_CANDIDATES",
            "block_id": block_id,
            "status": block["status"],
        }
    )
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit({"block_id": block_id, "status": block["status"], "selected": block["selected"], "candidates": normalized})


def command_select_block(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    block = state["target"]["blocks"].get(str(args.block_id))
    if not block:
        raise ValueError("目标 Block 不存在")
    candidate = next((item for item in block["candidates"] if item["id"] == args.candidate_id), None)
    if not candidate:
        raise ValueError("候选不存在")
    if candidate.get("hard_conflicts") and not args.override_conflict:
        raise ValueError("候选存在硬冲突；如已人工确认，显式使用 --override-conflict")
    candidate = copy.deepcopy(candidate)
    candidate["manual_selection"] = True
    candidate["selection_note"] = args.note or "人工确认"
    block["selected"] = candidate
    block["status"] = "SELECTED"
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit({"block_id": block["id"], "status": block["status"], "selected": candidate})


def command_submit_ports(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if state["interface_inventory"]["status"] not in {"COMPLETE", "PARTIAL"}:
        raise ValueError("必须先完成原始信号接口逆向，再提交 Port 映射")
    block_id = str(args.block_id)
    block = state["target"]["blocks"].get(block_id)
    if not block or block["status"] != "SELECTED":
        raise ValueError("只能为已选定实现的 Block 提交 Port 映射")
    payload = parse_json_input(args.input, args.json)
    bindings = payload.get("bindings", payload) if isinstance(payload, dict) else payload
    if not isinstance(bindings, list):
        raise ValueError("Port 映射必须是数组，或包含 bindings 数组")
    by_port: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        port_id = str(binding.get("port_id"))
        if port_id not in block["ports"]:
            raise ValueError(f"Port {port_id} 不属于 Block {block_id}")
        item = copy.deepcopy(binding)
        item["score"] = validate_score(item.get("score", 0), "port score")
        item["hard_conflicts"] = list(item.get("hard_conflicts") or [])
        by_port.setdefault(port_id, []).append(item)

    threshold = float(args.threshold)
    for port_id in block["ports"]:
        port = state["target"]["ports"][port_id]
        candidates = sorted(by_port.get(port_id, []), key=lambda item: -item["score"])
        viable = [item for item in candidates if not item["hard_conflicts"]]
        if viable and viable[0]["score"] >= threshold:
            port["status"] = "MAPPED"
            port["mapping"] = viable[0]
        elif candidates and all(item["hard_conflicts"] for item in candidates):
            port["status"] = "HARD_CONFLICT"
        else:
            port["status"] = "UNRESOLVED"
        port["mapping_candidates"] = candidates

    block["ports_submitted"] = True
    complete_action_by_key(state, f"ports:{block_id}")
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit(
        {
            "block_id": block_id,
            "ports": [state["target"]["ports"][port_id] for port_id in block["ports"]],
        }
    )


def command_record_interface_inventory(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    selected_count = sum(
        block["status"] == "SELECTED" for block in state["target"]["blocks"].values()
    )
    status = args.status
    if status == "NOT_APPLICABLE":
        if selected_count:
            raise ValueError("存在已映射 Block 时，接口逆向不能标记为 NOT_APPLICABLE")
        result: dict[str, Any] = {
            "coverage": {"selected_blocks": 0},
            "reason": args.reason or "没有已映射的 Block",
        }
    else:
        result = parse_json_input(args.input, args.json)
        if not isinstance(result, dict):
            raise ValueError("接口逆向结果必须是 JSON 对象")
        coverage = result.get("coverage")
        if not isinstance(coverage, dict):
            raise ValueError("接口逆向结果缺少 coverage 对象")
        reported_selected = int(coverage.get("selected_blocks", -1))
        if status == "COMPLETE" and reported_selected != selected_count:
            raise ValueError(
                f"COMPLETE 覆盖的 selected_blocks={reported_selected}，应为 {selected_count}"
            )
        if status == "COMPLETE":
            pins_total = int(coverage.get("pins_total", -1))
            pins_classified = int(coverage.get("pins_classified", -2))
            if pins_total < 0 or pins_classified != pins_total:
                raise ValueError("COMPLETE 要求 pins_total 与 pins_classified 相等且非负")
        if status == "PARTIAL" and not (args.reason or result.get("reason")):
            raise ValueError("PARTIAL 必须说明未完成原因")
        if not result.get("interfaces_file"):
            raise ValueError("接口逆向结果缺少 interfaces_file")
        if not result.get("evidence"):
            raise ValueError("接口逆向结果缺少 evidence，不能冻结事实基线")
        if args.reason:
            result["reason"] = args.reason

    state["interface_inventory"] = {"status": status, "result": result}
    complete_action_by_key(
        state,
        "inventory:interfaces",
        "DONE" if status in {"COMPLETE", "NOT_APPLICABLE"} else "FAILED",
        note=result.get("reason"),
    )
    state["events"].append(
        {"at": now_iso(), "type": "INTERFACE_INVENTORY", "status": status}
    )
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit(state_summary(state))


def command_submit_trace(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    edge_id = str(args.edge_id)
    edge = state["target"]["edges"].get(edge_id)
    if not edge:
        raise ValueError("目标边不存在")
    payload = parse_json_input(args.input, args.json)
    paths = payload.get("paths", payload) if isinstance(payload, dict) else payload
    if not isinstance(paths, list):
        raise ValueError("链路候选必须是数组，或包含 paths 数组")
    edge["trace_attempts"] += 1
    complete_action_by_key(state, f"trace:{edge_id}:round:{edge['trace_attempts']}")

    existing_chains = {item["chain"] for item in edge["paths"]}
    capacity = state["limits"]["max_edge_paths"] - len(edge["paths"])
    for index, path in enumerate(paths):
        item = {"chain": str(path)} if isinstance(path, str) else copy.deepcopy(path)
        chain = str(item.get("chain") or "").strip()
        if not chain or chain in existing_chains or capacity <= 0:
            continue
        path_id = str(item.get("id") or f"P{len(edge['paths']) + 1}")
        edge["paths"].append(
            {
                "id": path_id,
                "chain": chain,
                "evidence": item.get("evidence") or [],
                "semantics": item.get("semantics") or [],
                "verified": None,
                "verification_details": None,
            }
        )
        existing_chains.add(chain)
        capacity -= 1

    if not edge["paths"] and args.exhaustive:
        edge["status"] = "CONNECTION_MISSING"
        edge["finding"] = "追踪工具在声明的完整边界内确认不存在连接"
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit({"edge_id": edge_id, "status": edge["status"], "paths": edge["paths"]})


def bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("必须为 true 或 false")


def command_submit_chain(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    edge_id = str(args.edge_id)
    edge = state["target"]["edges"].get(edge_id)
    if not edge:
        raise ValueError("目标边不存在")
    path = next((item for item in edge["paths"] if item["id"] == args.path_id), None)
    if not path:
        raise ValueError("候选路径不存在")
    path["verified"] = args.verified
    path["verification_details"] = args.details or ""
    complete_action_by_key(
        state,
        f"chain:{edge_id}:{args.path_id}",
        "DONE" if args.verified else "FAILED",
    )
    if args.verified:
        edge["status"] = "VERIFIED"
        edge["verified_path_id"] = args.path_id
        edge["finding"] = "TOPOLOGY_EQUIVALENT"
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit({"edge_id": edge_id, "status": edge["status"], "path": path})


def command_submit_dependencies(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    block_id = str(args.block_id)
    block = state["target"]["blocks"].get(block_id)
    if not block or block["status"] != "SELECTED":
        raise ValueError("目标 Block 不存在或尚未映射")
    payload = parse_json_input(args.input, args.json)
    findings = payload.get("findings", payload) if isinstance(payload, dict) else payload
    if not isinstance(findings, list):
        raise ValueError("依赖检查结果必须是数组，或包含 findings 数组")
    block["dependency_findings"] = findings
    block["dependencies_status"] = args.status
    complete_action_by_key(state, f"dependencies:{block_id}")
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit({"block_id": block_id, "dependencies_status": block["dependencies_status"], "findings": findings})


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    blocks = list(state["target"]["blocks"].values())
    ports = list(state["target"]["ports"].values())
    edges = list(state["target"]["edges"].values())
    return {
        "analysis_id": state["analysis_id"],
        "phase": determine_phase(state),
        "state_revision": state["state_revision"],
        "budget": state["budget"],
        "target_counts": {
            "blocks": len(blocks),
            "ports": len(ports),
            "edges": len(edges),
            "issues": len(state["target"]["issues"]),
        },
        "progress": {
            "diagram_topology_render": state["diagram_topology_render"]["status"],
            "blocks_selected": sum(item["status"] == "SELECTED" for item in blocks),
            "blocks_unresolved": sum(item["status"] in {"UNRESOLVED", "HARD_CONFLICT"} for item in blocks),
            "ports_mapped": sum(item["status"] == "MAPPED" for item in ports),
            "edges_verified": sum(item["status"] == "VERIFIED" for item in edges),
            "edges_terminal": sum(item["status"] in TERMINAL_EDGE_STATES for item in edges),
            "interface_inventory": state["interface_inventory"]["status"],
        },
        "pending_actions": len(pending_actions(state)),
    }


def command_status(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    emit(state_summary(state))


def markdown_report(state: dict[str, Any]) -> str:
    target = state["target"]
    summary = state_summary(state)
    invalid_edges = sum(edge["status"] == "INVALID_TARGET" for edge in target["edges"].values())
    unresolved = sum(
        edge["status"] not in {"VERIFIED", "INVALID_TARGET"} for edge in target["edges"].values()
    )
    if target["edges"] and invalid_edges == len(target["edges"]):
        overall = "TARGET_DIAGRAM_INVALID"
    elif any(edge["status"] == "CONNECTION_MISSING" for edge in target["edges"].values()):
        overall = "INCONSISTENT"
    elif (
        unresolved
        or any(block["status"] != "SELECTED" for block in target["blocks"].values())
        or state["interface_inventory"]["status"] != "COMPLETE"
    ):
        overall = "PARTIALLY_CONSISTENT"
    else:
        overall = "CONSISTENT"

    lines = [
        "# 框图—原理图方案一致性分析",
        "",
        "## 结论与覆盖范围",
        "",
        f"- 总体状态：`{overall}`",
        f"- 分析 ID：`{state['analysis_id']}`",
        f"- 当前阶段：`{determine_phase(state)}`",
        f"- 框图拓扑 Graphviz：`{state['diagram_topology_render']['status']}`",
        f"- 查询预算：{state['budget']['used']}/{state['budget']['max']}",
        f"- Block：{summary['progress']['blocks_selected']}/{summary['target_counts']['blocks']} 已映射",
        f"- 原始信号接口清单：`{state['interface_inventory']['status']}`",
        f"- Port：{summary['progress']['ports_mapped']}/{summary['target_counts']['ports']} 已映射",
        f"- 目标边：{summary['progress']['edges_verified']}/{summary['target_counts']['edges']} 已通过 chain_check",
        "- 说明：本报告采用目标驱动的局部查询，不代表枚举了完整原理图。",
        "",
        "## 当前框图拓扑渲染",
        "",
        "| 状态 | DOT | SVG | 渲染器 |",
        "|---|---|---|---|",
        f"| {state['diagram_topology_render']['status']} | "
        f"{(state['diagram_topology_render'].get('result') or {}).get('dot_file', '-')} | "
        f"{(state['diagram_topology_render'].get('result') or {}).get('svg_file', '-')} | "
        f"{(state['diagram_topology_render'].get('result') or {}).get('renderer', '-')} |",
        "",
        "## 目标框图数据质量问题",
        "",
        "| 类型 | 对象 | 严重度 |",
        "|---|---|---|",
    ]
    if target["issues"]:
        for issue in target["issues"]:
            obj = issue.get("object_id") or issue.get("wire_id") or issue.get("block_id") or "-"
            lines.append(f"| {issue.get('type')} | {obj} | {issue.get('severity', '-')} |")
    else:
        lines.append("| 无 | - | - |")

    lines += [
        "",
        "## 原始信号接口事实基线",
        "",
        "| 状态 | 覆盖范围 | 接口文件 | 说明 |",
        "|---|---|---|---|",
    ]
    inventory = state["interface_inventory"]
    inventory_result = inventory.get("result") or {}
    coverage = inventory_result.get("coverage") or {}
    coverage_text = (
        f"Block {coverage.get('selected_blocks', '-')}; "
        f"Pin {coverage.get('pins_classified', '-')}/{coverage.get('pins_total', '-')}; "
        f"Interface {coverage.get('interfaces', '-')}"
    )
    lines.append(
        f"| {inventory['status']} | {coverage_text} | "
        f"{inventory_result.get('interfaces_file', '-')} | {inventory_result.get('reason', '-')} |"
    )

    lines += [
        "",
        "## Block 与实现映射",
        "",
        "| 目标 Block | 状态 | 原理图实现 | 得分 |",
        "|---|---|---|---:|",
    ]
    for block_id in target["ordered_blocks"]:
        block = target["blocks"][block_id]
        selected = block.get("selected") or {}
        implementation = selected.get("refdes") or selected.get("cbb_id") or selected.get("id") or "-"
        score = selected.get("score")
        score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "-"
        lines.append(f"| {block['name']} (`{block_id}`) | {block['status']} | {implementation} | {score_text} |")

    lines += [
        "",
        "## Port/Pin/Net 映射",
        "",
        "| 目标 Port | 状态 | 原理图 Pin/Net |",
        "|---|---|---|",
    ]
    for port in target["ports"].values():
        mapping = port.get("mapping") or {}
        endpoint = "/".join(
            str(value)
            for value in [mapping.get("refdes"), mapping.get("pin"), mapping.get("net")]
            if value
        ) or "-"
        lines.append(f"| {port['name'] or '(未命名)'} (`{port['id']}`) | {port['status']} | {endpoint} |")

    lines += [
        "",
        "## 目标连接验证",
        "",
        "| 目标边 | 状态 | 已验证链路/说明 |",
        "|---|---|---|",
    ]
    for edge in target["edges"].values():
        verified = next((item for item in edge["paths"] if item["id"] == edge.get("verified_path_id")), None)
        detail = verified["chain"] if verified else edge.get("finding") or "-"
        lines.append(f"| `{edge['id']}` | {edge['status']} | {detail} |")

    lines += [
        "",
        "## 局部依赖检查",
        "",
        "| 目标 Block | 状态 | 发现项 |",
        "|---|---|---|",
    ]
    for block_id in target["ordered_blocks"]:
        block = target["blocks"][block_id]
        if block["status"] != "SELECTED":
            continue
        detail = json.dumps(block["dependency_findings"], ensure_ascii=False) if block["dependency_findings"] else "-"
        lines.append(f"| {block['name']} | {block['dependencies_status']} | {detail} |")

    lines += [
        "",
        "## ECO 候选边界",
        "",
        "本控制器只维护分析证据，不执行原理图修改。未映射、未验证或存在硬冲突的项目只能形成调查或 ECO 候选。",
        "",
    ]
    return "\n".join(lines)


def command_report(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    report = markdown_report(state)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report + "\n", encoding="utf-8")
        emit({"output": str(output), "phase": determine_phase(state)})
    else:
        print(report)


def self_test() -> None:
    diagram = {
        "type": "block",
        "version": 4,
        "graph": {
            "type": "graph",
            "id": 0,
            "children": [
                {
                    "type": "block",
                    "id": 1,
                    "name": "MCU",
                    "business": {"model": "MCU", "code": "MCU-001"},
                    "children": [
                        {"type": "port", "id": 11, "parentId": 1, "name": "EN", "business": {"direction": "OUT"}}
                    ],
                },
                {
                    "type": "block",
                    "id": 2,
                    "name": "负载开关",
                    "business": {"model": "LOAD_SWITCH", "code": "SW-001"},
                    "children": [
                        {"type": "port", "id": 21, "parentId": 2, "name": "EN", "business": {"direction": "IN"}}
                    ],
                },
                {
                    "type": "wire",
                    "id": 31,
                    "business": {"source": 11, "target": 21},
                    "children": [],
                },
            ],
        },
    }
    target = normalize_diagram(diagram, None)
    assert len(target["blocks"]) == 2
    assert target["edges"]["31"]["status"] == "PENDING"
    assert target["ordered_blocks"]
    assert score_candidate(
        {
            "identity_score": 1,
            "capability_score": 1,
            "port_score": 1,
            "neighborhood_score": 1,
        }
    ) == 1.0
    broken = copy.deepcopy(diagram)
    broken["graph"]["children"][2]["business"]["target"] = 999
    broken_target = normalize_diagram(broken, None)
    assert broken_target["edges"]["31"]["status"] == "INVALID_TARGET"
    assert any(item["type"] == "BROKEN_WIRE_REFERENCE" for item in broken_target["issues"])
    candidate_template = {
        "kind": "COMPONENT",
        "mapping_role": "IMPLEMENTS",
        "identity_score": 1.0,
        "capability_score": 1.0,
        "port_score": 1.0,
        "neighborhood_score": 1.0,
        "hard_conflicts": [],
        "evidence": ["self-test"],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        diagram_path = Path(temp_dir) / "diagram.json"
        state_path = Path(temp_dir) / "state.json"
        diagram_path.write_text(json.dumps(diagram, ensure_ascii=False), encoding="utf-8")
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            command_init(
                argparse.Namespace(
                    diagram=str(diagram_path),
                    state=str(state_path),
                    analysis_id="self-test",
                    solution_id="solution",
                    schematic_id="schematic",
                    board_id="board",
                    scope_blocks=None,
                    query_budget=30,
                    max_block_rounds=2,
                    max_edge_paths=3,
                    max_edge_trace_rounds=2,
                    select_threshold=0.78,
                    select_margin=0.12,
                )
            )
            initial_state = load_state(state_path)
            assert determine_phase(initial_state) == "RENDER_DIAGRAM_TOPOLOGY"
            assert any(
                item["kind"] == "RENDER_DIAGRAM_TOPOLOGY"
                for item in pending_actions(initial_state)
            )
            topology_dot = Path(temp_dir) / "diagram-topology.dot"
            topology_svg = Path(temp_dir) / "diagram-topology.svg"
            topology_dot.write_text("digraph diagram_topology {}\n", encoding="utf-8")
            topology_svg.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n", encoding="utf-8")
            command_record_topology_render(
                argparse.Namespace(
                    state=str(state_path),
                    input=None,
                    json=json.dumps(
                        {
                            "analysis_id": "self-test",
                            "diagram_sha256": initial_state["diagram_sha256"],
                            "renderer": "graphviz-dot",
                            "dot_file": str(topology_dot),
                            "svg_file": str(topology_svg),
                            "dot_sha256": file_sha256(topology_dot),
                            "svg_sha256": file_sha256(topology_svg),
                        }
                    ),
                )
            )
            assert determine_phase(load_state(state_path)) == "SCHEMATIC_OVERVIEW"
            for kind in ("summary", "sheets"):
                command_record_overview(
                    argparse.Namespace(
                        state=str(state_path), kind=kind, status="SUCCESS", input=None, json="{}"
                    )
                )
            for block_id, refdes in (("1", "U1"), ("2", "U2")):
                candidate = copy.deepcopy(candidate_template)
                candidate.update({"id": f"component:{refdes}", "refdes": refdes})
                command_submit_blocks(
                    argparse.Namespace(
                        state=str(state_path),
                        block_id=block_id,
                        input=None,
                        json=json.dumps({"candidates": [candidate]}),
                    )
                )
            gated_state = load_state(state_path)
            assert determine_phase(gated_state) == "INVENTORY_SCHEMATIC_INTERFACES"
            scheduled = pending_actions(gated_state)
            assert any(item["kind"] == "RUN_INTERFACE_INVENTORY" for item in scheduled)
            command_record_interface_inventory(
                argparse.Namespace(
                    state=str(state_path),
                    status="COMPLETE",
                    reason=None,
                    input=None,
                    json=json.dumps(
                        {
                            "interfaces_file": "original-interfaces.json",
                            "coverage": {
                                "selected_blocks": 2,
                                "pins_total": 2,
                                "pins_classified": 2,
                                "interfaces": 1,
                                "verified": 1,
                                "unresolved": 0,
                            },
                            "evidence": ["chain_check:self-test"],
                        }
                    ),
                )
            )
            command_submit_ports(
                argparse.Namespace(
                    state=str(state_path),
                    block_id="1",
                    threshold=0.75,
                    input=None,
                    json=json.dumps(
                        {
                            "bindings": [
                                {
                                    "port_id": "11",
                                    "refdes": "U1",
                                    "pin": "1",
                                    "net": "ENABLE",
                                    "score": 1.0,
                                }
                            ]
                        }
                    ),
                )
            )
            command_submit_ports(
                argparse.Namespace(
                    state=str(state_path),
                    block_id="2",
                    threshold=0.75,
                    input=None,
                    json=json.dumps(
                        {
                            "bindings": [
                                {
                                    "port_id": "21",
                                    "refdes": "U2",
                                    "pin": "2",
                                    "net": "ENABLE",
                                    "score": 1.0,
                                }
                            ]
                        }
                    ),
                )
            )
            command_submit_trace(
                argparse.Namespace(
                    state=str(state_path),
                    edge_id="31",
                    exhaustive=False,
                    input=None,
                    json=json.dumps({"paths": [{"id": "P1", "chain": "U1[1] → U2[2]"}]}),
                )
            )
            command_submit_chain(
                argparse.Namespace(
                    state=str(state_path),
                    edge_id="31",
                    path_id="P1",
                    verified=True,
                    details="self-test verified",
                )
            )
            for block_id in ("1", "2"):
                command_submit_dependencies(
                    argparse.Namespace(
                        state=str(state_path),
                        block_id=block_id,
                        status="NOT_APPLICABLE",
                        input=None,
                        json="[]",
                    )
                )
        final_state = load_state(state_path)
        assert determine_phase(final_state) == "DONE"
        assert final_state["target"]["edges"]["31"]["status"] == "VERIFIED"
        assert "`CONSISTENT`" in markdown_report(final_state)
    emit({"self_test": "PASS", "tests": 14})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="框图—原理图一致性分析状态控制器")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="从 querySolutionDesign JSON 初始化状态")
    init.add_argument("--diagram", required=True)
    init.add_argument("--state", required=True)
    init.add_argument("--analysis-id")
    init.add_argument("--solution-id")
    init.add_argument("--schematic-id")
    init.add_argument("--board-id")
    init.add_argument("--scope-blocks", help="逗号分隔的 Block ID")
    init.add_argument("--query-budget", type=int, default=30)
    init.add_argument("--max-block-rounds", type=int, default=2)
    init.add_argument("--max-edge-paths", type=int, default=3)
    init.add_argument("--max-edge-trace-rounds", type=int, default=2)
    init.add_argument("--select-threshold", type=float, default=0.78)
    init.add_argument("--select-margin", type=float, default=0.12)
    init.set_defaults(func=command_init)

    next_cmd = sub.add_parser("next", help="返回下一批待执行动作")
    next_cmd.add_argument("--state", required=True)
    next_cmd.add_argument("--limit", type=int, default=2)
    next_cmd.set_defaults(func=command_next)

    topology = sub.add_parser(
        "record-topology-render", help="登记 Graphviz 生成的当前框图拓扑 DOT/SVG"
    )
    topology.add_argument("--state", required=True)
    topology.add_argument("--input")
    topology.add_argument("--json")
    topology.set_defaults(func=command_record_topology_render)

    overview = sub.add_parser("record-overview", help="记录概要或图页查询结果")
    overview.add_argument("--state", required=True)
    overview.add_argument("--kind", choices=["summary", "sheets"], required=True)
    overview.add_argument("--status", choices=["SUCCESS", "FAILED"], default="SUCCESS")
    overview.add_argument("--input")
    overview.add_argument("--json")
    overview.set_defaults(func=command_record_overview)

    blocks = sub.add_parser("submit-blocks", help="提交某个 Block 的规范化候选")
    blocks.add_argument("--state", required=True)
    blocks.add_argument("--block-id", required=True)
    blocks.add_argument("--input")
    blocks.add_argument("--json")
    blocks.set_defaults(func=command_submit_blocks)

    select = sub.add_parser("select-block", help="人工确认一个候选")
    select.add_argument("--state", required=True)
    select.add_argument("--block-id", required=True)
    select.add_argument("--candidate-id", required=True)
    select.add_argument("--note")
    select.add_argument("--override-conflict", action="store_true")
    select.set_defaults(func=command_select_block)

    inventory = sub.add_parser(
        "record-interface-inventory", help="记录并冻结旧原理图原始信号接口事实基线"
    )
    inventory.add_argument("--state", required=True)
    inventory.add_argument(
        "--status", choices=["COMPLETE", "PARTIAL", "NOT_APPLICABLE"], required=True
    )
    inventory.add_argument("--reason")
    inventory.add_argument("--input")
    inventory.add_argument("--json")
    inventory.set_defaults(func=command_record_interface_inventory)

    ports = sub.add_parser("submit-ports", help="批量提交 Block 的 Port 映射")
    ports.add_argument("--state", required=True)
    ports.add_argument("--block-id", required=True)
    ports.add_argument("--threshold", type=float, default=0.75)
    ports.add_argument("--input")
    ports.add_argument("--json")
    ports.set_defaults(func=command_submit_ports)

    trace = sub.add_parser("submit-trace", help="提交目标边的候选链路")
    trace.add_argument("--state", required=True)
    trace.add_argument("--edge-id", required=True)
    trace.add_argument("--exhaustive", type=bool_arg, default=False)
    trace.add_argument("--input")
    trace.add_argument("--json")
    trace.set_defaults(func=command_submit_trace)

    chain = sub.add_parser("submit-chain", help="提交 chain_check 结果")
    chain.add_argument("--state", required=True)
    chain.add_argument("--edge-id", required=True)
    chain.add_argument("--path-id", required=True)
    chain.add_argument("--verified", type=bool_arg, required=True)
    chain.add_argument("--details")
    chain.set_defaults(func=command_submit_chain)

    dependencies = sub.add_parser("submit-dependencies", help="提交局部依赖检查结果")
    dependencies.add_argument("--state", required=True)
    dependencies.add_argument("--block-id", required=True)
    dependencies.add_argument(
        "--status", choices=["CHECKED", "NOT_APPLICABLE", "INSUFFICIENT_INFORMATION"], default="CHECKED"
    )
    dependencies.add_argument("--input")
    dependencies.add_argument("--json")
    dependencies.set_defaults(func=command_submit_dependencies)

    status = sub.add_parser("status", help="查看分析进度")
    status.add_argument("--state", required=True)
    status.set_defaults(func=command_status)

    report = sub.add_parser("report", help="生成 Markdown 报告")
    report.add_argument("--state", required=True)
    report.add_argument("--output")
    report.set_defaults(func=command_report)

    test = sub.add_parser("self-test", help="运行控制器自测试")
    test.set_defaults(func=lambda _args: self_test())
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        args.func(args)
        return 0
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        emit({"error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
