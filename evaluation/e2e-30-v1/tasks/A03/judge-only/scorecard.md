# A03 堆叠柱：分项和总量：评分表

关键项全部通过才通过，参考图不做像素匹配。

| ID | 关键要求 | 预期 |
|---|---|---|
| structure | 识别堆叠柱及单位 | {"type": "stacked bar", "unit": "万元"} |
| parts | 正确读取全部标注分项 | {"Product": [8, 12, 10, 15], "Service": [5, 7, 9, 6]} |
| totals | 总量与极值正确 | {"totals": [13, 19, 19, 21], "max": "Q4"} |
| share | Q3 Service / Q3 总量，百分数 | 47.36842105263158 |

容差、轮次、证据要求见 answer-key.json。
