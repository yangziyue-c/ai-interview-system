# 致 P3（AI 评估）同学的工作汇报

> 来自 P1（后端）。本文档汇总与你对接相关的后端最新变化与题库评分素材，
> 请以此为准开展多维度评分与报告生成服务开发。

## 一、后端对接接口（不变 + 一处重要变化）

面试结束时，后端调用你的服务（配置 `backend/.env` 的 `AI_EVALUATOR_URL` 后生效）：

```
POST {你的服务}/evaluate
```

```json
{
  "position": "backend",        // 岗位 code —— 注意：已从固定两个枚举改为动态下发
  "qa_list": [
    { "round": 1, "question": "...", "answer": "...", "audio_url": "/uploads/xxx.webm" }
  ]
}
```

期望返回（**评分维度与字段不变**）：

```json
{
  "total_score": 85.5,
  "tech_score": 88.0,        // 技术能力
  "logic_score": 83.0,       // 逻辑思维
  "expression_score": 80.0,  // 表达沟通
  "match_score": 90.0,       // 岗位匹配度
  "summary": "综合评语……",
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1"],
  "suggestions": ["建议1", "建议2"]
}
```

**重要变化：岗位不再只有 backend / frontend 两个枚举。**
后端已改为岗位表动态维护（预留 5 个岗位位）。你收到的 `position` 是岗位
**code**（当前可能值：`backend` / `frontend` / `test_engineer`），请按 code
做岗位匹配度评估，不要写死岗位列表。约定 15 秒内未返回 / 非 2xx / 未配置 URL 时，
后端自动降级为内置 Mock 评分，保证流程不中断。

## 二、题库新格式提供的评分素材（v3，强烈建议使用）

题库同学已交付精修版（当前 Java 后端 150 题已就绪，前端/测试岗位陆续补齐），
新格式中两列对你的评分质量有直接价值：

### 1. 得分点（带权重）

每题都有结构化得分点，权重和为 1.0：

```
【basic 0.2】==比较基本类型的值是否相等，比较引用类型的内存地址是否相同
【core 0.3】equals()是Object类的方法……String、Integer等类重写了equals()用于比较内容
【advanced 0.5】能说明重写equals()时必须同时重写hashCode()的原因……
```

**建议用法**：把题目对应的得分点连同权重作为评分 Prompt 上下文——
命中 basic 给基准分、命中 core/advanced 按权重加权，可显著提升评分稳定性与可解释性。

### 2. 参考答案

每题有完整、专业、经过人工精修的参考答案（旧版的口语/拼接问题已全部修复），
可直接作为评分对照标准。

> 题库文件中还有「备注」列（如"高频考点""基础热身题"），可辅助判断题目权重。

## 三、其他约定

- 语音文件：`qa_list` 每项的 `audio_url` 是录音相对地址（如 `/uploads/12_ab3f9c2d.webm`，
  完整地址 = 服务地址 + url），可下载后做语音侧分析；该字段可能为 `null`（考生未录音）；
- 评分维度说明：后端数据库按 技术 0.35 / 逻辑 0.25 / 表达 0.20 / 匹配 0.20 加权
  计算 `total_score`（见后端 `ai_evaluator.py` 与 [DATABASE.md](DATABASE.md)），
  你返回的 `total_score` 与后端加权结果保持一致即可；
- 完整接口约定见 [API.md](API.md) 附录「P3：AI 评估」；
- 联调时后端 Swagger：http://localhost:8001/docs 。

有需要后端配合的字段或格式调整，随时提出。
