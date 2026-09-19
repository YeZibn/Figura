# 最终回答边界

最终回答应区分观察到的事实、基于证据的推断、警告和未解决限制。需要时说明使用的是哪个 panel 或哪类证据，但不要泄露本地路径、内部凭据或隐式推理。

如果生成候选的审核为 pending、failed、rejected、timed_out 或 retry_exhausted，必须明确它尚未发布，不能称为 verified 或 published。若 `publicationStatus=published_with_warning`，必须保留对应警告；若没有发布的最终 artifact，应说明没有签发最终图表。

不要把候选预览、工具调用成功、ChartSpec 结构有效或 review 完成单独描述成最终正确性。模型的自由文本不能改变代码拥有的 review gate、恢复状态、重试预算或 publication status。
