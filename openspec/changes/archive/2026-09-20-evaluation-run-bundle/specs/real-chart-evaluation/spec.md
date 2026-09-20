## MODIFIED Requirements

### Requirement: 真实样本必须通过现有运行边界执行

诊断系统 SHALL 使用最小版本化样本清单登记真实图片。每个样本至少包含稳定的 `case_id`、受控的相对图片引用、图片内容指纹以及用于人工核对的预期面板信息；预期信息可以只包含面板数量、名称或粗略区域，不要求本阶段提供完整数值真值。

每一批真实诊断 MUST 在创建 Gateway run 前建立并记录唯一的 `evaluation_id`，随后通过现有附件和 Gateway run 入口进入 Agent/VLM 生产链路，不得直接调用内部测量函数并将结果标记为端到端运行。每个运行必须记录 `evaluation_id`、`run_id`、provider、model、样本标识和运行模式；provider 不可用或运行未启动时必须明确标记原因，不得静默回退到契约数据或其他模型。

#### Scenario: 运行一张真实多面板图片

- **WHEN** 用户显式开启真实诊断并提交清单中的多面板图片
- **THEN** 系统通过现有附件和 Gateway run 创建真实运行，并将运行结果关联到评测批次、样本和 `run_id`

#### Scenario: 图片引用或指纹无效

- **WHEN** 样本引用包含绝对路径、图片不存在或内容指纹不匹配
- **THEN** 系统在启动真实运行前拒绝该样本，并返回可定位的清单错误

#### Scenario: provider 不可用

- **WHEN** provider 缺少配置、请求失败或运行被阻塞
- **THEN** 系统将该 case 诊断标记为 `not_run` 或 `blocked`，说明原因，并不使用替代模型或合成结果填充运行结果

### Requirement: 诊断报告必须指出第一个可确认的失败阶段

系统 SHALL 从阶段时间线生成有界的 JSON 事实结果和 Markdown 摘要，并将每个 case 的结果保存到所属评测根目录下的 `diagnostics/`。系统同时 MUST 生成评测批次级 JSON/Markdown 汇总，汇总样本、评测状态、provider/model、每个 case 的 run 引用、阶段状态、关键异常和第一个可由现有证据确认的失败阶段。诊断归因至少支持 `decomposition`、`panel_routing`、`measurement`、`repair`、`assembly_render`、`transport_runtime` 和 `unknown`。

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

#### Scenario: Default diagnostics location is evaluation-local

- **WHEN** 用户运行真实图表诊断且没有显式指定评测根目录
- **THEN** 每个 case 的 JSON 事实结果和 Markdown 摘要保存在 canonical data root 下对应 `evaluations/<evaluation_id>/diagnostics/` 中
- **AND** 批次汇总与 Gateway 的数据库、附件和 run artifacts 保存在同一个评测根目录下
