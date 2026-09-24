# generated-chart-verification Specification

## Purpose

为生成图提供单一、自动且代码强制的验证和发布契约，将图像、ChartSpec、来源范围及审核结论准确绑定，同时允许 Agent 根据结构化诊断自主选择后续修复动作。

## Requirements

### Requirement: Rendered output is staged with immutable attribution

每个生成图 SHALL 在验证前持久暂存图像及有界、不可变的尝试身份。记录 SHALL 绑定 run/tool call、图像摘要、准确 ChartSpec 摘要、授权来源 attachment/panel 与 revision、generation context、figure/collection 关联和验证策略版本。暂存引用 SHALL 为不透明、session/run scoped；相同图像内容不得自动等于相同验证上下文。

#### Scenario: Crash after render retains verification input
- **WHEN** render 图像及其绑定记录已提交而验证尚未完成时进程中断
- **THEN** resume 读取相同暂存输入继续验证
- **AND** 不把图像当作正式 artifact

#### Scenario: Identical pixels have different source claims
- **WHEN** 两次生成输出相同像素但来源范围或 ChartSpec 不同
- **THEN** 它们保留不同的尝试与验证身份

### Requirement: Verification runs automatically and returns one bounded decision

系统 SHALL 对每个生成尝试执行适用的确定性 ChartSpec、渲染和编码图像检查；源图关联或显式要求语义验证的尝试 SHALL 自动执行内部、无工具的 VLM 比较。结果 SHALL 为 pass、pass_with_warning、fail 或 unavailable 之一，并保留有界 checks、issues、严重级别、受影响位置、修复提示/目标、输入身份和策略版本。无效 VLM JSON、超时或来源缺失 MUST NOT 推断为通过。

#### Scenario: Source-linked chart requires scoped VLM
- **WHEN** 图像声称还原或转换授权源图范围
- **THEN** VLM 只接收该范围的源图、生成图、准确 ChartSpec 和任务上下文
- **AND** 它不能调用 OCR、CV、布局、测量或其他工具

#### Scenario: Direct data avoids a false fidelity claim
- **WHEN** 生成只使用用户提供的结构化数据且策略不要求源图语义比较
- **THEN** 系统执行适用的确定性检查
- **AND** 结果不声称与不存在的源图一致

#### Scenario: Invalid reviewer response fails closed
- **WHEN** VLM 返回无效、超限或自相矛盾的结论
- **THEN** 验证为失败或不可用，并给出有界原因
- **AND** 图像不能发布

### Requirement: Semantic reviewer retains a strict bounded content contract

内部 VLM SHALL 只返回一个 JSON 对象，且顶层恰好包含 `decision`、`confidence`、`checks`、`issues` 四个字段。`decision` 仅允许 `pass`、`pass_with_warning`、`fail`；`confidence` 为 0..1 的数字。`checks` SHALL 恰好包含 `chart_type`、`orientation`、`layout`、`data_mapping`、`labels`、`readability`，每项仅允许 `pass`、`warning`、`fail`。`issues` 最多 32 项，每项有有界且非空的 `code`、`location`、`message` 和 `warning` 或 `error` 严重级别。

审核 SHALL 结合 `reconstruct`、`transform`、`summarize`、`synthesize` 任务方式及适用来源，检查图表类型、整图旋转、横纵方向、坐标轴方向、类别顺序、系列身份、值或相对几何、零基线、标签和可读性；柱状、折线、饼图、散点图 SHALL 执行相应的图型检查。`pass` 要求所有检查通过且无 issues；`pass_with_warning` 不得有失败检查或 error issue，且至少有一条 warning；`fail` 要求至少有失败检查或 error issue。无法验证的关键关系、缺字段、多字段、无效枚举或不一致结论 SHALL NOT 推断为通过。每个生成尝试最多提交一个 VLM 结论；已提交结论在恢复时复用，未提交的远端请求仅在显式 resume 时可重发。

#### Scenario: Bar baseline is visually wrong
- **WHEN** 柱图的柱体起点没有对齐坐标系零基线
- **THEN** 审核返回 `fail` 和定位到布局或数据映射的 error issue
- **AND** 不因为图像底边或绘图区边缘最近就将其视为零基线

#### Scenario: Uncommitted VLM request is resumed
- **WHEN** VLM 远端请求已经发出但其响应未提交，用户显式恢复 Run
- **THEN** 系统可重发该请求并只提交一个有效结论
- **AND** 已提交的同尝试结论不会重复请求

### Requirement: Verification is bound to exact source and policy

验证前 SHALL 确认源附件仍属于当前 session、内容摘要及 panel handoff 有效，且引用的 measurement/evidence 与生成范围一致。已提交验证结果只适用于相同图像、ChartSpec、来源上下文和策略版本；失效或跨范围结果 SHALL 被拒绝。验证重试和重新生成尝试 SHALL 有界，次数从可归属的已提交尝试推导。

#### Scenario: Stale source is not semantic failure
- **WHEN** 源附件或 panel revision 已失效
- **THEN** 返回 source binding 诊断而不发布
- **AND** 不将其伪装成 VLM 对图表语义的判断

#### Scenario: Result belongs to another attempt
- **WHEN** 已保存结果的图像、Spec 或来源绑定与当前暂存尝试不符
- **THEN** 系统拒绝使用该结果并保持发布关闭

### Requirement: Promotion is idempotent and requires a matching nonblocking result

只有绑定完全匹配、已提交且策略允许的 pass 或 pass_with_warning 结果 SHALL 允许生成正式 artifact；warning SHALL 在用户结果中明确保留。重复发布同一尝试 SHALL 返回同一 artifact，失败、不可用、待验证或过期尝试 SHALL 不产生正式 artifact 引用。

#### Scenario: Crash during promotion
- **WHEN** 验证通过后发布完成但下一步游标尚未返回给 Agent
- **THEN** resume 核对已发布结果并复用同一 artifact
- **AND** 不生成第二份正式图表

#### Scenario: Failed image remains diagnostic only
- **WHEN** 验证失败但暂存图像仍可读取
- **THEN** 授权用户可以预览失败图及诊断
- **AND** 正式 artifact 下载和最终成功声明不可使用该图

### Requirement: Agent chooses correction while code guards completion

失败结果 SHALL 作为工具观察向主 Agent 提供有界诊断；Agent MAY 选择当前授权范围内的观察、测量、ChartSpec 修正、重新生成或停止。修复提示 SHALL NOT 自动调度工具或限制为固定 repair phase。最终回答和 Run 完成入口 SHALL 核对未决验证及引用的正式 artifact；耗尽预算或不可恢复失败 SHALL 给出明确非成功终态。

#### Scenario: Agent selects an alternative legal repair
- **WHEN** 验证建议修正 Spec 但 Agent 发现同一授权范围需要补充证据
- **THEN** 它可以显式调用适用的证据工具
- **AND** 新图仍必须重新验证

#### Scenario: Final answer cannot bypass verification
- **WHEN** 模型宣称某暂存或失败图已成功发布
- **THEN** 代码不以该宣称完成成功生成
- **AND** 运行结果保留可定位的失败或未完成原因

### Requirement: Collection children keep distinct outcomes

同一 collection 的子图 SHALL 保留 parent/figure/child 关联、各自范围、尝试、issues 和发布结果。集合投影 MAY 将它们分组，但一个子图的通过结果 SHALL NOT 覆盖另一个子图的失败或警告。

#### Scenario: One child fails
- **WHEN** collection 中一张子图通过而另一张失败
- **THEN** 用户时间线和预览可区分两个结果
- **AND** 失败子图不能通过兄弟图的结果发布
