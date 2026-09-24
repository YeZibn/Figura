## Purpose

为图表生成固定来源范围、覆盖目标和 generation context，并让验证使用同一份授权范围及准确 ChartSpec。
## Requirements

### Requirement: Rendered attempts bind an immutable generation contract

源图驱动的每个生成尝试 SHALL 保存有界 generation context，包括 reconstruct、transform、summarize 或 synthesize 模式、授权 source scope、coverage、selection basis 与 goal summary。该上下文 SHALL 与图像和 ChartSpec 版本一同固定；任务模式、来源或覆盖决策变化 SHALL 产生新的生成尝试。直接数据生成不需伪造源图归属。

#### Scenario: Panel transform omits an unrelated series
- **WHEN** 用户要求转换一个 dashboard panel 的指定系列
- **THEN** 该尝试绑定对应 panel 和明确的 intentionally omitted 系列
- **AND** 验证不得把其他 panel 或明确省略的系列当作缺失

#### Scenario: Intent changes after failure
- **WHEN** Agent 根据诊断改变源范围或 coverage 后重新生成
- **THEN** 新尝试保留自己的上下文
- **AND** 原尝试及其失败诊断仍可归属

### Requirement: Verification uses the authorized source scope

源图验证 SHALL 使用已授权的 attachment/panel 及有效 handoff 裁剪，不得因来源不可用而静默扩大至整张 dashboard。来源缺失、摘要变化或 handoff 失效 SHALL 返回来源绑定诊断并阻止发布；不声称来源保真的直接数据生成只执行适用检查。

#### Scenario: Stale handoff cannot widen scope
- **WHEN** panel handoff 的附件摘要失配
- **THEN** 验证给出 source-scope 诊断且不发布
- **AND** 不静默读取整张附件作为替代

### Requirement: Scope repair remains model selected and observable

验证结果的 issues、repair hint、target 与实际后续调用 SHALL 通过生成尝试、来源范围及集合子图身份关联。修复提示 SHALL 不成为代码控制的阶段或唯一工具白名单；每个新生成尝试 SHALL 重新验证。

#### Scenario: Agent chooses legal evidence work
- **WHEN** 验证提示需要修正 Spec 但 Agent 选择在同一授权范围补测
- **THEN** 普通测量调用及新尝试可归属
- **AND** 代码不会仅因提示类型拒绝该合法调用
