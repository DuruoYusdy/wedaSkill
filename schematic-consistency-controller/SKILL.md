---
name: schematic-consistency-controller
description: 使用确定性 Python 状态机比较当前框图与旧原理图，逆向原始信号接口，完成Block/Port映射、拓扑验证和逐信号增删改判定，并输出Graphviz差异图与四类可审计中间产物。适用于需要查询预算、证据、chain_check和最终统一答案的框图—原理图一致性分析。
---

# 脚本控制的框图—原理图一致性分析

把当前在线框图作为目标设计，把已有原理图作为当前实现。最终链路固定为：

```text
框图快照 → Block实现映射 → 原理图原始接口逆向并冻结
→ 原始接口与Block/Port映射 → 目标边验证
→ 逐信号增删改判定 → 一份最终答案
```

原始接口逆向是本一致性分析的必经阶段，不再等到已经判定出差异器件后才执行。

本 Skill 不定义 `agents/`，也不修改原理图。最终输出经过证据约束的一致性报告和 ECO 候选。

## 必需能力

- `querySolutionDesign`：读取当前在线框图 V4 JSON。
- `tianshu-schematic-dto-analysis`：提供 `get_schematic_summary`、`list_sheets`、CBB/器件查询、`trace_net`、`trace_connection` 和 `chain_check`。
- Python 3.10 或更高版本，仅使用标准库。

如果缺少前两项中的任一能力，说明缺失能力，不得伪造分析结果。

## 核心约束

- 所有状态只能通过 `scripts/consistency_controller.py` 更新，不要手工修改状态 JSON。
- 每轮先调用控制器的 `next`，只执行返回的待办动作，再把结构化结果提交给控制器。
- 原理图接口盘点覆盖全部已映射 Block 对应的器件/CBB，并从其全部信号 Pin 向局部边界追踪；不得只查询框图上名称相似的 Port，也不得只盘点已知差异器件。
- 名称和模型推理只能产生候选；目标连接必须经过 `chain_check` 才能成为 `VERIFIED`。
- 局部未发现使用 `NOT_OBSERVED_WITHIN_SCOPE`，不能直接判定原理图中不存在。
- 框图未展示的去耦、保护、测试和调试电路不能直接生成删除建议。

开始前阅读 [控制器调用协议](references/controller-protocol.md) 和 [接口盘点与差异合成](references/interface-inventory-and-delta.md)。需要生成正式中间产物时阅读 [四类中间产物协议](references/middleware-artifacts.md)；需要给候选打分或分类差异时，再阅读 [评分与结论规则](references/scoring-and-findings.md)。

## 执行流程

### 1. 获取并保存目标框图

调用一次 `querySolutionDesign`，把完整返回值保存为 UTF-8 JSON，例如：

```text
work/consistency/<analysis-id>/solution-design.json
```

这只是当前目标快照，不与旧框图比较。

### 2. 初始化控制器

```bash
python scripts/consistency_controller.py init \
  --diagram work/consistency/<analysis-id>/solution-design.json \
  --state work/consistency/<analysis-id>/state.json \
  --solution-id <solution-id> \
  --schematic-id <schematic-id> \
  --query-budget 30
```

若只分析部分 Block，增加：

```bash
--scope-blocks 337,401,402
```

初始化会完成：

- 解析 Block、Port 和 Wire。
- 检查断链、重复 ID、重叠和空名称 Port。
- 计算 Block 信息优先级。
- 创建动作队列、查询预算和证据状态。

### 3. 完成 Block 实现映射

```bash
python scripts/consistency_controller.py next \
  --state work/consistency/<analysis-id>/state.json \
  --limit 2
```

先循环控制器动作，直到全部 Block 进入 SELECTED、UNRESOLVED 或 HARD_CONFLICT。此阶段可能返回：

```text
CALL_TOOL
DISCOVER_BLOCK_CANDIDATES
```

此时先不要进入目标边结论；必须执行下一阶段的原始接口盘点。

### 4. 逆向并冻结原理图原始接口

调用 `schematic-diff-interface-extractor`，以当前一致性状态初始化，并启用 `include-all-selected`。这表示盘点所有已选 Block 实现，不是只盘点差异器件。

对每个器件先获取完整 Pin→Net，再用受限 BFS 追踪所有信号 Pin，分别保存扇出、无源支路、有源转换边界和 `chain_check` 结果。电源、地、NC和局部支撑也分类留档，但不作全局无界追踪。

原始接口达到声明范围的覆盖标准后冻结，生成：

```text
original-interfaces.json
interface-coverage.json
```

把覆盖声明登记回主控制器，解除 Port 映射门禁：

```bash
python scripts/consistency_controller.py record-interface-inventory \
  --state work/consistency/<analysis-id>/state.json \
  --status COMPLETE \
  --input work/consistency/<analysis-id>/interface-coverage.json
```

其中输入必须包含 `interfaces_file`、`coverage.selected_blocks`、`coverage.pins_total`、`coverage.pins_classified` 和非空 `evidence`。覆盖不足时使用 `PARTIAL` 并提供原因；只有不存在 SELECTED Block 时才允许 `NOT_APPLICABLE`。

未完成覆盖时可以继续一致性调查，但最终答案必须标为部分覆盖；不能把未观察到解释为不存在。

### 5. 映射 Port 并验证目标拓扑

恢复 `consistency_controller.py next`，使用已冻结的接口事实帮助完成 Port 映射和目标边验证。不要重新查询后覆盖原始接口事实。依据协议转换成精简 JSON，再使用对应子命令提交：

```text
record-overview
submit-blocks
select-block
submit-ports
submit-trace
submit-chain
submit-dependencies
```

控制器负责候选排序、阈值、差值、轮次、去重和阶段推进。

### 6. 形成逐信号增删改结论

使用 `scripts/interface_delta.py` 合并一致性状态与 `original-interfaces.json`：

```bash
python scripts/interface_delta.py build \
  --consistency-state work/consistency/<analysis-id>/state.json \
  --interfaces work/consistency/<analysis-id>/original-interfaces.json \
  --decisions work/consistency/<analysis-id>/interface-decisions.json \
  --json-output work/consistency/<analysis-id>/answer.json \
  --markdown-output outputs/<analysis-id>/answer.md
```

操作只能是：保留、新增、修改、删除、实现细节保留、待确认。自动规则只把在完整查询边界内确认缺失的目标边判为新增；未映射的原理图接口默认待确认或实现细节，不能自动删除。

若新增/修改包含新增器件、增加连线或源端 Pin 重新分配，调用 `diagram-logical-connection-mapping`。该 Skill 输出 Pin 映射，不负责网络命名；其结果回填后再生成最终答案。

### 7. 生成四类中间产物

按 [四类中间产物协议](references/middleware-artifacts.md) 生成并检查：

1. 当前框图目标相对旧原理图实现的 Block 增删改 Graphviz 图（`.dot` + `.svg`）。
2. 变化 Block 在旧原理图中的外围原始信号网络。
3. 框图 Port—原理图源端 Pin 映射及连接关系变化。
4. 变化后的信号接口列表（JSON/CSV/Excel）。

输出编号代表交付顺序，不改变分析顺序：原始接口仍必须在拓扑差异最终判定之前逆向并冻结。

先使用 `render_block_diff.py` 生成差异模型与 Graphviz 图，再使用 `build_middleware.py` 拆分第 2～4 项并生成 `middleware-manifest.json`。正式交付要求 manifest 的 `complete=true`。

### 8. 查看进度

```bash
python scripts/consistency_controller.py status --state <state.json>
```

不要依靠对话记忆估算完成度，以状态文件为准。

### 9. 生成一份最终答案

```bash
python scripts/consistency_controller.py report \
  --state <state.json> \
  --output <report.md>
```

最终以 `interface_delta.py` 生成的 `answer.md` 为主答案；一致性报告和原始接口 JSON 是证据附件。答案必须同时包含覆盖情况、原始接口数量、Block/Port映射、逐信号增删改、调用 Pin 映射的项目和未解决项。

## 异常处理

- `next` 返回 `STOPPED_BUDGET`：停止调用工具，输出当前覆盖和未解决项。
- Block 达到最大轮次仍无法区分：保持 `UNRESOLVED`，不要由模型强选。
- Port 没有可靠映射：相关边转为 `UNRESOLVED_ENDPOINT`。
- 追踪没有路径但不是完整边界查询：保持 `NOT_OBSERVED_WITHIN_SCOPE`。
- `chain_check` 失败：不得把 `trace_connection` 返回的候选当作真实连接。
- 目标 Wire 端点缺失：标记 `INVALID_TARGET`，要求修复框图。

## 输出要求

最终回答应优先引用控制器生成的报告，并补充：

1. 总体结论和实际覆盖范围。
2. 目标框图数据质量问题。
3. Block→器件/CBB/功能切片映射。
4. 已冻结的原理图原始信号接口及覆盖率。
5. 原始接口→Block/Port映射。
6. 已通过 `chain_check` 的目标连接。
7. 逐信号保留、新增、修改、删除、实现细节和待确认项。
8. 需要 `diagram-logical-connection-mapping` 的新增器件/新增连线任务。
9. ECO 候选及风险；不得声称已经修改原理图。

同时交付 `middleware-manifest.json` 中登记的四类中间产物。若 Graphviz、原始接口 Excel 或修改后接口 Excel 缺失，必须明确列为未完成，不能只给文字总结代替。
