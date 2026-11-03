# A09 双面板：避免单位串用：评分表

关键项全部通过才通过，参考图不做像素匹配。

| ID | 关键要求 | 预期 |
|---|---|---|
| panels | 左右面板类型与单位分别正确 | {"left": "bar / 万元", "right": "line / 单"} |
| values | 五个标注值准确 | {"Q1": 18, "Q2": 27, "Jan": 40, "Feb": 35, "Mar": 52} |
| changes | 增量正确且不跨单位相加 | {"sales_change": 9, "orders_change": 12, "can_add": false} |

容差、轮次、证据要求见 answer-key.json。
