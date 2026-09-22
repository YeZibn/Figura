# ChartSpec、面板和生成审核工作流

## 面板与局部证据

拆分结果必须保留 `panel_id`、源 `attachment_id`、source scope、analysis scope、状态、confidence、warnings 和 crop/resource reference。后续测量、OCR 和恢复都通过同一个 `panel_id` 关联；不要重新扫描完整 dashboard 来替代有效的局部范围。

## ChartSpec 组装

当需要结构化图表数据或生成图表时，先收集与请求相关的证据，再调用 `assemble_spec` 作为唯一的 construction-and-validation gate。单个图表使用 `ChartSpec`；同一个 `attachment_id + panel_id` 来源下有多个目标子图时，必须在一次 `figure` 输入中装配为一个 `ChartFigure`；一次运行涉及多个来源时才使用 `figures` 形成 `ChartSpecCollection`。

每个子图必须保留自己的 chart type、类别、数值、系列和标题，不能把多个饼图的类别拼成一个普通饼图。figure 必须明确 `source_series`、`represented_series`、`omitted_series` 和 `status`；`full_source` 遗漏系列不得标记为 `complete`，而 `requested_subset` 只有在明确记录 omitted 系列后才可表示当前任务范围内的 `complete`。不得为了继续生成而静默丢弃。成功只代表对应 ChartSpec/figure 的结构和生成约束有效，不代表图片中的每个数值已经视觉核验。

figure 还必须在有上下文时声明 `coverage.basis`：`full_source`、`requested_subset` 或 `not_applicable`。`requested_subset + complete` 表示当前任务范围内完成，并不表示把 omitted 系列补成零；`full_source` 缺失系列必须保持 incomplete 或被拒绝。集合中的每个 figure 独立携带 `generation_context`，不能把一个 panel 的 scope 或 coverage 传播给另一个 figure。

对于 line/scatter，如果证据中已经确认横轴类别（例如 `Jan`、`Feb`、`Mar`），必须在单图或 figure 子图中把有序类别传入 `x_categories`；`x_label` 只是轴标题，不能替代类别标签。没有可靠类别证据时不要猜测或伪造 `x_categories`，保留数值横轴。

当数据来自测量工具时，先读取结果中的 `measurement.reference`、`measurement.status`、`measurement.evidence.refs`、overlay 和 `measurement.quality.issues`。主 Agent 必须先形成一次明确的 `measurement_decision`，记录当前 attempt 的 `status`（`selected`、`discarded` 或 `abandoned`）、`selected_refs`、`discarded_refs`，必要时补充 `series_map` 与 `evidence_basis`，再在 `assemble_spec` 中原样传入 `measurement_ref` 和该 decision。`accepted` 不是主 Agent 必须伪造或等待的状态；warning 不会自动触发重测。不得手写、复制其他 panel 的 reference，也不得把普通 `source` 文本当作测量来源授权。

首次测量应优先复用已有 `panel_id`，并可在工具参数中提供简单的 `observation_scope`：`coordinate_space` 使用 `panel_norm`、`panel_px` 或 `source_px`，通过 `include`/`exclude` 指定待观察的几何区域和少量 `objectives`。它只限定本次搜索，不创建或替换 measurement session。后续只有在当前 attempt 已暴露不确定 refs 时，才传 `measurement_target` 做定向补充；不要把两种范围字段同时当成同一语义。

局部补充只使用原图表测量工具的 `measurement_target`。优先用当前 attempt 的 compact refs 和 `include`/`exclude` mode；target 必须属于同一 attachment、panel 和 parent attempt。定向调用返回 `focus` 后，检查 `requested`、`applied`、`search_scope` 以及 `focus_empty`/`focus_insufficient`，不得假定工具在失败时自动扩大到完整 panel。一次测量结果只允许一个主 Agent 决策点，代码不会在审核、批处理结束或恢复时偷偷追加测量。测量决策失败时返回可修复的组装错误；不创建 measurement review gate，也不因质量 warning 自动跳过同一批后续工具。

如果 `assemble_spec` 返回错误，读取其定位到的 bounded issues，修改输入、重新观察或重新组装；没有成功组装的 ChartSpec、ChartFigure 或 ChartSpecCollection 不得直接返回为结构化结果，也不得交给 `render_chart`。

## 生成候选与审核

`render_chart` 产生的是 candidate preview，不是已验证或已发布图。生成候选后必须等待代码触发的一次额外、无工具的 VLM review。审核结果中的 `decision`、`confidence`、`checks` 和 `issues` 是系统提供的证据，主 Agent 不得生成、编辑或覆盖审核 JSON。

审核失败但仍有预算时，严格按 `repairKind` 进入有界子循环：`evidence_needed -> 同 scope 的 measurement_target -> measurement_decision -> assemble_spec -> render_chart -> 一次 VLM review`；`spec_only` 只允许修正 ChartSpec；`source_rebind` 先恢复有效 attachment/panel handoff；`terminal` 立即保持未发布。同源 figure 不能只修复并发布其中一张子图。`source_binding_failure` 应恢复或重新选择源证据，不能凭空补数据。重试耗尽时保持未发布并输出有界诊断。

候选、ChartSpec、review result 和 publication status 必须独立关联。`reviewStatus=completed` 不等于通过；只有 `publicationStatus=published` 才能无条件称为已发布，`published_with_warning` 必须保留警告。
