## 1. 建立 Gateway/Evaluation 兼容基线

- [x] 1.1 盘点 Gateway、Evaluation 的包级导出、CLI 入口、动态字符串引用、SQLite 表/查询、RunEvent/checkpoint JSON 和评测 bundle 文件，形成稳定 API 与私有遗留清单。
- [x] 1.2 为协议值对象、GatewayService、EvaluationBundle、EvaluationReader、DiagnosticTimeline 和报告输出增加 identity、签名、JSON round-trip 与目录布局基线测试。
- [x] 1.3 使用 `rg`、运行入口和测试确认候选私有辅助无调用；保留公开导出、CLI 符号和兼容 façade，不提前删除实现。

## 2. 拆分 Gateway 持久化边界

- [x] 2.1 建立 Gateway persistence 的 canonical 模块边界，将 SQLite connection/transaction、session/run/history 查询和 operation journal 分离，并保留 `history.py` 的既有兼容入口。
- [x] 2.2 迁移历史记录、RunEvent、checkpoint 和 operation journal 的读写逻辑，保持事务边界、序列号、幂等键和 recovery JSON 完全兼容。
- [x] 2.3 让 `gateway.protocol` 成为协议模型、校验和有界序列化的唯一实现所有者，消除 persistence 对 service/server 的反向依赖。
- [x] 2.4 运行 Gateway history、checkpoint、operation journal、session isolation 和 concurrent lifecycle 测试，修复迁移期间的行为差异。

## 3. 拆分 Gateway 运行与传输编排

- [x] 3.1 将 `ManagedRun`、`HistoricalRun`、`RunManager`、`ObservationStore` 的运行状态与观察资源职责拆分为聚焦模块，保持同步运行、异步运行、terminal cleanup 和 observation reference 行为。
- [x] 3.2 收缩 `GatewayService` 为 session、attachment、provider、run 和 recovery 的应用编排层，移除重复的 payload 解析和状态投影。
- [x] 3.3 收缩 `server.py` 为 HTTP 请求校验、路由、SSE/响应适配层，确保业务状态只由 service/run/history 持有。
- [x] 3.4 增加同步/异步提交、SSE replay/reconnect、idempotency conflict、interrupt/resume、attachment authorization 和 no-fallback 回归测试。

## 4. 拆分 Evaluation 输入与归一化

- [x] 4.1 将 `EvaluationReader` 的 bundle 扫描、Gateway/history 读取、resource reference 加载、脱敏和有界裁剪拆成单向输入协作者，保持 reader 包级 API。
- [x] 4.2 明确 manifest、bundle、case、run 和 normalized record 的所有权，禁止 Evaluation 输入层直接调用 Agent、图表工具或 Gateway 内部 database connection。
- [x] 4.3 保持评测根目录、case 目录、原始历史、图片引用、JSON/Markdown 文件布局及缺失/截断状态语义不变。
- [x] 4.4 运行 manifest、bundle、reader、资源授权、脱敏和跨 Gateway restart 的 Evaluation 测试。

## 5. 拆分 Evaluation 时间线与报告

- [x] 5.1 将 timeline 的事件解析、stage status 归约、证据引用收集和阶段状态投影拆成可独立测试的模块，保持现有阶段名称和状态集合。
- [x] 5.2 将 repeated decomposition、panel handoff gap、unscoped measurement、repair、assembly/render 等诊断规则迁移到明确的 failure attribution 所有者，保持首个可确认失败优先级。
- [x] 5.3 将 JSON/Markdown 报告生成与 timeline 归约解耦，保持报告字段、脱敏、unknown/not_reached/not_observed 语义和 CLI 输出稳定。
- [x] 5.4 增加时间线顺序、第一失败归因、截断/缺失证据、报告 round-trip 和评测批次汇总回归测试。

## 6. 结构与完整回归验证

- [x] 6.1 更新结构兼容测试，验证 Gateway/Evaluation canonical ownership、包级 façade identity、单向依赖和无重复协议实现。
- [x] 6.2 更新受模块布局影响的文档与开发说明，使用 `rg` 确认不存在旧 canonical import、失效私有符号或 Evaluation 到 Gateway 内部实现的反向依赖。
- [x] 6.3 使用 `conda run -n agent python -m pytest -q` 运行完整 Python 测试，运行图表理解 smoke 和现有 Evaluation CLI/真实诊断入口。
- [x] 6.4 执行 `git diff --check` 与工作区范围审查，确认未混入 Agent、前端、图表传感器算法或 OpenSpec 主规格的非预期改动。
