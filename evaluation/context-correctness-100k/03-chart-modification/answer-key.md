# 图表修改答案键（评测人员专用）

## 初始图像事实

1. Quarterly Revenue by Region；grouped vertical bar；Revenue (M USD)；Q1–Q4。
   - North: 34, 39, 43, 50
   - South: 27, 32, 36, 41
   - Central: 22, 26, 31, 35
   - 季度总额：83、97、110、126；Q4−Q1=43；地区变化 North +16、South +14、Central +13。
2. Monthly Orders；line；初始轴标签 Orders；Jan–Dec：82, 90, 87, 95, 101, 108, 105, 115, 123, 119, 130, 138。
   - 原图最小 Jan=82，最大 Dec=138，Jan→Dec 净变化 +56。
3. Monthly Conversion Rate；line；Conversion (%)；Jan–Dec：2.4, 2.6, 2.5, 2.8, 3.0, 3.1, 3.0, 3.3, 3.4, 3.2, 3.6, 3.8。
   - 最小 Jan=2.4%，最大 Dec=3.8%，Jan→Dec 增加 1.4 个百分点。

## 最终有效状态

- Figure title：2025 Regional Sales and Operations (Revised)。
- layout.columns=2；图表顺序仍为 Quarterly Revenue、Monthly Orders、Monthly Conversion Rate。
- Monthly Orders metadata title=Monthly Orders (Corrected)；y-axis label 从 Orders 更新为 Orders (count)；note 包含 July corrected from the source ledger.。
- July Orders 最终值=109；原图读数=105；修订差值 +4，来源是第 5 轮用户明确提供的台账修订。
- 除 July 外的其他 11 个月不变；全年月均值由 107.75 变为 108.08，增加 1/3；Q3 月均值由 114.33 变为 115.67。
- Quarterly Revenue 和 Monthly Conversion Rate 的所有字段与初始 Figure 一致。
- 第 19 轮基准读取：North Q4 Revenue=50；原始 Orders June/July/August=108/105/115；December Conversion=3.8%。
- 第 3 轮候选的单列布局和面板重排已撤销，最终均不生效。

## 三面板原始数据

- Quarterly Revenue: North 34,39,43,50；South 27,32,36,41；Central 22,26,31,35。
- Monthly Orders source values: 82,90,87,95,101,108,105,115,123,119,130,138。
- Monthly Conversion: 2.4,2.6,2.5,2.8,3.0,3.1,3.0,3.3,3.4,3.2,3.6,3.8。
