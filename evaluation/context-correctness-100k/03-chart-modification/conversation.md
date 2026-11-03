# 固定对话脚本：图表修改（100k，34轮）

只在第 1 轮附加 input/quarterly-regional-sales.png。在同一 Session 按顺序发送 34 轮，不给 Agent 提供答案键或评分表。每轮说明当前有效状态与本轮变化，避免将候选修改误当成已应用修改。

## 第 1 轮：读图并建立初始 Figure

读取三个面板的标题、图表类型、轴标签、系列/类别和值。所有数值都在图上标注。调用 assemble_chart_figure 建立初始 Figure，按图中从上到下的顺序排列，采用两列布局；Figure 标题使用 Regional Operations Dashboard, 2025，子图 source 使用 Figura synthetic operations dataset。

## 第 2 轮：局部修改目标

将 Monthly Orders 面板的标题改为 Monthly Orders (Corrected)，轴标签改为 Orders (count)；其他两个面板及全部数据保持不变。重新装配完整 Figure。

## 第 3 轮：临时方案

我想评估一个候选方案：把 Figure 改成单列，并把 Monthly Conversion Rate 放到第一位。先只记录为候选，不要应用；说明当前仍生效的布局和面板顺序。

## 第 4 轮：撤销候选方案

明确撤销上一轮的单列与重排方案。保持两列布局和原面板顺序。说明这两项候选改动都不应出现在最终 Figure。

## 第 5 轮：应用有依据的数据修订

核实订单台账后，确认 July Orders 应为 109，而图上原始读取值为 105。只将 Monthly Orders 的 July 从 105 更新为 109；在该面板 note 中记录 July corrected from the source ledger.。不要把源图读数 105 从历史事实中抹去，也不要修改其他月份。

## 第 6 轮：应用整体标题

将 Figure 标题改为 2025 Regional Sales and Operations (Revised)。保持最终列数为 2，保持图表顺序为 Quarterly Revenue、Monthly Orders、Monthly Conversion Rate。

## 第 7 轮：当前状态清单

逐项区分当前有效修改、已撤销候选、原始图像读数、用户确认的修订值。列出 Orders 的 June、July、August 值，并说明 July 最终值与原图值为何不同。

## 第 8 轮：明确保持项

最终要求：只更新 Monthly Orders 的 July 值、标题、轴标签与 note，以及 Figure 总标题；Quarterly Revenue 和 Monthly Conversion Rate 必须与初始 Figure 完全相同。不要重新解释数据，也不要应用候选布局。

## 第 9 轮：季度收入核算

按季度计算三地区收入合计，给出 Q4 相对 Q1 的总额变化及每个地区的变化量。列出用于计算的原始值。

## 第 10 轮：订单序列核查

完整列出源图中的 Jan–Dec Orders 序列，标记原图最大值、最小值、Jan→Dec 净变化。明确 July 的 105 是原图值，不是后续台账修订值。

## 第 11 轮：转化率核查

完整列出 Jan–Dec Conversion (%)，计算最高/最低月份及 Jan→Dec 百分点变化。确认本轮不应修改转化率子图。

## 第 12 轮：收入面板差异检查

逐系列核对 Quarterly Revenue 的四季度数据与初始 Figure，确认本轮数值、标题、source、note、轴标签均无变化。

## 第 13 轮：修订影响量

比较 July=105 的源图序列和 July=109 的修订序列。计算修订差值、全年月均 Orders 的变化、Q3 月均 Orders 的变化；说明除 July 外其他月份保持原值。

## 第 14 轮：当前图表状态

汇总 Figure 标题、列数、顺序和三个子图的标题、轴标签、source、note。特别核查目标面板是否同时保留用户修订来源和其他原有元数据。

## 第 15 轮：目标与非目标内容审计

以字段清单比较：Monthly Orders 允许修改的字段和 July 值；Quarterly Revenue 与 Monthly Conversion Rate 的字段和值必须保持不变。逐项报告通过或发现的偏差。

## 第 16 轮：候选修改复核

再次检查早先的单列/重排候选。报告其状态为已撤销；不得通过重新装配把候选重新写入 Figure。

## 第 17 轮：最终 ChartSpec 台账

列出最终三个子图的完整类别和序列值，区分源图 July=105 与最终 July=109；同时列出所有生效的标题、轴标签、source 和 note。

## 第 18 轮：渲染前审计

在渲染前核对 Figure 总标题、两列布局、面板顺序、三个子图数据、source/note 和修订来源。确认目标外图表没有变化。

## 第 19 轮：初始与当前 Figure 对照

逐项对比初始 Figure 与当前有效 Figure 的结构。报告 Figure 标题、列数、面板顺序、目标子图标题和 y 轴标签；明确哪些字段发生变化、哪些不变。

## 第 20 轮：源图收入复算

重新列出四季度三地区收入值和季度总额；复核 North Q4=50。说明收入面板从建立 Figure 后一直不属于本次修改范围。

## 第 21 轮：订单原值与修订值台账

列出 12 个月 source 值与最终值的逐月对照，只允许 July 两列不同。对每个差异给出用户依据或说明无差异。

## 第 22 轮：修订幅度核算

计算 July 从 105 到 109 的绝对变化与相对变化，并核查全年合计、全年月均及 Q3 月均变化。避免将相对百分比写成百分点。

## 第 23 轮：Conversion 完整性复算

列出转化率 12 个值、最小/最大及 Jan→Dec 百分点差。再次确认最终 Figure 中该子图数据和元数据没有变化。

## 第 24 轮：布局与顺序复核

描述两列 Figure 的实际面板位置。确认 Quarterly Revenue 在首位、Monthly Orders 第二、Monthly Conversion Rate 第三；右下空格来自三面板放入两列布局。

## 第 25 轮：最终字段白名单

列出允许变化的字段：Figure title、Monthly Orders title、Monthly Orders y 轴 label、July Orders、Monthly Orders note。对所有其他字段声明保留初始值，并在 Figure 上逐项核对。

## 第 26 轮：变更来源复核

分别说明源图读取、用户台账确认、模型计算和图表渲染各自支持什么事实。不能把渲染成功作为数据正确的证明。

## 第 27 轮：订单统计口径核查

分别用源图序列与修订序列计算总和及月均值，验证两个口径只差 4 单和 1/3 单每月。列出使用的总和与分母。

## 第 28 轮：序列映射核查

按 Jan–Dec 顺序逐项确认订单折线横轴映射，特别核对 June、July、August 三个点；不得把 July 修订移到相邻月份。

## 第 29 轮：目标子图元数据核查

准确列出 Monthly Orders 的 chart_id、title、图表类型、x/y 轴标签、source、note 和系列 label。只对本轮允许修改的字段作变更。

## 第 30 轮：非目标子图逐字段审计

分别列出 Quarterly Revenue 与 Monthly Conversion Rate 的标题、图表类型、轴标签、source、note、类别和全部值，并对照初始 Figure 声明是否一致。

## 第 31 轮：最终重组前状态报告

汇总此刻有效的所有字段和值、已撤销候选、源图 July=105 与修订后 July=109。不要新增修改；说明即将重组的 Figure 合同。

## 第 32 轮：完整交付草稿

生成最终 ChartSpec 摘要草稿，包含三个面板全量序列数据、Figure 标题/列数/顺序、修订来源和非目标字段保留说明。不得遗漏图表标签。

## 第 33 轮：压缩后读取基准 Figure

使用资源目录中原始初始 ChartFigure 的完整类型化 ref 直接调用 read_history。根据目录线索选择修改前、Orders July 仍为 105 的 Figure；核对 Quarterly Revenue 的 North Q4、Monthly Orders 的 June/July/August 原始值和 December Conversion。不要先搜索历史，不要混用摘要的 message/tool-result 引用。

## 第 34 轮：最终重组、渲染和差异审计

基于有效合同重新装配并渲染最终结果。交付 ChartSpec 摘要和 PNG；列出最终保留的面板顺序/布局、July 修订及其来源，并明确确认临时单列/重排没有残留，两个非目标面板和其他订单月份未被修改。
