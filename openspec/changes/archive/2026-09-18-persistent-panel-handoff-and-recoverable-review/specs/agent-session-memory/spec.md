## ADDED Requirements

### Requirement: Session memory restores source and panel context

命名 session 的持久化状态 SHALL 包含活动源附件和有效 PanelHandoff 的安全引用。新 Agent run SHALL 在建立模型上下文前恢复这些引用；文本历史可作为语义辅助，但不得替代结构化 panel registry。

#### Scenario: New Agent runtime hydrates panel context
- **WHEN** named session 创建新的 Agent runtime
- **THEN** runtime 获得当前活动源和面板目录
- **AND** 模型可以直接使用已有 panel ID 而不依赖旧 run 的内存对象

### Requirement: Sessions isolate panel registries

一个 session 的源附件和 PanelHandoff SHALL 不得被另一个 session 的 run 解析或复用。

#### Scenario: Cross-session panel access is rejected
- **WHEN** run 使用属于其他 session 的 panel ID
- **THEN** 系统拒绝该引用并记录结构化授权错误
