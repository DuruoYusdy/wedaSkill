---
name: schematic-diff-interface-extractor
description: 在框图—旧原理图一致性分析期间，对所有已映射Block实现或明确范围逆向原理图信号接口，冻结原始Pin/Net/链路事实，并支持后续接口映射和表格输出。适用于原始接口盘点、器件替换、接口调整和外围阻容分析。
---

# 差异器件外围信号接口提取

本 Skill 可在框图—旧原理图一致性分析的中段执行。首要任务是对所有已映射 Block 对应的器件/CBB逆向 Pin、Net、外围器件、远端端点和电气链路，形成不受目标差异结论污染的原始接口事实；也可在用户明确限定范围时单独盘点。

局部查询使用 `scripts/interface_controller.py` 维护队列；原始快照、抽象接口映射和修改后清单使用 `scripts/interface_workbook.py` 维护。模型只提交小批量证据和修改提案，不得手工修改状态 JSON。

主流程：**全部已映射实现 → 逆向原始接口 → 冻结事实快照 → 映射框图抽象端口 → 按实例展开信号 → 形成接口差异**。不得先用目标框图填充原始网络名，也不得先筛出差异器件再决定哪些原始接口值得查询。

本 Skill 不定义 `agents/`，不要求一次解析完整张原理图，也不执行原理图修改。

## 必需能力

使用 `tianshu-schematic-dto-analysis` 提供的以下局部能力：

- `get_component_info_by_refdes`：确认差异器件身份。
- `get_cbb_info`、`get_cbb_components`、`get_cbb_topology`：处理差异对象为 CBB 的情况。
- `get_component_pins`：获取差异器件的 Pin→Net 清单。
- `trace_net`：从某个 Pin/Net 向外围局部追踪。
- `trace_connection`：候选远端明确时补充两端路径。
- `chain_check`：验证精确外围链路。

若需补充当前框图，只调用 `querySolutionDesign` 获取当前目标快照，不寻找旧框图。优先复用上一阶段同版本快照。

Python 3.10+ 维护状态，仅使用标准库。Excel 导出使用 Node.js 与 `@oai/artifact-tool`。如原理图工具不可用，可验证脚本或使用已有证据生成草稿，但必须报告缺失能力，不得通过器件常识编造接口事实。

开始前阅读 [控制器调用协议](references/controller-protocol.md) 和 [Excel 前后接口流程](references/excel-workflow.md)。解释接口分类和边界时，阅读 [接口数据与分类规则](references/interface-schema.md)。

## 输入优先级

控制器支持三种输入，优先顺序如下：

1. 一致性分析基线盘点：上一阶段 `$schematic-consistency-controller` 的 `state.json`，并使用 `--include-all-selected`。
2. 独立的规范化器件范围 JSON。
3. 用户明确给出的位号列表。

基线盘点必须覆盖所有 SELECTED Block 实现，不按差异状态过滤。无法映射的Block、原理图游离功能和工具无法枚举的范围单独进入覆盖缺口；不得假装完整。差异阶段可以缩小到已确认变化范围，但必须复用已冻结的基线，不能重新生成一个更窄的“原始清单”。

## 核心原则

- 先获取差异器件完整 Pin→Net 清单，再按精确 Net 合并接口种子。不同板卡/层次实例分开分析；不能用删除标点、忽略大小写后的名称当网络主键。
- 同一器件多个 Pin 连接同一 Net 时，只建立一个接口记录，保留全部 Pin。
- NC 和未连接 Pin 保留记录但不追踪。
- 电源和地记录为支撑接口，不沿全局电源或 GND 进行无界追踪。
- 普通信号、时钟、复位、配置和模拟网络才进入外围链路追踪队列。
- `trace_net` 只产生 E2 候选；链路只有通过 `chain_check` 才达到 E3 并标为 `VERIFIED`。
- 无源、保护和滤波器件保留在链路中，不因“可穿透”而从接口清单消失。
- 电平转换、隔离器、收发器和其他有源转换器必须作为中间功能节点保留。
- 局部查询未发现远端时使用 `NOT_OBSERVED_WITHIN_SCOPE`；只有工具明确覆盖完整局部边界时，才能记录 `NO_REMOTE_CONNECTION`。

## 执行流程

### 1. 初始化

一致性分析中，从上一阶段状态初始化全部已映射实现：

```bash
python scripts/interface_controller.py init \
  --upstream-state work/consistency/<analysis-id>/state.json \
  --include-all-selected \
  --state work/interface/<analysis-id>/state.json \
  --query-budget 60
```

若不带 `--include-all-selected`，仅用于已经存在冻结基线后的差异范围复核。过滤条件包括：

- 存在未映射 Port。
- 相邻目标边未通过验证。
- 存在依赖或支撑电路差异。
- 已选候选显式包含差异类型。

也可以使用独立差异文件：

```bash
python scripts/interface_controller.py init \
  --diffs work/difference-devices.json \
  --state work/interface/state.json
```

或直接指定：

```bash
python scripts/interface_controller.py init \
  --refdes U12,U20 \
  --state work/interface/state.json
```

### 2. 按控制器动作查询

```bash
python scripts/interface_controller.py next \
  --state work/interface/state.json \
  --limit 2
```

可能返回：

```text
FETCH_DEVICE_INFO
FETCH_PIN_INVENTORY
TRACE_INTERFACE
VERIFY_INTERFACE_CHAIN
```

模型只执行返回的动作，并使用相应提交命令更新状态。

### 3. 器件和 Pin 盘点

先调用器件/CBB信息工具确认身份，再调用 `get_component_pins` 或 `get_cbb_topology` 获取完整局部接口种子。

把工具结果转换为精简 Pin JSON，至少保留：

```text
pin_number
pin_name
net_name
electrical_type
direction
connected
```

控制器自动分类并按 Net 合并，不要由模型手工维护合并结果。

### 4. 追踪外围信号

控制器按以下顺序调度接口：

1. 能与目标 Port 对应的接口。
2. 数据、控制、时钟和复位接口。
3. 配置、模拟和其他信号。
4. 测试调试接口。

对 `TRACE_INTERFACE` 使用 `trace_net`。远端候选明确但链路信息不完整时，可补充调用 `trace_connection`。提交结果时保留：

- 精确链路字符串。
- 远端器件/引脚或 CBB 边界。
- 中间阻容、保护、滤波和转换器件。
- 外部接口或局部支撑分类。
- 与目标框图 Port 的关系。

### 5. 验证

控制器对每条候选链路生成 `VERIFY_INTERFACE_CHAIN`。必须使用动作中给出的精确 `chain` 调用 `chain_check`，再提交真值结果。

未通过验证的链路不得写成“已连接”。一个通道验证成功不得推广到其他通道。

### 6. 保存原始接口中间证据

```bash
python scripts/interface_controller.py report \
  --state work/interface/state.json \
  --output work/interface/interfaces.md \
  --json-output work/interface/interfaces.json \
  --csv-output work/interface/interfaces.csv
```

输出字段包括：

- 差异器件和差异类型。
- Pin、Pin 名称和 Net。
- 信号分类、协议、方向和电压。
- 总线和差分对信息。
- 外部信号、局部支撑、电源支撑或测试调试范围。
- 远端端点和中间器件。
- 已验证链路。
- 与目标 Port 的关系。
- 状态和证据等级。

在一致性分析工作流中，再按已确认 `MODIFY`/`DELETE` Block 的位号过滤冻结事实，形成 `changed-block-original-networks.json/.csv`。过滤只改变交付视图，不得重新追踪或覆盖原始快照；`ADD` Block 没有旧原理图网络，保持空集并注明原因。

### 7. 冻结原始接口，形成修改后接口与 Excel

执行 [Excel 前后接口流程](references/excel-workflow.md)。该流程是最终交付，不以 CSV 代替。

1. 将已确认的器件增删改写入 manifest；局部未找到或未验证不能自动视为新增/删除。`code` 是用户业务编码，不得自动用料号替代。
2. `interface_workbook.py init --diagram <当前框图JSON>` 初始化；脚本索引 graph.id、block.id、block.name。`seed` 从局部控制器导入全部已返回路径，再用 `capture` 提交原始接口和覆盖声明。
3. `freeze` 锁定旧器件 Pin/Net/链路快照。新增器件没有原始接口；删除器件也要逆向并留档。局部覆盖不足只能显式导出不完整草稿。
4. `map` 提交物理实例到抽象端口的证据映射。SPI0、SPI1 的 family 都可以是 SPI，但仍是两个独立实例。网络命名原样保留。
5. `expand` 声明目标端口有依据的成员表；`next` 按成员列出缺失或歧义。仅写“SPI”时不能自动断定四线、片选数量或 GPIO 分配。
6. `propose` 提交信号新增/变更/删除；没修改的原始信号自动保留。器件替换必须重新确认目标 Pin，新增网络名标为 PROPOSED。
7. `export` 生成前后数据模型和逐信号变更记录，再运行 `export_interfaces.mjs <model.json> <输出目录>`，输出 `原始信号接口.xlsx`、`修改后信号接口.xlsx` 和 `信号接口变更清单.xlsx`。最终保留 JSON 事实快照便于复核。

四类中间产物工作流中，`原始信号接口.xlsx` 支撑“变化 Block 的外围原始信号网络”，`修改后信号接口.xlsx` 是“变化后的信号接口列表”的正式表格。Port—Pin 映射与连接变化另存 JSON/Markdown，不能只隐藏在 Excel 单元格中。

`信号接口变更清单.xlsx` 是面向 ECO 评审的精简主表。第一页固定为 `BLOCK_INFO`，列出所有大器件的位号、code、类型（新增/删除/变更）、Block 身份、目标位号/code 和分析说明。每个新增或变更器件建立独立 Sheet；删除大器件只进入 `BLOCK_INFO`，不创建器件 Sheet。

每个新增/变更器件 Sheet 只列发生变化的信号，不输出保留行，列顺序固定为：

```text
源block标识、源block名称、源port、目的block标识、目的block名称、目的port、
原理图pin脚、分析说明、映射置信度、原网络命名、新网络命名、类型
```

类型只允许 `新增`、`修改`、`删除`。新增信号的原网络名为空，删除信号的新网络名为空；修改信号同时保留原网络名和新网络名，即使名称不变但 Pin、连接或外围发生变化也标记为修改。

Excel 布局：原始表与修改后表是两个独立 Excel 文件，不放在同一器件页上下两段。两份文件的第一页均为 `BLOCK_INFO`；新增/变更器件各有独立页签，每页只有该版本的接口表。新增器件在原始文件中不虚构接口；删除器件仅在原始文件的 `原始接口_删除` 留档，修改后文件在汇总中标明删除。前十列保持用户要求的列名。

最终变更清单严格使用上述十二列，不追加内部证据列。完整链路、目的端 Pin、物理脚号、证据、外围器件和待确认项保留在 JSON 事实模型与前后快照 Excel 中。

身份取值规则：所有源/目的 block 标识和 BLOCK_INFO 的 block 标识均为 **图页id-block id**，例如 graph.id=0、block.id=337 时输出 `0-337`。block 名称逐字使用该节点的 `name` 字段；不得拼接位号、翻译或改写。不同图页同一 block id 不可混淆；未知对应关系留空并解释，不能生成虚构 block。详见 [Excel流程的身份规则](references/excel-workflow.md)。

Pin列取值规则：`原理图pin脚` **只写源block端的Pin名称**，例如 `SPI0_SCK`，不能写 `U12[10:SPI0_SCK]`、物理脚号或目的端Pin。源端按该行的源block确定，不默认差异器件就是源端，也不因MISO电流/数据方向交换源目的。使用专用字段 `source_pin_names`；未知留空待确认，完整链路保留在证据中。

网络操作规则：接口页使用 `网络操作` 列，明确标记 **新增、删除、修改、保留**。原始表对应旧行标注删除/修改，修改后表对应目标行标注新增/修改；删除行不进入修改后列表。操作标签是差异注释，不改写冻结事实。名称未变但连接、源端Pin或外围连线需要调整也属于修改，不能仅凭网络名是否改变判断。BLOCK_INFO的器件操作与网络操作分开。

## 终止与异常

- 达到查询预算：停止并输出当前覆盖情况。
- 器件信息查询失败：仍可在位号明确时尝试 Pin 清单，但报告身份信息不足。
- Pin 清单为空：结束该器件，不推测接口。
- 接口达到最大追踪轮次：标记 `NOT_OBSERVED_WITHIN_SCOPE`。
- 所有候选链路验证失败：标记 `UNVERIFIED_PATH`。
- 用户只要求指定协议或 Pin：可以在初始化输入中缩小差异器件范围，但不要扩大到其他器件。

## 最终回答要求

以控制器生成的接口清单为主，明确区分：

1. 已通过 `chain_check` 的外围信号接口。
2. 仅由 Pin/Net 结构确认的电源、地和未连接接口。
3. 尚未验证或局部范围内未观察到的接口。
4. 与框图目标 Port 对应、疑似需新增/改名/重映射的接口。
5. 中间阻容和保护器件；不得在没有修改工具时声称已调整原理图。
