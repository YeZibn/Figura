# 图表构建标准答案（评测人员专用）

参考输入：`input/dataset.json`。严禁提供给 Agent。

## 最终合同

- 一个 Figure，两个面板，一行两列；Quarterly Sales 在左，Monthly Orders 在右。
- 总标题：`季度销售与月度订单`。
- 左面板为分组柱状图：类别 Q1、Q2、Q3、Q4；Target=[40,55,48,62]；Actual=[36,51,45,59]；纵轴 `Revenue (million USD)`；范围 0—70，步长 10。
- 右面板为折线图：类别 Jan、Feb、Mar、Apr、May、Jun、Jul；Orders=[22,28,25,36,44,41,53]；纵轴 `Number of Orders`；范围 0—60，步长 10。
- 不得合并面板、改变数据、改变类别顺序、归一化、插值或补造数据。

## 第三轮历史探针

- Q3 Target=48。
- Q3 Actual=45。
- Jul Orders=53。
