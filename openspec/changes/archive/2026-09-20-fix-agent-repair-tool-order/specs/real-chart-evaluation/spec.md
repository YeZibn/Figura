## MODIFIED Requirements

### Requirement: 诊断报告必须指出第一个可确认的失败阶段

系统 SHALL 从阶段时间线生成有界的 JSON 事实结果和 Markdown 摘要，并将每个 case 的结果保存到所属评测根目录下的 `diagnostics/`。系统同时 MUST 生成评测批次级 JSON/Markdown 汇总，汇总样本、评测状态、provider/model、每个 case 的 run 引用、阶段状态、关键异常和第一个可由现有证据确认的失败阶段。诊断归因至少支持 `decomposition`、`panel_routing`、`measurement`、`repair`、`assembly_render`、`transport_runtime` 和 `unknown`。模型或 provider 请求失败 SHALL 归因于实际发生的模型/传输失败，不得仅因后续阶段未到达而标记为 `render` 或 `assembly_render`；未观察到的后续阶段 SHALL 保持 `not_reached` 或 `not_observed`。

报告 MUST 对 API key、Authorization 头、绝对本地路径和未经授权的原始图片内容进行脱敏或只保留受控引用。本阶段报告不计算通用 IoU、数值准确率或跨模型回归分数；缺少证据时必须标记为 `unknown`，不能根据最终图片主观猜测根因。工具调用成功返回与测量质量接受必须分开表达；`remeasure_required`、repair 可用、repair 阻塞和 repair 已解决不得被汇总为同一个 `completed` 状态。provider 错误摘要可以保留有限的类型、状态和错误代码，但不得保存完整凭据或未经脱敏的 provider payload。

#### Scenario: 面板正确但后续未使用

- **WHEN** 事件显示分区产生了目标 panel，但测量使用整图或没有绑定该 panel
- **THEN** 报告将问题归因为 `panel_routing` 或 `measurement`，并关联分区和测量事件

#### Scenario: 测量完成但最终图缺少面板

- **WHEN** 某个 panel 的测量已完成且通过审核，但最终 assemble/render 没有包含该 panel
- **THEN** 报告将第一个可确认失败阶段标记为 `assembly_render`，并关联测量和最终产物证据

#### Scenario: 模型请求在 assemble 和 render 之前失败

- **WHEN** 已观察到输入、分区或测量事件，但下一次模型请求返回 provider/transport 错误，且没有观察到审核、assemble 或 render 事件
- **THEN** 报告将第一个失败归因为 `transport_runtime` 或等价的模型请求失败
- **AND** `quality_review`、`assembly` 和 `render` 均标记为 `not_reached` 或 `not_observed`
- **AND** 报告不得把该失败阶段标记为 `render`

#### Scenario: 测量工具返回但质量门禁要求重测

- **WHEN** 测量工具返回结构化数据，同时其质量状态为 `remeasure_required` 或 repair action 可用
- **THEN** 报告区分工具调用完成与测量未被接受
- **AND** repair 阶段显示待处理、阻塞或已解决的实际状态，而不是仅依据工具返回成功标记为已完成

#### Scenario: 没有足够证据

- **WHEN** 运行在事件不完整、历史缺失或 provider 异常处结束，无法确认更早阶段的责任
- **THEN** 报告标记 `unknown` 或 `transport_runtime`，说明缺少的证据，不输出伪造的准确率结论

#### Scenario: Default diagnostics location is evaluation-local

- **WHEN** 用户运行真实图表诊断且没有显式指定评测根目录
- **THEN** 每个 case 的 JSON 事实结果和 Markdown 摘要保存在 canonical data root 下对应 `evaluations/<evaluation_id>/diagnostics/` 中
- **AND** 批次汇总与 Gateway 的数据库、附件和 run artifacts 保存在同一个评测根目录下
