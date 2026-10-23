# 硬件接口参考文档

全部 **33 项接口，每项一个 `XX.md` 文件**，例如 `SPI.md`、`IIC.md`、`PCIe.md`。每个文件合并匹配流程和配套规则，包含别名、方向、电气判断、场景拓扑、连接矩阵、Checklist、来源及待补项。

版本：v0.1.0；状态：draft。资料整理日期：2026-10-22；文件整理日期：2026-10-23。本次只调整文件组织，不代表重新核验了全部标准。

| 序号 | 接口 | 文件 | 覆盖边界 |
| --- | --- | --- | --- |
| 01 | SPI | [SPI.md](SPI.md) | 具体器件应用需按手册核对 |
| 02 | IIC（I2C） | [IIC.md](IIC.md) | 具体器件应用需按手册核对 |
| 03 | eSPI（ESPI） | [ESPI.md](ESPI.md) | 具体器件应用需按手册核对 |
| 04 | JTAG | [JTAG.md](JTAG.md) | 具体器件应用需按手册核对 |
| 05 | PMBus | [PMBus.md](PMBus.md) | 具体器件应用需按手册核对 |
| 06 | MDIO | [MDIO.md](MDIO.md) | 具体器件应用需按手册核对 |
| 07 | SMBus（Smbus） | [Smbus.md](Smbus.md) | 具体器件应用需按手册核对 |
| 08 | LocalBus | [LocalBus.md](LocalBus.md) | 具体器件应用需按手册核对 |
| 09 | DDRx | [DDRx.md](DDRx.md) | 具体器件应用需按手册核对 |
| 10 | QSPI | [QSPI.md](QSPI.md) | 具体器件应用需按手册核对 |
| 11 | 串口（UART） | [UART.md](UART.md) | 具体器件应用需按手册核对 |
| 12 | MII | [MII.md](MII.md) | 具体器件应用需按手册核对 |
| 13 | RMII | [RMII.md](RMII.md) | 具体器件应用需按手册核对 |
| 14 | GMII | [GMII.md](GMII.md) | 具体器件应用需按手册核对 |
| 15 | CAN | [CAN.md](CAN.md) | 具体器件应用需按手册核对 |
| 16 | RS485（RS-485） | [RS485.md](RS485.md) | 具体器件应用需按手册核对 |
| 17 | RS422（RS-422） | [RS422.md](RS422.md) | 具体器件应用需按手册核对 |
| 18 | USB2.0 | [USB2.0.md](USB2.0.md) | 具体器件应用需按手册核对 |
| 19 | USB3.0 | [USB3.0.md](USB3.0.md) | 具体器件应用需按手册核对 |
| 20 | 基础数字信号（GPIO 等） | [GPIO.md](GPIO.md) | 具体器件应用需按手册核对 |
| 21 | 射频差分信号（AFE 相关） | [AFE.md](AFE.md) | 具体器件应用需按手册核对 |
| 22 | CFG（FPGA 加载信号） | [CFG.md](CFG.md) | 具体器件应用需按手册核对 |
| 23 | TBus | [TBus.md](TBus.md) | 内部定义待补 |
| 24 | CPRI | [CPRI.md](CPRI.md) | 具体器件应用需按手册核对 |
| 25 | ETH（Ethernet） | [ETH.md](ETH.md) | 具体器件应用需按手册核对 |
| 26 | eCPRI | [eCPRI.md](eCPRI.md) | 具体器件应用需按手册核对 |
| 27 | 204X（待绑定 JESD204x） | [204X.md](204X.md) | 204X 定义待确认；JESD204 为条件分支 |
| 28 | 背板高速 IDX1 | [IDX1.md](IDX1.md) | 内部定义待补 |
| 29 | 背板高速 IDX2 | [IDX2.md](IDX2.md) | 内部定义待补 |
| 30 | 背板高速 UDX | [UDX.md](UDX.md) | 内部定义待补 |
| 31 | XGE（10 Gigabit Ethernet） | [XGE.md](XGE.md) | 具体器件应用需按手册核对 |
| 32 | PCIe | [PCIe.md](PCIe.md) | 具体器件应用需按手册核对 |
| 33 | SRIO | [SRIO.md](SRIO.md) | 具体器件应用需按手册核对 |

GPIO.md 对应“基础数字信号（GPIO 等）”，AFE.md 对应“射频差分信号（AFE 相关）”，CFG.md 对应 FPGA 加载信号，IDX1.md/IDX2.md/UDX.md 对应各背板高速接口。

## 共用资料

- [通用规则与模板修正](00-通用规则与模板修正.md)
- [公开来源索引](01-公开来源索引.md)
- [交付结构核查](02-交付结构核查.md)
- [内部接口与版本待补表](03-内部接口与版本待补表.md)

## 使用示例

“依据 SPI.md，核对 A 与 B1/B2 的一驱二连接；以下是全部器件的原始引脚名、功能、方向及角色……”

运行时按电平判断、匹配矩阵、ASCII 示意图、风险检查、补充建议五部分输出；电气输入缺失的项目保持 UNKNOWN。文档仍为参考草稿，不代表已执行具体器件匹配、EDA 修改或硬件实测。
