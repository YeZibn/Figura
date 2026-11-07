## 1. 重复观察事实投影

- [x] 1.1 在 Agent 内增加当前 Run 已提交成功 OCR/测量调用的纯投影，复用既有事实配对、严格 JSON 编码和类型化结果来源引用；不新增数据库字段或公共协议。
- [x] 1.2 实现动作键与完整 result 精确比较，保留内部 ID、状态、置信度、证据及数组顺序，排除 envelope/attachments；若使用摘要索引，核对规范内容防止碰撞误判。
- [x] 1.3 实现每动作最新观察组、匹配次数、最近两个匹配引用与稳定排序，覆盖非连续调用和同批调用；排除跨 Run、失败、未解决及同逻辑调用恢复的重复计数。
- [x] 1.4 增加聚焦单元测试：参数键顺序/空白变化仍匹配，来源/范围/图表类型/Registry/观察变化不匹配，附件变化不影响，partial/unsupported/空观察参与，A-A-B 不保留旧提醒、A-B-A 统计非连续匹配，第三次合并更新。

## 2. 普通请求与 Prompt 集成

- [x] 2.1 在普通请求动态运行状态层加入可省略的 repeated_observations 投影，仅输出工具名、匹配次数与最近两个结果引用，不重复参数、源文字、图片或完整结果；不改工具消息或添加用户消息。
- [x] 2.2 更新 workflow.md 对提醒的中文解释与收敛建议，明确重复不代表正确、任务完成或强制停止；保持模型调用权限与现有批次执行路径。
- [x] 2.3 扩展 `tests/test_figura_agent_request.py` 与 `tests/test_figura_prompting.py`，验证提醒位置/内容/确定性、省略空段、同批完成后提醒、观察原文和图片配对不变，以及来源文本不被拼入提醒指令。
- [x] 2.4 在请求构建和执行回归中，通过 DurableToolExecutor 证明提醒后第三次相同调用仍真实执行并记录；同时验证冻结提醒请求的重启重试无漂移，不缓存或拦截逻辑调用。

## 3. 恢复、压缩与请求身份

- [x] 3.1 验证重启后从同一持久 Run 前缀重建相同提醒和可读取引用；不新增计数持久化、恢复状态或特殊测量门控。
- [x] 3.2 扩展 `tests/test_figura_context_compaction.py`/请求回归，验证当前 Run 原交互被摘要覆盖后提醒仍由原事实计算，摘要请求不注入提醒。
- [x] 3.3 在现有 Provider 重试测试中验证冻结请求的提醒内容、Prompt 资产和 fingerprint 重建不漂移；资产不兼容继续走既有安全拒绝路径，不按新状态重算绑定。

## 4. 文档与验收

- [x] 4.1 更新 `docs/figura/agent.md` 与 `docs/figura-implementation-overview.md`，记录事实投影 owner、字段生命周期、精确匹配边界和软提醒局限；不将提醒效果写成已证明的模型收敛率。
- [x] 4.2 使用 `agent` 环境先运行新增投影测试，再运行 Agent 请求/执行、Prompt、上下文压缩及相关 Provider 重试回归；运行 `tests/test_prompting.py` 进行提示兼容检查，并记录实际命令和结果。
- [x] 4.3 运行 `conda run -n agent python -m pytest -q`，如失败记录本次新增失败与既有环境/fixture 问题的证据，不将未通过全量标为通过；本变更未涉及前端，不要求前端构建或 smoke。
- [x] 4.4 运行 `openspec validate add-repeated-observation-guidance --store figura --strict` 与 `git diff --check`，核对 proposal/design/specs/tasks 一致及未改变公共协议、数据库、工具 Registry 或累计 Run 配额。

## Validation Notes

- Focused regression: `conda run -n agent python -m pytest -q tests/test_figura_repeated_observations.py tests/test_figura_agent_request.py tests/test_figura_agent_executor.py tests/test_figura_prompting.py tests/test_figura_context_compaction.py tests/test_prompting.py` — 159 passed.
- Full suite: `conda run -n agent python -m pytest -q` — 1378 passed, 1 skipped, 35 failed. The failing dashboard, evaluation bundle, panel handoff, and real-chart diagnostic tests reference missing `tests/fixtures/legacy_charts/` images and `tests/fixtures/real_chart_diagnostic_manifest.json`; failures originate from absent existing fixtures.
