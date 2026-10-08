# 图像反馈观察引导验证

日期：2026-10-08。范围：活动 change `add-figura-image-feedback-guidance` 的图像提示送达、分类、来源关联和恢复行为；不是正式图表审核能力。

## 离线验证

请求测试覆盖原图、OCR 标注、测量标注和生成图；历史重载按资源类型分类。测试检查图像邻近身份、混合调用顺序、原图去重、无图不触发、资产缺失/重复/空段、指令样式资源名、提示身份变化、摘要隔离，以及已有绑定重试与 continuation 关联。确定性 Provider transport 只用于执行合同测试，不能用于宣称模型检查效果。

针对性回归命令：`conda run -n agent python -m pytest -q tests/test_figura_image_feedback.py tests/test_figura_prompting.py tests/test_figura_agent_request.py tests/test_figura_agent_executor.py tests/test_figura_chart_figure_state.py tests/test_figura_history_retrieval.py tests/test_figura_execution_policy.py`，136 项通过。

全量命令 `conda run --no-capture-output -n agent python -m pytest -q`：1230 项通过、35 项失败、1 项跳过。独立 HEAD 归档基线同命令为 1201 项通过、39 项失败、12 项跳过；当前所有失败名称均在基线中，新增失败名称为零。两个新增恢复测试在最终针对性回归中运行；全量测试启动收集时尚未包含这两项。跳过/失败差异涉及旧系统本地 fixture 条件，不据此宣称旧系统问题已修复。

## 真实 Provider 探测

使用 Qwen `qwen3.8-flash`，分别发送类别遗漏关注、图例误检关注、文字布局关注、多图任务继续四种提示与仓库合成图像。四次均为非流式、无工具的独立图像请求，每次一次物理请求；不是真实 Agent Run，也没有植入并标注错误目标。结果见 [安全元数据](image-feedback-provider.json)。

四次均被 Provider 拒绝，HTTP 403，未取得模型响应。因此类别遗漏发现、图例误检识别、遮挡发现以及多图后续决策都**未完成真实行为验证**；不能给出检查准确率或质量提升结论。离线测试证明提示及引用正确进入主流程，不能替代这部分验证。Provider 恢复后应使用明确错误标注及真实 Agent 任务补测。

本报告不保存环境值、端点、密钥、模型原始响应或本机会话事实。
