## 1. Prompt 资源与装配基础

- [x] 1.1 建立包内 Prompt 资源目录和 loader，支持读取静态 Markdown、动态模板和 reviewer Prompt
- [x] 1.2 配置 setuptools package data，确保安装后的 Python 包可以读取 Markdown 资源
- [x] 1.3 定义 Prompt bundle version、层级标识和脱敏 trace metadata，并保留现有 `AGENT_SYSTEM_PROMPT` 兼容导出
- [x] 1.4 增加 loader 对资源缺失、空内容和重复层级标识的结构化错误处理

## 2. 静态职责层中文化

- [x] 2.1 将主 Agent 角色、语言、决策优先级和不可违反规则迁移为中文 Markdown
- [x] 2.2 将证据边界、panel 复用、局部测量、ChartSpec 组装和生成审核规则迁移为中文 Markdown
- [x] 2.3 将最终回答、publication status 和审核恢复规则迁移为中文 Markdown
- [x] 2.4 确认静态资源不包含 attachment、panel、candidate、run 或 turn 等运行时值
- [x] 2.5 将 VLM reviewer 的自然语言规则迁移到独立中文 Markdown 资源，同时保持严格 JSON 输出合同

## 3. 动态工具层

- [x] 3.1 从当前授权后的 ToolRegistry 生成动态工具面和中文用途摘要
- [x] 3.2 统一翻译图表工具 description，保留英文工具名、参数名、枚举和协议字段
- [x] 3.3 校验动态工具说明与原生 JSON Schema 的字段、必填项和限制一致
- [x] 3.4 确保动态工具面不暴露本地路径，并保留 attachment authorization boundary
- [x] 3.5 为工具面增加快照测试，覆盖主 Agent 和 MCP 映射使用同一份定义

## 4. 过程产物层

- [x] 4.1 定义 bounded artifact index，覆盖 source、panel、crop、observation、ChartSpec、candidate 和 review
- [x] 4.2 将持久化 PanelHandoff 转换为模型可见的 panel inventory，并保留 panel ID、scope、状态和 resource reference
- [x] 4.3 将 OCR、布局和图表传感器结果保留为带来源、范围、confidence 和 warnings 的结构化产物
- [x] 4.4 将 ChartSpec、候选图、审核结果和 publication status 保持独立关联，禁止候选 preview 被描述为 published
- [x] 4.5 保留原生 JSON tool message 和多模态图片消息，artifact index 仅作为有界索引和恢复摘要

## 5. Run / Turn 动态状态层

- [x] 5.1 定义运行状态摘要，覆盖 active source、selected panel、phase、current tool、pending action 和中断状态
- [x] 5.2 将 review gate、recovery classification、retry budget 和 publication status 注入下一次模型上下文
- [x] 5.3 确保状态变化后重新生成动态上下文，且模型自由文本不能覆盖代码拥有的状态
- [x] 5.4 将现有附件元数据、panel routing、checkpoint 和 review context 接入统一装配入口
- [x] 5.5 处理空的工具面、过程产物和运行状态，使用显式空状态而不是隐式缺失

## 6. Agent loop 集成

- [x] 6.1 将 Agent 的稳定系统提示词替换为静态职责层加载结果，并保持主循环消息顺序兼容
- [x] 6.2 在模型调用前装配动态工具和 Run / Turn 状态，避免把动态数据写入静态 Prompt
- [x] 6.3 在工具调用后更新过程产物索引和下一步状态，保留原生 tool observation 与 visual observation
- [x] 6.4 将 panel 复用、局部测量和审核修复场景接入主 Agent 的动态上下文
- [x] 6.5 确保 review gate 仍为代码拥有的门禁，主 Agent 不能用自由文本覆盖失败或未发布状态

## 7. 回归测试与验证

- [x] 7.1 增加静态 Markdown 中文化、协议标识符保留和 Prompt bundle 版本测试
- [x] 7.2 增加四层上下文装配测试，验证静态、工具、产物和 Run / Turn 状态互不串层
- [x] 7.3 增加新 runtime 从持久化 panel inventory 直接复用 panel 的测试
- [x] 7.4 增加 dashboard 两次运行不重复拆解、后续传感器使用 panel scope 的回归测试
- [x] 7.5 增加生成候选审核失败后进入修复、重试耗尽后不发布的回归测试
- [x] 7.6 增加 Markdown 资源打包和安装后加载 smoke test
- [x] 7.7 使用 `conda run -n agent python -m pytest -q`、`git diff --check` 和 OpenSpec 严格校验完成验证
