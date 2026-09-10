# 接口提取控制器调用协议

## 1. 状态机

```text
DEVICE_INFO
→ PIN_INVENTORY
→ TRACE_AND_VERIFY
→ DONE
```

查询预算耗尽时进入 `STOPPED_BUDGET`。状态文件由脚本原子写入，并通过 `state_revision` 记录更新次数。

## 2. 差异输入格式

```json
{
  "devices": [
    {
      "id": "DEV-U12",
      "refdes": "U12",
      "cbb_id": "",
      "current_part": "USB2512B",
      "proposed_part": "USB2514B",
      "difference_types": ["DEVICE_REPLACEMENT_REQUIRED"],
      "reason": "目标端口数量增加",
      "target_block": {
        "id": "337",
        "name": "USB HUB"
      },
      "target_ports": [
        {
          "id": "341",
          "name": "USB_DN1_DP",
          "direction": "INOUT",
          "protocol": "USB",
          "voltage": "3V3"
        }
      ]
    }
  ]
}
```

必须至少提供 `refdes` 或 `cbb_id`。

## 3. 初始化和下一动作

```bash
python scripts/interface_controller.py init \
  --diffs <differences.json> \
  --state <state.json> \
  --query-budget 30 \
  --max-trace-rounds 2 \
  --max-paths-per-interface 2

python scripts/interface_controller.py next \
  --state <state.json> \
  --limit 2
```

重复调用 `next` 不会创建重复动作；未提交的动作保持 `PENDING`。

## 4. 提交器件信息

执行 `get_component_info_by_refdes` 或 `get_cbb_info` 后：

```bash
python scripts/interface_controller.py record-device \
  --state <state.json> \
  --device-id DEV-U12 \
  --input <device-info.json>
```

失败时使用 `--status FAILED`，并提交错误摘要。

## 5. 提交 Pin→Net 清单

规范化输入：

```json
{
  "pins": [
    {
      "pin_number": "4",
      "pin_name": "SDA",
      "net_name": "I2C0_SDA",
      "electrical_type": "BIDIRECTIONAL",
      "direction": "INOUT",
      "voltage": "3V3",
      "connected": true,
      "evidence": ["get_component_pins"]
    }
  ]
}
```

兼容字段别名：

```text
pin_number / pinNumber / pin / number
pin_name / pinName / name
net_name / netName / net
electrical_type / electricalType / type
direction / io_type / ioType
connected / is_connected / isConnected
```

提交：

```bash
python scripts/interface_controller.py submit-pins \
  --state <state.json> \
  --device-id DEV-U12 \
  --input <pins.json>
```

控制器会自动按精确 Net 名合并 Pin，并创建接口 ID。限定同一板卡/层次实例；不同实例不得混入同一器件ID。

## 6. 提交外围链路

执行 `trace_net`，必要时补充 `trace_connection`，提交：

```json
{
  "paths": [
    {
      "id": "P1",
      "chain": "U12[SDA] → R31 → U1[SDA]",
      "remote_endpoints": ["U1[SDA]"],
      "intermediate_components": [
        {
          "refdes": "R31",
          "role": "SERIES_RESISTOR",
          "value": "33"
        }
      ],
      "scope_class": "EXTERNAL_SIGNAL",
      "semantics": ["I2C", "OPEN_DRAIN"],
      "target_relation": "MATCHED_TARGET_PORT",
      "evidence": ["trace_net 返回该链路"]
    }
  ]
}
```

`scope_class` 只能取：

```text
EXTERNAL_SIGNAL
LOCAL_SUPPORT
POWER_SUPPORT
TEST_DEBUG
UNKNOWN
```

```bash
python scripts/interface_controller.py submit-trace \
  --state <state.json> \
  --interface-id <interface-id> \
  --input <paths.json>
```

只有查询明确覆盖了相关完整边界时，空结果才可配合：

```text
--complete-boundary true
```

## 7. 提交 chain_check

控制器返回 `VERIFY_INTERFACE_CHAIN` 后，严格验证其 `payload.chain`：

```bash
python scripts/interface_controller.py submit-chain \
  --state <state.json> \
  --interface-id <interface-id> \
  --path-id P1 \
  --verified true \
  --details "chain_check connected=true"
```

只有 `verified=true` 才会把接口状态改为 `VERIFIED`。

## 8. 进度和输出

```bash
python scripts/interface_controller.py status --state <state.json>

python scripts/interface_controller.py report \
  --state <state.json> \
  --output <interfaces.md> \
  --json-output <interfaces.json> \
  --csv-output <interfaces.csv>
```

- Markdown 用于工程师评审。
- JSON 用于下一阶段 Pin Map/ECO 自动化。
- CSV 仅为中间调试输出。正式 Excel 前后对照按 [Excel 流程](excel-workflow.md) 执行。

注意：上拉/下拉是信号网到电源/地的支路，不得按上例串联在两个信号端点之间。支路单独保存并验证精确链路。默认路径数量上限会截断多分支网络；必须记录剩余覆盖，不能将第一条 VERIFIED 当作所有支路已完成。

## 9. 自测试

```bash
python scripts/interface_controller.py self-test
```

修改控制器后必须同时执行 Python 语法检查、自测试和 Skill 快速校验。
