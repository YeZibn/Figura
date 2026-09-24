## REMOVED Requirements

### Requirement: Durable memory excludes sensitive and binary content

**Reason**: 旧状态或快照控制契约已由提交事实和单一验证链路替代。
**Migration**: 使用 durable-execution-record 或 generated-chart-verification 的对应要求。

## ADDED Requirements

### Requirement: Ordinary memory and private recovery context have separate visibility

普通会话记忆 SHALL 继续排除 reasoning、凭证、原始 provider 响应、图像字节、数据 URL 和本地路径。恢复所必需的 provider 私有续接字段 MAY 在有界、受限的私有执行记录中保存，并只向经授权的显式 resume 提供；它们 MUST NOT 流入普通上下文、transcript、trace、SSE 或评测资源。

#### Scenario: Private continuation is not a transcript
- **WHEN** 某已中断 Run 包含 provider 私有续接字段
- **THEN** 授权子 Run 可以恢复所需模型协议
- **AND** 用户读取会话历史时看不到该字段

### Requirement: New schema starts with empty legacy session data

新版存储切换 SHALL 不迁移旧会话、附件、Run 历史和已发布图表；配置路径中的旧托管数据清理后，新创建的 session、附件和 Run 仍 SHALL 持久且相互隔离。外部原始源图 SHALL 不受清理影响。

#### Scenario: Fresh session after reset
- **WHEN** 旧托管数据库与附件/产物目录完成清理并启动新版
- **THEN** 会话列表为空且可创建持久的新会话
- **AND** 外部源图片仍位于原路径
