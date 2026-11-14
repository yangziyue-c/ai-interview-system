# A11 评分与报告字段说明（V8）

适用对象：前端、主后端、评估与统计脚本。评分版本：`SCORING_VERSION=8`。
日期：2026-11-14。

这份文档说明 A11 正式评分链在异常场景下的新口径，以及报告接口新增字段怎么用。目标是让「没评出分」和「评了低分」在页面上和统计里不再混为一谈。

---

## 一、口径变化

| 项 | 新口径 |
| :--- | :--- |
| 评分维度 | 行为素质题不再计入「技术水平」，行为题第一维单独作为岗位胜任力统计 |
| 有效回答 | 新增有效回答率；问满 10 题但有效回答不足时，报告标记为部分评分 |
| 评分失败 | 模型没有产出五维分时返回「评分不可用」，不再按回答长度生成 60 到 90 分 |
| 缺失维度 | 缺失维度对外返回 `null`，不用 0 占位；总分只按真实测到的维度归一化 |
| 客观核验 | 得分点覆盖率统一使用千问编号结果，原子断言只用于矛盾判断 |
| 评分护栏 | 事实错误封顶只影响技术维；无有效回答最高 1.5 分；代码明确错误时技术分最高 2.5 分 |
| RAG 与 KG | 题库 RAG 只负责出题参考，知识库和知识图谱才是评分证据；KG 只用纯图谱节点与共现方向 |
| 稳定性 | 评分温度改为 0；L3 计入难度上调；难度调整分按题数和难度权重计算 |

演示场景的显式 Mock 与离线兜底仍然保留。变化只针对 A11 正式评分链：正式评分失败时不再伪造一份可比较的成绩。

---

## 二、报告接口新增字段

`GET /reports/{interview_id}`、分享报告与结束面试的响应里都会带以下字段。

| 字段 | 类型 | 含义 |
| :--- | :--- | :--- |
| `score_status` | string | `valid` 完整评分 / `partial` 部分评分 / `unavailable` 评分不可用 |
| `score_available` | bool | 是否至少有一个维度评出了分 |
| `missing_dimensions` | list[string] | 没评出分的维度名，中文，如 `["技术水平"]` |
| `partial_reasons` | list[string] | 部分评分的原因 |
| `effective_rate` | float 或 null | 有效回答率 |
| `behavioral_role_fit` | float 或 null | 行为素质题的岗位胜任力统计 |
| `difficulty_adjusted_meta` | object 或 null | 难度调整的明细 |
| `objective_score_guard` | list[object] | 评分护栏的触发记录 |
| `objective_audit` | object 或 null | 客观核验的审计信息 |
| `scoring_evidence` | object 或 null | 逐维评分证据 |
| `tech_objective_fusion` | object 或 null | 技术维与客观线的融合明细 |
| `total_score` 与五个维度分 | float 或 null | 评分不可用时全为 `null`；部分评分时缺失维度为 `null` |
| `partial` | bool | 兼容字段，等价于 `score_status != "valid"`；新代码以 `score_status` 为准 |

`score_status` 在主后端对外只有以上三个取值。引擎内部可能出现 `invalid`，主后端在 `build_engine_meta` 里统一转成 `unavailable`，前端不要按 `invalid` 判断。

`missing_dimensions` 存的是中文维度名：技术水平、逻辑思维、沟通表达、应变能力、岗位匹配度。前端按名称映射到对应的分数字段。

---

## 三、三种状态怎么展示

### valid

五维齐全，`missing_dimensions` 为空。按原有方式画雷达图和分数卡片。

### partial

至少有一个维度或若干轮次没评出分。

- 只画有数据的维度，缺失维度显示「未评出」，不要补 0。
- `missing_dimensions` 里的维度对应分数是 `null`，不要当成 0 分。
- `total_score` 仍可能有值，因为它是按真实测到的维度归一化得到的；展示时要同时给出「部分评分」提示。
- `partial_reasons` 可以直接展示，说明为什么是部分评分。

### unavailable

`score_available=false`，`total_score` 与五个维度全部为 `null`。

- 不画雷达图，显示「本场评分未完成，暂无可比较的五维分数」。
- 问答记录与表达分析仍然可用，不要因为评分不可用把整页清空。
- 成长曲线会跳过这类场次，不会把它画成 0 分。

### 示例

评分不可用：

```json
{
  "total_score": null,
  "tech_score": null,
  "logic_score": null,
  "expression_score": null,
  "adaptability_score": null,
  "match_score": null,
  "score_status": "unavailable",
  "score_available": false,
  "missing_dimensions": ["技术水平", "逻辑思维", "沟通表达", "应变能力", "岗位匹配度"],
  "partial_reasons": ["评分模型未返回可解析的五维分"],
  "partial": true
}
```

部分评分：

```json
{
  "total_score": 72.5,
  "tech_score": null,
  "logic_score": 80.0,
  "expression_score": 76.0,
  "adaptability_score": 68.0,
  "match_score": 70.0,
  "score_status": "partial",
  "score_available": true,
  "missing_dimensions": ["技术水平"],
  "partial_reasons": ["有 1 轮评分未完成"],
  "partial": true
}
```

---

## 四、后端与统计脚本

- 成长曲线 `GET /reports/growth` 会跳过 `score_status=unavailable` 或 `score_available=false` 的场次，避免把失败场次画成 0 分。
- 个人中心的 `GET /reports/latest` 在评分不可用时 `total_score` 为 `null`，同时带 `score_status`。
- 学习计划仍按考察过的知识点推荐，不依赖单题分数。
- 成长档案需要 A11 引擎在线；离线版返回 `available=false`，与评分状态无关。
- 新旧报告不要混比。V8 之前的结果、旧缓存与 V8 结果口径不同，统计时应按 `SCORING_VERSION` 分组。

---

## 五、代码位置

| 内容 | 位置 |
| :--- | :--- |
| 评分版本 | `backend/dialogue_layer/app/config.py` 的 `SCORING_VERSION` |
| 报告组装与状态判定 | `backend/app/core/engine_report.py` 的 `build_engine_report`、`build_engine_meta` |
| 对外字段与 null 转换 | `backend/app/schemas/report.py` 的 `ReportOut`、`report_out` |
| 成长曲线与最近建议 | `backend/app/api/reports.py` |
| 5 号的原始说明 | 根目录 `A11评分与报告逻辑修改说明-给队友.docx` |

---

## 六、验证基线

- 后端全量测试：229 项通过。
- 对话层冒烟测试：2828 项通过，0 失败，1 项条件性跳过。
- 前端正式构建已同步到 `backend/static/`，完整、部分、不可用与分享报告均已检查。
