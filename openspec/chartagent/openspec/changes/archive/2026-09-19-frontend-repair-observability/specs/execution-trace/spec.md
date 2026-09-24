## ADDED Requirements

### Requirement: Measurement repair events have stable client presentation

执行追踪面向客户端的事件契约 SHALL 支持 `measurement_repair_required`、`measurement_repair_rejected` 和 `measurement_repair_exhausted` 三类测量修复事件。客户端 SHALL 能够保留稳定的英文事件类型作为机器标识，并为每类事件提供有界的简体中文展示标签和诊断摘要。

#### Scenario: Repair event preserves correlation fields

- **WHEN** 客户端接收测量修复事件
- **THEN** 事件仍可通过现有 run 和 sequence 关联到对应运行
- **AND** 客户端可以读取 bounded 的 panel、attempt、parent attempt、target 类型、状态、原因和下一动作字段（字段缺失时不得臆造）
- **AND** 原始图片、绝对路径、密钥和 provider 原始 payload 不进入用户可见事件正文

#### Scenario: Each supported repair state is localized

- **WHEN** 客户端渲染三类受支持的测量修复事件
- **THEN** 分别显示需要重测、修复被拒绝和修复预算耗尽等稳定的简体中文标签
- **AND** 标签不会把“请求修复”解释为“修复成功”

#### Scenario: Replay and live delivery share the same presentation

- **WHEN** 同一修复事件先通过历史回放返回、再通过实时流或重连流到达
- **THEN** 客户端使用相同的事件类型、标签和字段解释
- **AND** 按 run 与 sequence 去重，不产生第二条重复的用户可见事件

#### Scenario: Unsupported event kind has a safe fallback

- **WHEN** 客户端收到未知的生命周期或修复事件类型
- **THEN** 客户端保留该事件并显示有界的英文事件类型作为回退
- **AND** 未知事件不会阻断同一运行中其他事件的渲染
