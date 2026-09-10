# 控制器调用协议

本文件定义控制器与模型/MCP 工具之间的交互。控制器是唯一状态持有者；模型只执行动作并提交精简证据。

## 1. 状态机

```text
SCHEMATIC_OVERVIEW
→ MAP_BLOCKS
→ INVENTORY_SCHEMATIC_INTERFACES（由 schematic-diff-interface-extractor 子流程维护）
→ MAP_PORTS
→ VERIFY_EDGES
→ CHECK_DEPENDENCIES
→ CLASSIFY_INTERFACE_DELTAS
→ DONE
```

查询批次达到预算后转为：

```text
STOPPED_BUDGET
```

状态文件采用原子替换方式写入，并包含递增的 `state_revision`。不要同时运行两个修改同一状态文件的控制器进程。

主控制器在 MAP_BLOCKS 后强制进入接口盘点门禁，并返回 `RUN_INTERFACE_INVENTORY`。接口盘点结果未登记时，脚本拒绝 `submit-ports`；详见 [接口盘点与差异合成](interface-inventory-and-delta.md)。

## 2. 获取下一动作

```bash
python scripts/consistency_controller.py next --state <state.json> --limit 2
```

返回结构：

```json
{
  "phase": "MAP_BLOCKS",
  "budget": {"max": 30, "used": 2},
  "actions": [
    {
      "id": "A00003",
      "kind": "DISCOVER_BLOCK_CANDIDATES",
      "subject": "block:337",
      "tool": null,
      "payload": {}
    }
  ]
}
```

如果动作仍处于 `PENDING`，重复调用 `next` 会返回同一动作，从而避免任务丢失。

## 3. 工程概要

控制器首先返回 `get_schematic_summary` 和 `list_sheets` 动作。执行 MCP 调用后，把原始返回或必要摘要保存为 JSON，再提交：

```bash
python scripts/consistency_controller.py record-overview \
  --state <state.json> \
  --kind summary \
  --input <summary.json>

python scripts/consistency_controller.py record-overview \
  --state <state.json> \
  --kind sheets \
  --input <sheets.json>
```

查询失败时使用 `--status FAILED`，并把错误信息作为输入提交。

## 4. Block 候选

`DISCOVER_BLOCK_CANDIDATES` 会给出目标 Block、Port、已映射邻居和推荐工具路径。按推荐路径进行最小范围查询，然后提交规范化候选：

```json
{
  "candidates": [
    {
      "id": "component:U12",
      "kind": "COMPONENT",
      "refdes": "U12",
      "part_number": "TPS22918",
      "mapping_role": "IMPLEMENTS",
      "identity_score": 0.95,
      "capability_score": 0.90,
      "port_score": 0.85,
      "neighborhood_score": 0.80,
      "hard_conflicts": [],
      "evidence": [
        "业务编码匹配",
        "存在 EN、VIN、VOUT 引脚"
      ]
    }
  ]
}
```

提交：

```bash
python scripts/consistency_controller.py submit-blocks \
  --state <state.json> \
  --block-id 337 \
  --input <block-candidates.json>
```

控制器使用固定权重计算：

```text
0.35 × identity_score
+ 0.25 × capability_score
+ 0.25 × port_score
+ 0.15 × neighborhood_score
```

默认只有第一候选得分不低于 0.78，且领先第二候选至少 0.12，同时没有硬冲突，才自动选定。

如果工程师人工确认，可使用：

```bash
python scripts/consistency_controller.py select-block \
  --state <state.json> \
  --block-id 337 \
  --candidate-id component:U12 \
  --note "工程师确认"
```

不得为了推进状态机而随意人工选择。

## 5. 原始接口盘点门禁

按 `RUN_INTERFACE_INVENTORY` 动作调用 `schematic-diff-interface-extractor`，覆盖动作列出的全部 SELECTED Block 实现。冻结接口事实后提交覆盖声明：

```bash
python scripts/consistency_controller.py record-interface-inventory \
  --state <state.json> \
  --status COMPLETE \
  --input <interface-coverage.json>
```

完整声明示例：

```json
{
  "interfaces_file": "original-interfaces.json",
  "coverage": {
    "selected_blocks": 2,
    "pins_total": 128,
    "pins_classified": 128,
    "interfaces": 34,
    "verified": 26,
    "unresolved": 8
  },
  "evidence": ["interface-extractor-state.json", "chain_check-results.json"]
}
```

`COMPLETE` 要求已覆盖 Block 数与主状态一致，且全部 Pin 已分类。查询预算不足时使用 `PARTIAL --reason <原因>`，但最终结论必须降低覆盖声明。

## 6. Port 映射

控制器会按 Block 批量返回 `MAP_BLOCK_PORTS`。调用 `get_component_pins`，必要时结合 `trace_net`，提交：

```json
{
  "bindings": [
    {
      "port_id": "341",
      "refdes": "U12",
      "pin": "4",
      "pin_name": "EN",
      "net": "ENERGY_SWITCH_EN",
      "direction": "INPUT",
      "voltage": "3V3",
      "protocol": "GPIO",
      "score": 0.92,
      "hard_conflicts": [],
      "evidence": ["引脚功能与目标 S 一致"]
    }
  ]
}
```

```bash
python scripts/consistency_controller.py submit-ports \
  --state <state.json> \
  --block-id 337 \
  --input <port-bindings.json>
```

默认 Port 阈值为 0.75。没有达到阈值的 Port 保持 `UNRESOLVED`。

## 7. 目标边追踪

当目标边两端均有 Port 映射时，控制器返回 `TRACE_TARGET_EDGE`。使用其 `source` 和 `target` 调用 `trace_connection`，提交最多三条精简路径：

```json
{
  "paths": [
    {
      "id": "P1",
      "chain": "U1[GPIO12] → R31 → U12[EN]",
      "semantics": ["GPIO", "SERIES_RESISTOR"],
      "evidence": ["trace_connection 返回该路径"]
    }
  ]
}
```

```bash
python scripts/consistency_controller.py submit-trace \
  --state <state.json> \
  --edge-id 388 \
  --input <trace-paths.json>
```

只有当查询工具明确覆盖了完整相关边界且确认无路径时，才允许增加：

```text
--exhaustive true
```

否则空路径表示局部范围内未观察到，不表示连接必然缺失。

## 8. 链路验证

存在候选路径时，控制器返回 `VERIFY_CHAIN`。严格按 `payload.chain` 调用 `chain_check`，然后提交：

```bash
python scripts/consistency_controller.py submit-chain \
  --state <state.json> \
  --edge-id 388 \
  --path-id P1 \
  --verified true \
  --details "chain_check 返回 connected=true"
```

只有该命令提交 `true` 后，目标边才会成为 `VERIFIED`。

## 9. 局部依赖检查

控制器会为每个已映射 Block 返回 `CHECK_LOCAL_DEPENDENCIES`。根据目标要求检查电源、使能、时钟、复位、配置和必要外围，提交：

```json
{
  "findings": [
    {
      "type": "RESET_DEPENDENCY_MISMATCH",
      "status": "INCONSISTENT",
      "objects": ["U12.4", "R31"],
      "evidence_level": "E3",
      "detail": "复位默认电平与目标要求相反"
    }
  ]
}
```

```bash
python scripts/consistency_controller.py submit-dependencies \
  --state <state.json> \
  --block-id 337 \
  --status CHECKED \
  --input <dependency-findings.json>
```

无适用依赖使用 `NOT_APPLICABLE`；工具能力不足使用 `INSUFFICIENT_INFORMATION`。

## 10. 状态和报告

```bash
python scripts/consistency_controller.py status --state <state.json>

python scripts/consistency_controller.py report \
  --state <state.json> \
  --output <report.md>
```

报告由状态文件生成，模型只能对其解释和补充，不能把未验证项改写为已确认事实。

完成原始接口盘点和目标边验证后，运行 `scripts/interface_delta.py build` 输出唯一主答案。`consistency_controller.py report` 是拓扑证据报告，不再单独充当最终接口增删改答案。

## 11. 自测试

```bash
python scripts/consistency_controller.py self-test
```

修改脚本后必须运行自测试和 Skill 快速校验。
