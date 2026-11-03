# A05 折线缺失：未知不等于零：评分表

关键项全部通过才通过，参考图不做像素匹配。

| ID | 关键要求 | 预期 |
|---|---|---|
| values | 四个标注已知值准确 | ["Mon=12", "Tue=19", "Thu=17", "Fri=26"] |
| missing | Wed 为缺失/null，不能当作零或推断为 18 | "Wed=null" |
| summary | 净变化和已知最大值正确 | {"net_change": 14, "max": "Fri=26"} |

容差、轮次、证据要求见 answer-key.json。
