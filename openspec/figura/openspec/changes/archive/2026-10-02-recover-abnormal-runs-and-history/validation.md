# 实施验证记录

验证时状态：当前工作树实现；未提交、未同步主规格、未归档。验证日期：2026-10-02。

## 验证结果

- `conda run --no-capture-output -n agent python -m pytest -q tests/test_figura*.py --tb=short`：494 passed，33.48 秒。包含异常历史、Runtime、Provider、工具、资源、Gateway 和请求组装回归。
- `conda run --no-capture-output -n agent python -m pytest -q tests/test_figura_abnormal_runs.py tests/test_figura_agent_executor.py --tb=short`：67 passed。完整 owner/action 锁调整后的窄验证。
- `conda run --no-capture-output -n agent python -m pytest -q tests/test_figura_abnormal_runs.py tests/test_figura_agent_executor.py tests/test_figura_agent_request.py tests/test_figura_prompting.py tests/test_prompting.py --tb=short`：90 passed。
- `conda run --no-capture-output -n agent python -m pytest -q --tb=short`：1051 passed、8 failed，84.61 秒。失败均为旧 `tests/test_gateway.py`，Provider readiness 返回 `agent_unavailable`，异步 HTTP 接受返回 503。
- 对实施前 HEAD `4bff4edc5ece1843f7ddb9560ed8e8e62ddaab9e` 的独立临时 `git archive` 副本运行 `tests/test_gateway.py`：45 passed、相同 8 failed，6.92 秒。确认该组失败在本次修改前已存在；本次没有修改 `src/chartagent` 或这些旧测试。
- frontend `npm run build`：通过 TypeScript 检查与 Vite 生产构建。
- frontend `npm run smoke`：通过现有 UI、时间线、图像/渲染预览和 launcher 合同检查，以及新增 run-stop 行为与组件静态渲染检查。
- `openspec validate recover-abnormal-runs-and-history --strict --store figura`：通过。
- `git diff --check`：通过。新增文本也检查尾部空白与末尾换行。

启动器实现未修改，未额外运行 `smoke:launcher` 生命周期测试。未使用真实 Provider 网络调用；Provider 请求由兼容假 transport/client 校验。OCR 场景使用实际工具、PNG、资源重建和授权读取，OCR 引擎返回固定检测结果；不是 OCR 精度评测。前端验收为行为 smoke 与组件静态渲染，未做浏览器截图验收。

## 故障验收范围

- 合法异常批次保留成功/失败观察，区分未知与未开始；重复/错配事实仍拒绝。原始意图超过 Provider 限制时完整保留并在 claim 前失败。
- OCR 成功、测量未知、渲染未开始的局部成功场景：旧 Run 终结后，同 Session 新 Run 可 prepare；已提交 OCR 可以索引及授权读取，历史图像不自动发送。
- 停止幂等、事务回滚、v9→v10 迁移、重开存储、Session aggregate 清理、claim/prepare/completion 先后顺序。
- Provider 成功、已知失败和未知 outcome 与停止竞争，保留真实 attempt outcome；未知 Provider 不重发。
- 已开始工具成功/失败结果真实提交；剩余调用未开始。PNG 已写而结果未提交时恢复不重复文件、不改变原字节或修改时间。
- OS 跨进程 owner 竞争、正常退出及异常进程退出释放；终态 owner 未释放时新建和删除冲突，幂等重放可返回原 Run。
- 周期补偿、队列饱和延后、同 Run 去重、扫描线程关闭、连续提交失败仍遵守持久三次 attempt 上限。
- 停止 API 的 202/200 区别、空 body/空对象、坏字段 400、跨 Session 404、Origin 403；UI 重载、丢失响应、活动刷新及终态关闭轮询。

## 保留限制

停止为协作式：线程 handler 不返回时仍保持 running/stopping，不能强杀或提前释放 Session。reconcile_required 没有可信 adapter 时显式失败；未知效果没有被回滚。孤立文件清理、进程 worker、调用 ID 重映射、跨 Provider 历史转换和历史摘要不属于本次变更。新 schema、终态码与停止通知不承诺旧二进制直接兼容，回退需升级前备份。

## 规格同步与归档

2026-10-02：六份 delta 已合并到主规格（18 条修改要求、6 条新增要求）。逐项核对描述和场景，保留原 Purpose 与无关要求/场景，替换明确冲突的旧行为场景。Figura store 的 20 份主规格严格校验通过，change 严格校验通过，任务 40/40。change 已移入 `archive/2026-10-02-recover-abnormal-runs-and-history`，`.openspec.yaml` 原样保留；Git 尚未提交。
