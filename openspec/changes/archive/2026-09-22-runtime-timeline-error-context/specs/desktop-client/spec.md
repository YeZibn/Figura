## ADDED Requirements

### Requirement: Runtime timeline presents compatibility groups instead of event noise

桌面客户端 SHALL 将普通生命周期事件显示在可理解的运行过程或有界历史容器中；只有具备可解释 decision-unit 语义的事件才作为独立顶层决策单元。所有容器 SHALL 保留事件数量、顺序和展开入口，并使用稳定的中文状态。

#### Scenario: Test-style run is readable

- **WHEN** run 只完成加载、拆解、一次工具调用后失败
- **THEN** 用户可以看到加载、拆解、工具调用、失败原因和终态的连续过程
- **AND** 页面不会被大量相互独立的“关联不可用”卡片淹没

#### Scenario: Historical fallback is bounded

- **WHEN** 客户端读取旧版本事件且无法建立过程关联
- **THEN** 客户端将旧事件放入明确的兼容容器并标注关联能力边界
- **AND** 不把兼容容器内的事件解释为某个候选已通过审核或已发布

### Requirement: Client exposes actionable provider and scope errors

错误摘要 SHALL 优先展示结构化 failure category、provider 状态或工具字段错误、safe message 和下一步提示；原始 payload SHALL 继续以受限、只读方式展开。没有结构化字段时才使用通用 fallback 文本。

#### Scenario: Balance or authorization failure is visible

- **WHEN** provider 返回余额、授权或请求限制类拒绝
- **THEN** 客户端显示对应的可读原因和 provider 状态
- **AND** 用户不需要展开原始 JSON 才能知道失败不是图表数据问题

#### Scenario: Source scope validation failure is visible

- **WHEN** 图表工具因 source scope 缺失、不一致或歧义拒绝调用
- **THEN** 客户端显示具体字段、当前范围和 action hint
- **AND** 不把该错误显示成无上下文的 render 或 review 失败
