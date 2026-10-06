# 实施验证记录

日期：2026-10-06。对象为当前工作树；本记录不表示主规格同步、归档、Git 提交或发布。

## 七类提示场景审校

下表为对资产、动态指令与原生工具合同的人工审校，不是模型调用评测。

| 场景 | 预期选择与边界 | 当前覆盖与结论 |
|---|---|---|
| 用户直接提供数据绘图 | 数据充分时直接完整装配并按需绘制，不强制 OCR/测量 | agent/workflow + Charts Schema：按目标跳过无用观察；新展示标签不得补造数据或单位 |
| 解释图表 | 获取解释所需证据，不为解释强制生成新图 | agent/evidence/response：区分当前视觉、候选测量与推断；索引不能代替看到图像 |
| 局部文字或数据提取 | 相对所选来源指定范围，保留文字整框与校准线索 | workflow + measurement Schema：两种点格式分别说明；范围/透明外区不参与检测，局部结果不代表整图 |
| 取回历史精确数值 | 已知引用直接读，位置未知先查；需要时再读字段/切片 | workflow + history Schema：content-relative Pointer，字符串/数组 0-based 半开区间，文本查询未命中不证明不存在 |
| 修改已有 Figure | 读取完整 Figure，再提交新的完整 Figure | workflow + assemble/render Schema：无 patch，测量引用仅确认已成功提交；源事实保持不变 |
| 错误或观察不足后的选择 | 修正参数，必要时定向补充，否则保留缺口并交付 | evidence/workflow/response：outcome 与 available/status 分开；warning/retryable 不强制重复调用 |
| 源图与生成图比较 | Figure 已接受后同批加载来源与绘制，使两图同请求可见 | evidence/workflow + observation selection：标注图不是原始真值；渲染成功不是审核通过 |

四份普通静态资产维持 agent → evidence → workflow → response 顺序；工具字段留在原生 Schema，动态目录不重复整份 Schema。摘要生成指令独立在 compaction.md，普通请求不引入 JSON-only 输出合同。动态摘要/资源 JSON 的就地信任提醒保留，因为它们承载具体来源数据；详细决策规则集中在静态资产。

## 自动验证

- 窄回归：`conda run --no-capture-output -n agent python -m pytest -q tests/test_figura_prompting.py tests/test_figura_context_compaction.py tests/test_figura_history_retrieval.py tests/test_figura_observation_scope.py tests/test_figura_observation_tools.py tests/test_figura_panel_tools.py tests/test_figura_agent_executor.py tests/test_figura_chart_figure_tool.py tests/test_figura_chart_generation_flow.py tests/test_prompting.py`：155 passed。
- 包资源：测试通过 importlib.resources 读取新 Markdown；现有 package-data 的 `agent/prompting/assets/*.md` 已覆盖它，不需改打包声明。
- 合同与恢复：全部 12 个工具顺序/description/参数投影一致；五类图像引用可用，三类非图像引用在 handler 前拒绝；完整 v7 历史可在 v8 只读使用，未完成旧调用不执行；摘要重试保持请求身份，修改资产或 Registry 不绕过绑定核验。
- 图像：隐藏 RGB 不影响输入，半透明白底合成，scope/alpha 交集，真实 Panel crop，OCR 整框过滤，五个适配器在空可见范围前拒绝；五种标注反馈不重新显示隐藏 RGB。
- 文档：更新 Overview 与 Agent/Tools/Memory/Sources，更新 Web 的 Registry 版本；保留现有模型字段归属。该记录当时 delta 尚未同步/归档，随后已在本次 sync 完成主规格合并。

- 补充来源校验：`conda run --no-capture-output -n agent python -m pytest -q tests/test_figura_context_compaction.py tests/test_figura_context_checkpoint.py`：28 passed。覆盖 message/tool_result 两种引用、重复/越权/空引用拒绝、旧摘要与新增 Run 来源的增量保留。
- 首次全量：`conda run --no-capture-output -n agent python -m pytest -q`：1195 passed、8 failed（107.95s）。8 个失败全部在未修改的旧 `tests/test_gateway.py`；模拟 runtime 的用例仍使用真实默认 readiness probe，在缺少旧默认 Provider 配置时返回 agent_unavailable/503。
- 环境核验：仅给测试进程设置占位 OPENAI_API_KEY、测试地址与 CHARTAGENT_PROVIDER=openai，并将 CHARTAGENT_ENV_FILE 指向不存在的测试路径，未写入 .env 或仓库配置、未修改 src/chartagent。`tests/test_gateway.py`：53 passed，确认这批失败源于测试配置。
- `git diff --check`：通过；本 change 新增 Markdown 无尾部空格；相关文档的本地链接目标全部存在；Charts 和共享测量 Schema 去除 description 后的 AST 与 HEAD 相同，确认未改变原字段、约束、默认或 validator。
- `openspec validate refine-figura-prompts-and-tool-guidance --strict --store figura`：通过。

最终全量：`CHARTAGENT_ENV_FILE=/tmp/figura-offline-env-absent CHARTAGENT_PROVIDER=openai OPENAI_API_KEY=figura-offline-test-only OPENAI_BASE_URL=https://provider.example.test/v1 conda run --no-capture-output -n agent python -m pytest -q`：1209 passed（108.24s）。这些仅为当前测试进程的离线占位配置；用例使用模拟 runtime/transport，不是有效凭据或真实模型效果评估。

## 未执行的验证

本轮没有调用真实模型、付费 Provider 或进行识别准确率评估。确定性结构与回归测试不能证明新中文提示的模型遵循程度、摘要质量或图表语义准确率。

## v2 分层摘要补充验证

本次将摘要合同从扁平 `items` 升级为 v2 分组结构；该段是对上方首次实施记录的增补，以下为当前工作树的最新结果。

- v2 分组含 `current_goal`、`constraints`、`decisions`、`facts`、`progress`（`completed`、`in_progress`、`pending`、`blocked`）、`open_questions`、`resources`、`proposals`；校验拒绝缺字段、多字段、状态字段错误、条目附加字段及未授权／重复／空引用。
- 既有 checkpoint 持久化后重启可原样读取；增量摘要请求向模型提供此前摘要内容及来源，不暴露内部合同版本，输出统一为 v2。新 checkpoint 和摘要 request binding 写入版本 2；存储 schema 无修改。
- 定向验证：`conda run --no-capture-output -n agent python -m pytest -q tests/test_figura_context_compaction.py tests/test_figura_context_checkpoint.py tests/test_figura_history_retrieval.py tests/test_figura_prompting.py`：54 passed。
- 当前全量验证：使用上方记录的离线占位环境执行 `conda run --no-capture-output -n agent python -m pytest -q`：1214 passed（107.98s）。
- `git diff --check` 与 `openspec validate refine-figura-prompts-and-tool-guidance --strict --store figura`：通过。
- 更新 Agent／Runtime 与总览文档。本轮仍未执行真实模型质量评测；主规格已同步，change 尚未归档或提交。
- 按最终要求收敛模型输入：完整 `compaction.md` 只描述当前任务与输出结构，不出现历史版本名；摘要请求 payload 也不再暴露内部 checkpoint 版本。收敛后重跑上述 54 项定向测试，再次通过；OpenSpec strict 与 `git diff --check` 通过。
