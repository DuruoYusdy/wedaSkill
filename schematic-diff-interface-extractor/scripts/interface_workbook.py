"""原始接口冻结、实例映射、目标展开、修改后清单和 Excel 数据模型。Python 3.10+。"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import diagram_identity


COLS = ["源block标识", "源block名称", "源port", "目的block标识", "目的block名称",
        "目的port", "原理图pin脚", "分析说明", "映射置信度", "网络命名",
        "接口实例", "抽象协议", "展开信号", "网络操作", "网络来源", "物理连接状态",
        "原始行ID", "行ID", "证据", "外围器件与支路", "待确认项"]
FIELDS = ["source_block_id", "source_block_name", "source_port", "destination_block_id",
          "destination_block_name", "destination_port", "schematic_pins", "analysis",
          "mapping_confidence", "net_name", "instance", "family", "signal", "action",
          "net_origin", "connection_status", "original_id", "id", "evidence",
          "peripherals", "issues"]
ACTIONS = {"ADD": "新增", "CHANGE": "修改", "DELETE": "删除", "KEEP": "保留"}


def pin_names(value):
    require(isinstance(value, list) and all(isinstance(x, str) and x for x in value),
            "source_pin_names必须为源端Pin名称字符串数组，未知用[]")
    require(all(not any(token in x for token in ("->", "→", "[", "]", "\\n")) for x in value),
            "源端Pin名称不能包含位号/脚号包装或链路字符串")
    return list(dict.fromkeys(value))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def validate_frozen(state):
    if state.get("baseline_hash"):
        require(state["baseline_hash"] == digest([state["manifest"], state["original"], state["coverage"]]),
                "原始快照已被外部修改；请恢复快照或新建分析，不得继续")


def new_state(manifest, diagram=None):
    manifest = copy.deepcopy(manifest)
    diagram = diagram if diagram is not None else manifest.pop("diagram", None)
    require(diagram is not None, "初始化须传入 --diagram 当前框图JSON，不能自由填写block信息")
    manifest["diagram_catalog"] = diagram_identity.catalog(diagram)
    manifest["diagram_hash"] = digest(diagram)
    require(all(manifest.get(k) for k in ("analysis_id", "schematic_snapshot", "diagram_snapshot")),
            "manifest 缺少分析ID或两个来源快照标识")
    devices = manifest.get("devices", [])
    require(devices and len({d["id"] for d in devices}) == len(devices), "差异器件ID为空或重复")
    for d in devices:
        d.update(diagram_identity.fields(manifest["diagram_catalog"], d, ("",)))
        require(d.get("action") in {"ADD", "CHANGE", "DELETE"}, "必须显式确认器件增删改类型")
        require(d.get("reason") and d.get("evidence"), "器件增删改必须有原因和差异证据")
        require(d.get("scope"), "器件必须有板卡/层次实例scope，位号不单独作全局ID")
        if d["action"] != "ADD":
            require(d.get("refdes"), "旧器件须确认物理位号；CBB应先展开到器件")
        if d.get("target_code") and d.get("code") and d["target_code"] != d["code"]:
            d["replacement"] = True
    return {"schema_version": 3, "manifest": copy.deepcopy(manifest), "phase": "CAPTURE",
            "original": {}, "coverage": {}, "mappings": {}, "annotations": {}, "changes": {}, "targets": {},
            "baseline_hash": None, "revision": 0}


def device(state, device_id):
    return next(d for d in state["manifest"]["devices"] if d["id"] == device_id)


def evidence_ok(row):
    require(isinstance(row.get("evidence"), list) and row["evidence"], "接口必须保存工具结果的证据引用")
    if row.get("connection_status") == "VERIFIED":
        require(row.get("chain") and row.get("chain_check", {}).get("verified") is True
                and row["chain_check"].get("chain") == row["chain"]
                and row["chain_check"].get("evidence"), "VERIFIED 必须有该精确链路的 chain_check 真值和证据")


def capture(state, payload):
    require(state["phase"] == "CAPTURE", "原始清单已冻结，不可覆盖")
    for raw in payload.get("rows", []):
        r = diagram_identity.fields(state["manifest"]["diagram_catalog"], raw)
        d = device(state, r["device_id"])
        require(d["action"] != "ADD", "新增器件没有旧原理图接口，不得伪造原始行")
        require(r.get("id") and r.get("schematic_pins"), "原始行必须有稳定ID和物理Pin")
        require(isinstance(r.get("net_name"), str), "网络名必须逐字来自原理图，未知用空字符串")
        conf = r.get("mapping_confidence")
        require(conf is None or (type(conf) in (int, float) and 0 <= conf <= 1), "原始映射置信度应为数值或null")
        require(r.get("net_origin") in {None, "SCHEMATIC", "UNRESOLVED"}, "原始行不可含规划网络名")
        evidence_ok(r)
        r["source_pin_names"] = pin_names(r.get("source_pin_names", []))
        r.update(net_origin="SCHEMATIC" if r["net_name"] else "UNRESOLVED", action="KEEP",
                 original_id=r["id"])
        r.setdefault("connection_status", "STRUCTURED_ONLY")
        if r["id"] in state["original"]:
            require(state["original"][r["id"]] == r, "重复原始行ID内容冲突；用新分析修正快照")
        state["original"][r["id"]] = r
    for key, coverage in payload.get("coverage", {}).items():
        device(state, key)
        require(coverage.get("status") in {"COMPLETE", "PARTIAL", "NOT_APPLICABLE"}, "覆盖状态错误")
        require(coverage.get("evidence") and coverage.get("reason"), "覆盖声明必须有证据和范围说明")
        require(device(state, key)["action"] == "ADD" or coverage["status"] != "NOT_APPLICABLE",
                "已有器件不能声明不适用以跳过原始盘点")
        state["coverage"][key] = coverage


def freeze(state, allow_incomplete=False):
    require(state["phase"] == "CAPTURE", "快照已冻结")
    for d in state["manifest"]["devices"]:
        if d["action"] == "ADD":
            state["coverage"][d["id"]] = {"status": "NOT_APPLICABLE", "reason": "新增器件没有原始接口",
                                        "evidence": d["evidence"]}
        else:
            c = state["coverage"].get(d["id"], {})
            require(c.get("status") == "COMPLETE" or (allow_incomplete and c.get("status") == "PARTIAL"),
                    f"{d['id']} 缺少完整覆盖；局部未完成须声明PARTIAL并显式 --allow-incomplete")
    state["baseline_hash"] = digest([state["manifest"], state["original"], state["coverage"]])
    state["phase"] = "PROPOSE"


def protocol_hint(text):
    """仅作候选，不改写网络名，不用 family 作物理网络键。"""
    match = re.search(r"(?<![A-Z0-9])(SPI|I2C|UART|USB)(\d*)(?=$|[^A-Z0-9])", text.upper())
    return {"family": match[1], "instance": match[0]} if match else {"family": "", "instance": ""}


def map_rows(state, payload):
    require(state["phase"] == "PROPOSE", "先冻结原始接口，再进行框图映射")
    # 一条记录对应一个明确的物理实例和目标边；两个SPI实例不能凭family自动合并。
    for item in payload["mappings"]:
        item = copy.deepcopy(item)
        item["endpoint"] = diagram_identity.fields(state["manifest"]["diagram_catalog"], item.get("endpoint", {}))
        if item.get("source_pin_names"):
            require(item.get("source_pin_evidence"), "源端Pin名称映射必须引用源端引脚证据")
            item["source_pin_names"] = {k: pin_names(v) for k, v in item["source_pin_names"].items()}
        require(item.get("evidence") and item.get("reason"), "映射缺少目标端点/物理实例依据")
        require(item.get("instance") and item.get("family"), "映射须显式指定实例和抽象协议")
        conf = item.get("confidence")
        require(conf is None or (type(conf) in (int, float) and 0 <= conf <= 1), "置信度应为0..1或null")
        for row_id in item["row_ids"]:
            require(row_id in state["original"], "映射引用不存在的原始行")
            r = state["original"][row_id]
            require(item["device_id"] == r["device_id"], "映射不能跨差异器件误套用")
            known = r.get("instance") or protocol_hint(r["net_name"])["instance"]
            if known and known != item["instance"]:
                require(item.get("instance_override_evidence"), "物理实例不匹配；禁止SPI0/SPI1静默归并")
            endpoint = item.get("endpoint", {})
            require(all(endpoint.get(k) for k in ("source_block_id", "source_port",
                    "destination_block_id", "destination_port")), "映射须有完整两端block/port")
            require(not (set(endpoint) - set(FIELDS[:6])), "endpoint只能包含六个block/port字段")
            require(set(item.get("signals", {})) >= {row_id} and item["signals"][row_id], "须逐原始行确认展开信号")
            state["mappings"][row_id] = copy.deepcopy(item)


def observed_view(state, row):
    r = copy.deepcopy(row)
    mapping = state["mappings"].get(r["id"])
    if mapping:
        previous_source = r.get("source_block_id")
        if previous_source and previous_source != mapping["endpoint"]["source_block_id"]:
            r["source_pin_names"] = []
        r.update(mapping["endpoint"])
        r.update(instance=mapping["instance"], family=mapping["family"], signal=mapping["signals"][r["id"]],
                 mapping_confidence=mapping.get("confidence"))
        r["analysis"] = (r.get("analysis", "") + "；映射：" + mapping["reason"]).strip("；")
        r["evidence"] = r["evidence"] + mapping["evidence"]
        if r["id"] in mapping.get("source_pin_names", {}):
            r["source_pin_names"] = mapping["source_pin_names"][r["id"]]
            r["evidence"] += mapping["source_pin_evidence"]
    annotation = state.get("annotations", {}).get(r["id"])
    if annotation:
        r["analysis"] = (r.get("analysis", "") + "；" + annotation["reason"]).strip("；")
        r["mapping_disposition"] = annotation["disposition"]
        r["evidence"] += annotation["evidence"]
    return r


def explain_rows(state, payload):
    require(state["phase"] == "PROPOSE", "先冻结原始接口")
    for item in payload["annotations"]:
        require(item.get("row_id") in state["original"], "注释引用不存在的原始行")
        require(item.get("disposition") in {"IMPLICIT_SUPPORT", "UNRESOLVED", "NOT_APPLICABLE"}, "注释分类无效")
        require(item.get("reason") and item.get("evidence"), "注释必须有原因和证据")
        state.setdefault("annotations", {})[item["row_id"]] = copy.deepcopy(item)


def expand(state, payload):
    require(state["phase"] == "PROPOSE", "先冻结原始接口")
    for target in payload["targets"]:
        target = copy.deepcopy(target)
        target["endpoint"] = diagram_identity.fields(state["manifest"]["diagram_catalog"], target.get("endpoint", {}))
        d = device(state, target["device_id"])
        require(d["action"] != "DELETE", "删除器件没有目标接口")
        require(target.get("id") and target.get("evidence") and target.get("signals"), "目标须有ID、依据和明确成员表")
        require(target.get("instance") and target.get("family"), "目标必须指定实例；只有SPI抽象口不足以展开")
        require(len(set(target["signals"])) == len(target["signals"]), "目标信号成员重复")
        require(all(isinstance(x, str) and x for x in target["signals"]), "成员表应为非空信号名字符串")
        require(all(target.get("endpoint", {}).get(k) for k in ("source_block_id", "source_port", "destination_block_id", "destination_port")), "目标缺少两端block/port")
        if target["id"] in state["targets"]:
            require(state["targets"][target["id"]] == target, "同目标ID内容冲突，请用新分析版本")
        state["targets"][target["id"]] = copy.deepcopy(target)
    # 不产生伪已连接记录，只把缺失目标信号变成next待办；用户/模型须提供明确修改提案。


def propose(state, payload):
    require(state["phase"] == "PROPOSE", "先冻结原始接口")
    for raw in payload["changes"]:
        change = copy.deepcopy(raw)
        change["fields"] = diagram_identity.fields(state["manifest"]["diagram_catalog"], change.get("fields", {}))
        d = device(state, change["device_id"])
        require(d["action"] != "DELETE", "整器件删除在BLOCK_INFO留档，不新增修改后接口")
        require(change.get("id") and change.get("action") in {"ADD", "CHANGE", "DELETE"}, "信号修改缺少ID或动作")
        require(change.get("reason") and change.get("evidence"), "修改须有理由和目标设计依据")
        original_id = change.get("original_id")
        if change["action"] == "ADD":
            require(not original_id, "新增信号不得伪造原始行血缘")
        else:
            require(original_id in state["original"], "修改/删除须引用有效原始行")
            require(state["original"][original_id]["device_id"] == change["device_id"], "原始行不属于该器件")
        for key, old in state["changes"].items():
            if key != change["id"]:
                require(not original_id or old.get("original_id") != original_id, "同一原始行已有修改；复用原修改ID更新")
        if change["action"] != "DELETE":
            fields = change.get("fields", {})
            require(not (set(fields) - ((set(FIELDS) | {"source_pin_names"}) - {"id", "action", "original_id", "evidence", "issues", "connection_status"})),
                    "fields有不支持字段")
            conf = fields.get("mapping_confidence")
            require(conf is None or (type(conf) in (int, float) and 0 <= conf <= 1), "映射置信度无效")
            if fields.get("net_origin") == "SCHEMATIC":
                require(original_id and fields.get("net_name", state["original"][original_id]["net_name"])
                        == state["original"][original_id]["net_name"], "新网络名不能冒充原理图已有网络")
            # 新器件或改物理引脚时旧封装引脚证据不能延用。
            if "source_pin_names" in fields:
                fields["source_pin_names"] = pin_names(fields["source_pin_names"])
            if fields.get("schematic_pins") or fields.get("source_pin_names"):
                require(change.get("pin_evidence"), "目标物理pin必须有目标器件/封装映射依据")
        state["changes"][change["id"]] = change


def modified_rows(state):
    rows = []
    overrides = {c["original_id"]: c for c in state["changes"].values() if c.get("original_id")}
    for original in state["original"].values():
        d = device(state, original["device_id"])
        if d["action"] == "DELETE":
            continue
        r = observed_view(state, original)
        r.update(id="AFTER:" + r["id"], action="KEEP")
        change = overrides.get(original["id"])
        if change:
            if change["action"] == "DELETE":
                continue
            apply_change(r, change, original)
        # 替换器件时，即便信号保持也不能默认旧pin适用新器件。
        if d.get("replacement") is True and not (change and change.get("pin_evidence") and change.get("fields", {}).get("source_pin_names")):
            r["schematic_pins"] = ""
            if not d.get("block_id") or not r.get("source_block_id") or d["block_id"] == r["source_block_id"]:
                r["source_pin_names"] = []
            r["connection_status"] = "PROPOSED"
            r.setdefault("issues", []).append("目标器件pin映射待确认")
        rows.append(r)
    for c in state["changes"].values():
        if c["action"] == "ADD":
            r = {"device_id": c["device_id"], "net_name": "", "net_origin": "UNRESOLVED", "original_id": ""}
            apply_change(r, c, None)
            rows.append(r)
    return rows


def apply_change(row, change, original):
    source_changed = original is not None and any(k in change.get("fields", {}) and row.get(k) != change["fields"][k]
                           for k in ["source_block_id", "source_port", "instance", "signal"])
    endpoint_changed = original is not None and any(k in change.get("fields", {}) and row.get(k) != change["fields"][k]
                           for k in FIELDS[:6] + ["instance", "signal"])
    row.update(copy.deepcopy(change.get("fields", {})))
    row.update(id=change["id"], action=change["action"], connection_status="PROPOSED",
               analysis=change["reason"], evidence=change["evidence"] + change.get("pin_evidence", []))
    row.pop("chain_check", None)
    row.pop("chain", None)
    if endpoint_changed and not change.get("pin_evidence"):
        row["schematic_pins"] = ""
        row.setdefault("issues", []).append("端点已变更，目标Pin映射待确认")
    if source_changed and "source_pin_names" not in change.get("fields", {}):
        row["source_pin_names"] = []
    if change.get("fields", {}).get("schematic_pins") == "" and "source_pin_names" not in change.get("fields", {}):
        row["source_pin_names"] = []
    if not original or row.get("net_name") != original["net_name"]:
        row["net_origin"] = "PROPOSED" if row.get("net_name") else "UNRESOLVED"
    if change.get("target_id"):
        row["target_id"] = change["target_id"]


def issues_for(state, row):
    issues = list(row.get("issues", []))
    for k, label in [("source_block_id", "源block"), ("destination_block_id", "目的block"),
                     ("source_port", "源port"), ("destination_port", "目的port"),
                     ("instance", "实例"), ("signal", "展开信号"), ("source_pin_names", "源端Pin名称"),
                     ("net_name", "网络名")]:
        if not row.get(k) and not (row.get("mapping_disposition") in {"IMPLICIT_SUPPORT", "NOT_APPLICABLE"}
                                  and k not in {"source_pin_names", "net_name"}):
            issues.append(label + "待确认")
    if row.get("mapping_confidence") is None and row.get("mapping_disposition") not in {"IMPLICIT_SUPPORT", "NOT_APPLICABLE"}:
        issues.append("映射置信度未评定")
    if row.get("connection_status") not in {"VERIFIED", "UNCONNECTED", "SKIPPED_NC", "PROPOSED"}:
        issues.append("局部链路未验证")
    if state["coverage"].get(row["device_id"], {}).get("status") == "PARTIAL":
        issues.append("原始局部覆盖未完成")
    return list(dict.fromkeys(issues))


def next_actions(state):
    if state["phase"] == "CAPTURE":
        return [{"action": "CAPTURE_OR_DECLARE_COVERAGE", "device_id": d["id"]}
                for d in state["manifest"]["devices"] if d["action"] != "ADD"
                and state["coverage"].get(d["id"], {}).get("status") != "COMPLETE"] or [{"action": "FREEZE_BASELINE"}]
    tasks = []
    for r in state["original"].values():
        if r["id"] not in state["mappings"] and r["id"] not in state.get("annotations", {}) and device(state, r["device_id"])["action"] != "DELETE":
            tasks.append({"action": "MAP_OR_EXPLAIN_UNMAPPED", "row_id": r["id"],
                          "net_name": r["net_name"], "candidate": protocol_hint(r["net_name"])})
    rows = modified_rows(state)
    for r in rows:
        issues = issues_for(state, r)
        if issues:
            tasks.append({"action": "RESOLVE_ROW_DETAILS", "device_id": r["device_id"], "row_id": r["id"], "issues": issues})
    for d in state["manifest"]["devices"]:
        if d["action"] != "DELETE" and not any(t["device_id"] == d["id"] for t in state["targets"].values()):
            tasks.append({"action": "DECLARE_TARGET_SIGNALS", "device_id": d["id"]})
    for t in state["targets"].values():
        for signal in t["signals"]:
            matches = [r for r in rows if r["device_id"] == t["device_id"] and r.get("instance") == t["instance"]
                       and r.get("family") == t["family"] and r.get("signal") == signal
                       and all(r.get(k) == v for k, v in t["endpoint"].items())]
            if len(matches) != 1:
                tasks.append({"action": "RESOLVE_TARGET_SIGNAL", "target_id": t["id"], "signal": signal,
                              "matching_rows": [r["id"] for r in matches]})
    return tasks


def sheet_name(raw, used):
    base = re.sub(r"[\x00-\x1f\\/*?:\[\]]", "_", raw).strip(" '") or "DEVICE"
    name, count = base[:31], 1
    while name.casefold() in used or name.casefold() == "history":
        count += 1
        tail = "_" + str(count)
        name = base[:31 - len(tail)] + tail
    used.add(name.casefold())
    return name


def cell(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else value


def model(state):
    require(state["phase"] == "PROPOSE", "必须先冻结原始接口才能导出前后对照")
    validate_frozen(state)
    result = {"schema_version": 3, "title": state["manifest"].get("title", "外围信号接口清单"),
              "source": state["manifest"]["schematic_snapshot"], "target": state["manifest"]["diagram_snapshot"],
              "baseline_hash": state["baseline_hash"], "columns": COLS, "devices": [],
              "pending": next_actions(state), "original_snapshot": list(state["original"].values()),
              "modified_snapshot": modified_rows(state)}
    used = {"block_info", "原始接口_删除"}
    edits = {c["original_id"]: c for c in state["changes"].values() if c.get("original_id")}
    for d in state["manifest"]["devices"]:
        before = [observed_view(state, r) for r in state["original"].values() if r["device_id"] == d["id"]]
        after = [r for r in result["modified_snapshot"] if r["device_id"] == d["id"]]
        item = {**d, "sheet": "原始接口_删除" if d["action"] == "DELETE" else
                sheet_name(d.get("target_refdes") or d.get("refdes") or d["id"], used),
                "before": [], "after": [], "pending_count": 0,
                "coverage": state["coverage"][d["id"]]["status"]}
        for dest, rows in [("before", before), ("after", after)]:
            for r in rows:
                r["issues"] = issues_for(state, r)
                if dest == "after":
                    item["pending_count"] += bool(r["issues"])
                view = {**r, "action": ACTIONS.get(r.get("action"), r.get("action"))}
                # Excel只展示源block的Pin名称；完整物理定位和链路仍保存在证据中。
                view["schematic_pins"] = ", ".join(pin_names(r.get("source_pin_names", [])))
                if dest == "before":
                    edit = edits.get(r["original_id"])
                    action = "DELETE" if d["action"] == "DELETE" else edit["action"] if edit else "KEEP"
                    view["action"] = ACTIONS[action]
                    if edit or d["action"] == "DELETE":
                        reason = edit["reason"] if edit else d["reason"]
                        view["analysis"] = r.get("analysis", "") + "；网络操作：" + ACTIONS[action] + "。" + reason
                if r.get("chain_check"):
                    view["evidence"] = r["evidence"] + [r["chain_check"]]
                item[dest].append([cell(view.get(k)) for k in FIELDS])
        item["deleted_signals"] = [{"original_id": c["original_id"], "reason": c["reason"], "evidence": c["evidence"]}
                                   for c in state["changes"].values() if c["device_id"] == d["id"] and c["action"] == "DELETE"]
        item["target_pending"] = sum(1 for p in result["pending"] if p["action"] in {"DECLARE_TARGET_SIGNALS", "RESOLVE_TARGET_SIGNAL"}
                                     and (p.get("device_id") == d["id"] or p.get("target_id") in
                                          {t["id"] for t in state["targets"].values() if t["device_id"] == d["id"]}))
        result["devices"].append(item)
    return result


def seed_from_local(local, state):
    """从既有局部状态提取所有已返回路径，绝不把一条通过推广到其他支路。"""
    rows = []
    allowed = {d["id"] for d in state["manifest"]["devices"] if d["action"] != "ADD"}
    for interface in local["interfaces"].values():
        if interface["device_id"] not in allowed:
            continue
        paths = interface.get("paths") or [{}]
        for idx, path in enumerate(paths):
            endpoints = path.get("remote_endpoints") or [""]
            for j, endpoint in enumerate(endpoints):
                pins = [f"{interface['refdes']}[{p['pin_number']}:{p['pin_name']}]" for p in interface["pins"]]
                r = {"id": f"{interface['id']}:{idx}:{j}", "device_id": interface["device_id"],
                     "source_pin_names": [],
                     "schematic_pins": ", ".join(pins) + (" -> " + str(endpoint) if endpoint else ""),
                     "net_name": interface["net_name"], "evidence": ["local-state:" + interface["id"]] + path.get("evidence", []),
                     "peripherals": path.get("intermediate_components", []), "connection_status": "STRUCTURED_ONLY",
                     "analysis": "局部状态导入；需确认框图源block后，从该源端工具结果提取Pin名称，不能默认差异器件就是源端"}
                if path.get("verified") is True and (not endpoint or str(endpoint) in path["chain"]):
                    r.update(connection_status="VERIFIED", chain=path["chain"],
                             chain_check={"verified": True, "chain": path["chain"],
                                          "evidence": path.get("verification_details") or "local-state:path:" + path["id"]})
                rows.append(r)
    return {"rows": rows, "coverage": {}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "seed", "capture", "freeze", "map", "explain", "expand", "propose", "next", "export"])
    parser.add_argument("--state", required=True)
    parser.add_argument("--input")
    parser.add_argument("--diagram", help="querySolutionDesign当前框图JSON（已解包）")
    parser.add_argument("--output")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    if args.command == "init":
        require(not Path(args.state).exists(), "状态已存在，请使用新analysis目录")
        state = new_state(read(args.input), read(args.diagram) if args.diagram else None)
    else:
        state = read(args.state)
        require(state.get("schema_version") == 3, "旧状态未绑定框图身份；请保留旧版并使用--diagram新建v3分析")
        validate_frozen(state)
    if args.command in {"capture", "map", "explain", "expand", "propose"}:
        {"capture": capture, "map": map_rows, "explain": explain_rows, "expand": expand, "propose": propose}[args.command](state, read(args.input))
    elif args.command == "freeze":
        freeze(state, args.allow_incomplete)
    elif args.command == "seed":
        save(args.output, seed_from_local(read(args.input), state))
        return
    elif args.command == "export":
        save(args.output, model(state))
        print(json.dumps({"output": args.output, "pending": len(next_actions(state))}, ensure_ascii=False))
        return
    elif args.command == "next":
        tasks = next_actions(state)
        print(json.dumps({"phase": state["phase"], "total": len(tasks), "tasks": tasks[:args.limit]}, ensure_ascii=False, indent=2))
        return
    state["revision"] += 1
    save(args.state, state)
    print(json.dumps({"phase": state["phase"], "revision": state["revision"]}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise SystemExit("输入校验失败: " + str(exc))
