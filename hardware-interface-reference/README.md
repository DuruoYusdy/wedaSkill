# 硬件接口参考文档

已覆盖用户清单的全部 **33 项**，每项均提供 `SKILL.md`（匹配流程）和 `SPEC.md`（规则、条件、来源、待补项）。另有总览、通用规则、公开来源索引和合并阅读版。

- [全部接口参考文档](全部接口参考文档.md)：按用户顺序阅读全部 33 项及配套规则。
- [通用规则与模板修正](00-通用规则与模板修正.md)：电平兼容、转换选型和原示例修正。
- [公开来源索引](01-公开来源索引.md)：标准组织/厂商链接、版本和定位。
- [内部接口与版本待补表](03-内部接口与版本待补表.md)：TBus、IDX/UDX、204X 等后续补充入口。

本次交付为 **v0.1.0 参考草稿**，未安装到个人技能目录。保留独立文件可继续维护；复制单项时应同时保留其 SPEC、相对引用的通用规则和来源。不声称已完成具体器件匹配或硬件验证。

TBus、IDX1、IDX2、UDX 等待内部定义；204X 提供待确认是否为 JESD204 的条件分支。DDRx、ETH、XGE 等接口族需先选定代际/接口层。公开规则不能代替实际器件型号、封装和模式的手册。

## 逐项目录

| 序号 | 用户条目 | 匹配流程 | 配套规则 | 状态/特别边界 |
| --- | --- | --- | --- | --- |
| 01 | SPI | [SKILL](spi/SKILL.md) | [SPEC](spi/SPEC.md) | draft；实际器件应用需核对 |
| 02 | IIC（I2C） | [SKILL](iic/SKILL.md) | [SPEC](iic/SPEC.md) | draft；实际器件应用需核对 |
| 03 | eSPI（ESPI） | [SKILL](espi/SKILL.md) | [SPEC](espi/SPEC.md) | draft；实际器件应用需核对 |
| 04 | JTAG | [SKILL](jtag/SKILL.md) | [SPEC](jtag/SPEC.md) | draft；实际器件应用需核对 |
| 05 | PMBus | [SKILL](pmbus/SKILL.md) | [SPEC](pmbus/SPEC.md) | draft；实际器件应用需核对 |
| 06 | MDIO | [SKILL](mdio/SKILL.md) | [SPEC](mdio/SPEC.md) | draft；实际器件应用需核对 |
| 07 | SMBus（Smbus） | [SKILL](smbus/SKILL.md) | [SPEC](smbus/SPEC.md) | draft；实际器件应用需核对 |
| 08 | LocalBus | [SKILL](localbus/SKILL.md) | [SPEC](localbus/SPEC.md) | draft；实际器件应用需核对 |
| 09 | DDRx | [SKILL](ddrx/SKILL.md) | [SPEC](ddrx/SPEC.md) | draft；实际器件应用需核对 |
| 10 | QSPI | [SKILL](qspi/SKILL.md) | [SPEC](qspi/SPEC.md) | draft；实际器件应用需核对 |
| 11 | 串口（UART） | [SKILL](uart/SKILL.md) | [SPEC](uart/SPEC.md) | draft；实际器件应用需核对 |
| 12 | MII | [SKILL](mii/SKILL.md) | [SPEC](mii/SPEC.md) | draft；实际器件应用需核对 |
| 13 | RMII | [SKILL](rmii/SKILL.md) | [SPEC](rmii/SPEC.md) | draft；实际器件应用需核对 |
| 14 | GMII | [SKILL](gmii/SKILL.md) | [SPEC](gmii/SPEC.md) | draft；实际器件应用需核对 |
| 15 | CAN | [SKILL](can/SKILL.md) | [SPEC](can/SPEC.md) | draft；实际器件应用需核对 |
| 16 | RS485（RS-485） | [SKILL](rs485/SKILL.md) | [SPEC](rs485/SPEC.md) | draft；实际器件应用需核对 |
| 17 | RS422（RS-422） | [SKILL](rs422/SKILL.md) | [SPEC](rs422/SPEC.md) | draft；实际器件应用需核对 |
| 18 | USB2.0 | [SKILL](usb2/SKILL.md) | [SPEC](usb2/SPEC.md) | draft；实际器件应用需核对 |
| 19 | USB3.0 | [SKILL](usb3/SKILL.md) | [SPEC](usb3/SPEC.md) | draft；实际器件应用需核对 |
| 20 | 基础数字信号（GPIO 等） | [SKILL](gpio/SKILL.md) | [SPEC](gpio/SPEC.md) | draft；实际器件应用需核对 |
| 21 | 射频差分信号（AFE 相关） | [SKILL](afe/SKILL.md) | [SPEC](afe/SPEC.md) | draft；实际器件应用需核对 |
| 22 | CFG（FPGA 加载信号） | [SKILL](cfg/SKILL.md) | [SPEC](cfg/SPEC.md) | draft；实际器件应用需核对 |
| 23 | TBus | [SKILL](tbus/SKILL.md) | [SPEC](tbus/SPEC.md) | draft；内部定义待补 |
| 24 | CPRI | [SKILL](cpri/SKILL.md) | [SPEC](cpri/SPEC.md) | draft；实际器件应用需核对 |
| 25 | ETH（Ethernet） | [SKILL](eth/SKILL.md) | [SPEC](eth/SPEC.md) | draft；实际器件应用需核对 |
| 26 | eCPRI | [SKILL](ecpri/SKILL.md) | [SPEC](ecpri/SPEC.md) | draft；实际器件应用需核对 |
| 27 | 204X（待绑定 JESD204x） | [SKILL](204x/SKILL.md) | [SPEC](204x/SPEC.md) | draft；204X 定义待确认 |
| 28 | 背板高速 IDX1 | [SKILL](idx1/SKILL.md) | [SPEC](idx1/SPEC.md) | draft；内部定义待补 |
| 29 | 背板高速 IDX2 | [SKILL](idx2/SKILL.md) | [SPEC](idx2/SPEC.md) | draft；内部定义待补 |
| 30 | 背板高速 UDX | [SKILL](udx/SKILL.md) | [SPEC](udx/SPEC.md) | draft；内部定义待补 |
| 31 | XGE（10 Gigabit Ethernet） | [SKILL](xge/SKILL.md) | [SPEC](xge/SPEC.md) | draft；实际器件应用需核对 |
| 32 | PCIe | [SKILL](pcie/SKILL.md) | [SPEC](pcie/SPEC.md) | draft；实际器件应用需核对 |
| 33 | SRIO | [SKILL](srio/SKILL.md) | [SPEC](srio/SPEC.md) | draft；实际器件应用需核对 |

## 使用示例

“依据 SPI 的 SKILL/SPEC，核对 A 与 B1/B2 的一驱二连接；以下是全部器件原始引脚名、功能、方向及角色……”实际运行按五部分格式输出，电气输入缺失的项目保持 UNKNOWN。
