"""把一致性状态与原理图原始接口事实合成为逐信号增删改结论。仅用标准库。"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


SUPPORT_CATEGORIES = {"POWER", "GROUND", "NC"}
SUPPORT_SCOPES = {"LOCAL_SUPPORT", "POWER_SUPPORT", "TEST_DEBUG"}
DECISIONS = {"KEEP", "ADD", "MODIFY", "DELETE", "IMPLEMENTATION_DETAIL", "UNRESOLVED"}
CN = {
    "KEEP": "保留", "ADD": "新增", "MODIFY": "修改", "DELETE": "删除",
    "IMPLEMENTATION_DETAIL": "实现细节保留", "UNRESOLVED": "待确认",
}


def load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def block_identity(target: dict[str, Any], block_id: str | None) -> dict[str, str]:
    if block_id is None:
        return {"id": "", "name": ""}
    block = target.get("blocks", {}).get(str(block_id), {})
    graph_id = target.get("graph_id")
    compound = f"{graph_id}-{block_id}" if graph_id is not None else str(block_id)
    return {"id": compound, "name": str(block.get("name") or "")}


def pin_name(mapping: dict[str, Any]) -> str:
    return str(mapping.get("pin_name") or "")


def port_endpoint(target: dict[str, Any], port_id: str | None) -> dict[str, Any]:
    port = target.get("ports", {}).get(str(port_id), {})
    block = block_identity(target, port.get("block_id"))
    mapping = port.get("mapping") or {}
    return {
        "block_id": block["id"], "block_name": block["name"],
        "port_id": str(port.get("id") or ""), "port_name": str(port.get("name") or ""),
        "refdes": str(mapping.get("refdes") or ""), "pin_name": pin_name(mapping),
        "net_name": str(mapping.get("net") or ""), "mapping_status": str(port.get("status") or ""),
        "mapping_score": mapping.get("score"),
    }


def text_haystack(row: dict[str, Any]) -> str:
    pins = " ".join(str(item.get("name") or "") for item in row.get("pins", []))
    return " ".join([
        str(row.get("refdes") or ""), pins, str(row.get("net_name") or ""),
        str(row.get("verified_chain") or ""), " ".join(map(str, row.get("remote_endpoints") or [])),
    ])


def endpoint_score(row: dict[str, Any], source: dict[str, Any], target: dict[str, Any], chain: str) -> int:
    score = 0
    row_chain = str(row.get("verified_chain") or "")
    if chain and row_chain and chain == row_chain:
        score += 100
    hay = text_haystack(row)
    for endpoint in (source, target):
        if endpoint["refdes"] and endpoint["refdes"] in hay:
            score += 10
        if endpoint["pin_name"] and endpoint["pin_name"] in hay:
            score += 6
        if endpoint["net_name"] and endpoint["net_name"] in hay:
            score += 4
    return score


def normalize_interfaces(payload: Any) -> list[dict[str, Any]]:
    rows = payload.get("interfaces", payload) if isinstance(payload, dict) else payload
    require(isinstance(rows, list), "原始接口文件必须是数组或包含 interfaces 数组")
    result = []
    ids: set[str] = set()
    for raw in rows:
        require(isinstance(raw, dict) and raw.get("interface_id"), "每条原始接口必须有 interface_id")
        row = copy.deepcopy(raw)
        iid = str(row["interface_id"])
        require(iid not in ids, f"原始接口ID重复：{iid}")
        ids.add(iid)
        row["interface_id"] = iid
        result.append(row)
    return result


def verified_chain(edge: dict[str, Any]) -> str:
    path_id = edge.get("verified_path_id")
    path = next((item for item in edge.get("paths", []) if item.get("id") == path_id), None)
    return str((path or {}).get("chain") or "")


def automatic_rows(consistency: dict[str, Any], interfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target = consistency["target"]
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    for edge_id, edge in target.get("edges", {}).items():
        source = port_endpoint(target, edge.get("source_port_id"))
        destination = port_endpoint(target, edge.get("target_port_id"))
        chain = verified_chain(edge)
        ranked = sorted(
            ((endpoint_score(row, source, destination, chain), row) for row in interfaces),
            key=lambda item: (-item[0], item[1]["interface_id"]),
        )
        matched = ranked[0][1] if ranked and ranked[0][0] >= 16 else None
        status = str(edge.get("status") or "")
        if status == "VERIFIED" and matched:
            action, reason, evidence = "KEEP", "框图目标边存在已验证的原理图实现链路", [f"edge:{edge_id}:VERIFIED", chain]
            used.add(matched["interface_id"])
        elif status == "CONNECTION_MISSING":
            action, reason, evidence = "ADD", "目标框图连接在声明的完整原理图查询边界内不存在", [f"edge:{edge_id}:CONNECTION_MISSING"]
        else:
            action, reason, evidence = "UNRESOLVED", "目标边或原始接口对应关系尚未达到确定性判定条件", [f"edge:{edge_id}:{status or 'UNKNOWN'}"]
            if matched:
                used.add(matched["interface_id"])
        result.append({
            "delta_id": f"EDGE-{edge_id}", "action": action, "target_edge_id": str(edge_id),
            "original_interface_id": matched["interface_id"] if matched else "",
            "source": source, "destination": destination,
            "source_pin_name": source["pin_name"],
            "original_net_name": str((matched or {}).get("net_name") or ""),
            "target_net_name": source.get("net_name") or destination.get("net_name") or "",
            "connection_change": action,
            "reason": reason, "evidence": evidence,
            "requires_connection_mapping": action == "ADD",
        })

    for row in interfaces:
        if row["interface_id"] in used:
            continue
        is_support = row.get("category") in SUPPORT_CATEGORIES or row.get("scope_class") in SUPPORT_SCOPES
        action = "IMPLEMENTATION_DETAIL" if is_support else "UNRESOLVED"
        reason = "框图可省略的电源、局部支撑或测试实现" if is_support else "原理图接口未映射到目标边；不能仅因框图未显示而删除"
        result.append({
            "delta_id": f"ORIGINAL-{row['interface_id']}", "action": action, "target_edge_id": "",
            "original_interface_id": row["interface_id"], "source": {}, "destination": {},
            "source_pin_name": "", "original_net_name": str(row.get("net_name") or ""),
            "target_net_name": str(row.get("net_name") or ""), "connection_change": action,
            "reason": reason, "evidence": [f"interface:{row['interface_id']}:{row.get('status', 'UNKNOWN')}"],
            "requires_connection_mapping": False,
        })
    return result


def apply_decisions(rows: list[dict[str, Any]], payload: Any) -> None:
    decisions = payload.get("decisions", payload) if isinstance(payload, dict) else payload
    require(isinstance(decisions, list), "人工/模型判定必须是数组或包含 decisions 数组")
    by_id = {row["delta_id"]: row for row in rows}
    touched: set[str] = set()
    for decision in decisions:
        did = str(decision.get("delta_id") or "")
        require(did in by_id and did not in touched, f"差异判定ID不存在或重复：{did}")
        action = str(decision.get("action") or "")
        require(action in DECISIONS, f"不支持的接口操作：{action}")
        require(decision.get("reason") and decision.get("evidence"), "覆盖自动判定必须提供原因和证据")
        row = by_id[did]
        if action == "DELETE":
            require(row.get("original_interface_id"), "删除必须引用原始接口")
            require(decision.get("confirmed_functional_removal") is True, "删除必须明确确认功能已移除，不能由框图省略推导")
        if action == "ADD":
            require(row.get("target_edge_id"), "新增必须引用目标框图边")
        if action == "MODIFY":
            require(row.get("original_interface_id") and row.get("target_edge_id"), "修改必须同时绑定原始接口和目标边")
        row.update({key: copy.deepcopy(value) for key, value in decision.items() if key != "delta_id"})
        row["action"] = action
        row["requires_connection_mapping"] = bool(decision.get("requires_connection_mapping", action == "ADD"))
        touched.add(did)


def build(consistency: dict[str, Any], interface_payload: Any, decisions: Any | None = None) -> dict[str, Any]:
    require("target" in consistency and "analysis_id" in consistency, "一致性状态格式无效")
    interfaces = normalize_interfaces(interface_payload)
    rows = automatic_rows(consistency, interfaces)
    if decisions is not None:
        apply_decisions(rows, decisions)
    mapping_tasks = []
    for row in rows:
        if row["action"] in {"ADD", "MODIFY"} and row.get("requires_connection_mapping"):
            mapping_tasks.append({
                "delta_id": row["delta_id"], "skill": "diagram-logical-connection-mapping",
                "reason": "新增器件、增加连接或源端Pin需要重新分配",
                "source": row.get("source", {}), "destination": row.get("destination", {}),
            })
    counts = {key: sum(row["action"] == key for row in rows) for key in DECISIONS}
    return {
        "schema_version": 1, "analysis_id": consistency["analysis_id"],
        "diagram_sha256": consistency.get("diagram_sha256"),
        "original_interface_count": len(interfaces), "delta_counts": counts,
        "original_interfaces": interfaces, "signal_deltas": rows,
        "connection_mapping_tasks": mapping_tasks,
        "complete": counts["UNRESOLVED"] == 0,
    }


def markdown(answer: dict[str, Any]) -> str:
    counts = answer["delta_counts"]
    lines = [
        "# 框图—原理图拓扑与信号接口一致性结论", "",
        "## 覆盖和结论", "",
        f"- 原始信号接口：{answer['original_interface_count']}",
        f"- 保留：{counts['KEEP']}；新增：{counts['ADD']}；修改：{counts['MODIFY']}；删除：{counts['DELETE']}",
        f"- 实现细节保留：{counts['IMPLEMENTATION_DETAIL']}；待确认：{counts['UNRESOLVED']}",
        f"- 是否完成：{'是' if answer['complete'] else '否，仍有待确认项'}", "",
        "## 逐信号差异", "",
        "| 操作 | 源Block/Port | 目的Block/Port | 源端Pin名称 | 原网络名 | 原始接口 | 原因 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in answer["signal_deltas"]:
        source, destination = row.get("source", {}), row.get("destination", {})
        source_text = f"{source.get('block_id','')} {source.get('block_name','')}/{source.get('port_name','')}".strip(" /") or "-"
        destination_text = f"{destination.get('block_id','')} {destination.get('block_name','')}/{destination.get('port_name','')}".strip(" /") or "-"
        lines.append(
            f"| {CN[row['action']]} | {source_text} | {destination_text} | {row.get('source_pin_name') or '-'} | "
            f"{row.get('original_net_name') or '-'} | {row.get('original_interface_id') or '-'} | {row['reason']} |"
        )
    lines += ["", "## 新增/改线 Pin 映射任务", ""]
    if answer["connection_mapping_tasks"]:
        lines.append("以下项目调用 `diagram-logical-connection-mapping`；该 Skill 只分配/校验源端 Pin，不负责网络命名。")
        for task in answer["connection_mapping_tasks"]:
            lines.append(f"- `{task['delta_id']}`：{task['reason']}")
    else:
        lines.append("无。")
    lines += ["", "## 判定边界", "", "未映射到框图的原理图接口默认是待确认或实现细节，不能自动删除。新增和修改在完成 Pin 映射、网络命名及必要链路复核前均属于设计提案。", ""]
    return "\n".join(lines)


def self_test() -> None:
    state = {"analysis_id": "T", "diagram_sha256": "x", "target": {"graph_id": 0,
        "blocks": {"1": {"name": "MCU"}, "2": {"name": "Flash"}, "3": {"name": "Sensor"}},
        "ports": {
            "11": {"id": "11", "block_id": "1", "name": "SPI", "status": "MAPPED", "mapping": {"refdes": "U1", "pin_name": "SCK", "net": "SPI_CLK"}},
            "21": {"id": "21", "block_id": "2", "name": "SPI", "status": "MAPPED", "mapping": {"refdes": "U2", "pin_name": "CLK", "net": "SPI_CLK"}},
            "12": {"id": "12", "block_id": "1", "name": "GPIO", "status": "MAPPED", "mapping": {"refdes": "U1", "pin_name": "GPIO1", "net": ""}},
            "31": {"id": "31", "block_id": "3", "name": "INT", "status": "MAPPED", "mapping": {"refdes": "U3", "pin_name": "INT", "net": ""}},
        },
        "edges": {
            "E1": {"source_port_id": "11", "target_port_id": "21", "status": "VERIFIED", "verified_path_id": "P1", "paths": [{"id": "P1", "chain": "U1[SCK] -> U2[CLK]"}]},
            "E2": {"source_port_id": "12", "target_port_id": "31", "status": "CONNECTION_MISSING", "paths": []},
        }}}
    interfaces = {"interfaces": [
        {"interface_id": "I1", "refdes": "U1", "pins": [{"name": "SCK"}], "net_name": "SPI_CLK", "verified_chain": "U1[SCK] -> U2[CLK]", "status": "VERIFIED", "category": "DATA", "scope_class": "EXTERNAL_SIGNAL"},
        {"interface_id": "I2", "refdes": "U1", "pins": [{"name": "VDD"}], "net_name": "3V3", "status": "STRUCTURED_ONLY", "category": "POWER", "scope_class": "POWER_SUPPORT"},
        {"interface_id": "I3", "refdes": "U1", "pins": [{"name": "TX"}], "net_name": "DEBUG_TX", "status": "VERIFIED", "category": "DATA", "scope_class": "EXTERNAL_SIGNAL"},
    ]}
    answer = build(state, interfaces)
    assert answer["delta_counts"]["KEEP"] == 1
    assert answer["delta_counts"]["ADD"] == 1
    assert answer["delta_counts"]["IMPLEMENTATION_DETAIL"] == 1
    assert answer["delta_counts"]["UNRESOLVED"] == 1
    assert answer["connection_mapping_tasks"][0]["skill"] == "diagram-logical-connection-mapping"
    add = next(row for row in answer["signal_deltas"] if row["action"] == "ADD")
    assert add["source_pin_name"] == "GPIO1"
    delete_decision = {"decisions": [{"delta_id": "ORIGINAL-I3", "action": "DELETE", "reason": "确认移除调试功能", "evidence": ["review:1"], "confirmed_functional_removal": True}]}
    answer2 = build(state, interfaces, delete_decision)
    assert answer2["delta_counts"]["DELETE"] == 1
    try:
        build(state, interfaces, {"decisions": [{"delta_id": "ORIGINAL-I3", "action": "DELETE", "reason": "框图没画", "evidence": ["name-only"]}]})
    except ValueError:
        pass
    else:
        raise AssertionError("未确认的删除不应通过")
    print(json.dumps({"self_test": "PASS", "tests": 7}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "self-test"])
    parser.add_argument("--consistency-state")
    parser.add_argument("--interfaces")
    parser.add_argument("--decisions")
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return 0
        require(args.consistency_state and args.interfaces and args.json_output and args.markdown_output,
                "build 需要一致性状态、原始接口、JSON输出和Markdown输出")
        answer = build(load(args.consistency_state), load(args.interfaces), load(args.decisions) if args.decisions else None)
        write(args.json_output, answer)
        path = Path(args.markdown_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown(answer), encoding="utf-8")
        print(json.dumps({"json": args.json_output, "markdown": args.markdown_output, "complete": answer["complete"]}, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
