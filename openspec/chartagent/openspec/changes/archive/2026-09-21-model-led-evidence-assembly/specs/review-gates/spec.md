## MODIFIED Requirements

### Requirement: Review gates block downstream execution

系统 SHALL 仅对真正需要发布保护的审核阶段建立共享阻塞门禁。生成图审核处于 `reviewing`、`repair_required`、`failed` 或 `exhausted` 时，系统 SHALL 阻止 render 后的 publish 或成功终结；measurement observation 的 warning、`partial` 或 `remeasure_required` SHALL 作为可追踪诊断，不得独占阻塞 OCR、布局观察、其他测量或主 Agent 的候选组装。

#### Scenario: Measurement observation remains non-blocking

- **WHEN** 测量工具返回候选和质量 warning
- **THEN** 运行记录保存 observation、问题和可选下一动作
- **AND** 主 Agent 仍可调用其他证据工具或提交 evidence decision

#### Scenario: Generated chart review blocks publication

- **WHEN** 生成图候选尚未通过生成审核
- **THEN** 系统阻止发布和声称成功的最终结果
- **AND** 候选、ChartSpec 和审核状态仍可被主 Agent 和客户端查看

#### Scenario: Gate cannot be bypassed by final text

- **WHEN** 模型最终文本声称候选已经通过，但生成审核仍处于阻塞状态
- **THEN** 系统保持发布门禁关闭
- **AND** 客户端显示代码拥有的审核状态

### Requirement: Review repair is a controlled sub-loop

生成图审核返回 `repair_required` 且仍有预算时，系统 SHALL 只允许与该候选关联的 ChartSpec 修正和重新渲染，并在发布前重新审核。测量 observation 的局部重测不再作为共享 review gate 的独占子循环，而是主 Agent 可以主动调用的普通有界工具动作；两类动作都必须保留来源和父对象 lineage。

#### Scenario: Generated candidate repair is controlled

- **WHEN** 当前生成图审核要求修正 ChartSpec
- **THEN** 系统限制后续生成动作到该候选的修正和重新渲染
- **AND** 父失败候选保持不可发布且可追踪

#### Scenario: Measurement re-observation does not freeze unrelated work

- **WHEN** 主 Agent 根据测量 warning 请求局部补充
- **THEN** 系统记录新的 measurement attempt 和父 attempt
- **AND** OCR、布局观察或对其他未依赖候选的判断不因该补充请求被隐式跳过

### Requirement: Review failures close the gate without implicit bypass

生成图审核失败、超时、证据不可用、非法审核结果或重试耗尽 SHALL 保持生成发布门禁关闭，并返回有界的失败分类和恢复信息。测量 observation 的重测预算耗尽 SHALL 关闭该补充分支，但不应被伪装成生成图审核失败；如果模型选择其他可追溯证据，主链路可以继续。

#### Scenario: Generated review budget is exhausted

- **WHEN** 生成图审核或候选修复达到配置上限
- **THEN** 当前生成候选进入明确的 `exhausted` 非发布状态
- **AND** 运行结果不得声称生成成功

#### Scenario: Measurement repair budget is exhausted

- **WHEN** 某个 measurement session 的局部补充达到上限
- **THEN** 系统记录 `measurement_repair_exhausted` 及最后诊断
- **AND** 不再自动重测，但不把整个 run 错报为 generated chart review failure

#### Scenario: Stale review cannot release publication

- **WHEN** 审核结果引用错误的 subject、attempt、candidate 或 ChartSpec digest
- **THEN** 系统拒绝应用该结果
- **AND** 任何已通过的其他审核对象和发布状态不发生变化
