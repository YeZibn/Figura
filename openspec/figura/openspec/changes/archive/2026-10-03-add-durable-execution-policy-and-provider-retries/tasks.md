## 1. 统一执行载荷与正确性合同

- [x] 1.1 在 `src/figura/shared` 实现唯一 ExecutionPayloadLimits、配置解析和有界 canonical JSON 编解码；默认 32 MiB、实际 container depth 64，拒绝重复 keys、非有限数、非法 Unicode 与非 JSON 值，组合根注入同一配置实例。
- [x] 1.2 删除 shared JSON/Schema 通用 bytes/property/enum 数量微上限与 Schema depth 16；保留支持的 keywords、类型和领域 Schema 的 maxItems/maxLength，增加深度 64 边界及大对象/大 enum 校验用例。
- [x] 1.3 实现完整 Registry、observation、model response+intents+continuation、record/fact、Provider 结构化请求的载荷单元；图片使用 metadata/digest 占位计 JSON，原图继续独立校验；覆盖 Unicode bytes、arguments 字符串 escaping、完整批次合计超限的原子拒绝。
- [x] 1.4 将任意 call ID 长度限与 generic tool-name 长度限替换为共享身份校验；保留原值、有效 UTF-8、非空、唯一/配对、名称字符集和自有 ID 格式。测试超过 256 bytes 的 ID 跨 intent/result/history 完整一致。

## 2. 新版 Runtime 数据与原子存储迁移

- [x] 2.1 定义完整 ProviderRequestBinding、扩展 ProviderAttempt 和 provider_retry NextAction；严格 options/asset_manifest 字段与 legacy nullable 规则，扩展私有 RunState 读取；metadata 不进入公共 projection。
- [x] 2.2 实现 schema 10→11 事务迁移：binding 表、新 attempt 分组索引/响应唯一性、去掉 Run attempt<=8 与执行 payload 小 CHECK、store read ceiling；保留 FK、json_valid、不可变与 Session aggregate删除scope触发器。
- [x] 2.3 增加 RunInput2、ModelResponse3、FinalAnswer2、ToolFact2、continuation envelope2、checkpoint2 的 writers/readers；保留所有支持的旧 decoder和原始值，取消新版本 input/assistant/argument/result/continuation 微上限及 call position<64，降低写入限额不损坏历史读取。
- [x] 2.4 改为按逻辑 operation 验证 attempts/checkpoint：失败与unknown可在成功之前，最多一个started/accepted response，attempt连续、binding/prefix相同、due/link正确；加入损坏引用、重复响应、非连续序号和 legacy 数据回归。
- [x] 2.5 增加迁移成功/故障回滚/多进程首次打开/聚合删除测试；验证旧 schema3 至10受支持fixture、终态不可变、DeepSeek missing/empty/null不变，以及提高再降低部署guard后既有大事实可读。

## 3. Provider 准备、配置和网络错误分类

- [x] 3.1 将 ProviderOptions 升为2并使 max_completion_tokens可选；删除Agent4096与Provider131072通用限额，新增每Provider可选配置，未设置时省略wire参数；删除timeout<=600，保留默认60、有限正数与当前Adapter实际参数语义。
- [x] 3.2 删除Provider通用messages/instructions/tools/calls/text/schema/image-count以及原始content/reasoning字符微上限；接入shared guard，保留有证据的Adapter专属协议限制、Schema忠实转换、图片单体/总bytes保护，不增加context planner。
- [x] 3.3 实现 prepared request 安全 descriptor、endpoint/wire fingerprint与asset manifest；token仍绑定client且不可序列化。支持从原prefix和冻结options重建并校验；测试默认配置变化不覆盖绑定、endpoint/资产/contract变化拒绝发送。
- [x] 3.4 收窄failure分类并提取安全Retry-After：区分可证明no-send、临时unknown、临时拒绝、永久/invalid/internal；覆盖typed cause、408/429/500/502/503/504、quota429、鉴权、TLS/DNS配置、未知异常和malformed response，禁止用全部>=500或全部SDK异常推断transient。
- [x] 3.5 保持SDK与HTTP transport hidden retries为0；在SDK无限解析前有界读取完整原始response JSON，并对规范化transition再检查guard；已有直接Provider stream累计接入同一guard且不改变Agent non-streaming，验证超大body/stream早拒绝及失败日志无raw body/endpoint/secret。

## 4. Runtime 持久化 Provider 重试

- [x] 4.1 扩展初始claim事务，原子写binding+attempt+checkpoint并检查ownership/CAS/stop；支持旧facade直接claim兼容但无binding不允许unknown替代；删除repository和SQL残留Run累计attempt限。
- [x] 4.2 实现failure关闭与重试等待原子事务：固定每逻辑请求首次+3次、full jitter 1/2/4秒指数区间及30秒指数cap、有效Retry-After、UTCdue、progress仅revision；第4次永久关闭，无Run累计retry配额。
- [x] 4.3 实现到期replacement claim：严格上次已闭合、序号/allowance、binding、due、stop与ownership；unknown仅generation-only，close-old/new-identity，不允许改旧outcome或隐式fallback。
- [x] 4.4 实现orphan Provider闭合与安全replacement：只有lock证明原owner退出，legacy无binding保守unknown终止，stop优先；处理claim后未发送即crash仍占位，重启不重置次数。
- [x] 4.5 增加fake transport与真实repository组合测试：temporary→success、unknown→success、4次耗尽、late response拒绝、一个response/continuation/tool批次、due重启、claim race、active owner禁止replacement、commit失败不部分发布。

## 5. 工具明确失败与未知恢复边界

- [x] 5.1 删除ToolRegistry/Runtime/codec内count、Schema/description/argument/result/aggregate微上限，完整projection/observation用shared合同；保留safe error 512 B、pointer256 B与Schema语义。测试大合法参数/结果和完整batch超限。
- [x] 5.2 在初始/replay持久化claim入口统一执行每逻辑call最多3 attempts；版本/effect匹配、稳定Run/call幂等键、结果唯一、stop/CAS均在同边界检查，直接facade调用也不能绕过。
- [x] 5.3 保持明确failed observation只提交一次且不自动再调用；增加retryable=True仍只调用一次、模型修正参数发新call ID、同参数新决策、原failed history不可覆盖的回归，不新增ToolRetryPolicy。
- [x] 5.4 增加窄的内部ToolOutcomeUnknown信号并贯通durable owner，审计decompose_panels/render等写入handler；部分效果无法判断时无fabricated result，按声明effect恢复/对账。测试写入后异常、幂等结果复用、无reconciler和Registry升级不可重放。
- [x] 5.5 将ToolContext cancellation接入durable stop，存储读取失败显式fail-closed；测试工具协作退出、native handler未返回时不得释放owner/启动replacement/删除Session，真实在飞结果可提交。

## 6. Agent 无累计配额与执行切片

- [x] 6.1 删除Agent累计Provider/tool预算与相关终止分支；完整ordered batch继续串行，known failure交模型，unknown工具仅按恢复合同；Agent新Provider路径必须binding-aware。
- [x] 6.2 增加Gateway使用的单external-action quantum：稳定checkpoint提交后才让出，无active dispatch再释放owner；接入provider_retry动作。默认同步调用由外层driver释放owner后等待due/stop并继续，不新增Figura CLI入口。
- [x] 6.3 完整Session history、3个SYSTEM层、异常尾部数据、最近完整批次图片和来源continuation保留；取消generic16个attachment refs，参数未设输出限时省略；retry不将attempt元数据加到prompt、不摘要/裁断。
- [x] 6.4 增加超过8轮模型、超过32个已启动逻辑工具以及单响应超过64calls的正常任务测试；以支持该合同的fake Provider隔离厂商真实限制，验证无隐藏计数终止、工具顺序/批次完整与跨slice不重复执行。
- [x] 6.5 覆盖prepare拒绝不claim、length/malformed不自动补发、stop与Provider/tool/final claim竞争、stop过程中真实结果保存，以及默认同步入口遇网络恢复最终正常返回。

## 7. Gateway 到期与公平调度

- [x] 7.1 用单动作slice调度Agent，增加去重ready队列及稳定排序轮转cursor；保留3worker/8queue默认容量，长Run退出slice后加入队尾，多进程仍由Runtime lock仲裁。
- [x] 7.2 筛选durable retry due，等待者不占worker/queue；stop通知绕过due及时协调；启动/定期/退出补偿共用调度边界，避免busy loop或固定列表前缀饿死后续Run。
- [x] 7.3 Gateway Run-create JSON有界读取改用shared配置，upload仍Sources guard；保持HTTP/SSE字段、RunStatus、`runId:sequence`与安全activity，read/history/SSE/detail不得schedule/execute/reconcile。
- [x] 7.4 增加至少14个独立Session的公平性测试、多个retry waiter释放容量、队列满后的补偿、stop waiter立即收敛、worker异常退出和read-only路径零外部调用测试；测试保证动作边界公平，不假设native步骤可强杀。

## 8. 端到端验收与实现文档

- [x] 8.1 组合验证“多轮长Run+临时Provider故障+工具明确失败后模型修正+重启+stop”持久化链路，断言响应/调用/continuation只提交一次、完整异常history以及Session删除边界；不依赖付费真实模型调用完成可靠性测试。
- [x] 8.2 对默认32MiB附近请求、Registry、response、continuation做单独编码/有界接收内存检查，记录峰值及主要副本；审计Agent/Provider/Tool/codec/SQL/Gateway残留微限制，不误删事件、隐私、Sources、Charts/Measurement和并发保护。
- [x] 8.3 更新`.env.example`、`docs/figura-implementation-overview.md`及受影响分域文档：完整字段/owner/生命周期、限制保留删除表、重试与模型工具决策、配置和schema升级/备份恢复；明确远端重复计费和context窗口后续范围。
- [x] 8.4 先运行受影响Figura窄测试，再运行`conda run -n agent python -m pytest -q`；若修改前端实现则完成`npm --prefix frontend run build`与smoke，若改launcher则加smoke:launcher；记录真实验证结果，不把规划状态标为已实现。
- [x] 8.5 完成`git diff --check`、`openspec validate add-durable-execution-policy-and-provider-retries --strict --store figura`与capability交叉核对；验收任务全部完成后再单独进入sync/archive流程。
