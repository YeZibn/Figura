## ADDED Requirements

### Requirement: The four prompt layers carry one shared generation context

现有四层提示词 SHALL 保持不变：静态职责、动态工具、过程产物、Run/Turn 状态。source-
linked generation context SHALL 作为结构化动态上下文在适当层注入一次并在后续层引用，
不得复制成互相冲突的自由文本版本，也不得新增第五层来承载任务合同。

#### Scenario: Agent sees mode before choosing evidence

- **WHEN** 主 Agent 开始一个 panel transform
- **THEN** prompt context 显示 mode、source scope、coverage 和当前 attempt
- **AND** 工具说明与过程产物引用同一份字段
- **AND** Agent 可以在调用测量前决定 full observation、focused observation 或无需工具

### Requirement: Main prompt defines an explicit evidence decision matrix

静态职责和动态状态 SHALL 要求 Agent 依次判断：任务模式、来源范围、需要代表的系列、
证据是否足够、是否需要同范围补测，以及是否可以 assemble/render。提示词 SHALL 明确
工具 warning/remeasure suggestion 不是自动动作；Agent 必须显式选择 selected、discarded
或 request evidence repair。

#### Scenario: Warning does not cause an unexplained duplicate measurement

- **WHEN** 一次测量返回 warning 或 remeasure suggestion
- **THEN** Agent 可以选择接受、舍弃、局部补测或向用户澄清
- **AND** 未产生显式决策前不会自动再调用测量工具

### Requirement: Review prompt is a separate tool-free contract

审核提示词 SHALL 只接收候选、source crop、ChartSpec、generation context 和 bounded
review history；不得暴露可调用工具，也不得要求审核 VLM 自行重新测量。prompt SHALL 要求
严格 JSON decision，并声明 repair kind 与 scope/target。

#### Scenario: Reviewer returns machine-readable repair

- **WHEN** reviewer 认为一个值需要补充证据
- **THEN** 返回可解析的 decision、issue、repair_kind=evidence_needed 和 bounded target
- **AND** 不返回要求 reviewer 自己调用工具的指令

