## ADDED Requirements

### Requirement: Measurement gate failures drive targeted evidence recovery

当 `assemble_spec` 因 measurement evidence 未被接受而阻断时，系统 SHALL 返回可供 Agent 继续执行的 repair action、当前 panel/source 身份、受影响字段和父 attempt。Agent 可以据此请求当前 panel 的定向补充证据，但不得猜测缺失值或切换到其他 panel 规避门禁。

#### Scenario: Blocked assembly requests a targeted remeasurement

- **WHEN** 当前柱状图 attempt 因 baseline issue 未通过 measurement gate
- **THEN** 组装结果包含指向 baseline 或相关 bar region 的有界 repair action
- **AND** Agent 可以继续当前 run 的证据闭环，而不是直接结束为成功或发布结果

#### Scenario: Unrecoverable evidence remains non-final

- **WHEN** 定向补充证据仍不能解决关键字段，或 repair budget 已耗尽
- **THEN** 融合结果保留未解析字段、问题和 attempt lineage
- **AND** 系统不得用模型猜值替代 accepted measurement evidence
