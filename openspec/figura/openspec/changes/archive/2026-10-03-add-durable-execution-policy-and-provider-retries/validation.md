# 实现验收记录

核对日期：2026-10-03。范围是当前 `src/figura` 工作区；delta 已 sync 到主规格，尚未 archive 或提交。上下文压缩、摘要、窗口规划没有纳入本 change。

## 合同与实现交叉核对

| Capability | 实现边界 | 验证证据 |
|---|---|---|
| execution-payload-contract | shared/payloads；同一配置实例由 bootstrap 注入 Store、ProviderFactory、Registry、Gateway | execution_payloads 测试；完整 batch 超限原子拒绝；下述内存探针 |
| model-provider | ProviderOptions2 可选输出；prepare 冻结选项、phase timeout、POST/path/endpoint/payload fingerprint；raw JSON/SSE 有界严格接收；SDK/HTTP retries=0 | Provider 兼容测试、execution_policy 的默认变化/资产变化/重复 key/非有限数/超限与非法 UTF-8 测试 |
| provider-request-retries | binding 首 claim 原子写入；每 operation 4 claims；六类安全 failure；UTC due、jitter 与 Retry-After | known/unknown→success、四次耗尽、重启、早 claim 拒绝、活 owner、late response、竞态与 stop |
| run-execution-core | schema11 原子迁移、旧事实原值、单响应/continuation/batch；读 ceiling 单调增长；owner/CAS/stop | schema3 至10既有回归、真实 v10 DDL 故障回滚、多线程/多进程首次打开、SQLite writers、33MiB 写入后降低配置读取、Session 聚合删除 |
| durable-tool-execution | 明确 failed 不自动 retry；未知效果不伪造 result；每逻辑 call 最多3 claims；稳定幂等键；durable cancellation | 写入未知、直接 facade 恢复上限、已知失败后新模型决策、取消存储错误、native handler 在飞时拒绝接管/删除且保存真实结果 |
| tool-runtime | Registry、Schema、参数、observation、call ID 使用共享 guard；领域 Schema 与安全 error/pointer 仍生效 | tool_registry/tool_runtime/json_schema；长 ID 跨事实/history；大合法结果与整批原子拒绝 |
| agent-react-execution | 无 Run 累计 Provider/tool/token/time 配额；每 slice 一个动作；同步 driver 在 owner 外等 due | 超8轮、超32逻辑调用、单响应超64 calls、prepare 零 claim、length/malformed 不补发、组合长 Run 与 stop |
| session-memory | 保留所有真实提交事实、完整三层指令及异常尾部；attempt metadata 不进入消息；不裁断/摘要 | abnormal_runs/agent_request 的跨 Run/跨 Provider/不完整批次回归；组合链路后续 Run |
| provider-continuation-persistence | continuation envelope2 与旧版本并存；DeepSeek missing/empty/null 语义保留 | provider/run_execution_core/agent_request；重试只提交一次 continuation |
| figura-web-gateway | 单动作 quantum、公平轮转、durable due 过滤；保留3 worker/8 queue；HTTP/SSE兼容且 read-only 不推进 | 14 Sessions、小队列补偿、多个 waiter 零容量占用、stop waiter、worker commit 故障后的恢复、read/history/timeline/detail/SSE 零 schedule |

## 载荷与内存

复现：`conda run -n agent python tests/figura_execution_payload_memory_probe.py`。使用默认32MiB guard；请求、Registry、response、continuation 分别放入略低于32MiB的 ASCII 字符串，逐单元编码/解码。表中数字是 `tracemalloc` 的增量 Python 分配峰值；输入对象在追踪开始前已分配，不能当作整进程 RSS 或部署内存上限。

| 单元 | 编码字节 | 编码增量峰值 MiB | 解码增量峰值 MiB |
|---|---:|---:|---:|
| request | 33,546,283 | 63.99 | 32.01 |
| registry | 33,546,346 | 63.99 | 32.01 |
| response | 33,546,300 | 63.99 | 32.01 |
| continuation | 33,546,304 | 63.99 | 32.01 |

64KiB chunk 的有界接收，在完整32MiB body 时增量峰值64.06MiB（chunks 与合并 bytes 同时存在）；超过guard在接收阶段拒绝，尚未解析 JSON。结合接收与严格解码的33,488,896字节 content 峰值为63.93MiB；该探针让合并 bytes 在UTF-8解码后释放，峰值取决于阶段间对象的实际生命周期。SDK路径受相同字节guard，Python对象开销不等同于原始字节数。主要副本是输入字符串、编码片段/StringIO与最终字符串、原始 body chunks 与 bytes、UTF-8 解码字符串、解析对象。JSON对象/数组还有 Python 容器开销；规范化在复制过程中累计最低可能编码字节，先拒绝已超限容器。没有声称32MiB payload意味着32MiB进程内存。

残留限制审计：旧codec版本与 schema10 DDL 的微上限只为历史读取/迁移保留；schema11实际 records/tools/continuations 已移除相应CHECK，attempt_sequence 只有正数条件。事件16KiB、checkpoint小型动作 envelope、自有身份/Registry version、Session名、响应ID和usage诊断保护、error512B/pointer256B、Sources图片/像素、Charts/Measurement领域限制、3worker/8queue均保留。删除未使用的16图片通用常量。新的执行事实完整单元受共享JSON guard，不设 Run 累计配额。

## 验证命令与结果

- `conda run -n agent python -m pytest -q tests/test_figura* --tb=short`：538 passed（请求绑定/迁移改动后的回归）。随后新增只读SSE和SDK非法UTF-8/零hidden-retry断言、补全六类failure与endpoint/path fingerprint，受影响窄回归106 passed。
- `conda run -n agent python -m pytest -q`：1097 passed，8 failed。8项均为旧chartagent Gateway在缺少本地模型配置时的missing_configuration/503；对原Git HEAD `0ae62b58654b86f075ce1132317dea3ab00f4e69` 的独立临时导出运行 `tests/test_gateway.py`，复现完全相同8项失败（另45 passed），确认不是本change引入。只读 readiness probe 也返回missing_configuration。补充仅该测试进程生效的假 OPENAI_API_KEY/OPENAI_MODEL 和 loopback discard endpoint，完整离线运行 **1105 passed in 58.11s**。命令为 `OPENAI_API_KEY=figura-offline-test OPENAI_MODEL=figura-offline-test OPENAI_BASE_URL=http://127.0.0.1:9/v1 conda run -n agent python -m pytest -q`；没有写入.env或真实凭据，没有访问付费模型。
- `git diff --check`：最终通过。
- `openspec validate add-durable-execution-policy-and-provider-retries --strict --store figura`：最终通过。
- `openspec validate --specs --strict --no-interactive --store figura`：同步后22份主规格全部通过；10份目标规格已核对 Purpose、未涉及要求与场景的保留，以及重复同步的幂等性。

没有修改前端实现或 launcher，因此未运行前端build/smoke。可靠性验证全部使用fake transport或本地HTTP/SQLite，没有依赖付费远端模型。远端unknown后替代请求可能重复生成/计费；本地保证只接受一个响应，而非远端exactly-once。同步/native handler依靠协作停止或自然返回，不能被安全强杀。
