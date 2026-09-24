## MODIFIED Requirements

### Requirement: Timeline projection is derived from canonical execution events

系统 SHALL 从同一份有序、持久化的 execution events 生成两种确定性投影：用于关联、状态、重放和 lineage 的内部 decision/process projection，以及用于普通运行和评测展示的用户时间线 projection。系统 SHALL 不把独立且可能漂移的 timeline 文件作为事实来源；相同的事件集合和协议版本 SHALL 产生等价的内部关联、用户可见步骤、状态和顺序。用户时间线不得把 process、turn、operation 或 legacy 关联直接当作可见的业务容器。

#### Scenario: Ordinary and evaluation views use one projection

- **WHEN** 普通会话和评测 case 引用同一 run event history
- **THEN** 两个界面使用相同的用户时间线步骤、工具合并规则、状态标签、错误摘要和展开内容
- **AND** 评测工作台不会重新解释或压缩普通运行已经保存的审核事件

#### Scenario: Timeline rebuilds after reload

- **WHEN** 用户刷新页面或重新打开一个已完成、失败或中断的 run
- **THEN** 客户端可以从历史事件重新得到相同的内部关联和用户时间线
- **AND** 重建不会重新调用模型、工具、审核或发布动作

#### Scenario: Technical lifecycle events are retained but not presented

- **WHEN** history contains model-start、model-completion、operation-save 或 run lifecycle 事件
- **THEN** 这些事件继续作为事实来源参与状态和失败判断
- **AND** 默认用户时间线只显示由它们支持的可读状态、业务步骤或终态错误，不显示技术事件本身
