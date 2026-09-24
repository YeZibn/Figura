## ADDED Requirements

### Requirement: Client distinguishes new selection from active source

桌面客户端 SHALL 区分“本次新选择附件”和“当前 session 活动源附件”。发送消息后可以清空待上传选择，但不得在没有用户替换或移除意图时清空活动源。

#### Scenario: Follow-up keeps the active source
- **WHEN** 用户发送首条带图请求后继续发送不带新附件的追问
- **THEN** 后续请求仍携带或引用当前活动源 context
- **AND** 用户不需要重复上传同一图片

### Requirement: Client exposes panel and source recovery states

客户端 SHALL 能显示面板复用、需要源绑定、审核修复中、审核重试耗尽和未发布候选等状态，并使用简体中文提供可行动说明。

#### Scenario: Review repair is visible
- **WHEN** 后端正在依据审核诊断生成新候选
- **THEN** 客户端显示正在修复和重新审核，而不是立即显示运行失败
