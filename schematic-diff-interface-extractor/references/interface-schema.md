# 接口数据与分类规则

## 1. 接口定义

一个接口表示差异器件上共享同一原理图 Net 的一组 Pin，以及该 Net 向外围延伸的局部电气路径。

```text
Interface = Device + Pins[] + Net + Electrical Attributes + Verified Paths[]
```

不要把同一 Net 上的同一器件多个 Pin 重复输出为多个接口。

这是局部查询种子的合并规则，不是 Excel 信号行去重规则。一个种子存在多个远端/扇出分支时，正式 Excel 可展开为多行，每行保留独立端点、原始行ID和验证证据。前后清单使用 `interface_workbook.py seed` 导入全部已返回路径，不以旧 Markdown/CSV 中的单条 `verified_chain` 代替所有路径。

## 2. 输出字段

| 字段 | 含义 |
|---|---|
| `device_id` | 本次分析中的差异器件 ID |
| `refdes` / `cbb_id` | 原理图定位标识 |
| `difference_types` | 上一阶段识别的差异 |
| `interface_id` | 控制器生成的稳定接口 ID |
| `pins` | 属于该接口的器件 Pin 集合 |
| `net_name` | 旧原理图当前网络名 |
| `category` | DATA、CONTROL、CLOCK 等 |
| `protocol` | USB、I2C、SPI、UART 等 |
| `direction` | 从差异器件视角观察的方向 |
| `voltage` | 已知电压域 |
| `bus_group` | 总线组 |
| `differential_pair` | 差分对名称 |
| `scope_class` | 外部信号、局部支撑等范围分类 |
| `remote_endpoints` | 追踪到的远端器件/引脚或 CBB 边界 |
| `intermediate_components` | 路径中的阻容、保护、滤波和转换器件 |
| `verified_chain` | 通过 chain_check 的精确链路 |
| `target_relation` | 与当前框图目标 Port 的关系 |
| `status` | 当前提取和验证状态 |
| `evidence_level` | E1 或 E3 |

## 3. 信号分类

```text
DATA          数字数据或协议接口
CONTROL       使能、中断、片选、告警和同步
CLOCK         时钟、晶振和参考时钟
RESET         复位和上电复位
CONFIG        Boot、Strap、模式和地址配置
ANALOG        ADC/DAC、采样、反馈、补偿和基准
OTHER_SIGNAL  无法归入上述类型的普通信号
TEST_DEBUG    JTAG、SWD、测试和调试
POWER         电源
GROUND        地
NC            明确不连接
MIXED         同一 Net 上的 Pin 分类发生冲突
```

自动分类只用于调度和初始报告。如果器件数据明确给出不同语义，应以结构化器件信息为准。

## 4. 接口范围分类

```text
EXTERNAL_SIGNAL
    连接到另一个主器件、连接器、层次端口或 CBB 边界

LOCAL_SUPPORT
    只形成该器件的局部上拉、下拉、滤波、反馈、补偿或配置网络

POWER_SUPPORT
    电源和地支撑接口

TEST_DEBUG
    测试点、JTAG、SWD 或调试连接

UNKNOWN
    当前局部证据不足
```

## 5. 状态

```text
PENDING
    尚未追踪

VERIFIED
    至少一条外围链路通过 chain_check

STRUCTURED_ONLY
    由 Pin/Net 结构确认，但按规则不进行全局追踪，如电源和地

UNCONNECTED
    Pin 明确未连接

NO_REMOTE_CONNECTION
    查询覆盖完整局部边界并确认没有远端连接

NOT_OBSERVED_WITHIN_SCOPE
    达到局部查询边界仍未观察到远端

UNVERIFIED_PATH
    候选路径均未通过 chain_check

SKIPPED_NC
    明确 NC
```

## 6. 证据等级

```text
E1  get_component_pins 或 CBB 拓扑提供的 Pin/Net 结构证据
E2  trace_net/trace_connection 提供的候选路径
E3  chain_check 验证通过的精确链路
```

接口清单可以包含 E1 项，但必须在状态中说明尚未完成远端验证。

## 7. 中间器件角色

建议记录：

```text
SERIES_RESISTOR
PULL_UP
PULL_DOWN
TERMINATION
DECOUPLING
FILTER
ESD_OR_TVS
COMMON_MODE_CHOKE
LEVEL_SHIFTER
ISOLATOR
TRANSCEIVER
CONNECTOR
TEST_POINT
UNKNOWN
```

无源器件可以被 `trace_net` 穿透，但必须保留位号、值和角色。有源转换器必须保留方向、电压域和功能，不得折叠成普通连接。

## 8. 与目标框图的关系

```text
MATCHED_TARGET_PORT
MATCHED_TARGET_PORT_NAME
PORT_RENAME_CANDIDATE
PIN_REMAP_CANDIDATE
IMPLICIT_SUPPORT
UNMATCHED_TO_TARGET_PORT
NO_TARGET_PORT_CONTEXT
```

`UNMATCHED_TO_TARGET_PORT` 不能直接解释为应删除；它可能是必要实现细节、调试接口或框图省略项。
