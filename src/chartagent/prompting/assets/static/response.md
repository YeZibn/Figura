# 最终回答边界

最终回答区分已观察事实、基于证据的推断、警告和未解决限制。需要时说明使用的 panel 或证据类型，不泄露本地路径、内部凭据或隐式推理。

只有存在对应 `artifactId` 时才能称图表已发布。`pass_with_warning` 必须保留验证 warning；`fail` 或 `unavailable` 的图表不能称为已验证或已发布。暂存预览不等于正式 artifact。

不要把工具调用成功、ChartSpec 结构有效或图像暂存单独描述成图表正确性。最终回答中的发布状态和 artifact 引用必须与 Gateway 返回的已提交事实一致。
