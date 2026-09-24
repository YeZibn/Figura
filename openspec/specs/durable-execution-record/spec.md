# durable-execution-record Specification

## Purpose

为 Figura 的 Run 提供唯一、受限且可恢复的已提交执行事实，使中断后的明确继续执行能够复用结果，同时让普通会话历史与公开事件保持安全、可观察和互不冒充权威。

## Requirements

### Requirement: Committed execution entries are the recovery authority

系统 SHALL 按 Run 和顺序保存模型响应、工具结果、验证结果、发布结果及最终回答的已提交执行事实。每个可恢复步骤的结果及下一动作游标 SHALL 原子提交；未提交结果不得被 checkpoint、历史或客户端显示为已完成。普通会话记录、SSE 和评测详情 SHALL 由这些事实安全投影，不得成为第二个恢复权威。

#### Scenario: Tool result commits with its cursor
- **WHEN** 工具结果提交后进程在下一动作前中断
- **THEN** 显式 resume 读取该已提交结果并从下一动作继续
- **AND** 不重复执行这个工具调用

#### Scenario: Crash precedes commit
- **WHEN** 工具返回但结果和下一动作尚未提交时进程中断
- **THEN** 恢复不得声称该结果已完成
- **AND** 根据该工具的重放契约处理原调用

### Requirement: Private model context is recoverable without public disclosure

系统 SHALL 以有界、受限的私有记录保存恢复模型协议所必需的消息和 provider 上下文，包括适用 provider 所要求的私有 continuation 字段。普通会话 transcript、Gateway 事件、评测投影和 trace SHALL 排除私有 reasoning、凭证、原始响应、图像字节、本地路径及超限内容。只有经授权的显式 resume SHALL 读取中断父 Run 的私有上下文。

#### Scenario: Provider context stays private
- **WHEN** 某 provider 的工具续接需要私有 reasoning 内容
- **THEN** 子 Run 可从受限记录重建所需上下文
- **AND** 用户可读历史和 SSE 不包含该内容

#### Scenario: Unrelated turn excludes interrupted work
- **WHEN** 用户从同一 session 发起普通新 Run
- **THEN** 未完成父 Run 的私有执行前缀不进入普通历史上下文

### Requirement: Committed model and tool batches are replayed by identity

每个模型响应 SHALL 保存稳定的响应身份及有序 tool calls；每个工具结果 SHALL 关联准确的响应和 call ID。恢复 SHALL 从已提交响应推导剩余调用，复用已提交的单个调用结果，且不得把有相同参数的独立调用合并为同一次尝试。

#### Scenario: Resume between batch calls
- **WHEN** 模型返回三个调用且前两个结果已提交
- **THEN** resume 只执行第三个调用并继续下一次模型动作

#### Scenario: Intentional repeated arguments remain separate
- **WHEN** 模型在两个已提交响应中有意使用相同参数调用同一工具
- **THEN** 两次调用保留各自身份和结果

### Requirement: Replay follows the action effect contract

恢复 SHALL 先查询当前动作的已提交结果。未提交的纯读取/计算动作 MAY 重跑；本地持久写入 SHALL 根据稳定工作身份核对或幂等重试；无可核对契约的外部副作用结果不明时 SHALL 阻止自动执行。未提交的模型或内部 VLM 请求仅在用户显式 resume 后 MAY 重新请求，并 SHALL 允许额外费用及结果差异；已提交响应 MUST 被复用。

#### Scenario: Uncommitted model request is resumed
- **WHEN** 模型请求已发出但没有可复用的已提交响应
- **THEN** 显式 resume 可以重新发出该请求
- **AND** 用户可见恢复说明不保证只产生一次 provider 费用

#### Scenario: External effect is unknown
- **WHEN** 某未来工具可能已修改外部系统而本地无法核对结果
- **THEN** resume 返回有界阻止原因且不自动重复该修改

### Requirement: A committed final answer resumes as the final action

最终回答 SHALL 作为已提交执行事实与指向该回答的 `final` 下一动作游标一起保存。若进程在回答提交后、Run 完成前中断，显式 resume SHALL 从已提交回答继续，复用其准确内容，不再次请求模型或重放已完成工具。已提交模型响应但尚未写入最终回答事实时，恢复 SHALL 复用该响应并完成最终回答提交。

#### Scenario: Resume after the final answer commit
- **WHEN** 最终回答及其 `final` 游标已经提交，但原 Run 尚未完成
- **AND** 用户显式恢复该 Run
- **THEN** 新子 Run 使用已提交的最终回答完成执行
- **AND** 不发出新的模型请求或重复执行工具

#### Scenario: A model response is committed before finalization
- **WHEN** 无工具调用的模型响应已提交为 final action，但最终回答事实尚未提交
- **THEN** 恢复复用该模型响应并继续最终回答保护和提交
- **AND** 不再次请求模型

#### Scenario: No committed model response exists
- **WHEN** 模型响应尚未提交且 cursor 指向模型动作
- **THEN** 恢复按现有模型动作重放规则继续
- **AND** 系统不声称存在可复用的模型响应或最终回答
