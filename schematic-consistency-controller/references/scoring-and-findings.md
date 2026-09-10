# 评分与结论规则

只有在提交 Block、Port 和局部依赖证据时阅读本文件。

## 1. Block 候选评分口径

### identity_score

```text
1.00  已验证的 componentUuid、Pinlist 或人工绑定
0.90  企业业务编码/CBB 编码精确匹配
0.80  精确料号或型号匹配，且所在功能上下文合理
0.65  功能角色和主要 Port 组合匹配
0.45  名称相似，但缺少器件或拓扑证据
0.20  仅页面位置、坐标或弱关键词相似
0.00  身份冲突
```

### capability_score

```text
1.00  所有目标强制能力均已验证
0.85  主要能力满足，次要属性尚未验证
0.60  功能类型匹配，但参数信息不足
0.30  只有部分能力匹配
0.00  存在明确能力冲突
```

未知信息不能按 1.0 处理，也不应无条件按 0 处理。

### port_score

优先按目标必要 Port 的加权覆盖率计算：

```text
已匹配必要 Port 权重 / 目标必要 Port 总权重
```

电源、时钟、复位、协议主通道的权重应高于测试和可选 Port。

### neighborhood_score

```text
1.00  所有已映射相邻 Block 均存在兼容链路证据
0.80  大多数相邻关系兼容
0.50  尚未检查邻接关系
0.25  邻接关系明显不同
0.00  存在已验证的错误远端
```

## 2. Block 硬冲突

以下问题写入 `hard_conflicts`，由控制器排除自动选择：

- 器件角色完全不兼容。
- 目标必需协议不受支持。
- 通道数量不足。
- 电压、电流或功率能力明确不满足。
- 差分接口被映射到不兼容的单端接口。
- 目标要求隔离，但候选无法提供隔离功能。
- 已验证的相邻拓扑连接到错误功能模块。

## 3. Port 映射评分

```text
1.00  框图 Pinlist 与原理图 Pin/Net 精确验证
0.90  引脚功能、协议、方向、电压域和远端均匹配
0.80  引脚功能及协议匹配，远端尚未完成链路验证
0.75  名称、角色和方向高度匹配
0.60  名称相似，但方向或电压域信息不足
0.40  仅网络名称相似
0.00  明确错误引脚、通道、方向或电压域
```

Port 评分达到阈值只代表端点映射可用，不代表目标边已经连通。

## 4. 证据等级

```text
E0  语义推测
E1  器件、引脚、CBB 或局部拓扑结构化证据
E2  trace_net/trace_connection 候选链路
E3  chain_check 验证的精确链路
```

目标边成为 `VERIFIED` 必须达到 E3。

## 5. 差异类型

### 模块与器件

```text
MISSING_IMPLEMENTATION
EXTRA_IMPLEMENTATION_CANDIDATE
AMBIGUOUS_MODULE_MAPPING
DEVICE_CAPABILITY_MISMATCH
DEVICE_PARAMETER_MISMATCH
DEVICE_REPLACEMENT_REQUIRED
```

### 接口

```text
PORT_MISSING
PORT_RENAME_CANDIDATE
PORT_DIRECTION_MISMATCH
PIN_MAPPING_MISMATCH
BUS_MEMBER_MISSING
DIFFERENTIAL_MEMBER_MISMATCH
```

### 拓扑

```text
TOPOLOGY_EQUIVALENT
TOPOLOGY_EQUIVALENT_WITH_IMPLEMENTATION_DETAIL
CONNECTION_MISSING
WRONG_ENDPOINT
WRONG_DIRECTION
AMBIGUOUS_PATH
UNVERIFIED_PATH
NOT_OBSERVED_WITHIN_SCOPE
```

### 支撑网络

```text
VOLTAGE_DOMAIN_MISMATCH
PROTOCOL_MISMATCH
REQUIRED_TRANSFORM_MISSING
POWER_DEPENDENCY_MISMATCH
CLOCK_DEPENDENCY_MISMATCH
RESET_DEPENDENCY_MISMATCH
CONFIGURATION_MISMATCH
SUPPORT_CIRCUIT_MISMATCH
```

## 6. 中间器件处理

```text
TRANSPARENT_OR_PASSIVE  电阻、0Ω、磁珠、连接器触点
PROTECTIVE              ESD、TVS、保险丝
FILTERING               RC/LC、共模滤波
TRANSFORMING             电平转换、隔离器、收发器、变压器
ACTIVE_ENDPOINT          MCU、处理器、转换器、传感器、存储器
UNEXPLAINED              未知或复杂有源网络
```

前三类可以在功能图中折叠，但应保留在路径字符串和语义列表中。`TRANSFORMING` 必须检查方向、电压域、协议和隔离属性；`UNEXPLAINED` 不得自动判定等价。

## 7. 删除建议限制

原理图存在而框图没有显示的对象，先归类：

```text
IMPLEMENTATION_DETAIL
DEBUG_OR_TEST
POWER_INFRASTRUCTURE
OPTIONAL_VARIANT
FUNCTIONAL_EXTRA
UNKNOWN_EXTRA
```

只有证据充分的 `FUNCTIONAL_EXTRA` 可以形成调查或删除候选。`UNKNOWN_EXTRA` 不能转成删除操作。

即使归类为 `FUNCTIONAL_EXTRA`，逐信号操作仍先保持 UNRESOLVED；只有确认目标功能已经移除、绑定具体原始interface_id并提交 `confirmed_functional_removal:true` 后，才能成为 DELETE。
