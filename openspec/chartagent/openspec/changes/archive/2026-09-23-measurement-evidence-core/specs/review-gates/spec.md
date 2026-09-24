## MODIFIED Requirements

### Requirement: Review gates block downstream execution

系统 SHALL 仅对真正需要发布保护的审核阶段建立共享阻塞门禁。generated-chart review 处于 `reviewing`、`repair_required`、`failed` 或 `exhausted` 时，系统 SHALL 阻止 render 后的 publish 或成功终结；measurement observation 的 warning 或 `partial` 状态 SHALL 作为工具结果中的诊断，不得独占阻塞 OCR、布局观察、其他测量或主 Agent 的候选组装。

#### Scenario: Measurement observation remains non-blocking

- **WHEN** 测量工具返回候选和质量 warning
- **THEN** 运行记录保存 observation、问题和可选的局部范围线索
- **AND** 主 Agent 可自主调用其他证据工具、再次调用带范围的测量工具，或直接提交合法 assembly

#### Scenario: Generated chart review blocks publication

- **WHEN** 生成图候选尚未通过生成审核
- **THEN** 系统阻止发布和声称成功的最终结果
- **AND** 候选、ChartSpec 和审核状态仍可被主 Agent 和客户端查看

#### Scenario: Gate cannot be bypassed by final text

- **WHEN** 模型最终文本声称候选已通过审核但代码拥有的 generated-chart review 仍处于阻塞状态
- **THEN** 系统保持发布门禁关闭
- **AND** 客户端显示代码拥有的审核状态

### Requirement: Review failures close the gate without implicit bypass

生成图审核失败、超时、证据不可用、非法审核结果或候选修复耗尽 SHALL 保持 generated-chart 发布门禁关闭，并返回有界的失败分类和恢复信息。局部测量的失败或无法补充 SHALL 作为普通 measurement tool result 返回，不改变 generated-chart gate，不产生单独的 measurement repair-exhausted 生命周期状态；主 Agent 可以自主选择其他可追溯证据或结束运行。

#### Scenario: Generated review budget is exhausted

- **WHEN** 生成图审核或候选修复达到配置上限
- **THEN** 当前生成候选进入明确的 `exhausted` 非发布状态
- **AND** 运行结果不得声称生成成功

#### Scenario: Measurement failure does not create a review gate

- **WHEN** 局部测量失败、区域不充分或模型选择不再补充证据
- **THEN** 运行记录保留该 measurement 工具结果及 bounded 诊断
- **AND** 不创建 measurement review/repair gate 或 `measurement_repair_exhausted` 状态
- **AND** 其他合法证据路线和 ChartSpec assembly 不因该结果被独占阻塞

#### Scenario: Stale review cannot release publication

- **WHEN** 审核结果引用了错误的 subject、attempt、candidate 或 ChartSpec digest
- **THEN** 系统拒绝应用该结果
- **AND** 任何其他审核对象的门禁或发布状态都不发生变化
