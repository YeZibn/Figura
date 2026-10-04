## 1. 统一估算和模型配置

- [x] 1.1 声明 tiktoken 直接依赖，确定兼容版本范围，准备 o200k_base 缓存与初始化路径，验证资源缺失时无请求路径下载且估算可禁用。
- [x] 1.2 ProviderProfile 增加可选 context_window_tokens，解析 FIGURA_<PROVIDER>_CONTEXT_WINDOW_TOKENS；覆盖正整数、空值和非法值，保持 availability 不受影响。
- [x] 1.3 实现 messages/tools 的确定性输入投影与 encode_ordinary 分词；排除传输和生成配置，并保留实际 tool-call 关联字段和 continuation。
- [x] 1.4 实现图片节点替换及每次出现 1,024 tokens 的统一近似，固定 estimator_version=tiktoken-o200k-v1，确保不分词 URL/base64、不重复读取图片。
- [x] 1.5 在 Provider prepare 接入私有可选估算元数据，支持重试跳过估算；验证估算不改变 payload、descriptor 指纹、options、manifest 和 dispatch 行为。
- [x] 1.6 添加估算与 Provider 回归测试：中文、英文、代码、JSON、工具 Schema、特殊 token 字符串、真实 continuation、重复图片、未发送资源、失败降级和超过容量继续执行。

## 2. Durable 请求快照与旧版本兼容

- [x] 2.1 新增不可变 ContextEstimate 值对象与 ProviderRequestBinding 可选字段；实现 binding v2 精确校验，支持 null、未知容量并拒绝非法数字。
- [x] 2.2 保留 binding v1 的原键集合、原序列化结果和读取语义；用真实旧 payload 验证 encode/decode 字节级往返，不自动升级或补算。
- [x] 2.3 首次 claim 将 prepared estimate 与 binding/attempt 一起持久化；重试和恢复复用原快照，保留旧版本 binding 与全部现有指纹和 claim 检查。
- [x] 2.4 添加 Runtime/Executor 回归覆盖：原子提交、失败后可读、多个逻辑请求、重试不累加、重启恢复、配置变化不改旧快照、v1 重试兼容。

## 3. Gateway 安全摘要与生命周期更新

- [x] 3.1 Run summary 从最新 base_record_sequence 的 binding 投影 contextUsage，只暴露 inputTokens 和 nullable contextWindowTokens；最新无估算时不退回旧值。
- [x] 3.2 验证 Session/history 读取不构造请求、加载图片或调用 tokenizer；确认摘要不泄漏 continuation、原文、URL、图片、指纹或私有 binding 元数据。
- [x] 3.3 接入首次 claim 后既有进度通知与 history compensation，确保模型等待期间可见快照，保持唯一生命周期 owner 和原 SSE 序号身份。
- [x] 3.4 添加 Gateway 回归测试：Run handle 缺省字段、首次绑定可见、Provider 失败、刷新恢复、legacy 无值、最新 binding 无值和原 HTTP/SSE 合同。

## 4. 前端上下文占比

- [x] 4.1 扩展 Figura DTO、共享 RunSummary 与 workspace 适配，保留兼容 façade，确保旧 DTO 和其他 client 模式支持缺省 contextUsage。
- [x] 4.2 在输入区增加轻量上下文指示器，选择 active Run 或 ordinal 最新 Run，展示估算 token、已知容量百分比、未知容量和待估算状态。
- [x] 4.3 实现原模型详情、最近请求口径、Provider 切换保留原分母、百分比超过 100% 和正数小于 1% 的显示；不增加独立轮询或提交限制。
- [x] 4.4 扩展 frontend smoke 覆盖新 Run 待估算、连续请求替换、重试稳定、历史刷新、缺省 DTO、模型切换和超容量展示。

## 5. 文档与验证

- [x] 5.1 更新 .env.example 及相关使用/实现说明，写明编码缓存准备、可选容量、图像近似、最近请求口径、v1 兼容和升级后数据回滚边界。
- [x] 5.2 在 agent Conda 环境先运行新增估算测试与 tests/test_figura_provider.py、tests/test_figura_provider_attempts.py、tests/test_figura_agent_executor.py、tests/test_figura_gateway.py 的相关窄测试，再运行 conda run -n agent python -m pytest -q。
- [x] 5.3 在 frontend 执行 npm run build 和 npm run smoke，并确认模型等待、失败与刷新时指示器实际可见；若改动 launcher，再执行 npm run smoke:launcher。
- [x] 5.4 运行 openspec validate add-local-context-token-estimation --store figura --strict 和 git diff --check，确认没有引入预算、输出限制、裁断或压缩行为。

## 6. 验证记录

- 新增 `tests/test_figura_context_estimation.py`：23 passed。
- 相关 Provider / attempt / Executor / retry policy / Gateway 窄测试：148 passed。
- 默认环境全量：1120 passed、8 failed；失败均为旧 ChartAgent 默认 Provider 缺少可用配置，发生于 FakeRuntime 之前。
- 使用进程级测试占位配置（CHARTAGENT_PROVIDER=openai、OPENAI_API_KEY=local-test-key、OPENAI_MODEL=test-model、OPENAI_BASE_URL=https://example.test/v1）运行全量：1128 passed；没有修改用户 .env 或旧 ChartAgent 实现。
- 前端 `npm run build`、`npm run smoke` 通过；新增 context smoke 验证 DTO 映射、既有 controller 更新、失败/刷新、重试稳定、原模型身份、旧 DTO、超容量与真实组件渲染。
- 使用本地组件预览在浏览器验证折叠占比、展开数字/模型说明和进度条；临时页面及服务器已关闭。未进行真实付费模型调用。
- OpenSpec strict 校验与 git diff --check 通过。未改动 Gateway launcher，无需额外 launcher lifecycle 测试。
