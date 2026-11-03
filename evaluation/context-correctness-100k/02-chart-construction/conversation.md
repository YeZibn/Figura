# 固定对话脚本：图表构建（100k，30轮）

第 1 轮由运行器把 input/dataset.json 原文嵌入用户消息。之后在同一 Session 按顺序发送，共 30 轮。不要提供答案键或评分表。需要审计的轮次请给出数值和计算，不要只报结论。

## 第 1 轮：建立数据合同

请读取用户消息中的结构化数据，说明四个面板的类型、数据来源、类别轴、系列或矩阵方向、数据点数量及单位。Revenue 覆盖 2024Q1–2026Q4，Orders 面板覆盖 2026 年 12 个月。特别标出 Orders 的一个 null 和 heatmap 的一个 null：它们代表缺失观测，不是数值零。

## 第 2 轮：建立前两个面板

调用 assemble_chart_figure 先建立一个两面板 ChartFigure，包含 Quarterly Revenue 和 Monthly Orders，采用两列布局。保留所有值、类别/系列顺序、标题、source 和 note；保留 Orders 的 March null，不插值。

## 第 3 轮：扩展为四面板 Figure

重新装配完整四面板 ChartFigure，顺序为 Quarterly Revenue、Monthly Orders、Orders by Region and Channel、Delivery Time and Satisfaction；采用两列布局。保留全部 88 个数据位置、两个 null、所有类别/系列顺序、标题、source 和 note。

## 第 4 轮：审计收入面板

列出 North、East、West 在 2024Q1–2026Q4 的收入，并计算 12 个季度的三地区合计。指出 2024Q1 到 2026Q4 合计的变化量和增长率，逐项展示计算所用值。

## 第 5 轮：审计时间序列

列出 Orders 中有多少个月份位置、已观测值有多少。说明 2026-03 的值如何表达；不插值、不填零。计算 2026 年 1 月到 12 月的净变化、观测值均值和极值月份。

## 第 6 轮：审计矩阵和散点

报告 heatmap 的行列顺序、North/Retail 数值和 North/Direct 的缺失状态。报告 scatter 点数、x/y 含义、范围与变化方向，并指出它没有提供足够证据支持因果结论。

## 第 7 轮：更新 Figure 元数据

将整体标题改为 Regional Operations: Revenue, Orders and Delivery，将四个子图的 source 统一保留为数据文件提供的来源；只在 Quarterly Revenue 的 note 中添加 Quarterly revenue values are unchanged.。保留原有的其他 note 和完整数据，重新装配。

## 第 8 轮：局部布局修改

把 Figure 列数从 2 改为 1，按原面板顺序保留四个图表。不要改变任何子图的数据、标题、轴标签或来源。

## 第 9 轮：汇总当前有效合同

汇总当前有效的 Figure 标题、列数、四个面板顺序、2026Q4 收入合计、Orders 的 null 位置，以及 heatmap 的 North/Direct 缺失状态。若已有资源目录列出成功的四面板 ChartFigure，记录它的类型化 ref，不要复制或猜测引用。

## 第 10 轮：年度收入汇总

分别计算 2024、2025、2026 的季度总收入和全年总额；计算 2025 对 2024、2026 对 2025 的年度增幅。列出分子、分母和百分比口径，不把年度总额写成地区单项值。

## 第 11 轮：地区年度汇总

分别汇总 North、East、West 在三个年度的收入，给出每年的地区排名和 2024Q1 到 2026Q4 的变化量。所有结果都要能从原始季度值复算。

## 第 12 轮：Orders 序列统计

重新列出 2026 年 Jan–Dec 序列，按缺失值排除口径计算已观测月份均值、最小值、最大值及 Jan→Dec 净变化。明确不对 March 做插值。

## 第 13 轮：Heatmap 边际核算

按 North、East、West、Central 计算行合计，按 Retail、Web、Partner、Direct 计算列合计。跳过 North/Direct 的 null 并说明总和只含已观测单元格。

## 第 14 轮：Scatter 数据核查

核查 scatter 的 24 个点、x/y 轴含义、两个轴的最小/最大值及整体关联方向。区分相关描述和因果结论，不改写点值。

## 第 15 轮：2026 年收入变化

列出 2026Q1–Q4 的季度收入合计和相邻季度变化量。与 2025 全年总额对照说明 2026 年变化，避免把季度与年度指标直接混为一谈。

## 第 16 轮：结构完整性审计

检查四类 ChartSpec 的数据形状、所有系列/行列顺序、88 个数据位置和两个 null。报告哪些值必须原样保留、哪些位置是缺失观测。

## 第 17 轮：候选布局方案

我想评估一个候选方案：将 Figure 改为两列，并把 Monthly Orders 放到第一位、其余面板保持相对顺序。先只记录为候选，不要应用；说明当前实际生效的标题、列数和顺序。

## 第 18 轮：撤销候选布局

明确撤销上一轮的两列及重新排序候选。最终仍保持一列和原面板顺序；不要改变任何子图数据或元数据。

## 第 19 轮：季度收入增幅

列出 12 个季度收入合计，并计算每一相邻季度的绝对变化。标明变化为收入金额，不要把它与百分比增长混淆。

## 第 20 轮：年度地区排名复核

用表格列出 2024、2025、2026 三年 North、East、West 的收入总额，并确认三个年度的地区排名是否一致。不要改动 Figure 数据。

## 第 21 轮：Orders 月度变化复核

按月份列出相邻已观测点变化；对 March 缺失两侧的区间明确写“无法从缺失月份计算相邻变化”，不要把 April 与 February 当作相邻月份。

## 第 22 轮：Heatmap 排名复核

根据原矩阵列出每个地区/渠道的已观测总量排名，并指出 North/Direct 缺失意味着不能把 Direct 列总计当作完整总量。

## 第 23 轮：轴与单位审计

逐面板核对类别轴、数值轴或矩阵坐标、轴标签和单位。确认订单 count、收入 M USD、满意度 score、配送小时数没有互换。

## 第 24 轮：元数据保留审计

逐一核对 Figure title、每张 ChartSpec title、source 和 note。确认只给 Quarterly Revenue 追加指定 note，其他原有 note 与来源全部保留。

## 第 25 轮：Figure 结构审计

列出四个 chart_id、图表类型和次序，确认单列布局且只有一个四面板 ChartFigure 作为最终交付。不要把第 2 轮的两面板中间产物当作最终 Figure。

## 第 26 轮：缺失值语义审计

分别解释 Monthly Orders 2026-03 和 heatmap North/Direct 的缺失状态。说明为何填零或插值都会改变原始数据。

## 第 27 轮：完整数据合同台账

按每个面板给出完整数据行数/点数、类别次序、系列/矩阵方向及 null 位置。列出 88 个数据位置的完整性核查结果。

## 第 28 轮：最终 Figure 复核

重述最终 Figure 标题、列数、四面板顺序、元数据变更和关键派生数值。候选两列和重排必须保持撤销。

## 第 29 轮：压缩后读取与核对

使用当前资源目录中成功四面板 ChartFigure 的完整 ref 直接调用 read_history 读取 Figure。核对 North 的 2025Q4 Revenue、2026-03 Orders 和 North/Direct cell；不得把缺失值改成零或插值。不要先搜索历史。

## 第 30 轮：最终渲染和交付

按第 7–29 轮最后确认的合同重新装配并调用 render_chart_figure。交付 PNG 和简明 ChartSpec 摘要，并检查四面板顺序、一列布局、数据完整性、null 语义、标题、来源和备注。
