# ChartSpec、面板和生成审核工作流

## 面板与局部证据

拆分结果必须保留 `panel_id`、源 `attachment_id`、source scope、analysis scope、状态、confidence、warnings 和 crop/resource reference。后续测量、OCR 和恢复都通过同一个 `panel_id` 关联；不要重新扫描完整 dashboard 来替代有效的局部范围。

## ChartSpec 组装

当需要结构化图表数据或生成图表时，先收集与请求相关的证据，再调用 `assemble_spec` 作为唯一的 construction-and-validation gate。成功只代表 ChartSpec 结构和生成约束有效，不代表图片中的每个数值已经视觉核验。

如果 `assemble_spec` 返回错误，读取其定位到的 bounded issues，修改输入、重新观察或重新组装；没有成功组装的 ChartSpec 不得直接返回为结构化结果，也不得交给 `render_chart`。

## 生成候选与审核

`render_chart` 产生的是 candidate preview，不是已验证或已发布图。生成候选后必须等待代码触发的一次额外、无工具的 VLM review。审核结果中的 `decision`、`confidence`、`checks` 和 `issues` 是系统提供的证据，主 Agent 不得生成、编辑或覆盖审核 JSON。

审核失败但仍有预算时，根据 issue 的 code、location 和 severity 修正 ChartSpec，重新调用 `assemble_spec`，再生成并审核新的候选。`source_binding_failure` 应恢复或重新选择源证据，不能凭空补数据。重试耗尽时保持未发布并输出有界诊断。

候选、ChartSpec、review result 和 publication status 必须独立关联。`reviewStatus=completed` 不等于通过；只有 `publicationStatus=published` 才能无条件称为已发布，`published_with_warning` 必须保留警告。
