## REMOVED Requirements

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

**Reason**: 旧事件/字段的兼容归并会在用户界面重新引入第二套语义推断，与 canonical timeline 契约冲突。

**Migration**: 不迁移或删除本地历史数据。当前客户端只展示受支持协议的时间线；旧历史显示明确的不可用/不支持提示，不猜测业务状态。公开 Gateway/client façade 和当前 SSE/API 契约保持不变。

## MODIFIED Requirements

### Requirement: Timeline details remain read-only and recoverable

展开、刷新和重连时间线 SHALL 只读取已有事件、诊断和安全资源，不得重新触发模型、工具、审核或发布。用户默认看到面向业务的步骤；技术生命周期字段、sequence 和原始 payload SHALL 只能通过受限的按需详情读取。历史缺失、截断、不支持和不可用状态 SHALL 在对应可见步骤或运行摘要上明确展示。

#### Scenario: Refresh does not repeat a review

- **WHEN** 用户刷新一个已完成或失败的 Run
- **THEN** UI 从受支持的历史记录重建相同的用户时间线和 review cycle
- **AND** 不产生新的 VLM invocation 或 publication action

#### Scenario: Unsupported history stays explicit

- **WHEN** 用户打开不支持的旧事件版本或无法解析的事件字段形状
- **THEN** UI 显示明确的历史不可用/协议不支持状态并保留可用的运行摘要
- **AND** 不创建兼容容器或推断审核、发布和终态成功

## ADDED Requirements

### Requirement: Desktop timeline consumes one canonical event projection

桌面客户端 SHALL 通过单一用户时间线投影呈现受支持的 Run 事件。投影 SHALL 使用事件类型规定的字段，不得从 `execution_gate`、`executionGate`、`gate` 或其他同义字段 fallback 读取同一 Gate；Run summary 中的派生 Gate 可以提供当前状态摘要，但不得覆盖事件历史表达的转移。技术审核子检查可以留在受限详情中，不得作为重复的顶层审核步骤。

#### Scenario: Review appears as one business cycle

- **WHEN** 一个候选产生审核开始、审核结果和发布转移
- **THEN** 用户看到一个审核周期及清晰的结果/原因，并能查看受限技术详情
- **AND** Gate 快照、技术子检查和重复事件不生成额外审核卡片

#### Scenario: Existing public API contract remains stable

- **WHEN** 当前客户端通过 Gateway/SSE 接收受支持的事件和 Run summary
- **THEN** 客户端继续使用现有公开字段约定、run identity、sequence 和 opaque IDs
- **AND** 只移除内部及同一 payload 中的重复 fallback，不进行无关的 API 重命名
