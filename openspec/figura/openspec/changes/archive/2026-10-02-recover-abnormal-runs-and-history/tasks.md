## 1. 合法异常历史与请求投影

- [x] 1.1 在 Memory 定义 design 中完整的 `RunHistoryOutcome`、`IncompleteBatchContext`、`IncompleteCallContext` 和 `SessionHistory.run_outcomes`；默认兼容现有调用，无新增持久历史。
- [x] 1.2 将完整性校验与终态尾部分流：只转换较早 failed/interrupted Run 的合法未完成尾部；current/completed 不完整、重复结果、身份错误和非法顺序继续拒绝；增加窄测试。
- [x] 1.3 保留全部闭合交互，将整个未完成批次转成原始意图、调用状态和源结果观察；为无响应失败也生成 outcome；验证成功、失败、未开始与未知四类以及 user/final 不重复。
- [x] 1.4 在第三层运行时 JSON 添加有序 `prior_run_outcomes`，保留现有三层指令与硬限制；确保异常观察只出现一次、没有伪造 tool result 或 continuation。
- [x] 1.5 更新对应 prompt 资产中的异常意图/观察数据规则；验证 prompt 注入内容不会替代静态规则，运行 `tests/test_prompting.py`（适用时）及新 Figura prompting/request 窄测试。
- [x] 1.6 验证部分批次中已提交成功资源仍可索引和授权读取，未确认文件不提升为资源，历史图片不自动加载；用兼容 Provider 和不重复 call ID 验证旧 Run 中断后能 prepare 下一请求。

## 2. Runtime 停止请求与兼容迁移

- [x] 2.1 确认现有 schema version，按现有迁移机制增加 `run_stop_requests` 表、PK/FK与唯一 request ID；旧数据库升级后原事实不变。
- [x] 2.2 实现 `RunStopRequest` 完整字段、编解码/校验与 `RunState.stop_request` 同快照读取；旧 Run 默认 None，新增表随 Session aggregate 删除。
- [x] 2.3 实现停止请求原子接受与幂等重放：只第一次写请求和 progress；终态只返回原状态，跨 Session拒绝；加入事务回滚测试。
- [x] 2.4 更新 progress 事件校验与编码合同，允许停止通知使用未增加的当前 checkpoint revision；验证事件序号增加而执行事实、游标和 revision 不变。
- [x] 2.5 在 Provider claim、工具初始/replay claim 和 final completion 事务内检查停止请求，提供明确内部停止信号；测试 stop-first、claim-first与completion-first顺序。
- [x] 2.6 新增三种工具恢复终态码与固定中文说明，保留旧 terminal code/preparation message读取；测试 raw exception/path不能进入公开错误。
- [x] 2.7 实现停止收尾与 attempt outcome 的原子事务，支持 interrupted 下已知失败/未知 Provider outcome及保留 checkpoint；验证唯一终态、失败回滚和终态后拒绝写入。

## 3. 执行所有权与安全竞争

- [x] 3.1 增加独立 Run 所有权锁，复用安全路径和跨进程非阻塞 OS锁；保留动作锁，测试目录权限、锁忙、进程退出释放和锁顺序。
- [x] 3.2 让统一 Agent执行入口持有全任务所有权；调整 DurableToolExecutor 内部恢复 wrapper 与已持锁路径，避免嵌套取得同一锁。
- [x] 3.3 所有推进步骤重读 Run/停止请求；prepare之后claim前复查，已开始动作仍能提交真实结果，后续动作被停止；测试准备/执行/最终完成的竞态。
- [x] 3.4 将终态公开写入/interrupt路径接入安全所有权协调，禁止绕过锁中断活跃 handler；锁忙和 stale checkpoint不被误当作 Run失败。
- [x] 3.5 新 Run创建与 Session删除检查并协调前序执行者释放，维持幂等重放、一 Session一 running与删除文件事务；测试终态owner尚未释放、stale队列和跨进程竞争。

## 4. 单调用恢复与异常收敛

- [x] 4.1 扩展工具执行为可单调用推进及单步恢复，保持 provider顺序，每步之间回到统一协调检查停止；测试恢复后不直接执行整批。
- [x] 4.2 将 eligible TOOL_ATTEMPT连接安全重放，保留原 registry和本地幂等key；测试初次handler产生本地效果后未提交的恢复不重复Panel/PNG。
- [x] 4.3 从持久 attempt_number实施每逻辑调用最多两次自动replay，重启不清零；保留8 Provider/32 distinct calls计数，known failed结果不按retryable自动重试。
- [x] 4.4 对 Registry不可用、预算耗尽、无trusted adapter的reconcile_required写明确安全失败；保留未知事实，不调用handler或伪造结果。
- [x] 4.5 持久停止优先于恢复；Provider未知仍不重发，已有真实响应/已知失败与stop竞争正确保留事实并裁决终态。
- [x] 4.6 对 unexpected executor退出依据最新合法checkpoint收敛；存储/完整性错误维持fail-closed，锁忙保持等待；添加窄回归。

## 5. Gateway 调度、停止 API 与活动投影

- [x] 5.1 让普通调度、启动接管和退出补偿调用同一协调入口，去除吞异常后丢弃责任路径；queued和执行所有权分别判断。
- [x] 5.2 增加有生命周期的有界周期扫描，容量不足延后、同Run去重、锁忙退让，关闭扫描后关闭线程池；测试队列饱和、重复补偿和退出清理。
- [x] 5.3 实现 Session-scoped stop POST，支持空body/空对象，按design返回202/200/400/404/安全500及幂等 StopRequestDto；Origin规则不变，容量不足不丢请求。
- [x] 5.4 扩展 Run DTO 的 executionState、stopRequestedAt、availableActions，并按优先级投影；纠正所有TOOL_ATTEMPT都标needs_reconciliation的行为。
- [x] 5.5 接通既有progress/terminal SSE刷新，保持event identity与cursor；GET/history/timeline均无执行副作用，公开字段无私有payload。
- [x] 5.6 Gateway集成测试覆盖stop后重启、结果提交与停止竞争、未知Provider无重发、终态后续Run创建、停止与Session删除竞争。

## 6. 前端协作式停止与会话续用

- [x] 6.1 在 Figura client/DTO mapper及workspace可选能力中提供 `requestRunStop`，保留兼容façade；ChartAgent/mock既有控制行为不被改变。
- [x] 6.2 按availableActions显示停止按钮，接受后呈现stopping并禁用重复停止/新提交/删除；保持工具细节折叠和固定中文说明。
- [x] 6.3 在既有唯一Run生命周期owner内接入停止刷新、running期间有界活动读取、重连/页面重载恢复；不新增另一套事件合并逻辑。
- [x] 6.4 failed/interrupted后保留已提交图库和工具时间线，允许owner释放后的新消息；冲突刷新等待，不自动重发用户提交或重开旧Run。
- [x] 6.5 前端smoke覆盖停止接受与终态区别、刷新后stopping恢复、网络丢失响应、活动状态变化与异常后继续；不返回handler仍显示等待，不宣称强制停止。

## 7. 完整故障验收与交付文档

- [x] 7.1 增加真实跨进程锁/退出测试及局部成功工具批次fixture，验证旧owner退出前不接管、退出后可重放/收尾、终态只有一条且后续无写入。
- [x] 7.2 完成代表场景：OCR成功、测量未知、渲染未开始 → 结束旧Run → 同Session新Run可prepare并保留真实观察；另验证腐坏历史仍拒绝、请求超限不裁剪。
- [x] 7.3 运行受影响窄测试后执行 `conda run -n agent python -m pytest -q`、frontend `npm run build` 与 `npm run smoke`；若实际改动launcher，补 `npm run smoke:launcher`，记录结果及限制。
- [x] 7.4 更新总览及Runtime/Agent/Memory/Web owner文档，完整记录新增字段、API、锁、恢复预算和协作停止限制；不把后续工作进程或独立Provider/ID修复标成已实现。
- [x] 7.5 核对六份delta与最终实现，修正同Provider continuation旧文字冲突，运行OpenSpec严格校验及 `git diff --check`；主规格同步、归档和Git提交按后续明确工作分别执行。
