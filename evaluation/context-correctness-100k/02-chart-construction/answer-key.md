# 图表构建答案键（评测人员专用）

## 初始数据事实

- Quarterly Revenue 是 grouped vertical bar，12 个类别依次为 24Q1–24Q4、25Q1–25Q4、26Q1–26Q4；纵轴 Revenue (M USD)。
  - North: 41, 44, 46, 49, 52, 55, 58, 62, 65, 68, 72, 75
  - East: 35, 38, 40, 43, 46, 50, 52, 56, 59, 62, 65, 69
  - West: 28, 30, 34, 36, 39, 42, 44, 47, 50, 53, 56, 60
  - 季度合计：104、112、120、128、137、147、154、165、174、183、193、204；2026Q4−2024Q1=100，增长率约 96.15%。
  - 年度总额：2024=464，2025=603，2026=754；2025 对 2024 增长约 29.96%，2026 对 2025 增长约 25.04%。
  - 地区年度合计：North=180/227/280，East=156/204/255，West=128/172/219（依次为 2024/2025/2026）。
- Monthly Orders 是 line，2026 年 Jan–Dec 共 12 个有序位置；Mar 的 y 是 null，不是 0 或插值；11 个月有观测。Jan→Dec 净变化 +60；观测均值约 198.45；最小 Jan=168，最大 Dec=228。
- Orders heatmap 的列顺序 Retail/Web/Partner/Direct，行顺序 North/East/West/Central；North/Retail=12，North/Direct=null。
  - 行合计：North=37、East=47、West=45、Central=38。
  - 列合计：Retail=37、Web=48、Partner=44、Direct=38；总和只包含已观测的 15 个单元格，合计 167。
- Delivery scatter 为 24 点，x 是 Delivery time (hours)，y 是 Satisfaction (score)；x 范围 1.1–5.7，y 范围 2.4–4.7；总体为负向关联，不能表述为因果。

## 最终 Figure 合同

- 整体标题：Regional Operations: Revenue, Orders and Delivery
- layout.columns=1；四个 chart_id 和初始顺序不变。
- Quarterly Revenue 的 note 精确追加 Quarterly revenue values are unchanged.；其他子图 note 不得被清除或覆盖；四个 source 不变。
- 两个 null 位置必须保留：Monthly Orders 2026-03 的 y；heatmap North/Direct 的 cell。
- 第 19 轮读取值：North 2025Q4 Revenue=62；2026-03 Orders=null；North/Direct=null。
- 临时两列/重排方案已撤销，不进入最终状态。
