## Why

当前契约测试已经覆盖工具、测量质量门、修复和装配，但仍不能回答一张真实图片经过 Gateway、VLM、面板交接、测量、修复和渲染后到底在哪一步失败。完整的多模型评测平台需要先有一条可信的真实运行诊断链，因此本次先建立最小的真实链路观察能力，而不是直接引入大规模指标和回归体系。

## What Changes

- 新增第一阶段真实图表链路诊断，使用少量经过授权的真实图片进行人工触发的端到端运行。
- 登记首批多面板图片和折线图图片，记录相对资源引用、内容指纹以及用于人工核对的预期面板信息；不要求本阶段具备完整数值真值。
- 通过现有附件和 Gateway run 入口执行真实 provider 链路，明确记录 provider/model；真实 provider 不可用时不得静默回退到替代模型或契约数据。
- 复用已有 run/event、panel、measurement、repair 和 artifact 引用，整理出输入、分区、面板交接、测量、审核、修复、assemble、render 的阶段时间线。
- 输出有界的 JSON 与 Markdown 诊断报告，展示每个阶段是否到达、相关证据引用和第一个可确认的失败阶段。
- 为重复拆分、整图测量、审核失败未修复、面板未进入 assemble、运行中断等现有问题提供可定位的诊断结果。

本阶段不实现通用 IoU/数值准确率体系、多 provider 回归比较、成本统计、CI 自动调用真实模型、大规模标注管理或前端评测控制台；这些内容留给后续独立 change。

## Capabilities

### New Capabilities

- `real-chart-evaluation`: 以真实授权图表图片运行第一阶段完整链路诊断，采集阶段证据并定位第一个可确认的失败环节。

### Modified Capabilities

- 无。现有 `chart-understanding`、`execution-trace` 和 `measurement-quality-gate` 作为被评估的生产契约被复用，本变更不修改它们的要求。

## Impact

- 新增最小真实样本清单、Gateway 运行适配、事件阶段归一化和诊断报告模块，以及对应的离线测试。
- 诊断依赖现有 Gateway、Agent、VLM provider、测量工具、质量门、assemble 和渲染链路；真实 provider 调用必须由显式配置开启。
- 诊断只复用现有 run/history/event、panel 和 artifact 引用，不新增生产协议、数据库或前端评测界面。
- Python 命令和测试继续使用 `agent` Conda 环境；现有契约测试保持不变，真实运行结果只作为人工诊断证据。
