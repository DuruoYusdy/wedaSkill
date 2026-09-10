# 原始接口、修改后接口与 Excel

## 1. 事实、映射、目标分层

只比较当前框图目标和旧原理图实现。`interface_workbook.py` 不调用 MCP：模型负责执行局部工具、读原始结果并提交小批 JSON；脚本负责快照、去重、校验、实例分组、目标成员缺项和前后清单生成。不依赖模型记住已处理列表，也不创建 agents。

| 层 | 来源 | 可否覆盖旧事实 |
|---|---|---|
| 原始 Pin/Net/外围链路 | get_component_pins、trace_net、chain_check | freeze 后不可覆盖 |
| 原始 block/port 映射注释 | 上一阶段 block 映射、当前框图、已验证局部路径 | 独立维护，不修改原始网络名和物理 Pin |
| 修改后接口 | 目标边、明确端口需求、目标器件 Pin Map | 另存提案，保留 original_id |

`BLOCK_INFO.code` 表示输入提供的器件业务 code，可能与厂家料号不同；未知留空并在 Excel 显示“未提供”。`target_code` 是变更后编码。`refdes` 是旧位号，`target_refdes` 是已确认目标位号，新增未分配时用稳定设备 ID 命名页签，不能假造 U 编号。

## 2. 原始列表如何逆向

1. 上一阶段候选不等于已确认差异。先根据明确证据建立差异 manifest，显式填写 ADD/CHANGE/DELETE。范围包括改变连接的大器件，不仅是换料器件。
2. 以板卡、层次实例、器件 UUID/位号定位。相同位号在不同实例中必须使用不同 device_id/scope，且分开运行局部查询控制器。CBB 先定位其中主器件，不把 CBB 的引脚伪装成器件 Pin。
3. 完整分页获取该器件 Pin→Net。NC、未连接、电源、地、复位、启动配置和测试接口也登记；不要因为框图没有画就删除。
4. 对每个精确 Net 局部追踪至首个主器件/连接器/层次端口/有源转换器边界。电源地不跨全局展开。记录串联电阻两侧的不同 Net；多个 Net 段用 `peripherals` 中的 `segments` 保存，`net_name` 固定表示本行差异器件 Pin 直接所在的网络名。
5. 扇出分支各自保留原始行与端点，不按网络名简单丢弃目的端。共享原始 interface_id 可作为行 ID 前缀。上拉/下拉支路单独记录精确 chain；不是串联传输路径。ESD、RC、终端、电平转换器保留位号和支路角色。
6. 每条需要标为 VERIFIED 的路径都调用 chain_check，保持返回值和链路一一对应。路径上限或查询预算截断意味着 PARTIAL，不代表没有其他接口。
7. `seed` 只搬运控制器实际返回的路径，不声明完整性。若它没有拿到所有支路，用现有局部工具补充后分批 capture。不能只搬 CSV 中的一条 verified_path 就声称全接口覆盖。

## 3. 初始化与冻结

### block身份来源（v3）

初始化必须传入 `--diagram <当前框图JSON>`。`scripts/diagram_identity.py` 从真实 `graph` 节点取图页 `id`，从其中的 block 节点取自身 `id` 和 `name`，建立只读索引。图页 id 不是原理图图页 id，也不是 children 数组序号。多个图页可传入 graph 对象数组；API外层封装先按实际响应结构解包。脚本不猜测未提供的图页ID。

例如用户提供的 `graph.id=0`、`block.id=337`、`block.name="节能开关2"`，输出必须为 `0-337` 和 `节能开关2`。name 为空时保留空，不自动补名。

manifest 的 `block_id`、两端的 `source_block_id` / `destination_block_id` 推荐填写结构化引用 `{"page_id":0,"block_id":337}`；脚本输出时统一转为 `0-337`。已知复合标识字符串也可使用。单独的 block id 仅在全框图唯一时可解析，否则拒绝并要求提供图页。

名称字段可以省略，由脚本填充；若调用方提交的名称与JSON原文不同则报错。不允许用器件型号、位号或推测名称替代框图 name。找不到映射的旧端点（包括目标中已移除的block）将 block 标识、名称留空，并在分析说明里记录“当前框图无对应/未映射”，原理图Pin和网络事实仍保留。图页重复或复合标识冲突时报错，不静默覆盖。

v3 状态保存框图内容哈希和派生索引，与原始快照一起冻结。旧v2状态请保留，使用同一原始证据和明确框图新建v3分析，禁止静默迁移自由填写的block名称。

以下 JSON 是合成结构示例，不是真实器件事实。完整可运行演示由 `scripts/test_interface_workbook.py --demo-dir <directory>` 生成。

manifest.json：

```json
{
  "analysis_id": "analysis-001",
  "schematic_snapshot": "schematic-uuid/revision-01",
  "diagram_snapshot": "querySolutionDesign:solution-001/version-04",
  "devices": [{
    "id": "DEV-U12", "scope": "board-A/root", "refdes": "U12",
    "code": "OLD-CODE", "target_code": "NEW-CODE", "replacement": true,
    "action": "CHANGE", "block_id": "B12", "block_name": "控制器",
    "reason": "明确的器件替换结论", "evidence": ["diff-result:item-3"]
  }]
}
```

```bash
python scripts/interface_workbook.py init --state work/book/state.json --input work/manifest.json --diagram work/solution-design.json
python scripts/interface_workbook.py seed --state work/book/state.json --input work/interface/state.json --output work/original-seed.json
python scripts/interface_workbook.py capture --state work/book/state.json --input work/original-seed.json
```

seed 的 device_id 必须与 manifest 一致。旧工具输出没有业务 code 时，从实际差异结果或器件信息补齐，而不是从位号推导。

capture 可追加行，也可单独提交 coverage：

```json
{
  "rows": [{
    "id": "O-U12-SPI0-SCLK", "device_id": "DEV-U12",
    "schematic_pins": "U12[12:SCLK] -> U20[6:CLK]",
    "source_pin_names": ["SCLK"],
    "net_name": "SPI0_SCLK", "instance": "SPI0",
    "analysis": "从U12的Pin 12追踪到U20的Pin 6",
    "connection_status": "VERIFIED",
    "chain": "U12[12] -> U20[6]",
    "chain_check": {"verified": true, "chain": "U12[12] -> U20[6]", "evidence": "tool-call-18"},
    "evidence": ["get_component_pins:call-12", "trace_net:call-16", "chain_check:call-18"],
    "peripherals": []
  }],
  "coverage": {
    "DEV-U12": {"status": "PARTIAL", "reason": "这里只演示单条信号，其他引脚未盘点", "evidence": ["call-12:page-1"]}
  }
}
```

工具原始响应应单独保存，证据引用包含调用 ID、文件位置/JSON 路径和同一工程快照标识；字符串引用不能代替实际工具调用。脚本检查结构和一致性，不能证明引用内容真实。

```bash
python scripts/interface_workbook.py next --state work/book/state.json --limit 3
python scripts/interface_workbook.py freeze --state work/book/state.json --allow-incomplete
```

正常完整结果不带 `--allow-incomplete`。COMPLETE 指“声明的差异器件局部边界及其所有 Pin 已覆盖”，不是整张图。空 Pin 响应不构成 COMPLETE。快照哈希包含 manifest、原始行、覆盖声明；发现外部改写会拒绝后续操作。发现原始事实错误时新建分析目录，不能反向改写已冻结记录。一个 state 由一个执行流程串行写入，不支持多个进程同时提交。

## 4. SPI0/SPI1 → SPI 的实现

顺序是 **原始 Net → Pin 功能/链路端点 → 物理接口实例 → 抽象协议候选 → 框图两端 Port → 信号成员**。

- 正则仅从原始名给出 family/instance 候选；SPI0 与 SPI1 不同，USB_D+ 与 USB_D- 也不同。物理网络名永远逐字保存。
- group key 应包含 scope + device_id + instance + 对端身份；不能只用 SPI 作为键。映射必须提供明确 row_ids，不使用“所有 SPI 网络”通配。
- 同一个抽象 SPI Port 可代表多个实例，允许多对一抽象映射，但 Excel 仍按实例/信号独立成行。多个目标 SPI Port 竞争同一物理实例时保留歧义，不选第一个。
- 原理图 Net 没有协议前缀时根据实际 Pin 名、器件功能和验证路径建立显式别名；不能改名来迎合正则。
- 源/目的 block 和 port 按当前框图边的方向填写，不因为 MISO 电气方向相反就交换框图端点。`schematic_pins` 按物理连接记录；双向、角色、电压等写分析说明或外围属性。不要用框图箭头推定电气输出方向。

Excel 的 `原理图pin脚` 只从 `source_pin_names` 导出源端名称，不直接输出内部 `schematic_pins` 链路字符串。例如源端Pin名称为 `SPI0_SCK` 时只写 `SPI0_SCK`，不写位号、脚号或目的端。Pin名称必须取源block对应器件的 `get_component_pins.pin_name`，不要把展开信号的规范名 SCLK 冒充真实Pin名 SPI0_SCK。同网有多个源端Pin时保留全部名称，以逗号分隔。未知用 `[]`，导出为空并列入待确认，禁止从链路左侧字符串猜测源端。

局部 seed 不知道框图源端归属，因此默认不填 source_pin_names。完成 map 时可提交 `"source_pin_names":{"原始行ID":["SPI0_SCK"]}` 和 `"source_pin_evidence":["源端get_component_pins调用引用"]`；这是映射后的源端注释，不覆盖冻结的原始事实。差异器件若是目的block，必须查询真正源block端的Pin名称。

新增/修改提案在 fields 提交 `"source_pin_names":["SPI0_SCK"]` 并附 `pin_evidence`。源端变化而没有新名称证据时清空旧名称，不能把旧端点Pin继续用于新源端。源端已知、目的端未知时，本列仍可填写已知源端名称，目的端缺项写入分析说明。
- 置信度是有依据的映射评估值，不是统计概率；0..1 数值或 null。仅名称相似时保持待确认，不用高分替代 chain_check。协议族一致本身不足以确认映射。

map.json 示例：

```json
{"mappings":[{
  "device_id":"DEV-U12", "row_ids":["O-U12-SPI0-SCLK"],
  "instance":"SPI0", "family":"SPI", "confidence":0.9,
  "endpoint":{"source_block_id":"B12","source_block_name":"控制器","source_port":"SPI",
    "destination_block_id":"B20","destination_block_name":"存储器","destination_port":"SPI"},
  "signals":{"O-U12-SPI0-SCLK":"SCLK"},
  "reason":"已确认两端block身份和SPI0局部路径", "evidence":["block-map:12-20","chain_check:call-18"]
}]}
```

```bash
python scripts/interface_workbook.py map --state work/book/state.json --input work/map.json
```

`instance_override_evidence` 仅用于工具/器件资料证明网络名前缀不是实际实例的情况，不能用于方便地把 SPI1 改成 SPI0。

对于框图省略的支撑电路或目前无法映射的接口，使用 `explain --input annotations.json`，格式为 `{"annotations":[{"row_id":"O1","disposition":"IMPLICIT_SUPPORT","reason":"局部上拉支路，不对应独立框图端口","evidence":["trace:真实证据引用"]}]}`。disposition 可选 IMPLICIT_SUPPORT、NOT_APPLICABLE、UNRESOLVED；它只解释映射缺失，不能消除未验证路径或删除原始行。`next` 同时返回 RESOLVE_ROW_DETAILS，避免“目标成员已有记录”掩盖物理Pin或网络仍未知。

## 5. 展开与修改

SPI 的 SCLK/MOSI/MISO/CS 是检查提示，不是强制模板：三线、四线、双/四线、只写设备、多个片选均须实际证据。I2C 同样要区分 SDA/SCL 及上拉；UART 区分 TX/RX、角色交叉及可选握手；USB 区分 D+/D- 和各通道。电压、电平转换、速率/终端、配置拉阻不能仅由协议名确定。

通过 expand 明确每条目标边的成员需求。同一 target.id 重复提交幂等。只有抽象 SPI 且资料不足时先报告 `DECLARE_TARGET_SIGNALS`，不填虚构四根线。

```json
{"targets":[{
  "id":"EDGE-12-20", "device_id":"DEV-U12", "instance":"SPI0", "family":"SPI",
  "endpoint":{"source_block_id":"B12","source_block_name":"控制器","source_port":"SPI",
    "destination_block_id":"B20","destination_block_name":"存储器","destination_port":"SPI"},
  "signals":["SCLK","MOSI","MISO","CS0"],
  "evidence":["target-requirement:explicit-4wire-spi"]
}]}
```

```bash
python scripts/interface_workbook.py expand --state work/book/state.json --input work/targets.json
python scripts/interface_workbook.py next --state work/book/state.json --limit 3
```

脚本将每个目标实例成员与修改后行精确比对：一个匹配表示该项有记录；零个是缺项；多个是歧义。它不推断电气兼容性，不能把“有记录”当作“可布线”。与目标成员无关的原始信号默认保留，可能是必要实现细节。

修改示例：

```json
{"changes":[{
  "id":"C-U12-SCLK", "device_id":"DEV-U12", "original_id":"O-U12-SPI0-SCLK",
  "action":"CHANGE", "target_id":"EDGE-12-20",
  "reason":"目标器件更换，时钟网络保留，目标Pin尚待确认",
  "evidence":["diff-result:item-3"],
  "fields":{"schematic_pins":"", "net_name":"SPI0_SCLK", "net_origin":"SCHEMATIC"}
}]}
```

ADD 不填 original_id；CHANGE/DELETE 必须引用同器件原始行。DELETE 信号必须有明确目标依据，不因目标框图省略而删除。CHANGE 若提供目标物理 Pin，额外提交 `pin_evidence` 数组，来源必须适用目标 code/封装；未知留空。器件 `replacement:true` 会清空未重新证明适用的旧 Pin。

新增信号的 fields 必须独立描述两端 block/port、instance、family、signal；网络名称未知留空，需要命名则 `net_origin:PROPOSED`。旧网络改名也只能是 PROPOSED。PROPOSED 仅说明设计意图，不可标为已执行或 VERIFIED。

```bash
python scripts/interface_workbook.py propose --state work/book/state.json --input work/changes.json
python scripts/interface_workbook.py export --state work/book/state.json --output work/book/model.json
node scripts/export_interfaces.mjs work/book/model.json outputs/interfaces work/book/previews
```

输出两个独立文件：`outputs/interfaces/原始信号接口.xlsx` 和 `outputs/interfaces/修改后信号接口.xlsx`。每个文件有自己的 BLOCK_INFO 和逐器件页签，每页只包含当前版本接口表，不再在同页上下拼放前后表。

修改后列表是目标快照：删除行从该列表移除，原始文件保留原始行，JSON中的 deleted_signals 保留删除血缘和原因。删除大器件仅在原始文件 `原始接口_删除` 留档；修改后文件的 BLOCK_INFO 仍标注删除，但不创建对应接口页。新增器件的原始接口为零行，不从目标需求虚构原始接口。

## 6. Excel 与运行依赖

前十列固定为：源block标识、源block名称、源port、目的block标识、目的block名称、目的port、原理图pin脚、分析说明、映射置信度、网络命名。

附加列用于保留：接口实例、抽象协议、展开信号、网络操作、网络来源、物理连接状态、原始行ID、行ID、证据、外围器件与支路、待确认项。不同器件可共享网络名，禁止跨器件去重。页签名自动去除非法字符、截断到31字符并消歧。

网络操作映射为 ADD=新增、DELETE=删除、CHANGE=修改、KEEP=保留。原始表显示旧接口对应的删除/修改计划；修改后表显示新增/修改结果。未变行标保留，不硬凑成三种变更。删除器件的原始接口全部标删除；单独删除信号也在原始表显式标删除。操作针对本行的接口/支路，同名网络其他器件仍可能使用，不能据此自动删除全局Net。仅改连接、Pin或外围电阻电容而保持网络名时，仍需提交CHANGE并说明修改内容。原始表的标签和说明由修改记录派生，不改变原始快照哈希。

两份文件的 `BLOCK_INFO` 使用同一分析版本的器件范围和增删改结论，方便对照。源/目的block和汇总block身份都由同一框图JSON索引生成。Excel 是评审快照，不是回写编辑器；手工改 Excel 不会更新控制器。要刷新修改后清单须提交 propose 并重新导出。完整冻结原始数据位于导出 model.json 的 original_snapshot；原始 Excel 表中的映射注释来自独立 mappings。

在有 spreadsheets 技能的环境，按该技能获取已捆绑 Node/模块并渲染检查。可把 exporter 复制到临时运行目录，在该目录创建指向现有 node_modules 的 junction/symlink，再运行；不要改写依赖目录。非 Codex 环境使用已安装的 Node 与 `@oai/artifact-tool`；也可通过 `ARTIFACT_TOOL_MODULE` 指向其公开模块入口。缺少 Excel 依赖时交付 JSON 草稿并明确 Excel 未完成，不能把 CSV 改扩展名冒充 xlsx。

## 7. 验证和停止

```bash
python scripts/test_interface_workbook.py
python scripts/interface_controller.py self-test
```

测试覆盖快照不可覆盖、实例和极性名称保留、增删改血缘、重复提交、目标缺项、替换器件 Pin、Excel 列顺序与页签名。另行检查导出的 xlsx 表头、数值置信度、各页记录数量和渲染外观。

外部工具未接入时只能声明合成测试通过；不能声称真实原理图验证完成。`pending`/待确认项非空或覆盖 PARTIAL 时必须说明是待补证据的方案草稿。预算耗尽时停止工具调用并保存状态；未冻结时可继续局部采集。已冻结的部分原始清单如需补充物理事实，保留旧版本并新建下一版分析，不能追加覆盖冻结数据。目标或原理图版本改变也须新建分析。
