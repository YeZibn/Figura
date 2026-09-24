## MODIFIED Requirements

### Requirement: 诊断报告必须指出第一个可确认的失败阶段

系统 SHALL 从阶段时间线生成有界的 JSON 事实结果和 Markdown 摘要，并在未指定其他输出目录时将它们保存到 canonical data root 下的 `diagnostics/`。报告必须展示样本、run、provider/model、各阶段状态、关键事件引用、最终产物引用以及第一个可由现有证据确认的失败阶段。诊断归因至少支持 `decomposition`、`panel_routing`、`measurement`、`repair`、`assembly_render`、`transport_runtime` 和 `unknown`。

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

#### Scenario: Default diagnostics location is project-local

- **WHEN** 用户运行真实图表诊断且没有显式指定输出目录
- **THEN** JSON 事实结果和 Markdown 摘要保存在 canonical data root 下的 `diagnostics/`
- **AND** 不会默认写入项目外的临时报告目录或用户 home 目录
