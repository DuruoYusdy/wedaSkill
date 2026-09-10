# 四类中间产物协议

本协议把一次分析拆成可复核、可继续加工的四类中间产物。每个文件必须携带同一个 `analysis_id`；不得混用不同框图快照或不同原理图工程的结果。

## 1. Block 增删改差异图

输入是当前框图与旧原理图实现的对照判定，不是新旧两个框图的比较。使用 `block-differences.json` 明确覆盖自动判断：

```json
{
  "blocks": [
    {
      "block_id": "337",
      "operation": "MODIFY",
      "refdes": "U12",
      "reason": "目标器件能力与旧实现不同",
      "evidence": ["器件身份与接口能力对比"]
    }
  ],
  "legacy_blocks": [
    {
      "legacy_id": "schematic:U20",
      "name": "旧接口转换",
      "refdes": "U20",
      "operation": "DELETE",
      "confirmed_functional_removal": true,
      "reason": "目标方案明确移除该功能",
      "evidence": ["工程师确认记录"]
    }
  ]
}
```

旧原理图中找不到目标实现不能自动判为新增；框图未展示旧功能也不能自动判为删除。删除必须显式确认。

渲染：

```bash
python scripts/render_block_diff.py build \
  --state work/consistency/<analysis-id>/state.json \
  --decisions work/consistency/<analysis-id>/block-differences.json \
  --json-output outputs/<analysis-id>/01_block_diff/block-diff.json \
  --dot-output outputs/<analysis-id>/01_block_diff/block-diff.dot \
  --svg-output outputs/<analysis-id>/01_block_diff/block-diff.svg
```

必须使用 Graphviz `dot` 渲染。`.dot` 是可审计源文件，`.svg` 是正式图形产物；缺少 `dot` 时报告依赖缺失，不能用其他渲染器冒充。

颜色固定：绿色新增、黄色变更、红色删除、蓝灰保留、灰色待确认。图中保留当前框图连接作为上下文，新增或待确认连接使用虚线。

## 2. 变化 Block 的外围原始信号网络

来源只能是已经冻结的 `original-interfaces.json`。先按第 1 项中 `MODIFY`/`DELETE` Block 的 `refdes` 过滤，再补充所有被信号差异直接引用的原始接口。`ADD` Block 没有旧原理图接口，不得虚构原始网络。

产物：

```text
02_changed_block_original_networks/
├── changed-block-original-networks.json
└── changed-block-original-networks.csv
```

每条记录保留位号、全部 Pin 名称/脚号、精确网络名、接口分类、作用域、远端端点、完整验证链路和证据等级。该产物是旧原理图事实，不能写入目标网络名。

在最终包中，同时保留 `原始信号接口.xlsx`；Excel 的 Block/Sheet 规则由 `schematic-diff-interface-extractor` 负责。

## 3. Port—Pin 映射与连接关系变化

以冻结的原始接口为事实侧、框图 Block/Port/Wire 为目标侧，逐目标边输出：

- 源/目的 Block 标识与名称。
- 源/目的 Port。
- 原理图源端 Pin 名称。
- 原网络名与目标网络名。
- `KEEP`、`ADD`、`MODIFY`、`DELETE` 或 `UNRESOLVED`。
- 映射置信度、分析说明、证据和是否需要重新分配 Pin。

正式展示列中的原理图 Pin 只写源端 Pin 名称。目的端 Pin、物理脚号和完整链路可以保留在 JSON 证据对象中，但不能混入该展示列。

产物：

```text
03_port_pin_connection_changes/
├── port-pin-connection-changes.json
└── port-pin-connection-changes.md
```

若 `ADD`/`MODIFY` 涉及新增器件、新增连线或源端 Pin 重分配，调用 `diagram-logical-connection-mapping`。只采用其 Pin 映射结果；网络命名仍由本流程结合旧网络和目标 Block/Port 决定。

## 4. 变化后的信号接口列表

由逐信号差异合成目标接口列表：删除行不进入目标列表；保留、新增、修改、实现细节和待确认项均保留对应状态，避免丢失尚未决策的接口。

产物：

```text
04_modified_signal_interfaces/
├── modified-signal-interface-list.json
├── modified-signal-interface-list.csv
└── 修改后信号接口.xlsx
```

Excel 使用 `schematic-diff-interface-extractor` 的导出脚本生成，必须包含 `BLOCK_INFO`，并按新增/变更器件建立独立 Sheet。源/目的 Block 标识为 `图页id-block id`，名称逐字来自框图 `name`。

## 统一生成和完整性检查

先运行 `interface_delta.py` 得到 `answer.json`，再运行：

```bash
python scripts/build_middleware.py build \
  --consistency-state work/consistency/<analysis-id>/state.json \
  --answer work/consistency/<analysis-id>/answer.json \
  --block-diff-json outputs/<analysis-id>/01_block_diff/block-diff.json \
  --block-diff-dot outputs/<analysis-id>/01_block_diff/block-diff.dot \
  --block-diff-svg outputs/<analysis-id>/01_block_diff/block-diff.svg \
  --output-dir outputs/<analysis-id> \
  --original-xlsx outputs/<analysis-id>/原始信号接口.xlsx \
  --modified-xlsx outputs/<analysis-id>/04_modified_signal_interfaces/修改后信号接口.xlsx \
  --require-xlsx
```

输出根目录生成 `middleware-manifest.json`，记录每个文件的大小、SHA-256 和 READY/MISSING 状态。只有 Graphviz SVG、原始接口 Excel、修改后接口 Excel 以及第 2～4 项结构化文件全部 READY 时，`complete` 才能为 `true`。

推荐目录：

```text
outputs/<analysis-id>/
├── 01_block_diff/
├── 02_changed_block_original_networks/
├── 03_port_pin_connection_changes/
├── 04_modified_signal_interfaces/
├── 原始信号接口.xlsx
└── middleware-manifest.json
```
