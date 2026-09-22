## Context

See `proposal.md` for the motivation and compatibility boundary. 当前 Gateway 的公开入口主要是 `GatewayService`、`gateway.protocol` 的协议值对象以及 `gateway.__init__` 的包级导出；内部实现分别集中在 `history.py`、`runs.py`、`service.py` 和 `server.py`。Evaluation 则由 `EvaluationBundle`、`EvaluationReader`、`build_timeline` 和报告投影组成，但 `reader.py` 与 `timeline.py` 同时承担输入读取、归一化、证据收集和诊断归因。

本 change 的持久化边界是现有 SQLite 记录、RunEvent JSON、checkpoint/recovery JSON 和评测 bundle 文件。重构只能移动实现所有权，不能重新定义这些边界；Evaluation 必须继续通过已有 Gateway/history/bundle 投影观察运行，不能重新执行 Agent 或图表工具。

## Goals / Non-Goals

**Goals:**

- 让 Gateway 的存储、运行状态、HTTP 适配和服务编排拥有可识别的单向依赖方向。
- 让 Evaluation 的输入读取、事件归一化、阶段归约、失败分类和报告输出分别可独立测试。
- 以 façade 或兼容导出保留当前包级入口、CLI 入口和公共协议对象的 identity/签名/序列化行为。
- 在每个迁移阶段固定 JSON round-trip、事件顺序、checkpoint 恢复和评测目录布局。

**Non-Goals:**

- 不修改 HTTP 路由、SSE 帧格式、SQLite schema、Run/Event 字段、评测 bundle 布局或前端消费协议。
- 不新增 Gateway 与 Evaluation 的第二套运行状态，不让 Evaluation 直接访问 Agent、工具 registry 或数据库内部 connection。
- 不在本 change 中拆分前端、图表传感器、ChartSpec、Prompt 或 Agent 主循环。
- 不为了减少行数批量删除仍被包级导出、动态字符串注册、CLI 或外部集成使用的符号。

## Decisions

### 1. 先建立公共边界，再移动私有实现

先通过 `rg`、包级导出和运行入口盘点稳定 API、内部 API 与私有候选。`gateway.protocol` 继续作为协议 canonical owner；`GatewayService`、`EvaluationBundle`、`EvaluationReader`、`DiagnosticTimeline` 和报告函数的现有导入保持可用。私有函数只有在静态引用、字符串入口、测试和文档检查均确认无调用后才删除。

备选方案是直接按文件长度切片并批量改名。该方案容易让 SQLite/HTTP 序列化逻辑出现两个所有者，也会破坏外部导入，因此不采用。

### 2. Gateway 按数据层、运行层和传输层拆分

目标依赖方向为：

```text
protocol/models  ───────────────┐
history persistence ─▶ run state ├─▶ service orchestration ─▶ server/http
attachments/projection ─────────┘
```

具体文件名可以根据现有符号调整，但职责固定：

- history 的 SQLite 连接、事务、事件/记录查询和 operation journal 分到聚焦的持久化实现；
- runs 保留 `ManagedRun`、`HistoricalRun`、`RunManager` 的生命周期与内存观察存储，只通过显式 store/protocol 依赖持久化；
- service 只编排 session、attachment、run、provider 和恢复入口，不重复解析 HTTP payload；
- server 只负责请求校验、路由和响应/SSE 适配，不持有业务状态；
- protocol 保留协议值对象、校验和有界序列化，禁止反向导入 service/server。

保留历史子模块的公开入口时使用明确的兼容导出，并在结构测试中验证对象 identity；不再新增只有一行重导出的中间层。

### 3. Evaluation 采用“输入 → 归约 → 报告”的流水线

Evaluation 内部固定为三层：

```text
manifest/bundle/reader input
            ↓
       normalized records
            ↓
 timeline reducer → failure attribution → report projection
```

Reader 负责从评测根目录、Gateway 历史和受控 resource reference 读取并做脱敏/边界裁剪；timeline 只消费有界事件记录和 normalized run facts，不读取数据库 connection；failure attribution 只根据已观察证据选择首个可确认阶段，不把未到达的 render 当作根因；report 只把诊断对象投影为 JSON/Markdown。

这能保持现有 `EvaluationReader` 和 `build_timeline` 结果不变，同时为后续真实评测扩展提供可测试的中间结构。新中间结构只作为内部类型，外部输出仍使用现有字段。

### 4. 迁移按可回归边界推进

实施顺序为：Gateway protocol/exports 基线 → history persistence → run lifecycle/recovery → service/server façade → Evaluation reader/bundle → timeline/attribution → report/CLI。每一步先更新调用点，再运行对应窄测试；不得在同一阶段改变协议字段或输出目录。

### 5. 用结构与行为双重测试保护兼容性

结构测试验证 canonical 定义所有权、下层不反向导入 façade、Gateway 与 Evaluation 不共享可变内部对象；行为测试验证同步/异步 run、SSE replay、idempotency、interrupt/resume、attachment authorization、bundle 读写、timeline stage status 和 report 脱敏。所有 JSON 比较以序列化结果和关键字段为准，不依赖模块 `__file__` 以外的实现细节。

## Risks / Trade-offs

- **[Risk]** SQLite 事务或连接生命周期被拆散后产生锁、泄漏或事件顺序变化。→ 先把 connection/transaction owner 固定在 persistence 层，运行层只能调用有界方法；保留 Gateway lifecycle、operation journal 和并发测试。
- **[Risk]** SSE/历史回放与实时 Run 使用不同的 event projection。→ 统一从 protocol canonical serializer 生成事件，并增加实时与历史投影一致性测试。
- **[Risk]** Evaluation 归约时丢失第一失败证据或把截断数据当作事实。→ normalized record 显式保留 `not_observed`、`truncated`、sequence 和 resource refs；没有证据时返回 `unknown`。
- **[Risk]** 兼容导出遮蔽了新的实现所有权。→ 只保留已有公开入口，结构测试要求包级对象指向 canonical 定义，禁止新建无职责 façade。
- **[Trade-off]** 迁移期间会暂时保留少量私有委托方法。→ 只在窄测试与完整回归通过后删除，确保每次迁移可独立回滚。

## Migration Plan

1. 盘点 Gateway/Evaluation 导出、动态入口、数据库字段、事件序列化和评测目录结构，增加迁移前 identity/round-trip 基线。
2. 提取 Gateway persistence 与 protocol 边界，迁移 history 查询、事务和 operation journal，运行 Gateway history/recovery 测试。
3. 提取 run lifecycle、observation store 和服务编排，保持同步/异步入口、SSE replay、幂等和恢复行为，运行 Gateway 全套测试。
4. 拆分 Evaluation reader/bundle 的读取与归一化，再拆分 timeline、failure attribution 和 report 投影，运行评测测试与真实诊断 smoke。
5. 更新结构测试、集成文档和旧引用检查，运行完整 Python 测试、图表理解 smoke、评测 CLI 检查及 `git diff --check`。

回滚按 Gateway persistence、Gateway transport/service、Evaluation reader、Evaluation timeline/report 四个边界执行。每个边界完成后保持前一阶段的 canonical 导出不变，出现行为差异时只回退当前边界。
