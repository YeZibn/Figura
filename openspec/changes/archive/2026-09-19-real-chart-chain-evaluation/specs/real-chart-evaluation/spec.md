## Purpose

为少量真实授权图表图片提供一条轻量、可追溯的端到端诊断链，帮助确认分区、面板交接、测量、修复和最终装配究竟在哪个阶段出现问题，而不是立即建立完整的准确率评测平台。

## ADDED Requirements

### Requirement: 真实样本必须通过现有运行边界执行

诊断系统 SHALL 使用最小版本化样本清单登记真实图片。每个样本至少包含稳定的 `case_id`、受控的相对图片引用、图片内容指纹以及用于人工核对的预期面板信息；预期信息可以只包含面板数量、名称或粗略区域，不要求本阶段提供完整数值真值。

真实诊断 MUST 通过现有附件和 Gateway run 入口进入 Agent/VLM 生产链路，不得直接调用内部测量函数并将结果标记为端到端运行。运行必须记录 `run_id`、provider、model、样本标识和运行模式；provider 不可用或运行未启动时必须明确标记原因，不得静默回退到契约数据或其他模型。

#### Scenario: 运行一张真实多面板图片

- **WHEN** 用户显式开启真实诊断并提交清单中的多面板图片
- **THEN** 系统通过现有附件和 Gateway run 创建真实运行，并将运行结果关联到该样本和 `run_id`

#### Scenario: 图片引用或指纹无效

- **WHEN** 样本引用包含绝对路径、图片不存在或内容指纹不匹配
- **THEN** 系统在启动真实运行前拒绝该样本，并返回可定位的清单错误

#### Scenario: provider 不可用

- **WHEN** provider 缺少配置、请求失败或运行被阻塞
- **THEN** 系统将诊断标记为 `not_run` 或 `blocked`，说明原因，并不使用替代模型或合成结果填充运行结果

### Requirement: 诊断必须整理已有事件为阶段时间线

诊断结果 SHALL 复用现有 run/history/event、panel、measurement、repair 和 artifact 引用，整理出输入、分区、面板交接、测量、审核、修复、assemble 和 render 阶段。每个阶段至少必须有 `completed`、`failed`、`not_reached` 或 `not_observed` 状态，并保留相关事件 sequence、面板/attempt/artifact 引用和有限错误摘要。

诊断不得新增一套与 Gateway 冲突的运行状态或持久化协议。运行中断或中途失败时，已经收到的阶段必须保留，未到达阶段必须明确标记为 `not_reached`，不能生成看似完整的成功时间线。

#### Scenario: 链路完整结束

- **WHEN** 真实运行完成最终 assemble 或渲染
- **THEN** 时间线能够展示从输入到最终产物的阶段顺序，并关联每个已完成阶段的稳定证据引用

#### Scenario: 运行在审核或修复阶段结束

- **WHEN** 质量审核失败、修复预算耗尽或运行在后续阶段中断
- **THEN** 时间线保留已有测量和审核事件，将修复或后续阶段标记为失败/未到达，并显示其错误摘要

#### Scenario: 运行重复拆分或整图测量

- **WHEN** 事件中出现多次分区，或多面板图片的测量事件没有绑定 `panel_id`
- **THEN** 时间线明确展示重复分区或未作用域测量，并将其作为可诊断问题，而不是隐藏在最终结果中

### Requirement: 诊断报告必须指出第一个可确认的失败阶段

系统 SHALL 从阶段时间线生成有界的 JSON 事实结果和 Markdown 摘要。报告必须展示样本、run、provider/model、各阶段状态、关键事件引用、最终产物引用以及第一个可由现有证据确认的失败阶段。诊断归因至少支持 `decomposition`、`panel_routing`、`measurement`、`repair`、`assembly_render`、`transport_runtime` 和 `unknown`。

报告 MUST 对 API key、Authorization 头、绝对本地路径和未经授权的原始图片内容进行脱敏或只保留受控引用。本阶段报告不计算通用 IoU、数值准确率或跨模型回归分数；缺少证据时必须标记为 `unknown`，不能根据最终图片主观猜测根因。

#### Scenario: 面板正确但后续未使用

- **WHEN** 事件显示分区产生了目标 panel，但测量使用整图或没有绑定该 panel
- **THEN** 报告将问题归因为 `panel_routing` 或 `measurement`，并关联分区和测量事件

#### Scenario: 测量完成但最终图缺少面板

- **WHEN** 某个 panel 的测量已完成且通过审核，但最终 assemble/render 没有包含该 panel
- **THEN** 报告将第一个可确认失败阶段标记为 `assembly_render`，并关联测量和最终产物证据

#### Scenario: 没有足够证据

- **WHEN** 运行在事件不完整、历史缺失或 provider 异常处结束，无法确认更早阶段的责任
- **THEN** 报告标记 `unknown` 或 `transport_runtime`，说明缺少的证据，不输出伪造的准确率结论
