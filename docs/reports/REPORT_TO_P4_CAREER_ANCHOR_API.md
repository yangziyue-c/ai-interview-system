# 职业速测接口返回示例（P4）

下面是真实接口返回，不是手写示例。请求环境为测试库，已注册一个用户并携带 Bearer Token。

- `GET /api/v1/career-anchor/questions`
- `POST /api/v1/career-anchor/submit`

---

## 一、GET /career-anchor/questions

请求：

```
GET /api/v1/career-anchor/questions
Authorization: Bearer <token>
```

完整返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "total": 20,
    "questions": [
      { "id": "q1", "category": "interest", "role": "backend", "text": "我喜欢把业务规则拆成清晰的数据模型和接口边界。" },
      { "id": "q2", "category": "interest", "role": "frontend", "text": "我愿意反复打磨页面交互、视觉细节和操作路径。" },
      { "id": "q3", "category": "interest", "role": "test_engineer", "text": "我喜欢提前设计异常场景和验收标准。" },
      { "id": "q4", "category": "interest", "role": "system_design", "text": "我喜欢权衡模块边界、容量、扩展性和可用性。" },
      { "id": "q5", "category": "interest", "role": "algorithm", "text": "我愿意用数据和实验判断一个方案是否真的有效。" },
      { "id": "q6", "category": "interest", "role": "backend", "text": "看到一套服务稳定支撑高并发请求，我会很有成就感。" },
      { "id": "q7", "category": "interest", "role": "frontend", "text": "我享受把复杂功能整理成清晰、顺手的界面。" },
      { "id": "q8", "category": "interest", "role": "test_engineer", "text": "我愿意追查偶现问题，直到它能够稳定复现。" },
      { "id": "q9", "category": "interest", "role": "system_design", "text": "我对多个服务如何协作、部署和承受流量很感兴趣。" },
      { "id": "q10", "category": "interest", "role": "algorithm", "text": "我喜欢研究模型、特征或指标为什么发生变化。" },
      { "id": "q11", "category": "ability", "role": "backend", "text": "我能独立设计数据表、接口和基本的登录权限。" },
      { "id": "q12", "category": "ability", "role": "frontend", "text": "我能独立完成响应式页面、组件交互和状态联动。" },
      { "id": "q13", "category": "ability", "role": "test_engineer", "text": "我能独立设计测试用例、自动化脚本和回归检查。" },
      { "id": "q14", "category": "ability", "role": "system_design", "text": "我能拆分模块、画架构图并说明部署方案。" },
      { "id": "q15", "category": "ability", "role": "algorithm", "text": "我能完成数据清洗、模型训练和基本效果评估。" },
      { "id": "q16", "category": "ability", "role": "backend", "text": "遇到数据库异常、并发或消息堆积时，我知道从哪里排查。" },
      { "id": "q17", "category": "ability", "role": "frontend", "text": "遇到渲染、兼容性或网络请求问题时，我能定位到具体环节。" },
      { "id": "q18", "category": "ability", "role": "test_engineer", "text": "我能复现环境差异、边界输入和偶现缺陷。" },
      { "id": "q19", "category": "ability", "role": "system_design", "text": "我能分析服务依赖、资源瓶颈和扩展方案。" },
      { "id": "q20", "category": "ability", "role": "algorithm", "text": "遇到指标异常时，我能判断是数据、特征还是训练过程的问题。" }
    ],
    "interest_ratings": [
      { "value": 1, "label": "完全不符合" },
      { "value": 2, "label": "不太符合" },
      { "value": 3, "label": "一般或不确定" },
      { "value": 4, "label": "比较符合" },
      { "value": 5, "label": "非常符合" }
    ],
    "ability_ratings": [
      { "value": 1, "label": "目前做不到" },
      { "value": 2, "label": "需要较多帮助" },
      { "value": 3, "label": "基本了解，但不够独立" },
      { "value": 4, "label": "基本可以独立完成" },
      { "value": 5, "label": "能够稳定独立完成" }
    ]
  }
}
```

说明：

- `questions[].category` 为 `interest` 或 `ability`，分别对应上面两套评分标签。
- `questions[].role` 是该条陈述对应的岗位 code，前端展示时可以不使用。
- 题目顺序固定，提交的 `answers` 必须按这个顺序排列。

---

## 二、POST /career-anchor/submit

### 请求示例

```json
{
  "answers": [5, 2, 2, 2, 2, 5, 2, 2, 2, 2, 5, 2, 2, 2, 2, 5, 2, 2, 2, 2]
}
```

这是刻意偏向「后端」的 20 项评分：第 1、6、11、16 条给 5 分，其余给 2 分。

### 成功返回

```json
{
  "code": 0,
  "message": "推荐岗位已生成",
  "data": {
    "recommended": {
      "position": "backend",
      "name": "后端开发工程师",
      "index": 100,
      "reason": "更关注数据、接口与系统稳定性，后端的学习路径和你的选择更接近。"
    },
    "alternatives": [
      { "position": "frontend", "name": "前端开发工程师", "index": 25 },
      { "position": "test_engineer", "name": "测试开发工程师", "index": 25 }
    ],
    "scores": [
      {
        "position": "backend",
        "name": "后端开发工程师",
        "interest_raw": 10,
        "ability_raw": 10,
        "interest_norm": 1.0,
        "ability_norm": 1.0,
        "composite": 1.0,
        "index": 100
      },
      {
        "position": "frontend",
        "name": "前端开发工程师",
        "interest_raw": 4,
        "ability_raw": 4,
        "interest_norm": -0.5,
        "ability_norm": -0.5,
        "composite": -0.5,
        "index": 25
      },
      {
        "position": "test_engineer",
        "name": "测试开发工程师",
        "interest_raw": 4,
        "ability_raw": 4,
        "interest_norm": -0.5,
        "ability_norm": -0.5,
        "composite": -0.5,
        "index": 25
      },
      {
        "position": "algorithm",
        "name": "算法工程师",
        "interest_raw": 4,
        "ability_raw": 4,
        "interest_norm": -0.5,
        "ability_norm": -0.5,
        "composite": -0.5,
        "index": 25
      },
      {
        "position": "system_design",
        "name": "系统设计工程师",
        "interest_raw": 4,
        "ability_raw": 4,
        "interest_norm": -0.5,
        "ability_norm": -0.5,
        "composite": -0.5,
        "index": 25
      }
    ],
    "consistency_percent": 100,
    "confidence": "高",
    "margin": 75,
    "title": "后端开发工程师",
    "narrative": "兴趣量表与能力自评都更支持「后端开发工程师」。更关注数据、接口与系统稳定性，后端的学习路径和你的选择更接近。",
    "signal_label": "兴趣与能力方向一致",
    "signal_narrative": "两类量表都把「后端开发工程师」排在首位，方向较一致。 主次方向区分较清楚，可以作为优先探索方向。",
    "guide": "可以先用「后端开发工程师」开始一场模拟面试，系统会按该岗位的题目出题。"
  }
}
```

---

## 三、字段说明

| 字段 | 含义 |
| :--- | :--- |
| `recommended.position` | 推荐岗位 code，直接传给 `POST /interviews` |
| `recommended.name` | 岗位展示名，来自 positions 表 |
| `recommended.index` | 倾向指数，0~100 |
| `recommended.reason` | 推荐理由 |
| `alternatives` | 第 2~3 名，含 code、name、index |
| `scores` | 五个岗位的完整得分，按综合分降序 |
| `scores[].interest_raw` | 兴趣原始分，2 条陈述之和，2~10 |
| `scores[].ability_raw` | 能力原始分，2 条陈述之和，2~10 |
| `scores[].interest_norm` | 兴趣归一化分，-1~1 |
| `scores[].ability_norm` | 能力归一化分，-1~1 |
| `scores[].composite` | 综合分，兴趣 60% + 能力 40% |
| `scores[].index` | 倾向指数，0~100 |
| `consistency_percent` | 同类陈述回答一致性，0~100 |
| `confidence` | 置信度：高 / 中 / 低 |
| `margin` | 第一名与第二名的指数差 |
| `title` | 结果页主标题；分差小于 5 时为「方向暂不明确」 |
| `narrative` | 主推荐说明 |
| `signal_label` | 兴趣与能力信号标签 |
| `signal_narrative` | 兴趣与能力信号说明 |
| `guide` | 引导用语 |

---

## 四、注意事项

- `answers` 必须正好 20 项，每项为 1~5 的整数，顺序与题目接口一致。缺项或越界返回 400。
- 示例里的 `index: 100` 是因为刻意把后端相关题目全给 5 分，正常作答会落在 0~100 之间，不是固定上限。
- `recommended.name` 来自后端 positions 表，可能与前端本地 `POSITIONS` 的文案略有差异。显示以后端返回为准。
- 未登录返回 401；岗位全部下线时返回 503（业务码 50300）。

---

## 五、测试记录（是否测过）

`POST /career-anchor/submit` 成功后，后端会把最近一次结果摘要写进用户设置。前端打开速测入口时调 `GET /settings`，读 `career_anchor_result`：

- `null`：没测过。
- 非 `null`：测过，可以直接展示上次推荐，并给出「重新测一次」入口。

结构：

```json
{
  "position": "backend",
  "name": "后端开发工程师",
  "index": 90,
  "consistency_percent": 88,
  "confidence": "高",
  "tested_at": "2026-11-08T15:30:00"
}
```

每次重新提交会覆盖为最新一次。该字段只读，`PUT /settings` 传了也不会生效。换设备登录仍能读到；localStorage 可以留作离线兜底，但不要作为唯一来源。
