# A02 分组柱：系列关联与差值：评分表

关键项全部通过才通过，参考图不做像素匹配。

| ID | 关键要求 | 预期 |
|---|---|---|
| structure | 分组柱、两个系列、季度顺序与单位正确 | {"type": "grouped bar", "categories": ["Q1", "Q2", "Q3", "Q4"], "unit": "万元"} |
| values | 八个标注数值与系列关联正确 | {"North": [14, 22, 18, 30], "South": [10, 16, 21, 25]} |
| difference | 差值和更高季度正确 | {"difference": [4, 6, -3, 5], "south_higher": ["Q3"]} |

容差、轮次、证据要求见 answer-key.json。
