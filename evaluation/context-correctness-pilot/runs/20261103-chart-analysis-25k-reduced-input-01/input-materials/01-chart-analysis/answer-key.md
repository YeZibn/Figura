# 图表分析标准答案（评测人员专用）

标准来源：`tests/fixtures/bar_line_evaluation/ground_truth.json`。严禁提供给 Agent。

## 面板一：Quarterly Sales

- 类型：分组柱状图。
- 类别：Q1、Q2、Q3、Q4。
- 纵轴：`Revenue (million USD)`，范围 0—70，主刻度间隔 10。
- Target：40、55、48、62。
- Actual：36、51、45、59。
- `Target - Actual`：4、4、3、3。最大值 Q1/Q2 并列，最小值 Q3/Q4 并列。

## 面板二：Monthly Orders

- 类型：折线图。
- 类别：Jan、Feb、Mar、Apr、May、Jun、Jul。
- 纵轴：`Number of Orders`，范围 0—60，主刻度间隔 10。
- Orders：22、28、25、36、44、41、53。
- Jan 到 Jul 净变化：+31；最低值 Jan=22；最高值 Jul=53。

## 第三轮历史探针

- Q3 Target：48。
- Q3 Actual：45。
- May Orders：44。
- Jul Orders：53。
