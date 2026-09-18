## ADDED Requirements

### Requirement: Active source context is recoverable within a session

系统 SHALL 为 named session 保存当前活动源附件引用。后续 run 在没有新附件时 SHALL 可以恢复该引用，但必须重新校验附件归属、存在性和内容哈希；系统不得依据模型文本中未经校验的附件 ID 绑定源图。

#### Scenario: Follow-up run inherits the active source
- **WHEN** 用户在已上传图片的 session 中继续提问且没有选择新附件
- **THEN** Gateway 为新 run 解析同一个 active source context
- **AND** source-linked 工具和审核可以使用该附件

#### Scenario: Source binding is ambiguous
- **WHEN** session 中存在多个候选附件且请求没有明确活动源
- **THEN** 系统不得静默选择全部附件或任意一张图片
- **AND** 返回需要重新绑定源附件的可恢复状态
