## Context

See `proposal.md` for the motivation and user-visible scope. 当前系统已经有持久化 execution events、generation context、measurement evidence lifecycle、shared review gate、tool-free VLM review 和普通/评测两套读取入口。

目前的问题不是缺少事件，而是事件的语义层级不统一：测量 focus、observation、Agent evidence decision、assemble、candidate review 和 publication 分别写入 trace；前端只自动合并 tool call/result，其他事件按平面列表显示。生成图审核还同时存在 gate 状态更新、VLM 开始事件、review snapshot 和 tool result projection，导致同一个 candidate attempt 看起来像多次审核。

本设计把 execution event history 作为唯一事实来源，在其上增加稳定关联字段和一个可重复计算的 timeline projection。generation context、ChartSpec、测量工具、审核器和发布门禁的职责保持不变。

## Goals / Non-Goals

**Goals:**

- 让一次测量、一次候选生成和一次审核修复都有明确的 decision unit、attempt 和 parent lineage。
- 让 focused measurement 的 request、effective scope、observation、evidence decision 和 assemble 关系闭合且可解释。
- 让一个 candidate attempt 对外只表现为一个 review cycle，并将 deterministic audit、VLM review、repair 和 publication 作为子阶段或后续 transition。
- 让普通运行与评测工作台从同一事件集合得到一致的时间线和详情。
- 让主 Agent 看到精简、结构化、不会漂移的当前决策上下文，同时保留模型主动选择证据和是否放弃的权力。
- 在实时事件、历史重放、重连和重复 snapshot 场景下保持幂等投影。

**Non-Goals:**

- 不另存一份独立的 timeline 数据库或 `timeline.json`，不改变 execution history 的唯一事实来源。
- 不重新设计 `generation_context` 的 mode、source scope 和 coverage 语义。
- 不新增测量、OCR、SAM/CV 或审核工具，也不把 OCR/CV 观察提升为语义角色判断。
- 不强制所有 measurement warning 自动触发重测；只有 review gate 明确要求的 evidence repair 才形成必需动作。
- 不改变 ChartSpec/ChartFigure 的核心数据模型、评测目录结构或 publication 的安全门禁。
- 不在本 change 中制作新的视觉风格；目标是统一信息架构和状态语义。

## Decisions

### 1. 原始 execution events 是唯一事实来源

不新增独立的 timeline 持久化格式。每个事件继续使用现有 run sequence、timestamp、call_id 和安全 payload；新增关联字段只作为 projection 所需的 bounded metadata。

```json
{
  "run_id": "run_x",
  "sequence": 42,
  "kind": "measurement_observed",
  "unit_id": "measurement_attempt_2",
  "unit_type": "measurement",
  "phase": "observe",
  "actor": "tool",
  "parent_unit_id": "candidate_attempt_1",
  "transition_id": "transition_x",
  "next_action": {
    "required": true,
    "allowed": ["select_evidence", "request_same_scope_measurement", "abandon"]
  }
}
```

时间线只是对事件进行确定性归组、排序和状态折叠。这样可以避免普通运行、评测运行和未来其他客户端各自维护一套状态。

备选方案是持久化一个“最终 timeline”。该方案读起来简单，但在实时追加、重连、历史截断和旧数据兼容时容易与原始 event history 漂移，因此不采用。

### 2. 用 Decision Unit 连接领域事件，而不是合并事件类型

Decision unit 是跨事件的关联概念，不是新的单一 event kind。建议使用以下有限类型：

- `measurement`：一次 observation、focused target 或 evidence decision。
- `generation`：一次 ChartSpec/collection candidate attempt。
- `review`：一个 candidate review cycle。
- `publication`：候选发布或拒绝的结果。

每个 unit 通过 `unit_id` 和 `parent_unit_id` 建立 lineage；通过 `phase` 表达 `observe`、`decide`、`assemble`、`render`、`review`、`repair`、`publish`；通过 `actor` 区分 `agent`、`tool`、`system` 和 `vlm`。领域已有的 `session_id`、`attempt_id`、`candidate_id`、`review_id`、`source_scope` 和 `repair_kind` 继续作为详细引用，不被 unit 字段替代。

这可以同时满足“完整保留原始过程”和“前端显示一个可理解的过程”两个目标。

### 3. 将 transition 作为去重和下一步边界

`transition_id` 表示一次状态变化，而不是每一条日志。相同 run、unit、attempt、phase 和 transition 的重复事件在 projection 中只产生一条可见转换；原始事件仍全部保留，便于审计。

每个未终结 unit 必须有 bounded next-action 描述：

```json
{
  "required": true,
  "allowed": ["measure_same_scope"],
  "blocked": ["cross_panel_measure", "assemble", "publish"],
  "reason": "evidence_needed"
}
```

`focus_applied` 只表示 scope resolver 或测量工具接受了范围，不表示已有数值证据。只有同一 unit 的 `measurement_observed` 才能关闭 observation obligation；若没有 observation，必须记录 `failed`、`abandoned` 或可恢复的 `pending`。

可选 focused observation 不阻塞整个 run；但 review gate 明确要求的 evidence repair 属于 required obligation，未关闭时禁止该 candidate 进入 assemble。

### 4. 证据决策由 Agent 产生，assemble 只消费和验证

一次 measurement attempt 的 `selected`、`discarded` 或 `abandoned` decision 在该 attempt 下只保留一个当前有效版本，并与 evidence refs、scope、decision basis 和 parent unit 关联。

assemble 收到同一 decision 时只执行引用、范围、字段和一致性验证，不重新发出证据决策 transition。tool result 中的 `_measurement_decision` 视为 decision snapshot；如果它与已经持久化的 transition 相同，则只更新详情而不制造新的顶层时间线行。

如果 Agent 需要补证据，正确顺序是：

```text
evidence_needed
  -> same-scope measurement
  -> evidence decision
  -> assemble
  -> render
  -> review
```

如果 Agent 明确选择 abandon，则关闭该 obligation 并进入 terminal/alternative decision；不能无记录地跳过 required action。

### 5. 一个 candidate attempt 对应一个 review cycle

review cycle 的内部子阶段如下：

```text
review_cycle
  ├── deterministic_quality_audit
  ├── semantic_vlm_review
  ├── repair_decision
  └── final_review_state
```

代码拥有的 review coordinator 负责创建和关闭 cycle；VLM reviewer 只返回一次结构化语义判断。shared review adapter 的 pending/complete 更新、tool result 中的 review metadata 和 VLM 调用的 model trace 都属于同一 cycle，不应各自产生 `review_started` 顶层 transition。

同一个 candidate attempt 的重复提交使用 review identity 和输入 digest 幂等返回已有结果。真正重新审核必须因为 spec/evidence/source 修复生成新 candidate attempt，并保留 parent candidate、parent attempt 和 repair kind。

deterministic audit 与 VLM review 仍然分别保留检查结果：前者不能冒充后者通过，后者也不能覆盖前者的布局/编码诊断。

### 6. Collection 使用父级 review unit

一次 collection render 可能生成多个 child candidates。每个 child 保留自身的 candidate、figure、attempt、issue、scope 和 publication 状态；collection 创建一个 review parent 汇总 pending、partial、failed 和 published 状态。

前端默认显示 parent，展开后显示 child。父级只有在所有要求发布的 child 达到允许状态时才能显示可发布；单个 child 失败不得被其他 child 的成功覆盖。

### 7. 前端使用共享 projector，保留原始展开能力

在共享 domain 层实现确定性的 projector：

1. 按 run sequence 排序并去重历史/实时事件。
2. 按 `unit_id`、`parent_unit_id` 和 `transition_id` 建立 unit tree。
3. 将 phase 和 event role 转成稳定的中文 presentation state。
4. 将 tool call/result、visual observation、decision、review sub-check 和 publication 放入对应 unit。
5. 对 pending、blocked、truncated、history gap 和 unavailable 保留明确状态。

普通运行和 evaluation workspace 只传入不同的外层上下文和资源 resolver，不复制归组逻辑。这样评测查看 test4 时，可以与普通对话看到完全相同的过程。

不在 Gateway 另外生成一套只面向前端的摘要事件；如果需要批次索引，只保存 case/run 引用和现有安全事件边界。

### 8. Prompt 只注入当前决策状态

主 Agent 继续使用现有四层 prompt。将 projector/Agent 状态生成的 bounded decision context 放入 Run/Turn 动态层，内容只包括当前 unit、phase、status、scope、evidence/candidate refs、required/allowed/blocked actions 和预算。

不把完整 timeline、重复 tool result 或所有历史事件塞入 prompt。模型需要的是当前可行动状态，用户需要的是前端完整历史；二者使用同一字段，但展示粒度不同。

review prompt 仍然是独立的 tool-free 合同，不继承主 Agent 的工具列表，不读取前端 projection 作为语义事实。

## Risks / Trade-offs

- **[事件字段增多]** → 只对适用事件写入有界字段，旧事件进入 legacy/unknown；保留固定枚举和长度限制。
- **[投影逻辑与后端状态漂移]** → transition 和 next-action 由代码拥有，前端只消费协议字段；增加实时、历史、重复 snapshot 的同源 fixture。
- **[旧事件无法完整归组]** → 明确显示 legacy/unknown 和 history limitation，不推测缺失的父子关系。
- **[模型被过多状态干扰]** → prompt 只注入当前 unit 的压缩上下文，完整 timeline 仅用于客户端和诊断。
- **[collection 聚合掩盖 child 失败]** → 父级使用保守汇总；任一 required child 未发布时父级不能标记完整发布。
- **[review 去重误吞真实重试]** → 去重键包含 candidate attempt、review identity 和输入 digest；真实修复必须创建新的 attempt lineage。
- **[required measurement 变成隐式硬门禁]** → 只对 review 明确产生的 evidence-needed obligation 阻塞；普通 warning 和可选 focused observation 仍由 Agent 自主决定。

## Migration Plan

1. 增加 bounded correlation envelope 和 transition/next-action 序列化，保持现有 event kind、sequence 和旧字段兼容。
2. 将 measurement focus、observation、decision 和 assemble 的关联补齐；为缺少 observation 的 focus 生成 pending/failed/abandoned 状态，不回填伪造 evidence。
3. 将 candidate review 的 shared gate、deterministic audit、VLM review 和 tool result snapshot 收敛到一个 review cycle，并确保同一 candidate attempt 的重复提交幂等。
4. 增加 collection review parent 和 child outcome projection。
5. 在共享前端 domain 层实现 timeline projector，先接普通运行，再接 evaluation workspace；旧事件以 legacy/unknown 显示。
6. 将 decision context 接入四层 prompt 的 Run/Turn 层，验证模型在 focused measurement、evidence discard 和 review repair 场景下的可行动状态。
7. 使用 test4 类真实运行和回放 fixture 验证：局部范围闭合、证据选择顺序、审核次数、collection 聚合、刷新/重连幂等和评测/普通视图一致。

回滚时可以关闭新的 projection 展示并继续读取原始事件，但不得删除新字段或放宽已有 scope、review 和 publication 门禁。这样旧客户端仍能读取基础事件，新客户端可以在修复后重建时间线。

## Open Questions

无会改变当前规格或架构的未决问题。具体字段长度、事件保留上限和 timeline UI 的折叠默认值可以在实现任务中沿用现有协议限制，并通过测试固定。
