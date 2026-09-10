# 接口盘点与差异合成

## 1. 阶段边界

一致性分析分成三类不可混写的数据：

| 数据 | 来源 | 约束 |
|---|---|---|
| 原始接口事实 | 旧原理图局部工具 | 与目标框图差异结论无关，完成后冻结 |
| 逻辑映射 | 当前框图 + 原始接口 | 可以修正映射，不改原始Pin/Net/链路 |
| 接口差异 | 映射后的目标边与原始接口比较 | 新增/修改是设计意图，删除要求明确证据 |

原始接口的盘点范围是当前分析中所有已映射 Block 的物理实现，加上追踪遇到的连接器、层次端口、CBB边界和有源转换边界。若原理图工具不能枚举整图，报告该范围，不使用“全原理图完整”表述。

## 2. 原始接口盘点

使用 `schematic-diff-interface-extractor` 从一致性状态初始化时启用全部已选实现：

```bash
python scripts/interface_controller.py init \
  --upstream-state work/consistency/<analysis-id>/state.json \
  --include-all-selected \
  --state work/consistency/<analysis-id>/interface-state.json \
  --query-budget 60
```

实际运行时从所调用 Skill 的根目录解析脚本，不在文档中固化安装绝对路径。

遍历粒度是 `scope + refdes/CBB + pin + exact net`，使用脚本队列执行有界 BFS：

1. `get_component_info_by_refdes` / CBB查询确认实现身份。
2. `get_component_pins` 获取该器件完整 Pin→Net，不能只提交框图 Port 的子集。
3. 精确 Net 名分组；名称标准化只用于候选识别，不作为电气网络主键。
4. 普通信号用 `trace_net` 追踪。串联阻容可穿透但保留；上拉、下拉和保护支路独立留档；有源转换器成为功能边界。
5. 每个远端/扇出分支独立保存，不能在第一条链路成功后停止其他已发现分支。
6. 每条候选链路分别 `chain_check`，达到 E3 才是 VERIFIED。
7. 每个 Pin 最终归入 VERIFIED、LOCAL_SUPPORT、POWER、GROUND、NC、UNCONNECTED、UNVERIFIED或NOT_OBSERVED。

导出：

```bash
python scripts/interface_controller.py report \
  --state work/consistency/<analysis-id>/interface-state.json \
  --output work/consistency/<analysis-id>/original-interfaces.md \
  --json-output work/consistency/<analysis-id>/original-interfaces.json
```

JSON才是后续机器输入；Markdown用于人工复核。原始接口内部保留两端Pin和完整路径。最终展示的“原理图Pin脚”只取框图源Block端的Pin名称。

## 3. Port和接口映射

Port映射优先复用原始接口事实，避免为同一 Pin/Net 重复查询。每条映射同时绑定：

```text
原始interface_id
物理实例（如SPI0）
协议族（如SPI）
信号成员（如SCLK）
源Block/Port
目的Block/Port
```

Block标识使用 `graph.id-block.id`，Block名称逐字使用JSON的 `name`。SPI0/SPI1可以映射到相同抽象协议SPI，但仍是两个物理实例，不能按协议族合并。

目标边验证与原始接口映射是两个判断：Port映射得分达标不等于连接存在；`trace_connection`候选不等于VERIFIED。目标边必须通过对应的 `chain_check`。

## 4. 差异判定

`scripts/interface_delta.py`先做保守自动对齐，再接受带证据的 `interface-decisions.json` 覆盖：

```json
{
  "decisions": [{
    "delta_id": "EDGE-388",
    "action": "MODIFY",
    "reason": "目标器件改变，源端Pin需要重新分配",
    "evidence": ["device-diff:U12", "target-edge:388"],
    "requires_connection_mapping": true
  }]
}
```

规则：

- KEEP：目标边已有对应的E3原理图接口。
- ADD：目标边在声明的完整查询边界内确认缺失，或者明确新增Block/Port/信号成员。
- MODIFY：原始接口与目标边能对应，但端点、实例、Pin、Net、转换器或外围链路需要变化。必须同时有原始interface_id和target_edge_id。
- DELETE：旧功能明确取消且原始接口已绑定。必须提交 `confirmed_functional_removal:true`；“框图未画”不足以删除。
- IMPLEMENTATION_DETAIL：电源、地、局部支撑、保护、测试等框图可省略实现。
- UNRESOLVED：证据不够，不能硬归类。

新增和修改不能只比较网络名称。网络名称不变但Pin、端点或外围阻容改变，仍然是MODIFY。

## 5. 新增连接的条件调用

以下情况调用 `diagram-logical-connection-mapping`：

- 新增器件带来新连线。
- 框图新增连接，而旧原理图没有对应接口。
- 修改连接导致源端器件或源端Port改变。
- 器件替换后需要重新确定源端Pin。

传入目标连接、框图Block/Port、实际 `pin_info` 和必要规则。接受结果前检查源端Pin逐字存在于源器件pin_info。该 Skill 不负责网络命名；网络名由后续命名能力或明确规则处理。

如果该 Skill 在当前运行环境不可用，ADD/MODIFY保持 `PIN_MAPPING_REQUIRED`，最终答案不得填写推测Pin。其自身要求的执行会话属于被调用 Skill 的内部约束；本 Skill 仍不定义 `agents/`。

## 6. 一份最终答案

最终 `answer.md` 按顺序给出：

1. 实际覆盖、原始接口数和验证率。
2. Block与物理实现映射。
3. 原始接口与目标Block/Port映射。
4. 逐信号KEEP/ADD/MODIFY/DELETE/IMPLEMENTATION_DETAIL/UNRESOLVED。
5. 需要Pin映射、网络命名或人工复核的后续项。

原始接口清单和状态JSON是证据附件，不与主答案竞争结论。只要存在UNRESOLVED、接口覆盖PARTIAL或映射任务未完成，主答案标记为部分完成。
