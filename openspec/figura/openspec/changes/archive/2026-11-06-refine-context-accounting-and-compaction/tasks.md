## 1. 固定合同与兼容基线

- [x] 1.1 核对最新工作树的 request builder、Provider prepare、摘要选择及其他活动变更，保留重复观察/周期回看行为并记录定向测试命令。定向基线：`conda run -n agent python -m pytest -q tests/test_figura_context_estimation.py tests/test_figura_context_checkpoint.py tests/test_figura_context_compaction.py tests/test_figura_agent_request.py tests/test_figura_agent_executor.py`。
- [x] 1.2 核对既有旧 ContextEstimate、selection plan v1、旧 checkpoint 和冻结普通/摘要请求回归 fixture；基线定向测试 160 项通过，原持久格式可读。
- [x] 1.3 定义 input-aware summary v3、selection plan v2 和投影/accounting 版本；补齐解码、验证及原请求不可重绑测试。

## 2. 双统计和组件归属

- [x] 2.1 建立调用期完整请求/历史双统计，明确摘要、raw 历史、当前输入、资源目录、状态、native tools、continuation 和图片归属，保持持久 ContextEstimate 不变。
- [x] 2.2 覆盖 full 高于阈值但 history 低于阈值、工具 Schema 和 continuation 占用、图片不重复计数、未知容量及编码不可用等测试。
- [x] 2.3 接入仅计数及安全原因的内部诊断，测试没有用户文本、路径、图片或完整工具 payload 泄漏，不新增公开 API/UI 字段。

## 3. 用户输入与完整交互覆盖

- [x] 3.1 调整历史输入投影：covered 旧输入由 input-aware 摘要承接，未覆盖旧输入出现一次；当前用户输入始终为完整 native user message。
- [x] 3.2 将合格历史输入纳入连续覆盖和预算，支持当前 Run 已提交前缀、跨 Run 近期尾部及 input-only 历史，保持工具批次完整性和视觉回看保护。
- [x] 3.3 更新摘要提示资产与来源校验，要求保留有效约束、更正、关键数据和资源引用，原文精确读取不受摘要影响。
- [x] 3.4 增加 legacy input reconciliation 的新操作身份和恢复路径，旧 checkpoint 不直接授权删减旧用户输入；超大源或无效摘要回退不推进覆盖。
- [x] 3.5 验证同文不同 Run、空文附件、检查点位于当前/此前 Run 中间、失败/中断 barrier、已覆盖 Run 后续异常、原文授权检索及原事实不变。

## 4. 资源目录分层与软预算

- [x] 4.1 实现 mandatory/optional/discoverable 选择与稳定排序，覆盖当前附件、最新批次、已声明类型化参数及直接来源关系，避免仅因当前 Run 就全量保留 Panel。
- [x] 4.2 在无 checkpoint 时也支持目录预算；缺少容量/估算时回到现有引用筛选，mandatory 超目标仍保留精确引用。
- [x] 4.3 验证隐藏资源的搜索、精确读取和媒体授权仍使用完整目录，摘要 source ref 与资源 ref 不混用，条目不截断/伪造、不重复展开大结果。

## 5. 压缩协调与恢复

- [x] 5.1 根据设计中的 P、G、A、R、U、S 分配冻结软目标，避免保护交互及图片重复扣减；摘要 preflight 继续检查冻结容量与已配置输出上限。
- [x] 5.2 接入“目录收缩→至多一次新增摘要→最终重估”流程，覆盖同 base 已失败/无收益操作不重新生成、下一新增前缀可再评估和软目标不可满足等分支。
- [x] 5.3 验证 stop/CAS、重启、容量或 Prompt 变化、普通/摘要 Provider 重试均保持冻结输入、目录排序和 fingerprint；不可重建时安全回退/失败，不启动并发替代副作用。
- [x] 5.4 验证最新完整视觉批次超过目标、巨大当前输入、异常历史占满空间时不静默截断、不循环摘要、不新增普通请求近似 token 硬拒绝。

## 6. 验收与文档

- [x] 6.1 运行新增及相关定向测试，至少覆盖 Agent request/executor、context compaction、Provider token estimation、Prompt、Runtime 编解码与恢复；全部使用 `conda run -n agent python -m pytest`。
- [x] 6.2 运行全量 Python 测试，记录真实失败及环境/fixture 边界；不将离线结构测试描述为在线模型的摘要保真率。`conda run -n agent python -m pytest -q --tb=short`：1396 passed、35 failed、1 skipped；35 项均关联缺失的 `tests/fixtures/legacy_charts/` 图像或 `real_chart_diagnostic_manifest.json`，集中在旧 `chartagent` dashboard/evaluation/panel 测试。
- [x] 6.3 运行可复现的长会话场景：跨 Run 保留/更正要求、当前 Run 内多轮测量、摘要后精确读旧输入、遗漏目录的旧 Figure 定位与修改，比较 full/history/目录占用及摘要调用次数。离线测试使用固定 Tokenizer 和 Fake Provider；不评估真实模型的摘要保真度。
- [x] 6.4 更新总览和 Agent/Provider/Memory 相关文档，明确软目标、异常历史边界、legacy 兼容和未执行的在线验证。
- [x] 6.5 运行 `openspec validate refine-context-accounting-and-compaction --store figura --strict` 和 `git diff --check`，核对 proposal/design/specs/tasks 一致；实现验收完成后再单独同步和归档。严格校验与差异检查通过；本 change 保持活动状态，主规格同步与归档留待单独执行。
