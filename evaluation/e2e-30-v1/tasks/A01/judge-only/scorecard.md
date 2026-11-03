# A01 真实图：四国预期寿命：评分表

关键项全部通过才通过，参考图不做像素匹配。

| ID | 关键要求 | 预期 |
|---|---|---|
| structure | 正确识别横向柱状图、2023 年、出生时预期寿命，单位年 | "horizontal bar / 2023 / life expectancy at birth / years" |
| values | 四国数值与国家正确关联 | {"China": 77.9529, "India": 72.0026, "Japan": 84.7123, "United States": 79.3043} |
| extrema | 最高与最低国家正确 | {"max": "Japan", "min": "India"} |
| difference | Japan 减 India，单位年 | 12.709699999999998 |

容差、轮次、证据要求见 answer-key.json。
