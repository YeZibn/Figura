## Context

当前七个 durable callback 分别在 `GatewayService._build_runtime_for_run` 创建，并作为独立关键字参数穿过 `GatewayRuntimeFactory`、`create_agent_runtime`、`Agent` 和 `GeneratedChartVerificationFlow`。执行记录提交还会单独传入模型轮次与工具处理；详见 proposal 的 Why。

Gateway 的七项操作共享同一 Run、session 和 history store 上下文：暂存图表、保存验证结果、发布图表、读取已提交工作结果、按引用读取暂存图表、按 work key 读取暂存工作、提交 execution entry。Gateway 可将当前执行 Run 和 session 绑定到一个 per-run 实现中。恢复时，子 Run 也可能发布 lineage 中父 Run 暂存的图表；该图表的原始 owner 必须保留在已校验的 `ChartManifest` 中。CLI 和其他非 Gateway Agent 路径没有该持久化服务，仍可不提供 port。

## Goals / Non-Goals

**Goals:**

- 建立一个类型化的 `DurableExecutionPort`，作为 Agent 核心与 Gateway 持久化适配器之间唯一的 durable execution 接口。
- 在 Gateway runtime 的创建、恢复和执行过程中复用同一个 per-run port 实例。
- 删除旧的七个 callback 参数和所有过渡转发层，不保留兼容别名、适配器或双轨代码。
- 保持当前执行记录原子提交、work-key 幂等、恢复校验、图表暂存和发布安全语义。

**Non-Goals:**

- 拆分执行记录、checkpoint 或图表验证的数据模型。
- 改变 SQLite schema、HTTP/SSE 协议、Agent 提示、验证策略或前端行为。
- 把 trace、interruption 和 visual observation 注入也并入 durable execution port；它们不负责 durable execution。
- 为非 Gateway Agent 创建兼容适配器或无操作 port。

## Decisions

### 在共享核心模块定义 port，由 Gateway 实现

在 `src/chartagent/durable_execution.py` 定义 `DurableExecutionPort` Protocol 和提交结果所需的最小结构类型。Agent 与验证流程依赖该共享接口；Gateway 提供 per-run 实现并绑定 `run_id`、`session_id`、history store 和 `ManagedRun`。这样避免 Agent 或验证包导入 Gateway 持久化模块，也不把 port 放进会反向导入 Agent 的 runtime factory。

考虑过将 Protocol 放在 `gateway` 包中，但 Agent/验证核心导入 Gateway 会反转依赖方向。也考虑过放在 `agent` 子包；验证流程导入时会触发 Agent 包初始化并增加循环导入风险。单一共享模块避免这两种耦合，不扩成通用 ports 框架。

### 为每个 Gateway Run 构造一个绑定上下文的实现

Gateway 在 `_build_runtime_for_run` 建立 port 实例。暂存、恢复查询和 execution commit 从该实例取得绑定的当前 Run/session 身份；消费方不再重复传入可互相矛盾的身份值。发布操作接收已校验的 `ChartManifest`，核对其 session，并使用 manifest 记录的原始 Run owner，这样恢复子 Run 可以继续发布父 Run 已暂存的图表。checkpoint 恢复入口已经按 execution lineage 校验该暂存引用。每个方法仍调用现有 history store 或 `ManagedRun` 的持久化入口，不把存储实现移动到 Agent。

### 通过一个明确对象替换七个 callback 入口

`GatewayRuntimeFactory` 和 `create_agent_runtime` 接收 `durable_execution_port`；`Agent`、`AgentRunOrchestrator`、模型轮次执行、工具执行和 `GeneratedChartVerificationFlow` 使用该 port 调用所需操作。port 对执行提交提供显式参数类型，不保留 `Callable[..., Any]` 的旧注入签名。

Gateway runtime factory 必须提供非空 port；非 Gateway 的 Agent 可省略 port，保留当前无 Gateway 持久化服务时的执行模式。该可选性表示运行模式边界，不提供旧 callback 的兼容路径。

考虑过用 `**kwargs` 接收新旧接口、将七个 callback 包成闭包对象，或同时保留新旧入口。它们都会继续隐藏依赖缺失或保留两套调用方式，因此不采用。直接迁移所有仓库内工厂、构造器和测试调用点。

### 在原有边界保留失败处理

port 的 Gateway 方法直接调用现有持久化方法。Verification flow 在暂存、验证保存或发布读取失败时沿用当前 unavailable/fail-closed 结果；execution commit 的存储错误继续向现有恢复/运行错误边界传播。重构不新增统一吞错层，也不更改错误分类。

## Risks / Trade-offs

- **Port 把错误 Run/session 绑定给图表或恢复引用 →** 在 Gateway 适配器构造时只捕获当前 Run/session；发布使用经过恢复流程校验的 manifest owner，并用 fresh run、resume child 和跨 session 引用测试验证两种身份边界。
- **Protocol 仍过宽或方法含义不清 →** 只纳入这七项 durable 操作；方法使用明确名称和返回类型，执行提交使用显式关键字参数。
- **遗漏旧 callback 调用点导致部分迁移 →** 先全仓搜索七个旧字段名，再用结构测试断言旧参数不再出现在 factory、Agent 和验证流程接口中；同步更新所有测试工厂。
- **抽象层改变故障语义 →** 端到端回归覆盖 stage、verify、promote、执行记录提交和 resume，并验证发布仍在持久化失败时关闭。

## Migration Plan

1. 定义共享 Protocol、最小执行提交结果类型和 Gateway per-run 实现，并单测当前 Run/session 绑定及父 Run 暂存图的恢复发布。
2. 将 Gateway factory 与 `create_agent_runtime` 改为传递单个 port；将 Agent、orchestrator、turn/tool execution 和 verification flow 的七个 callback 字段改为直接使用 port。
3. 更新仓库内所有构造器、runtime factory 和测试替身；删除旧 callback 类型、参数、转发映射、逐项完整性检查和兼容处理。一次完成迁移，不设置过渡期。
4. 运行相关 Gateway、Agent、verification、execution-record 测试，再运行完整 Python suite、`openspec validate` 和 `git diff --check`。

无需数据迁移。若验证发现回归，通过一次代码回退恢复旧接口版本；不混合部署新旧调用协议。
