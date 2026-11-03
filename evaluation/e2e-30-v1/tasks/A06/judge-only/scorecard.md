# A06 环图：占比与标签关联：评分表

关键项全部通过才通过，参考图不做像素匹配。

| ID | 关键要求 | 预期 |
|---|---|---|
| type | 正确识别环图 | "donut" |
| shares | 四个标签与标注百分比准确关联 | {"Online": 40, "Store": 30, "Partner": 20, "Other": 10} |
| summary | 极值和合计正确 | {"max": "Online", "min": "Other", "combined": 60} |
| boundary | 不捏造绝对人数 | "unknown" |

容差、轮次、证据要求见 answer-key.json。
