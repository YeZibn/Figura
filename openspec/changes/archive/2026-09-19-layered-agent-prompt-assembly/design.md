## Context

See `proposal.md` for the motivation and scope. 当前主 Agent 通过 `runtime/prompts.py` 拼接一份稳定系统提示词，工具定义来自 registry，session/run 历史和工具结果由 memory/context 组合，审核门禁和视觉观察又通过额外消息注入。现有代码已经具备授权附件、持久化 panel、结构化工具结果、生成候选和 review gate，但这些信息在模型上下文中缺少统一的来源边界。

本设计把上下文组织为四层，而不是把 session、run、turn 拆成更多独立层：

1. 静态职责：长期稳定的 Agent 行为规则。
2. 动态工具：当前 registry 和授权边界实际提供的工具面。
3. 过程产物：当前分析产生的 panel、crop、观测、ChartSpec、候选和审核证据。
4. Run/Turn 动态状态：当前 source、selected panel、phase、pending action、review/recovery 和预算。

这些层是语义边界；具体传输仍可使用 system、user、tool 和 multimodal message。工具 Schema、JSON 结果和图片资源继续是机器协议，Markdown 只负责自然语言规则和上下文可读性。

## Goals / Non-Goals

**Goals:**

- 使用中文 Markdown 管理主 Agent 的静态职责和领域规则。
- 通过统一装配入口组合四层上下文，并让每层有稳定来源标记。
- 从注册工具定义派生当前模型可见工具面，避免 Prompt 与 Schema 漂移。
- 将持久化 panel inventory 作为模型可见的过程/运行上下文，而不只留在内部路由缓存。
- 保留过程产物的结构化 JSON、图片和资源引用，支持压缩后的 artifact index 与原始工具消息并存。
- 让 review gate、恢复动作和 publication status 作为代码拥有的动态状态进入下一轮上下文。
- 为 Prompt bundle 提供版本和层级标识，便于 trace、回归测试和问题定位。
- 保持现有原生工具调用、附件授权、ChartSpec、审核 JSON 和前端事件协议兼容。

**Non-Goals:**

- 不重写 OCR、CV、图表几何传感器、SAM 或渲染算法。
- 不改变工具名称、函数参数、ChartSpec Schema、review JSON 字段或 publication 状态机。
- 不把 VLM reviewer 合并到主 Agent 的工具面；reviewer 仍是独立、无工具的调用。
- 不实现新的长期学习系统，也不把未经代码校验的模型文本写入 session registry。
- 不要求 Agent 输出额外的自然语言计划；动态层用于决策，不用于展示内部推理。

## Decisions

### 1. 使用四层上下文，而不是更多层级

选择四层是因为它们分别对应四种不同的生命周期：静态规则、工具能力、分析产物和控制状态。Run 与 Turn 合并为动态状态层；Run 保存整体 phase 和恢复信息，Turn 保存当前模型调用、最近工具和 pending action。

替代方案是把 session、run、turn、review、artifact 分成多个独立 Prompt 层。该方案边界更细，但会增加装配顺序、优先级和压缩逻辑的复杂度，当前项目没有必要。

### 2. 静态职责使用 Markdown 资源，Python 保留兼容导出

新增包内 Prompt 资源目录，例如：

```text
src/chartagent/prompting/
├── loader.py
└── assets/
    ├── static/agent.md
    ├── static/evidence.md
    ├── static/workflow.md
    ├── static/response.md
    ├── dynamic/tools.md
    ├── dynamic/runtime.md
    ├── dynamic/artifacts.md
    └── reviewer/chart-review.md
```

`runtime/prompts.py` 继续导出 `AGENT_SYSTEM_PROMPT`，但改为通过 loader 读取静态资源，避免 CLI、测试和外部调用方立即改接口。Markdown 自然语言统一为简体中文，稳定英文技术标识符不翻译。

选择包内资源而不是只放仓库根目录，是为了 CLI、Gateway 和安装后的 Python 包使用同一份 Prompt。setuptools package data 配置负责把 Markdown 一起打包。

### 3. 动态工具层由 registry 派生，Schema 是唯一参数真相

装配器从授权后的 registry 读取工具定义，生成中文用途和限制摘要，同时把原生 OpenAI-compatible tool schema 原样传给模型。工具说明不得重新定义参数，也不得暴露内部本地路径。

自然语言工具说明可以拆成 Markdown 片段或由工具 metadata 提供，但名称、参数、枚举和边界只从 `Tool` 定义生成。未来如果按任务过滤工具，过滤只能发生在 registry projection 层，不能通过 Prompt 文字假装工具不可用。

### 4. 过程产物采用“结构化真相 + 可读索引”双表示

工具的原始结构化结果和图片仍作为原生 tool/multimodal message 进入历史。装配器额外构建一个 bounded artifact index，记录：

- `artifact_id`、`kind` 和 `status`；
- `source_attachment_id`、`panel_id`、scope 或 lineage；
- confidence、warnings 和可支持的结论；
- 图片或 Gateway resource reference。

索引只用于快速恢复和上下文压缩，不能替代原始 JSON、图片或代码拥有的状态。panel crop、generated chart 和 review result 分别保留，不把候选图伪装成源证据。

### 5. Run/Turn 状态作为代码生成的控制上下文

动态状态由 Gateway、memory、review manager 和 Agent loop 的当前状态组成。推荐字段包括：

```text
run_id
phase
active_source
selected_panel
current_tool
pending_action
review_gate
recovery_status
retry_count / retry_budget
interrupted
```

状态以中文 Markdown 摘要结合稳定 JSON 字段传递。模型文本、OCR 文本、图片内文字和工具自由文本只能作为证据，不能覆盖授权状态、panel 路由、publication status 或 recovery status。

### 6. 装配顺序与优先级分开定义

语义层级为四层，但推荐的模型上下文顺序是：

```text
静态职责
  → 动态工具
  → Run/Turn 当前状态
  → 过程产物索引
  → 当前请求、历史消息、tool 结果和视觉内容
```

这是为了让模型先知道“应该如何工作”和“现在处于哪一步”，再解释已有证据。原生 tool message 仍按照 OpenAI message ordering 规则插入，不重复复制成自由文本。

优先级固定为：代码授权与状态、工具 Schema、静态职责、当前用户明确请求、结构化过程产物、视觉/自由文本推断。用户可以明确要求重新拆解，但不能绕过授权或审核门禁。

### 7. Prompt bundle 版本只记录元数据

每次装配生成 `prompt_bundle_id` 或等价版本元数据，并将静态资源版本、动态层名称和工具面摘要写入 trace。只记录 bounded metadata，不写入图片字节、本地路径、凭据或未经授权的原始响应。

### 8. VLM reviewer 保持独立资源和独立合同

主 Agent 的四层装配不把 reviewer 变成普通工具。VLM reviewer 使用独立中文 Markdown Prompt，接收 source image、candidate image 和 immutable ChartSpec，继续只返回严格 JSON。主 Agent 只消费代码验证后的 review result 和 recovery action。

## Risks / Trade-offs

- **[Risk]** 静态 Markdown、工具 description 和 Schema 可能再次漂移 → **Mitigation:** 工具 Schema 继续作为参数唯一真相；增加装配快照和 description/schema 对齐测试。
- **[Risk]** 动态上下文重复发送导致 token 增长 → **Mitigation:** 只发送 bounded runtime/artifact index；原始 tool result 和图片按现有历史规则保留；无变化的静态层保持稳定。
- **[Risk]** 过程产物中的图片文字可能被模型当成指令 → **Mitigation:** 明确标注为 evidence，静态层和代码状态拥有更高权威；路由与发布仍由代码强制。
- **[Risk]** 新 runtime 没有历史消息时仍无法选择 panel → **Mitigation:** 每次有 active source 时从持久化 registry 构建可见 panel inventory，且 panel 引用必须通过代码校验。
- **[Risk]** provider 对多段 system/context message 的支持不一致 → **Mitigation:** 装配器先生成逻辑层，再由 transport adapter 合并为当前 provider 支持的消息形态，保持内容顺序和层级标记。
- **[Risk]** 迁移 Markdown 资源后安装包遗漏文件 → **Mitigation:** 增加 package-data 检查和安装后 loader smoke test。

## Migration Plan

1. 创建 Prompt loader、Markdown 资源和四层内部表示，先保持现有 `AGENT_SYSTEM_PROMPT` 导出。
2. 将当前主 Agent 静态提示词逐段迁移为中文 Markdown，并建立等价内容的快照测试。
3. 接入 registry-derived tool surface，先保持完整工具集合，再按需要增加安全的任务过滤。
4. 将 panel inventory、过程产物索引和 Run/Turn 状态接入 Agent loop 与 memory context。
5. 将 review gate 和视觉观察改为对应的动态/产物层输入，保持原生 JSON 和图片消息。
6. 通过 dashboard panel 复用、局部测量、生成审核失败恢复和中断恢复回归测试。
7. 如出现问题，可回退到兼容导出的旧静态内容；四层装配器不应改变代码层授权和发布门禁。

## Open Questions

无。工具是否按任务进一步过滤可以在保持四层合同不变的情况下作为后续优化，不阻塞本 change。
