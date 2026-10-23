---
spec_type: interface-scenario
spec_version: 0.1.0
status: draft
evidence_review: partial
review_date: 2026-10-22
---

# DDRx信号匹配规则与来源

## 身份与覆盖范围

通用分代检查；详细公开实例以 AMD DDR4 为主；DDR1/2/3/3L/5 的落板参数须另补对应手册。

对应 [SKILL.md](SKILL.md)。本文件保存规则和来源；入口流程、别名表、方向规则、两个优先级、矩阵和 Checklist 见 Skill；共用电气方法见 [COMMON](../00-通用规则与模板修正.md)。当前为通用资料整理草稿，无实际 A/B 器件验收结果。

## 场景

在待实例化的系统中，A 与 B1…Bn 根据所选接口承担明确角色，通过该分支规定的板内/板间/线缆链路交换其功能数据或控制信息，目标是在端点共同支持的模式和性能约束下完成连接。实际器件、物理边界、电气/时序和验收限值由本次输入绑定。

| 场景ID | 触发条件与连接规则 | 异常/不适用处理 |
| --- | --- | --- |
| SCN-001 | 一驱一：单颗粒/单 Rank；逐 Byte Lane 绑定 DQ/DQS/DM、CA/CK 和参考网。 | 不支持/未知的共享、数量或模式不得擅自扩展；回到独立端口/合适中间功能或补充资料 |
| SCN-002 | 一驱二：先区分位宽扩展和双 Rank；前者分配不同 DQ，后者仅按控制器支持方式共享，不把两颗数据全并联。 | 不支持/未知的共享、数量或模式不得擅自扩展；回到独立端口/合适中间功能或补充资料 |
| SCN-003 | 一驱多：按 Rank 数、DIMM 类型、控制器和负载设计；CA/CK 可能采用 fly-by，数据依 Byte Lane/Rank 规则。 | 不支持/未知的共享、数量或模式不得擅自扩展；回到独立端口/合适中间功能或补充资料 |

适用例：按确切器件资料执行本接口分支的信号匹配。不适用例：只给接口名称就要求确认可直连，或将另一接口的同名端口当本接口规则。

## 要求与决策

| 要求ID | 归属/条件 | 要求与通过判据 | 决策/检查 |
| --- | --- | --- | --- |
| REQ-001 | 全部 SCN，进入实际匹配前 | 全部端点 pin 功能/方向和角色拓扑齐全 | DEC-001；CHK-001 |
| REQ-002 | 逐信号/电源状态 | 适用电气限制全部满足；未知不记通过 | DEC-002；CHK-003/004 |
| REQ-003 | 选定拓扑 | 端点共享/独立和数量能力符合规则 | DEC-003；CHK-005/006 |
| REQ-004 | 项目验收 | 时序/SI/业务指标采用项目/器件限值并可判定 | DEC-004；CHK-007 |

- DEC-001：必选入口缺失则询问等待；可选电气缺失只阻塞依赖它的结论。
- DEC-002：按 Skill 第二步核对电气；通过才考虑直连，不兼容按功能/方向选择中间节点；未知不猜。
- DEC-003：按 SCN 与 R 规则选择拓扑；不支持多点的链路用独立端口/适用主动结构，不被动并联。
- DEC-004：按 SI-001 和器件/项目指标安排原理图、PCB、仿真与实测验证，尚未执行保持 NOT_CHECKED。

## 规则与要求

| 规则ID | 条件/范围 | 等级与内容 | 来源/证据状态 | 检查与阶段 |
| --- | --- | --- | --- | --- |
| R-001 | 声明范围内，按本次模式选择 | MUST：先锁定 DDR/DDR2/DDR3/DDR3L/DDR4/DDR5 及颗粒组织；LPDDR 系列需独立规则，不能直接套用。 | SRC-DDR；SRC-DDR5；verified-source（通用机制；器件适用性待核） | 原理图/配置审查；逐条对照所用器件资料；未执行 NOT_CHECKED |
| R-002 | 声明范围内，按本次模式选择 | MUST：同 Rank 多颗粒常分配不同 DQ 位段扩展位宽，共享规定的 CA/CK；多 Rank 才可能按控制器规则共享数据组。 | SRC-DDR；SRC-DDR5；verified-source（通用机制；器件适用性待核） | 原理图/配置审查；逐条对照所用器件资料；未执行 NOT_CHECKED |
| R-003 | 声明范围内，按本次模式选择 | MUST：DQ/Byte Lane 交换、DQS 极性、地址镜像和 ECC 映射仅在 IP/颗粒明确支持时允许，并记录配置。 | SRC-DDR；SRC-DDR5；verified-source（通用机制；器件适用性待核） | 原理图/配置审查；逐条对照所用器件资料；未执行 NOT_CHECKED |
| R-004 | 声明范围内，按本次模式选择 | MUST：供电、VREF、ODT/外部终端、ZQ、电源顺序和训练按代际联合设计；普通逻辑转换器不能连接不兼容代际。 | SRC-DDR；SRC-DDR5；verified-source（通用机制；器件适用性待核） | 原理图/配置审查；逐条对照所用器件资料；未执行 NOT_CHECKED |

规则为公开资料的工程归纳，`verified-source` 表示已读取相关来源的通用机制，并非覆盖所有型号、版本和边界条件的逐条标准认证。器件引脚别名均是候选；每次应用必须补充确切型号/封装/模式的 Pin Function、DC/AC、勘误位置。超出来源覆盖的版本/参数保持 unresolved。

## 信号完整优化分析

**SI-001（SHOULD；触发条件：实际链路/负载/速率已知）：** 依控制器 PCB 指南和 pin planner 核查封装延迟、Byte Lane 内偏斜、CA 对 CK、跨 Rank 负载、ODT 与训练窗口；不设统一长度差。

方法：收集边沿/速率、负载、层叠/线缆及元件模型，采用适用的时序计算、传输线/频域分析或实验；通过标准来自所用器件/协议版本或明确项目需求。没有限值/模型时只提出有条件建议，结果 UNKNOWN。共用布线方法参见 [SRC-HS](https://www.ti.com/lit/an/spraar7j/spraar7j.pdf)，其平台实例参数不能跨接口照搬。

## 验收与追踪

| 检查组 | 要求/规则 | 方法 | 初始结果 |
| --- | --- | --- | --- |
| 入口 | REQ-001 / DEC-001 | 检查资料及角色清单 | NOT_CHECKED |
| 电气 | REQ-002 / DEC-002 | 按类别比较限值及电源状态 | NOT_CHECKED |
| 连接 | REQ-003 / SCN / 全部 R | 检查矩阵、共享关系、中间节点及真实针位 | NOT_CHECKED |
| 优化/业务 | REQ-004 / SI-001 | 对照可定位限值进行配置/PCB/仿真/实测检查 | NOT_CHECKED |

具体 CHK 编号和判据在 [Skill Checklist](SKILL.md#通用设计-checklist每次信号匹配必须执行)；所有结果仅限实际已执行的项目。

## 来源

| 来源ID | 原始资料 | 版本/日期 | 定位/限制 |
| --- | --- | --- | --- |
| SRC-DDR | [AMD UltraScale Architecture PCB Design User Guide](https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/Topology-and-Routing-Guidelines-for-DDR4-SDRAM) | UG583 v1.29，2025-12-23 | Topology and Routing Guidelines for DDR4 SDRAM 及子节 |
| SRC-DDR5 | [AMD Versal PCB Guidelines for Memory Interfaces](https://docs.amd.com/r/en-US/ug863-versal-pcb-design/PCB-Guidelines-for-Memory-Interfaces) | UG863 v1.12，2026-06-16 | 支持架构列表；Required Memory Routing Guidelines 入口 |

读取/整理日：2026-10-22。只核验与本参考库有关的部分和版本入口，不宣称已逐条审阅全部标准。需登录/付费/未取得的正文及其条款不能写成已核实数值。标准入口页只证明版本/范围，不替代正文电气条款。器件手册是具体实现例证。

## 待补项

| 待补ID | 缺口 | 影响/是否阻塞就绪 | 下一步/状态 |
| --- | --- | --- | --- |
| Q-001 | 各代颗粒手册及 IP 配置 | 影响对应分支最终连接；阻塞该范围 ready | 取得器件/内部规范并冻结版本；OPEN |
| Q-002 | 层叠/时序预算/训练验收 | 影响对应分支最终连接；阻塞该范围 ready | 取得器件/内部规范并冻结版本；OPEN |

别名原名、角色/驱动方式、精确数值和未支持拓扑均随这些条目补齐。全部关键规则在声明范围内有可定位来源与适用边界后才可评估 ready；不要求提前虚构未来某组 A/B，亦不表示通过硬件实测。
