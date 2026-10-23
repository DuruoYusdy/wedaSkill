---
name: hw-pcie-signal-matching
description: "PCI Express 根端口、端点/交换机数据 lane、参考时钟与复位旁带匹配。"
文件名: "PCIe信号匹配SKILL.md"
描述: "PCI Express 根端口、端点/交换机数据 lane、参考时钟与复位旁带匹配。"
status: draft
version: 0.1.0
---

# PCIe信号匹配技能

**功能说明：** PCI Express 根端口、端点/交换机数据 lane、参考时钟与复位旁带匹配。

主要内容：引脚别名与方向、电气兼容、拓扑决策、连接矩阵、SI/时序和检查项。先读取 [SPEC.md](SPEC.md) 的范围、规则与待补项，以及 [通用规则](../00-通用规则与模板修正.md)。本文是参考库草稿；不是某组器件已完成的匹配报告。

**覆盖范围：** PCI Express 根端口、端点/交换机数据 lane、参考时钟与复位旁带匹配。 不适用于仅凭接口名称直接落板、跨协议套线或缺少必选入口的实际匹配。

## 输入要求或入口条件（必选）

用户提供信息应包含：

- **器件 A 和器件 B**（多设备时为全部参与器件）的接口引脚定义：原始名称、功能、相对本器件的方向；有复用时给出本次模式。
- 工作场景、端点角色、设备数量与物理连接边界：一驱一 / 一驱二 / 一驱多，或本文明确定义的点到点、链式、总线、交换网络等拓扑。
- 可选：工作电压、电平标准、速率、线长、层叠、连接器、上电/掉电状态及性能目标；这些不是统一入口必填项。

**必选信息不全，先询问并等待补充，再分析实际连接。** 等待期间只整理资料与缺口，不输出候选连线。可选电气信息缺失时可做依据充分的逻辑匹配，但电平/SI 为 `UNKNOWN`，不能确认最终电气直连。编写参考文档时可继续维护草稿，不要求虚构一组 A/B。

## 核心工作流（必选）

### 第一步：解析PCIe信号引脚（必选）

提取所有参与器件相关引脚，按功能、角色和模式标准化；先查确切型号/封装的 datasheet、勘误和 pin mux。网络名只生成候选。

#### PCIe信号常见引脚命名变体（必选）

| 标准名/功能组 | 必须识别的候选别名 | 常见变体 | 功能/方向与限制 | 证据状态 |
| --- | --- | --- | --- | --- |
| TX_LANE | TXP/TXN | TX_P/N, TD_P/N, SERDOUT | 本端发射对；名字须与具体端口功能核对 | 候选别名；须器件手册复核 |
| RX_LANE | RXP/RXN | RX_P/N, RD_P/N, SERDIN | 本端接收对；lane 序号不自动可交换 | 候选别名；须器件手册复核 |
| REFERENCE | REFCLK_P/N | SERDES_REFCLK, GTREFCLK | 本地参考源，架构决定是否共享 | 候选别名；须器件手册复核 |
| RESET | PERST# | PCIE_PERST_N, nPERST | 根/平台→端点复位，电平/时序查实现 | 候选别名；须器件手册复核 |
| CLOCK_REQUEST | CLKREQ# | PCIE_CLKREQ_N | 可选开漏旁带，核对适用省电模式 | 候选别名；须器件手册复核 |
| WAKE | WAKE# | PCIE_WAKE_N | 可选唤醒旁带 | 候选别名；须器件手册复核 |
| CONNECTOR_NAMES | PET/PER | PETp/n, PERp/n | 以对应 CEM/M.2 等连接器规范视角定义，不直接当芯片本端 TX/RX 别名 | 候选别名；须器件手册复核 |

#### 引脚方向判断规则（必选）

根端口/交换机下游 TX→端点/上游 RX，反向同理；连接器 PET/PER 方向须按该规范展开。REFCLK 方向由 Common Clock/SRNS/SRIS 架构决定。

- 使用已配置模式下的引脚功能表为准；I/O 是能力标记，不代表所有时刻都允许同时驱动。
- `n`、`#`、横线等是低有效命名线索，仍须核对；无此前缀不能推断高有效。
- 厂商对照表为可选。本稿不将某器件命名或 GPIO 编号推广为整个厂商惯例。

### 第二步：电平判断结论

#### 判断器件电平（按优先级）

1. 读取具体引脚功能、电气类型、所属 bank/IO 域与实际配置、供电；不能只读芯片核心 VCC。
2. 读取对应工作条件下的推荐范围、DC/AC Electrical Characteristics、输入容限、输出负载、掉电与钳位限制。
3. 用 Supply Voltage 与板上供电确认适用工作点和允许范围；可调供电范围不代表实际能同时兼容范围内全部电平。
4. 以协议/PHY 规范和参考设计复核；同一条件资料冲突时列明冲突，不能用优先级静默覆盖。缺关键依据记 `UNKNOWN`。

**本接口判据：** 逐方向核对差分摆幅、接收灵敏度、共模、终端、AC/DC 耦合和协议速率/编码能力；参考时钟和低速旁带分别评价。P/N 名称相似和名义供电相同不能证明兼容。 来源与实施细节见 [通用电气规则](../00-通用规则与模板修正.md) 和 [SPEC](SPEC.md)。

结论必须逐器件、逐信号方向记录：实际 IO 域/电气标准、门限或摆幅/共模、额定/掉电条件、资料位置、兼容性及是否需要中间功能。结论使用 `PASS / FAIL / UNKNOWN`；未分析为 `NOT_CHECKED`。

#### 电平转换方案选择（按优先级）

1. 原生收发器电气和协议模式兼容时按专用耦合/终端规则连接。
2. 通道不足且两端模式兼容时评估专用 redriver/retimer/PHY，核对其协议与时钟要求；它们不必然能做协议转换。
3. 端点电气或协议不兼容时选完整 PHY/桥接或更改端点；TXS0108E 等普通逻辑转换器不适用高速数据 lane。

任何候选方案都需核对 DIR/OE、供电顺序、输出释放、负载、延迟和本接口协议行为；未选型时只写功能节点，不能编造器件引脚号。

### 第三步：连接规则与场景判断匹配（必选）

#### 信号流向及连接规则

根端口/交换机下游 TX→端点/上游 RX，反向同理；连接器 PET/PER 方向须按该规范展开。REFCLK 方向由 Common Clock/SRNS/SRIS 架构决定。

逐条执行 [SPEC 的 R-001 起各规则](SPEC.md#规则与要求)，规则包含适用条件与来源。以下是本接口的拓扑分支；“一驱”只是便于对照用户格式，不表示所有接口都有 Master/Slave。

**一驱一（SCN-001）**

一驱一：一个根/下游端口对应一个端点/上游端口，多 lane 组成同一训练链路。

```text
Port A <-> compatible Port B1
```

**一驱二（SCN-002）**

一驱二：两个独立根端口、受支持 bifurcation，或根端口→PCIe switch→两个端点；不能分叉同一 TX 对。

```text
A.P1 <-> B1; A.P2 <-> B2 OR supported active switch/chain
```

**一驱多（SCN-003）**

一驱多：通过 PCIe switch/多个独立端口构造树；逐段核对时钟/复位域、lane 和带宽。

```text
Independent point-to-point ports / supported active fabric <-> B1..Bn; no passive lane split
```

**接口详细链路示意（抽象功能例图）：**

```text
A.TX_P/N -- [coupling/channel as specified] --> B.RX_P/N
A.RX_P/N <-- [coupling/channel as specified] -- B.TX_P/N
Multiple endpoints: independent ports / supported active fabric
Reference clocks and sidebands: separate verified paths
```

### 第四步：输出信号连接矩阵

以下是填写格式示例，原名为示例记号，**不代表本次已确认接线**。实际运行时替换为手册中的真实名称/引脚号，并逐信号、逐 bit/lane、逐共享成员展开。

| 示例连接ID | 标准信号 | 起点原名/方向（示例） | 终点原名/方向（示例） | 共享/连接方式 | 规则 | 初始状态 |
| --- | --- | --- | --- | --- | --- | --- |
| CON-001 | TX lane i | A.原TX_P/N [OUT] | B.原RX_P/N [IN] | 记录 lane 映射、极性、耦合 | SPEC R/SCN + 对应器件手册 | NOT_CHECKED |
| CON-002 | RX lane j | B.原TX_P/N [OUT] | A.原RX_P/N [IN] | 反方向逐 lane | SPEC R/SCN + 对应器件手册 | NOT_CHECKED |
| CON-003 | REFCLK | 已确认参考时钟源 | 各本地参考输入 | 按实际时钟架构 | SPEC R/SCN + 对应器件手册 | NOT_CHECKED |
| CON-004 | SIDEBAND | 本协议实际源 | 实际目标端口 | 逐信号/中间节点，不省略 | SPEC R/SCN + 对应器件手册 | NOT_CHECKED |

- 一驱一：列出 A 与 B1 的全部目标信号；不存在的可选脚注明“不存在/不适用及依据”。
- 一驱二/一驱多：分别列出 B1、B2…Bn；共享网标识相同但每个端点单列。独立端口/链式逐段展开，不能只复制共享总线假设。
- 每行补齐场景 ID、网络名、电压域、中间功能/连接器针位/视图、规则与 datasheet 位置、电平结果、连接状态和未决项。
- 区分“连接 / 禁止连接 / 按手册悬空 / 待确认”；NC/DNU 按手册处理。未知引脚保留，不静默丢弃。
- 未确认电气条件时写“逻辑候选，电气 UNKNOWN”；建议不等同已写入 EDA，也不等同已观测原理图。

### 第五步：信号完整优化分析

核查通道预算、均衡、参考时钟抖动和复位释放；redriver/retimer 是否需要由预算确定。资料以特定 TI 平台作方法实例，各 PCIe 代际的阻抗/电容/速率限制须取得对应规范。

按 [SPEC 的 SI-001](SPEC.md#信号完整优化分析) 记录输入、方法、限值来源、计算/仿真/实测和结果；缺资料的具体项目为 `UNKNOWN`。不得固定使用“Stub<20mm”“差长<5mm”“节点增加就降至固定百分比”或“一律添加固定阻容”等跨接口阈值。

## 输出格式

始终按以下顺序输出五部分：

1. **电平判断结论** — 每器件/电源域及每方向的兼容性、依据和未知项。
2. **信号匹配结论** — 逐场景连接矩阵，保留标准名与原始引脚名；说明哪些连、哪些禁止、哪些未定。
3. **连接示意图** — 本次实际拓扑 ASCII 图，展开所有中间功能和共享/独立关系。
4. **风险检查清单** — 下述通用与本接口分场景检查项的逐项证据/结果。
5. **补充建议** — 有条件的时序/SI/外围/转换方案、所需资料和下一步验证。

## 通用设计 Checklist（每次信号匹配必须执行）

| 检查ID | 对象 | 方法与通过判据 | 依据 | 初始结果 |
| --- | --- | --- | --- | --- |
| CHK-001 | 入口 | 所有参与器件/封装、原始引脚名/功能/方向及角色拓扑齐全；入口缺失停止匹配 | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-002 | 解析 | 逐脚保留原始名、标准名、模式、极性/驱动类型及手册位置；同名不代替功能证据 | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-003 | 电平 | 按每个方向/电源状态核对门限或差分/模拟标准；未知不能记作无需转换 | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-004 | 转换 | 中间功能满足方向、速率、负载、延迟、掉电和使能条件；无不适用通用器件 | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-005 | 拓扑 | 一/二/多设备的共享、独立、仲裁/选通及数量边界满足协议与端点能力 | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-006 | 矩阵 | 覆盖全部范围内信号、端点、bit/lane、共享成员、中间功能及连接器针位/视图 | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-007 | 时序/SI | 建立保持/往返、边沿/负载、回流/差分/终端或模拟性能按适用分支分析 | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-008 | 启动/故障 | 复位、strap、上下电、未选中高阻、热插拔和故障行为按实际场景检查 | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-009 | 证据/结果 | 每个结论可回溯来源；建议、观察、仿真和实测结果分开，未做检查不记 PASS | 本节流程 + COMMON + SPEC | NOT_CHECKED |
| CHK-010 | 接口专项 | 角色/代际/宽度及分叉配置支持 | SPEC R/SCN | NOT_CHECKED |
| CHK-011 | 接口专项 | TX/RX 与连接器视角正确 | SPEC R/SCN | NOT_CHECKED |
| CHK-012 | 接口专项 | 时钟架构双方兼容 | SPEC R/SCN | NOT_CHECKED |
| CHK-013 | 接口专项 | AC 耦合和复位/低功耗旁带正确 | SPEC R/SCN | NOT_CHECKED |

**分场景加检：**

- 一驱一：一驱一：一个根/下游端口对应一个端点/上游端口，多 lane 组成同一训练链路。 检查双方功能、默认态和单链路电气/时序。
- 一驱二：一驱二：两个独立根端口、受支持 bifurcation，或根端口→PCIe switch→两个端点；不能分叉同一 TX 对。 增查共享返回、片选/仲裁或第二独立端口的约束。
- 一驱多：一驱多：通过 PCIe switch/多个独立端口构造树；逐段核对时钟/复位域、lane 和带宽。 逐端点复核总负载、域/时钟、地址/路由或链顺序，不按数量套统一降速。

运行时给每项补上对象、方法、限值来源、证据、结果和未决项。结果只用 `PASS / FAIL / UNKNOWN / NOT_APPLICABLE / NOT_CHECKED`。入口不满足时只执行入口核查，其余记 `NOT_CHECKED` 并写原因；不能报告整体通过。

## 备注与参考资料

- 未给出的关键规则和数值见 [SPEC 待补项](SPEC.md#待补项)；知识状态 `draft` 与硬件测试结果分开。
- 若环境确有符号/引脚查询工具，可辅助获取原始信息；仍需 datasheet 核实。本次未使用、也不假定存在 `symbol-pin-fetcher`。
- 来源（公开实现仅适用于所注明的器件/模式，不构成默认选型）：[SRC-PCIE：TI Jacinto7 AM6x/TDA4x/DRA8x High-Speed Interface Design Guidelines](https://www.ti.com/lit/an/spracp4a/spracp4a.pdf)；[SRC-HS：TI High-Speed Interface Layout Guidelines](https://www.ti.com/lit/an/spraar7j/spraar7j.pdf)。
