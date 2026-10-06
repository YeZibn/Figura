## 1. 固定提示词整体改写

- [x] 1.1 重写 `agent.md`，明确多目标理解、必要动作、当前用户要求与历史偏好／更正的关系，保留模型自主选择工具的职责。
- [x] 1.2 重写 `evidence.md`，集中解释信息来源、OCR available／空结果／截断、测量质量与字段有效性、局部观察、坐标和数值边界。
- [x] 1.3 重写 `workflow.md`，补齐按需历史读取、针对性观察、完整 Figure 修改、参数错误修正、生成图回看与任务结束路径，去除强制重复动作的歧义。
- [x] 1.4 重写 `response.md`，明确按目标交付、近似值与未知值、描述性新标签、完成阶段和必要限制，避免把内部编排当作用户流程。
- [x] 1.5 对四份资产及动态工具／摘要／资源指令做七类场景审校并去重，保持普通加载顺序和来源边界；记录审校结果，不以逐句字符串测试声称模型行为已验证。

## 2. 工具描述与原生参数说明

- [x] 2.1 审校 `load_image`、`decompose_chart_image` 的 description 与参数注释，说明授权来源、图像附加时点、两种工具的选择关系、分割坐标和独立 Panel 坐标。
- [x] 2.2 审校 `search_history`、`read_history`、`read_resource_image` 的 description 与参数注释，说明文本匹配、异常调用状态、分页查询一致性、完整资源内容与图像读取分工。
- [x] 2.3 在共享 `measurement_schema.py` 补齐 source_kind/source_id 与 observation_scope 的坐标、点格式、include/exclude、默认范围和有效像素规则，不改既有坐标映射公式。
- [x] 2.4 审校 `extract_text` 和四种 `measure_*` 的 description，准确说明主要返回内容、校准、采样／可见性、缺失与限制、成功批次标注图反馈，不引入自动失败重试。
- [x] 2.5 审校 `assemble_chart_figure`、`render_chart_figure` 的 description 与引用参数，说明完整新 Figure、返回引用、measurement_refs 校验边界和嵌套 figure_ref 格式。
- [x] 2.6 在 Charts 原生 Schema 补齐 bar/pie 与 line/scatter 数据点形状、类别折线位置、递增顺序和现有类别覆盖／系列关系语义；保留原字段、默认值和 validator 行为。
- [x] 2.7 增加关键参数说明经过 Provider 投影保留、Registry 与 SYSTEM 工具目录一致的合同测试，验证全部 12 个工具的顺序与原有合法调用可用。

## 3. 历史图像引用与局部读取合同

- [x] 3.1 为历史图像工具建立专用参数／结果引用 Schema，仅包含 attachment、panel、ocr、measurement、chart_render；保留 search/read 的通用引用与底层授权校验。
- [x] 3.2 在 `test_figura_history_retrieval.py` 验证合法图像引用，以及 message/tool_result/chart_figure 在 handler 前被拒绝；验证 read_history 仍能读取完整 Figure 与原工具结果。
- [x] 3.3 验证 content-relative field_path、字符串／数组 0-based 起始包含和结束排除的切片、对象切片错误与游标筛选一致性，补充必要回归用例。

## 4. 独立压缩提示词资产

- [x] 4.1 新增 `assets/compaction.md`，写明保留优先级、旧摘要增量合并、更正／计划／事实区分、不可信历史边界，以及 message/tool_result 引用和严格 v2 分层输出。
- [x] 4.2 在 prompting loader 提供独立 `build_compaction_instruction()` 并接入 `build_summary_request()`；移除内嵌摘要字符串，保持来源 JSON 与纯文本无工具请求，升级 v2 输出校验。
- [x] 4.3 为缺失／空摘要资产保留明确加载错误，在摘要准备边界映射到既有 invalid_summary_input fallback；验证没有空指令请求、硬编码回退或 checkpoint 覆盖。
- [x] 4.4 验证普通请求不加载 compaction 的 JSON-only 指令、摘要请求无图像／无工具、新资产可通过包资源读取；摘要 prompt 不要求模型计算最终占比。
- [x] 4.5 运行／补齐摘要增量来源校验、原历史 fallback、同一请求重试与恢复身份测试，确认资产变化使 digest 变化且不绕过已有绑定检查。
- [x] 4.6 把 v2 摘要合同固定为目标、约束、决定、事实、进度状态、未决问题、资源及未接受提议分组；每个条目都必须有授权来源引用，用户未接受的建议不得变成待办。
- [x] 4.7 将 summary contract 与 request registry identity 升为 v2；兼容读取已有 checkpoint，但不向摘要模型暴露存储版本，并在下一次摘要时按来源迁移到 v2，不做数据库迁移。

## 5. 透明图像观察解码修复

- [x] 5.1 在共享 decode_scoped_image 实现白底 alpha 合成、alpha>0 固有可见 mask、与显式 scope 相交，以及不透明且未传 scope 的原有快路径；不修改源 bytes、尺寸与坐标。
- [x] 5.2 处理无有效像素分支：显式 scope 空交集返回 invalid_observation_scope；无 scope 全透明返回 image_unavailable，确认检测器未被调用。
- [x] 5.3 在 `test_figura_observation_scope.py` 覆盖隐藏 RGB 不影响结果、部分透明合成颜色、范围与 alpha 交集、尺寸保留、全透明错误和不透明输入回归。
- [x] 5.4 增加真实 Panel crop 与 OCR 整框过滤回归，使用确定的候选／几何 fixture 验证五个观察适配器均消费有效可见输入，并验证标注底图白底 alpha 合成，不把模型或 OCR 识别随机性作为核心断言。

## 6. 版本、文档与最终验证

- [x] 6.1 将 bootstrap Registry 升为 figura-web-v8，更新相关期望；验证旧版本完整交互仍是只读历史，未完成调用和已绑定身份不匹配仍沿现有受控路径处理。
- [x] 6.2 对照实现更新 overview 与 Agent／Tools／Memory／Sources 的相关内容，说明五份资产分工、完整 Figure 取回、工具语义、透明观察和 Registry 升级；清理 Agent 专题重复职责表。
- [x] 6.3 在 agent 环境先运行 prompting、context_compaction、history_retrieval、observation_scope、observation_tools、panel_tools、Agent／Figure 流程相关窄测试，修复与本 change 有关的问题。
- [x] 6.4 运行 `conda run -n agent python -m pytest -q`、`git diff --check` 及该 change 的 OpenSpec strict 验证；报告真实模型评估是否执行，不将结构／单元测试当作模型质量证明。
- [x] 6.5 增加 v2 分组／字段／来源拒绝用例、v1 增量迁移输入、checkpoint v2 写入及旧 checkpoint 可读回归；更新 Agent／Runtime 文档并重新运行相关与完整验证。
