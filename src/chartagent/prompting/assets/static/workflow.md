# ChartSpec、面板和生成图工作流

## 面板与局部证据

拆分结果要保留 `panel_id`、源 `attachment_id`、source scope、analysis scope、状态、confidence、warnings 和 crop/resource reference。后续测量、OCR 和恢复沿用同一个 `panel_id`；不要重新扫描整张 dashboard 替代有效局部范围。

## ChartSpec 组装

需要结构化图表数据或生成图表时，先收集相关证据，再调用 `assemble_spec`。单图使用 `ChartSpec`；同一 `attachment_id + panel_id` 下多个目标子图使用一个 `ChartFigure`；一次任务涉及多个来源时才使用 `ChartSpecCollection`。

figure 保留每个子图自己的类型、类别、数值、系列和标题。明确 `source_series`、`represented_series`、`omitted_series` 和 `status`。`full_source` 遗漏系列不得标记为 `complete`；`requested_subset` 只有明确记录省略系列后才表示当前任务范围完成。集合中的每个 figure 独立携带 `generation_context`。

对于 line/scatter，证据已确认横轴类别时，把有序类别传入 `x_categories`；`x_label` 是轴标题，不能替代类别。没有可靠类别证据时不要猜测。

当数据来自测量工具时，读取 `measurement.reference`、`measurement.status`、`measurement.evidence.refs`、overlay 和 `measurement.quality.issues`。主 Agent 判断采用哪些候选；使用时传入服务端返回的 `measurement_ref` 和实际依赖的 `evidence_refs`。warning 不自动触发重测或阻止其他操作。

首次测量可传 `observation_scope` 限定 panel 内搜索区域。后续定向补充使用同一工具的 `measurement_target`，并检查返回的 `focus`、`requested`、`applied` 和 `search_scope`。不得跨 attachment、panel 或 parent attempt 扩大范围。

`assemble_spec` 返回错误时，按有界 issues 修改输入、重新观察或重新组装。未成功组装的 ChartSpec、ChartFigure 或 ChartSpecCollection 不能交给 `render_chart`。

## 生成图验证与发布

`render_chart` 产生暂存图。系统为每张图保存有界 manifest，绑定确切图像字节、ChartSpec 摘要、来源 attachment/panel/revision、generation context、figure/collection 和策略版本。

系统执行确定性结构、编码和渲染检查；源图关联或策略要求时，自动执行一次无工具 VLM 检查。验证状态为 `pass`、`pass_with_warning`、`fail` 或 `unavailable`。VLM 只返回 `decision`、`confidence`、六项固定 `checks` 和有界 `issues`。

只有匹配 manifest 的 `pass`，或策略允许 warning 时的 `pass_with_warning`，才能产生正式 artifact。失败图可用于诊断预览，不能下载为正式图表。每张 collection 子图保留独立 manifest、issues、验证和发布结果。

验证诊断交给主 Agent 选择新的观察、修改 ChartSpec、重新生成或结束。每次重新生成使用新的暂存身份；最终回答中的 artifact 引用必须存在于已提交的发布结果中。
