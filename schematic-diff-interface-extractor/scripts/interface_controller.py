#!/usr/bin/env python3
"""差异器件外围信号接口提取状态控制器。

本脚本不直接调用 MCP；它维护差异器件、Pin/Net 接口种子、局部追踪动作、
chain_check 结果和查询预算。模型仅执行 next 返回的动作并提交精简证据。
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import csv
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


SCHEMA_VERSION = 1
TERMINAL_INTERFACE_STATES = {
    "VERIFIED",
    "STRUCTURED_ONLY",
    "UNCONNECTED",
    "NO_REMOTE_CONNECTION",
    "NOT_OBSERVED_WITHIN_SCOPE",
    "UNVERIFIED_PATH",
    "SKIPPED_NC",
}
ALLOWED_SCOPE_CLASSES = {
    "EXTERNAL_SIGNAL",
    "LOCAL_SUPPORT",
    "POWER_SUPPORT",
    "TEST_DEBUG",
    "UNKNOWN",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_json(path: str | Path) -> Any:
    if str(path) == "-":
        return json.load(sys.stdin)
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_payload(input_path: str | None, json_text: str | None) -> Any:
    if input_path:
        return load_json(input_path)
    if json_text:
        return json.loads(json_text)
    raise ValueError("必须提供 --input 或 --json")


def atomic_save(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False
    ) as handle:
        handle.write(data)
        temp_name = handle.name
    os.replace(temp_name, target)


def load_state(path: str | Path) -> dict[str, Any]:
    state = load_json(path)
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("状态文件版本不兼容")
    return state


def touch(state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    state["state_revision"] = int(state.get("state_revision", 0)) + 1


def canonical(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[\s\-+/\\.#]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def first(item: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in item and item[name] is not None:
            return item[name]
    return default


def bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("必须为 true 或 false")


def stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]}"


def extract_explicit_devices(payload: Any) -> list[dict[str, Any]]:
    devices = payload.get("devices", payload) if isinstance(payload, dict) else payload
    if not isinstance(devices, list):
        raise ValueError("差异输入必须为数组，或包含 devices 数组")
    result = []
    for index, raw in enumerate(devices):
        if not isinstance(raw, dict):
            raise ValueError("每个差异器件必须是对象")
        refdes = str(first(raw, "refdes", "reference", "designator", default="")).strip()
        cbb_id = str(first(raw, "cbb_id", "cbbId", default="")).strip()
        if not refdes and not cbb_id:
            raise ValueError("差异器件必须至少包含 refdes 或 cbb_id")
        target_block = copy.deepcopy(raw.get("target_block") or {})
        target_ports = copy.deepcopy(raw.get("target_ports") or [])
        difference_types = raw.get("difference_types") or raw.get("differences") or []
        if isinstance(difference_types, str):
            difference_types = [difference_types]
        device_id = str(raw.get("id") or stable_id("DEV", refdes, cbb_id, index))
        result.append(
            {
                "id": device_id,
                "refdes": refdes,
                "cbb_id": cbb_id,
                "current_part": str(raw.get("current_part") or ""),
                "proposed_part": str(raw.get("proposed_part") or ""),
                "target_block": target_block,
                "target_ports": target_ports,
                "difference_types": list(difference_types),
                "reason": str(raw.get("reason") or ""),
            }
        )
    return result


def extract_from_upstream(upstream: dict[str, Any], include_all: bool) -> list[dict[str, Any]]:
    target = upstream.get("target") or {}
    blocks = target.get("blocks") or {}
    ports = target.get("ports") or {}
    edges = target.get("edges") or {}
    result = []

    for block_id, block in blocks.items():
        selected = block.get("selected") or {}
        refdes = str(selected.get("refdes") or "")
        cbb_id = str(selected.get("cbb_id") or "")
        if not refdes and not cbb_id:
            continue
        differences: list[str] = []
        selected_diffs = selected.get("difference_types") or []
        if isinstance(selected_diffs, str):
            selected_diffs = [selected_diffs]
        differences.extend(str(value) for value in selected_diffs)

        block_ports = [ports.get(str(port_id)) for port_id in block.get("ports", [])]
        block_ports = [port for port in block_ports if port]
        if any(port.get("status") != "MAPPED" for port in block_ports):
            differences.append("PORT_MAPPING_DIFFERENCE")

        for edge in edges.values():
            source = ports.get(str(edge.get("source_port_id")))
            target_port = ports.get(str(edge.get("target_port_id")))
            endpoint_blocks = {
                source.get("block_id") if source else None,
                target_port.get("block_id") if target_port else None,
            }
            if str(block_id) in {str(value) for value in endpoint_blocks if value is not None}:
                if edge.get("status") != "VERIFIED":
                    differences.append(str(edge.get("finding") or edge.get("status") or "TOPOLOGY_DIFFERENCE"))

        for finding in block.get("dependency_findings") or []:
            if isinstance(finding, dict):
                status = str(finding.get("status") or "")
                if status not in {"CONSISTENT", "OK", "PASS"}:
                    differences.append(str(finding.get("type") or "DEPENDENCY_DIFFERENCE"))

        differences = sorted(set(filter(None, differences)))
        if not differences and not include_all:
            continue
        target_port_summary = [
            {
                "id": str(port.get("id")),
                "name": port.get("name") or "",
                "direction": port.get("direction") or "UNKNOWN",
                "protocol": port.get("protocol") or "",
                "voltage": port.get("voltage") or "",
                "status": port.get("status") or "",
            }
            for port in block_ports
        ]
        result.append(
            {
                "id": stable_id("DEV", upstream.get("analysis_id"), block_id, refdes, cbb_id),
                "refdes": refdes,
                "cbb_id": cbb_id,
                "current_part": str(selected.get("part_number") or ""),
                "proposed_part": "",
                "target_block": {"id": str(block_id), "name": block.get("name") or ""},
                "target_ports": target_port_summary,
                "difference_types": differences or ["UPSTREAM_SELECTED_BLOCK"],
                "reason": "由 schematic-consistency-controller 状态导入",
            }
        )
    return result


def explicit_refdes_devices(refdes_text: str | None) -> list[dict[str, Any]]:
    result = []
    for value in filter(None, (refdes_text or "").split(",")):
        refdes = value.strip().upper()
        result.append(
            {
                "id": stable_id("DEV", refdes),
                "refdes": refdes,
                "cbb_id": "",
                "current_part": "",
                "proposed_part": "",
                "target_block": {},
                "target_ports": [],
                "difference_types": ["USER_SELECTED_DIFFERENCE_DEVICE"],
                "reason": "用户显式指定",
            }
        )
    return result


def dedupe_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for device in devices:
        key = (device.get("refdes", "").upper(), device.get("cbb_id", ""))
        if key not in merged:
            merged[key] = copy.deepcopy(device)
            continue
        current = merged[key]
        current["difference_types"] = sorted(
            set(current.get("difference_types", [])) | set(device.get("difference_types", []))
        )
        current["target_ports"] = current.get("target_ports") or device.get("target_ports") or []
        current["target_block"] = current.get("target_block") or device.get("target_block") or {}
    return list(merged.values())


def category_for_pin(pin_name: str, net_name: str, electrical_type: str) -> str:
    text = canonical(f"{pin_name}_{net_name}_{electrical_type}")
    if re.search(r"(^|_)(NC|N_C|DNC|NO_CONNECT)($|_)", text):
        return "NC"
    if re.search(r"(^|_)(GND|AGND|DGND|PGND|VSS|GROUND)($|_)", text):
        return "GROUND"
    if re.search(r"(^|_)(VCC|VDD|AVDD|DVDD|PVDD|VCORE|VBAT|VIN|VOUT|VREFP|VREFN)($|_)", text):
        return "POWER"
    if re.search(r"CLK|CLOCK|XTAL|XIN|XOUT|OSC|REFCLK|MCLK|BCLK", text):
        return "CLOCK"
    if re.search(r"RESET|RST|POR|PWRON", text):
        return "RESET"
    if re.search(r"BOOT|STRAP|MODE|CFG|CONFIG|ADDR|OPTION", text):
        return "CONFIG"
    if re.search(r"JTAG|SWD|TCK|TMS|TDI|TDO|TRST|TEST|DEBUG", text):
        return "TEST_DEBUG"
    if re.search(r"ADC|DAC|AIN|AOUT|ANALOG|SENSE|FB|COMP|BIAS|REF", text):
        return "ANALOG"
    if re.search(r"EN|ENABLE|INT|IRQ|CS|OE|PG|PWRGOOD|FAULT|ALERT|SYNC|TRIG", text):
        return "CONTROL"
    if re.search(r"USB|SDA|SCL|MOSI|MISO|SCLK|SPI|UART|TX|RX|CAN|ETH|PCIE|DDR|MIPI|HDMI", text):
        return "DATA"
    return "OTHER_SIGNAL"


def protocol_for_pin(pin_name: str, net_name: str) -> str:
    text = canonical(f"{pin_name}_{net_name}")
    checks = [
        (r"USB", "USB"),
        (r"SDA|SCL|I2C", "I2C"),
        (r"MOSI|MISO|SCLK|SPI", "SPI"),
        (r"UART|(^|_)TX|(^|_)RX", "UART"),
        (r"CAN", "CAN"),
        (r"PCIE", "PCIE"),
        (r"DDR", "DDR"),
        (r"MIPI", "MIPI"),
        (r"HDMI", "HDMI"),
        (r"ETH|RGMII|RMII|MDIO|MDC", "ETHERNET"),
        (r"JTAG|TCK|TMS|TDI|TDO", "JTAG"),
        (r"SWD", "SWD"),
    ]
    for pattern, protocol in checks:
        if re.search(pattern, text):
            return protocol
    return ""


def pair_info(pin_name: str, net_name: str) -> tuple[str, str]:
    text = canonical(net_name or pin_name)
    for suffix, member in (("_DP", "P"), ("_DM", "N"), ("_P", "P"), ("_N", "N"), ("+", "P"), ("-", "N")):
        if text.endswith(suffix):
            return text[: -len(suffix)], member
    return "", ""


def bus_group(pin_name: str, net_name: str) -> str:
    text = canonical(net_name or pin_name)
    base = re.sub(r"\[?\d+\]?$", "", text).rstrip("_")
    return base if base != text and len(base) >= 2 else ""


def normalize_pin(raw: dict[str, Any]) -> dict[str, Any]:
    pin_number = str(first(raw, "pin_number", "pinNumber", "pin", "number", default=""))
    pin_name = str(first(raw, "pin_name", "pinName", "name", default=""))
    net_name = str(first(raw, "net_name", "netName", "net", default=""))
    electrical_type = str(first(raw, "electrical_type", "electricalType", "type", default=""))
    direction = str(first(raw, "direction", "io_type", "ioType", default="UNKNOWN"))
    connected_value = first(raw, "connected", "is_connected", "isConnected", default=None)
    connected = bool(net_name) if connected_value is None else (
        bool_arg(connected_value) if isinstance(connected_value, str) else bool(connected_value)
    )
    category = str(raw.get("category") or category_for_pin(pin_name, net_name, electrical_type))
    pair, member = pair_info(pin_name, net_name)
    return {
        "pin_number": pin_number,
        "pin_name": pin_name,
        "net_name": net_name,
        "electrical_type": electrical_type,
        "direction": direction,
        "voltage": str(raw.get("voltage") or ""),
        "connected": connected,
        "category": category,
        "protocol": str(raw.get("protocol") or protocol_for_pin(pin_name, net_name)),
        "bus_group": str(raw.get("bus_group") or bus_group(pin_name, net_name)),
        "differential_pair": str(raw.get("differential_pair") or pair),
        "differential_member": str(raw.get("differential_member") or member),
        "evidence": raw.get("evidence") or [],
    }


def target_relation(interface: dict[str, Any], device: dict[str, Any]) -> str:
    target_ports = device.get("target_ports") or []
    if not target_ports:
        return "NO_TARGET_PORT_CONTEXT"
    names = {
        canonical(port.get("name"))
        for port in target_ports
        if isinstance(port, dict) and port.get("name")
    }
    signal_names = {
        canonical(interface.get("net_name")),
        *(canonical(pin.get("pin_name")) for pin in interface.get("pins", [])),
    }
    signal_names.discard("")
    if names & signal_names:
        return "MATCHED_TARGET_PORT_NAME"
    if interface.get("category") in {"POWER", "GROUND"}:
        return "IMPLICIT_SUPPORT"
    return "UNMATCHED_TO_TARGET_PORT"


def build_interfaces(device: dict[str, Any], pins: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for pin in pins:
        # Net identity is exact; SPI0/SPI1, D+/D- and case must not collapse.
        key = f"NET:{pin['net_name']}" if pin["net_name"] else f"PIN:{pin['pin_number']}"
        groups.setdefault(key, []).append(pin)

    result: dict[str, dict[str, Any]] = {}
    for group_key, group_pins in groups.items():
        categories = [pin["category"] for pin in group_pins]
        category = categories[0] if len(set(categories)) == 1 else "MIXED"
        net_name = next((pin["net_name"] for pin in group_pins if pin["net_name"]), "")
        connected = any(pin["connected"] for pin in group_pins)
        interface_id = stable_id("IF", device["id"], group_key)
        status = "PENDING"
        scope_class = "UNKNOWN"
        if category == "NC":
            status = "SKIPPED_NC"
        elif not connected:
            status = "UNCONNECTED"
        elif category in {"GROUND", "POWER"}:
            status = "STRUCTURED_ONLY"
            scope_class = "POWER_SUPPORT"
        interface = {
            "id": interface_id,
            "device_id": device["id"],
            "refdes": device.get("refdes") or "",
            "cbb_id": device.get("cbb_id") or "",
            "net_name": net_name,
            "canonical_net": canonical(net_name),
            "pins": group_pins,
            "category": category,
            "protocol": next((pin["protocol"] for pin in group_pins if pin["protocol"]), ""),
            "direction": next((pin["direction"] for pin in group_pins if pin["direction"] != "UNKNOWN"), "UNKNOWN"),
            "voltage": next((pin["voltage"] for pin in group_pins if pin["voltage"]), ""),
            "bus_group": next((pin["bus_group"] for pin in group_pins if pin["bus_group"]), ""),
            "differential_pair": next((pin["differential_pair"] for pin in group_pins if pin["differential_pair"]), ""),
            "differential_members": sorted(set(pin["differential_member"] for pin in group_pins if pin["differential_member"])),
            "target_relation": "",
            "scope_class": scope_class,
            "status": status,
            "trace_attempts": 0,
            "paths": [],
            "verified_path_id": None,
            "finding": None,
        }
        interface["target_relation"] = target_relation(interface, device)
        result[interface_id] = interface
    return result


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


def complete_action(state: dict[str, Any], key: str, ok: bool = True) -> None:
    action_id = state["action_keys"].get(key)
    if not action_id:
        return
    action = state["actions"][action_id]
    if action["status"] != "PENDING":
        return
    action["status"] = "DONE" if ok else "FAILED"
    action["completed_at"] = now_iso()
    if action.get("tool"):
        state["budget"]["used"] += 1


def pending_actions(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [action for action in state["actions"].values() if action["status"] == "PENDING"]


def determine_phase(state: dict[str, Any]) -> str:
    if state["budget"]["used"] >= state["budget"]["max"]:
        return "STOPPED_BUDGET"
    devices = list(state["devices"].values())
    if any(device["info_status"] == "PENDING" for device in devices):
        return "DEVICE_INFO"
    if any(device["pins_status"] == "PENDING" for device in devices):
        return "PIN_INVENTORY"
    if any(interface["status"] not in TERMINAL_INTERFACE_STATES or
           any(path["verified"] is None for path in interface["paths"])
           for interface in state["interfaces"].values()):
        return "TRACE_AND_VERIFY"
    return "DONE"


def trace_payload(interface: dict[str, Any]) -> dict[str, Any]:
    pin_names = [pin["pin_name"] or pin["pin_number"] for pin in interface["pins"]]
    return {
        "refdes_or_cbb_id": interface["refdes"] or interface["cbb_id"],
        "pin_names": pin_names,
        "net_name": interface["net_name"],
        "category": interface["category"],
        "protocol": interface["protocol"],
        "目的": "追踪该差异器件接口的局部外围链路和远端边界",
        "提交命令": "submit-trace",
    }


def schedule(state: dict[str, Any]) -> None:
    state["phase"] = determine_phase(state)
    if state["phase"] == "STOPPED_BUDGET":
        return
    if state["phase"] == "DEVICE_INFO":
        for device in state["devices"].values():
            if device["info_status"] != "PENDING":
                continue
            tool = "get_component_info_by_refdes" if device["refdes"] else "get_cbb_info"
            new_action(
                state,
                f"device-info:{device['id']}",
                "FETCH_DEVICE_INFO",
                f"device:{device['id']}",
                tool,
                {
                    "refdes": device["refdes"],
                    "cbb_id": device["cbb_id"],
                    "difference_types": device["difference_types"],
                    "目的": "确认差异器件或 CBB 身份",
                    "提交命令": "record-device",
                },
            )
            break
        return
    if state["phase"] == "PIN_INVENTORY":
        for device in state["devices"].values():
            if device["pins_status"] != "PENDING":
                continue
            if device["refdes"]:
                tool = "get_component_pins"
                purpose = "获取该差异器件的完整 Pin→Net 映射"
            else:
                tool = "get_cbb_topology"
                purpose = "获取差异 CBB 的边界接口和内部拓扑"
            new_action(
                state,
                f"pins:{device['id']}",
                "FETCH_PIN_INVENTORY",
                f"device:{device['id']}",
                tool,
                {
                    "refdes": device["refdes"],
                    "cbb_id": device["cbb_id"],
                    "目的": purpose,
                    "提交命令": "submit-pins",
                },
            )
            break
        return
    if state["phase"] == "TRACE_AND_VERIFY":
        ordered = sorted(
            state["interfaces"].values(),
            key=lambda item: (
                0 if item["target_relation"].startswith("MATCHED") else 1,
                0 if item["category"] in {"DATA", "CONTROL", "CLOCK", "RESET"} else 1,
                item["id"],
            ),
        )
        for interface in ordered:
            unchecked = next((path for path in interface["paths"] if path["verified"] is None), None)
            if unchecked:
                new_action(
                    state,
                    f"chain:{interface['id']}:{unchecked['id']}",
                    "VERIFY_INTERFACE_CHAIN",
                    f"interface:{interface['id']}",
                    "chain_check",
                    {
                        "chain": unchecked["chain"],
                        "path_id": unchecked["id"],
                        "目的": "确认外围接口链路真实存在",
                        "提交命令": "submit-chain",
                    },
                )
                return
            if interface["status"] in TERMINAL_INTERFACE_STATES:
                continue
            if interface["paths"] and all(path["verified"] is False for path in interface["paths"]):
                interface["status"] = "UNVERIFIED_PATH"
                interface["finding"] = "所有候选外围链路均未通过 chain_check"
                continue
            if interface["trace_attempts"] >= state["limits"]["max_trace_rounds"]:
                interface["status"] = "NOT_OBSERVED_WITHIN_SCOPE"
                interface["finding"] = "达到局部追踪上限，未发现可验证远端链路"
                continue
            new_action(
                state,
                f"trace:{interface['id']}:round:{interface['trace_attempts'] + 1}",
                "TRACE_INTERFACE",
                f"interface:{interface['id']}",
                "trace_net",
                trace_payload(interface),
            )
            return
        state["phase"] = determine_phase(state)


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    interfaces = list(state["interfaces"].values())
    return {
        "analysis_id": state["analysis_id"],
        "phase": determine_phase(state),
        "state_revision": state["state_revision"],
        "budget": state["budget"],
        "devices": {
            "total": len(state["devices"]),
            "info_loaded": sum(device["info_status"] == "LOADED" for device in state["devices"].values()),
            "pins_loaded": sum(device["pins_status"] == "LOADED" for device in state["devices"].values()),
        },
        "interfaces": {
            "total": len(interfaces),
            "verified": sum(item["status"] == "VERIFIED" for item in interfaces),
            "structured_only": sum(item["status"] == "STRUCTURED_ONLY" for item in interfaces),
            "unresolved": sum(item["status"] not in TERMINAL_INTERFACE_STATES for item in interfaces),
        },
        "pending_actions": len(pending_actions(state)),
    }


def command_init(args: argparse.Namespace) -> None:
    devices: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    if args.diffs:
        payload = load_json(args.diffs)
        devices.extend(extract_explicit_devices(payload))
        sources.append({"type": "diffs", "path": str(args.diffs)})
    if args.upstream_state:
        upstream = load_json(args.upstream_state)
        devices.extend(extract_from_upstream(upstream, args.include_all_selected))
        sources.append({"type": "upstream_state", "path": str(args.upstream_state)})
    devices.extend(explicit_refdes_devices(args.refdes))
    if args.refdes:
        sources.append({"type": "refdes", "value": args.refdes})
    devices = dedupe_devices(devices)
    if not devices:
        raise ValueError("没有可提取接口的差异器件；请提供 --diffs、--upstream-state 或 --refdes")

    device_map: dict[str, dict[str, Any]] = {}
    for item in devices:
        device = copy.deepcopy(item)
        device.update(
            {
                "info_status": "PENDING",
                "info": None,
                "pins_status": "PENDING",
                "pins": [],
                "interface_ids": [],
            }
        )
        device_map[device["id"]] = device

    state = {
        "schema_version": SCHEMA_VERSION,
        "state_revision": 0,
        "analysis_id": args.analysis_id or f"interface-{hashlib.sha1(now_iso().encode()).hexdigest()[:12]}",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "sources": sources,
        "phase": "DEVICE_INFO",
        "limits": {
            "max_trace_rounds": args.max_trace_rounds,
            "max_paths_per_interface": args.max_paths_per_interface,
        },
        "budget": {"max": args.query_budget, "used": 0},
        "devices": device_map,
        "interfaces": {},
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
    emit(
        {
            "phase": state["phase"],
            "budget": state["budget"],
            "actions": pending_actions(state)[: args.limit],
        }
    )


def command_record_device(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    device = state["devices"].get(args.device_id)
    if not device:
        raise ValueError("差异器件不存在")
    device["info"] = read_payload(args.input, args.json)
    device["info_status"] = "LOADED" if args.status == "SUCCESS" else "FAILED"
    complete_action(state, f"device-info:{args.device_id}", args.status == "SUCCESS")
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit({"device_id": args.device_id, "info_status": device["info_status"]})


def command_submit_pins(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    device = state["devices"].get(args.device_id)
    if not device:
        raise ValueError("差异器件不存在")
    payload = read_payload(args.input, args.json)
    pins = payload.get("pins", payload) if isinstance(payload, dict) else payload
    if not isinstance(pins, list):
        raise ValueError("Pin 数据必须是数组，或包含 pins 数组")
    normalized = [normalize_pin(pin) for pin in pins if isinstance(pin, dict)]
    if device["pins_status"] in {"LOADED", "EMPTY"}:
        if device["pins"] != normalized:
            raise ValueError("Pin清单已提交且内容不同；请汇总完整分页后使用新分析，不能覆盖已有追踪证据")
        emit({"device_id": args.device_id, "reused": True, "interfaces": len(device["interface_ids"])})
        return
    device["pins"] = normalized
    device["pins_status"] = "LOADED" if normalized else "EMPTY"
    interfaces = build_interfaces(device, normalized)
    for interface_id, interface in interfaces.items():
        state["interfaces"][interface_id] = interface
        device["interface_ids"].append(interface_id)
    complete_action(state, f"pins:{args.device_id}", bool(normalized))
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit(
        {
            "device_id": args.device_id,
            "pins": len(normalized),
            "interfaces": len(interfaces),
            "categories": sorted(set(item["category"] for item in interfaces.values())),
        }
    )


def command_submit_trace(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    interface = state["interfaces"].get(args.interface_id)
    if not interface:
        raise ValueError("接口不存在")
    payload = read_payload(args.input, args.json)
    paths = payload.get("paths", payload) if isinstance(payload, dict) else payload
    if not isinstance(paths, list):
        raise ValueError("路径必须是数组，或包含 paths 数组")
    interface["trace_attempts"] += 1
    complete_action(state, f"trace:{args.interface_id}:round:{interface['trace_attempts']}")
    capacity = state["limits"]["max_paths_per_interface"] - len(interface["paths"])
    known_chains = {path["chain"] for path in interface["paths"]}
    for index, raw in enumerate(paths):
        item = {"chain": str(raw)} if isinstance(raw, str) else copy.deepcopy(raw)
        chain = str(item.get("chain") or "").strip()
        if not chain or chain in known_chains or capacity <= 0:
            continue
        scope_class = str(item.get("scope_class") or "UNKNOWN")
        if scope_class not in ALLOWED_SCOPE_CLASSES:
            raise ValueError(f"无效 scope_class：{scope_class}")
        path_id = str(item.get("id") or f"P{len(interface['paths']) + 1}")
        interface["paths"].append(
            {
                "id": path_id,
                "chain": chain,
                "remote_endpoints": item.get("remote_endpoints") or [],
                "intermediate_components": item.get("intermediate_components") or [],
                "scope_class": scope_class,
                "semantics": item.get("semantics") or [],
                "target_relation": item.get("target_relation") or interface["target_relation"],
                "evidence": item.get("evidence") or [],
                "verified": None,
                "verification_details": "",
            }
        )
        capacity -= 1
        known_chains.add(chain)
    if not interface["paths"] and args.complete_boundary:
        interface["status"] = "NO_REMOTE_CONNECTION"
        interface["finding"] = "在声明的完整局部边界内未发现远端连接"
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit({"interface_id": args.interface_id, "status": interface["status"], "paths": interface["paths"]})


def command_submit_chain(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    interface = state["interfaces"].get(args.interface_id)
    if not interface:
        raise ValueError("接口不存在")
    path = next((item for item in interface["paths"] if item["id"] == args.path_id), None)
    if not path:
        raise ValueError("候选路径不存在")
    path["verified"] = args.verified
    path["verification_details"] = args.details or ""
    complete_action(state, f"chain:{args.interface_id}:{args.path_id}", args.verified)
    if args.verified:
        interface["status"] = "VERIFIED"
        interface["verified_path_id"] = args.path_id
        interface["scope_class"] = path["scope_class"]
        interface["target_relation"] = path["target_relation"]
        interface["finding"] = "INTERFACE_CHAIN_VERIFIED"
    schedule(state)
    touch(state)
    atomic_save(args.state, state)
    emit({"interface_id": args.interface_id, "status": interface["status"], "path": path})


def command_status(args: argparse.Namespace) -> None:
    emit(state_summary(load_state(args.state)))


def verified_path(interface: dict[str, Any]) -> dict[str, Any]:
    path_id = interface.get("verified_path_id")
    return next((path for path in interface["paths"] if path["id"] == path_id), {})


def interface_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for device in state["devices"].values():
        for interface_id in device["interface_ids"]:
            interface = state["interfaces"][interface_id]
            path = verified_path(interface)
            rows.append(
                {
                    "device_id": device["id"],
                    "refdes": device["refdes"],
                    "cbb_id": device["cbb_id"],
                    "current_part": device["current_part"],
                    "proposed_part": device["proposed_part"],
                    "difference_types": device["difference_types"],
                    "target_block": device.get("target_block") or {},
                    "interface_id": interface_id,
                    "category": interface["category"],
                    "scope_class": interface["scope_class"],
                    "pins": [
                        {"number": pin["pin_number"], "name": pin["pin_name"]}
                        for pin in interface["pins"]
                    ],
                    "net_name": interface["net_name"],
                    "direction": interface["direction"],
                    "protocol": interface["protocol"],
                    "voltage": interface["voltage"],
                    "bus_group": interface["bus_group"],
                    "differential_pair": interface["differential_pair"],
                    "differential_members": interface["differential_members"],
                    "target_relation": interface["target_relation"],
                    "status": interface["status"],
                    "verified_chain": path.get("chain") or "",
                    "remote_endpoints": path.get("remote_endpoints") or [],
                    "intermediate_components": path.get("intermediate_components") or [],
                    "finding": interface.get("finding") or "",
                    "evidence_level": "E3" if interface["status"] == "VERIFIED" else "E1",
                }
            )
    return rows


def markdown_report(state: dict[str, Any]) -> str:
    summary = state_summary(state)
    rows = interface_rows(state)
    signal_rows = [row for row in rows if row["category"] not in {"POWER", "GROUND", "NC"}]
    support_rows = [row for row in rows if row["category"] in {"POWER", "GROUND"}]
    lines = [
        "# 差异器件外围信号接口清单",
        "",
        "## 覆盖范围",
        "",
        f"- 分析 ID：`{state['analysis_id']}`",
        f"- 当前阶段：`{summary['phase']}`",
        f"- 差异器件：{summary['devices']['total']}",
        f"- 接口种子：{summary['interfaces']['total']}",
        f"- 已验证外围链路：{summary['interfaces']['verified']}",
        f"- 查询预算：{state['budget']['used']}/{state['budget']['max']}",
        "- 说明：结果来自差异器件周围的局部拓扑查询，不代表枚举完整张原理图。",
        "",
        "## 差异器件",
        "",
        "| 位号/CBB | 当前料号 | 目标 Block | 差异原因 |",
        "|---|---|---|---|",
    ]
    for device in state["devices"].values():
        identity = device["refdes"] or device["cbb_id"]
        target_name = (device.get("target_block") or {}).get("name") or "-"
        differences = ", ".join(device["difference_types"]) or device["reason"] or "-"
        lines.append(f"| {identity} | {device['current_part'] or '-'} | {target_name} | {differences} |")

    lines += [
        "",
        "## 外围信号接口",
        "",
        "| 位号 | Pin | Net | 分类/协议 | 方向 | 远端及中间链路 | 与目标关系 | 状态 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    if not signal_rows:
        lines.append("| - | - | - | - | - | - | - | 无信号接口记录 |")
    for row in signal_rows:
        pin_text = ", ".join(f"{pin['number']}:{pin['name']}" for pin in row["pins"])
        class_text = row["category"] + (f"/{row['protocol']}" if row["protocol"] else "")
        path_text = row["verified_chain"] or row["finding"] or "-"
        lines.append(
            f"| {row['refdes'] or row['cbb_id']} | {pin_text} | {row['net_name'] or '-'} | "
            f"{class_text} | {row['direction']} | {path_text} | {row['target_relation']} | {row['status']} |"
        )

    lines += [
        "",
        "## 电源与地支撑接口",
        "",
        "| 位号 | Pin | Net | 分类 | 状态 |",
        "|---|---|---|---|---|",
    ]
    if not support_rows:
        lines.append("| - | - | - | - | 无记录 |")
    for row in support_rows:
        pin_text = ", ".join(f"{pin['number']}:{pin['name']}" for pin in row["pins"])
        lines.append(
            f"| {row['refdes'] or row['cbb_id']} | {pin_text} | {row['net_name'] or '-'} | {row['category']} | {row['status']} |"
        )

    lines += [
        "",
        "## 未解决接口",
        "",
        "| 位号 | Pin/Net | 原因 | 最小下一步 |",
        "|---|---|---|---|",
    ]
    unresolved = [
        row
        for row in signal_rows
        if row["status"] not in {"VERIFIED", "UNCONNECTED", "NO_REMOTE_CONNECTION"}
    ]
    if not unresolved:
        lines.append("| - | - | - | - |")
    for row in unresolved:
        pin_text = ", ".join(pin["number"] for pin in row["pins"])
        next_step = "补充局部 trace_net/trace_connection 证据" if row["status"] != "UNVERIFIED_PATH" else "检查端点选择后重新 chain_check"
        lines.append(
            f"| {row['refdes'] or row['cbb_id']} | {pin_text}/{row['net_name'] or '-'} | "
            f"{row['finding'] or row['status']} | {next_step} |"
        )

    lines += [
        "",
        "## 使用边界",
        "",
        "本清单描述当前旧原理图中声明范围内器件的原始接口事实和局部链路，不代表已经修改原理图。只有 `VERIFIED` 链路达到 E3 证据等级。",
        "",
    ]
    return "\n".join(lines)


def command_report(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    rows = interface_rows(state)
    report = markdown_report(state)
    outputs: dict[str, str] = {}
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report + "\n", encoding="utf-8")
        outputs["markdown"] = str(path)
    else:
        print(report)
    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"analysis_id": state["analysis_id"], "interfaces": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        outputs["json"] = str(path)
    if args.csv_output:
        path = Path(args.csv_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "refdes", "cbb_id", "current_part", "interface_id", "category", "scope_class",
            "pins", "net_name", "direction", "protocol", "voltage", "bus_group",
            "differential_pair", "target_relation", "status", "verified_chain",
            "remote_endpoints", "intermediate_components", "evidence_level",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                flat = copy.deepcopy(row)
                for key in ("pins", "remote_endpoints", "intermediate_components"):
                    flat[key] = json.dumps(flat[key], ensure_ascii=False)
                writer.writerow(flat)
        outputs["csv"] = str(path)
    if outputs:
        emit({"outputs": outputs, "rows": len(rows), "phase": determine_phase(state)})


def self_test() -> None:
    pins = [
        {"pin": "1", "name": "VDD", "net": "3V3", "direction": "POWER_IN"},
        {"pin": "2", "name": "GND", "net": "GND", "direction": "POWER_IN"},
        {"pin": "3", "name": "SDA", "net": "I2C0_SDA", "direction": "BIDIRECTIONAL"},
        {"pin": "4", "name": "SCL", "net": "I2C0_SCL", "direction": "INPUT"},
        {"pin": "5", "name": "INT_N", "net": "SENSOR_INT_N", "direction": "OUTPUT"},
        {"pin": "6", "name": "NC", "net": "", "connected": False},
    ]
    normalized = [normalize_pin(item) for item in pins]
    assert normalized[0]["category"] == "POWER"
    assert normalized[1]["category"] == "GROUND"
    assert normalized[2]["protocol"] == "I2C"
    assert normalized[5]["category"] == "NC"
    device = {
        "id": "DEV1",
        "refdes": "U12",
        "cbb_id": "",
        "target_ports": [{"name": "SDA"}, {"name": "SCL"}],
    }
    interfaces = build_interfaces(device, normalized)
    assert len(interfaces) == 6
    assert sum(item["status"] == "STRUCTURED_ONLY" for item in interfaces.values()) == 2

    with tempfile.TemporaryDirectory() as temp_dir:
        diff_path = Path(temp_dir) / "diff.json"
        state_path = Path(temp_dir) / "state.json"
        diff_path.write_text(
            json.dumps(
                {
                    "devices": [
                        {
                            "id": "DEV1",
                            "refdes": "U12",
                            "current_part": "SENSOR_A",
                            "difference_types": ["DEVICE_REPLACEMENT_REQUIRED"],
                            "target_block": {"id": "337", "name": "传感器"},
                            "target_ports": [{"name": "SDA"}, {"name": "SCL"}],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            command_init(
                argparse.Namespace(
                    diffs=str(diff_path),
                    upstream_state=None,
                    refdes=None,
                    include_all_selected=False,
                    state=str(state_path),
                    analysis_id="self-test",
                    query_budget=30,
                    max_trace_rounds=1,
                    max_paths_per_interface=2,
                )
            )
            command_record_device(
                argparse.Namespace(
                    state=str(state_path), device_id="DEV1", status="SUCCESS", input=None, json='{"part":"SENSOR_A"}'
                )
            )
            command_submit_pins(
                argparse.Namespace(
                    state=str(state_path), device_id="DEV1", input=None, json=json.dumps({"pins": pins})
                )
            )
        state = load_state(state_path)
        sda = next(item for item in state["interfaces"].values() if item["net_name"] == "I2C0_SDA")
        with contextlib.redirect_stdout(quiet):
            command_submit_trace(
                argparse.Namespace(
                    state=str(state_path),
                    interface_id=sda["id"],
                    complete_boundary=False,
                    input=None,
                    json=json.dumps(
                        {
                            "paths": [
                                {
                                    "id": "P1",
                                    "chain": "U12[SDA] → R10 → U1[SDA]",
                                    "scope_class": "EXTERNAL_SIGNAL",
                                    "remote_endpoints": ["U1[SDA]"],
                                    "intermediate_components": ["R10"],
                                }
                            ]
                        }
                    ),
                )
            )
            command_submit_chain(
                argparse.Namespace(
                    state=str(state_path),
                    interface_id=sda["id"],
                    path_id="P1",
                    verified=True,
                    details="connected=true",
                )
            )
        state = load_state(state_path)
        assert state["interfaces"][sda["id"]]["status"] == "VERIFIED"
        assert "U12[SDA]" in markdown_report(state)
        for interface in list(state["interfaces"].values()):
            if interface["status"] != "PENDING":
                continue
            with contextlib.redirect_stdout(quiet):
                command_submit_trace(
                    argparse.Namespace(
                        state=str(state_path),
                        interface_id=interface["id"],
                        complete_boundary=True,
                        input=None,
                        json='{"paths": []}',
                    )
                )
        final_state = load_state(state_path)
        assert determine_phase(final_state) == "DONE"
        markdown_path = Path(temp_dir) / "interfaces.md"
        json_path = Path(temp_dir) / "interfaces.json"
        csv_path = Path(temp_dir) / "interfaces.csv"
        with contextlib.redirect_stdout(quiet):
            command_report(
                argparse.Namespace(
                    state=str(state_path),
                    output=str(markdown_path),
                    json_output=str(json_path),
                    csv_output=str(csv_path),
                )
            )
        assert markdown_path.exists() and json_path.exists() and csv_path.exists()
    emit({"self_test": "PASS", "tests": 11})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="原理图范围内器件的外围信号接口提取状态控制器")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="初始化接口提取任务")
    init.add_argument("--state", required=True)
    init.add_argument("--diffs", help="规范化差异器件 JSON")
    init.add_argument("--upstream-state", help="schematic-consistency-controller 状态文件")
    init.add_argument("--refdes", help="逗号分隔的显式差异位号")
    init.add_argument("--include-all-selected", action="store_true", help="基线盘点：包含一致性状态中的全部SELECTED Block实现")
    init.add_argument("--analysis-id")
    init.add_argument("--query-budget", type=int, default=30)
    init.add_argument("--max-trace-rounds", type=int, default=2)
    init.add_argument("--max-paths-per-interface", type=int, default=2)
    init.set_defaults(func=command_init)

    next_cmd = sub.add_parser("next", help="获取下一批动作")
    next_cmd.add_argument("--state", required=True)
    next_cmd.add_argument("--limit", type=int, default=2)
    next_cmd.set_defaults(func=command_next)

    device = sub.add_parser("record-device", help="记录器件或 CBB 信息")
    device.add_argument("--state", required=True)
    device.add_argument("--device-id", required=True)
    device.add_argument("--status", choices=["SUCCESS", "FAILED"], default="SUCCESS")
    device.add_argument("--input")
    device.add_argument("--json")
    device.set_defaults(func=command_record_device)

    pins_cmd = sub.add_parser("submit-pins", help="提交完整 Pin→Net 清单")
    pins_cmd.add_argument("--state", required=True)
    pins_cmd.add_argument("--device-id", required=True)
    pins_cmd.add_argument("--input")
    pins_cmd.add_argument("--json")
    pins_cmd.set_defaults(func=command_submit_pins)

    trace = sub.add_parser("submit-trace", help="提交接口外围路径")
    trace.add_argument("--state", required=True)
    trace.add_argument("--interface-id", required=True)
    trace.add_argument("--complete-boundary", type=bool_arg, default=False)
    trace.add_argument("--input")
    trace.add_argument("--json")
    trace.set_defaults(func=command_submit_trace)

    chain = sub.add_parser("submit-chain", help="提交 chain_check 结果")
    chain.add_argument("--state", required=True)
    chain.add_argument("--interface-id", required=True)
    chain.add_argument("--path-id", required=True)
    chain.add_argument("--verified", type=bool_arg, required=True)
    chain.add_argument("--details")
    chain.set_defaults(func=command_submit_chain)

    status = sub.add_parser("status", help="查看提取进度")
    status.add_argument("--state", required=True)
    status.set_defaults(func=command_status)

    report = sub.add_parser("report", help="生成接口清单")
    report.add_argument("--state", required=True)
    report.add_argument("--output", help="Markdown 输出")
    report.add_argument("--json-output")
    report.add_argument("--csv-output")
    report.set_defaults(func=command_report)

    test = sub.add_parser("self-test", help="运行自测试")
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
