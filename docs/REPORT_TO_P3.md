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

期望返回（**2026-09-04 起评分维度扩展为 5 维**）：

```json
{
  "total_score": 85.5,
  "tech_score": 88.0,          // 技术水平
  "logic_score": 83.0,         // 逻辑思维
  "expression_score": 80.0,    // 沟通表达
  "adaptability_score": 82.0,  // 应变能力（新增维度）
  "match_score": 90.0,         // 岗位匹配度
  "summary": "综合评语……",
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1"],
  "suggestions": ["建议1", "建议2"]
}
```

维度与权重源自团队《评估维度.csv》（2026-09-04 定稿）：

| 岗位 code | 技术 | 逻辑 | 表达 | 应变 | 匹配 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| backend | 35% | 25% | 10% | 10% | 20% |
| frontend | 30% | 20% | 15% | 15% | 20% |
| test_engineer | 25% | 25% | 20% | 15% | 15% |

`total_score` 由各维度按岗位权重加权计算（不要直接填平均值）；
权重单一事实源在 `backend/app/core/evaluation_weights.py`（`POSITION_CONFIG` /
`weights_for()`），主后端 Mock 兜底与评估服务共用，测试机器校验与《评估维度.csv》一致。

**重要变化：岗位不再只有 backend / frontend 两个枚举。**
后端已改为岗位表动态维护（预留 5 个岗位位）。你收到的 `position` 是岗位
**code**（当前可能值：`backend` / `frontend` / `test_engineer`），请按 code
做岗位匹配度评估，不要写死岗位列表。评估接口单独 30 秒预算（其余适配器仍 15 秒），
超时 / 非 2xx / 未配置 URL 时，后端自动降级为内置 Mock 评分，保证流程不中断。

## 二、题库新格式提供的评分素材（v13，强烈建议使用）

题库同学已交付 v13 个性化内容版（3 岗位 × 150 题，共 450 题），
已由 P1 导入 `questions` 表并提供查询 API（见 [API.md](API.md) 第 5 章）。
其中两列对你的评分质量有直接价值：

### 1. 得分点（带权重）

每题都有结构化得分点，三段权重合计 1.0：

```
【basic 0.3】==比较基本类型的值是否相等，比较引用类型的内存地址是否相同
【core 0.5】equals()是Object类的方法……String、Integer等类重写了equals()用于比较内容
【advanced 0.2】能说明重写equals()时必须同时重写hashCode()的原因……
```

**建议用法**：把题目对应的得分点连同权重作为评分 Prompt 上下文——
命中 basic 给基准分、命中 core/advanced 按权重加权，可显著提升评分稳定性与可解释性。

### 2. 参考答案

每题有完整、专业、经过人工精修的参考答案（v13 平均 570~760 字），
可直接作为评分对照标准。

> 另有「追问触发条件」（L1/L2/L3/降级策略四层）与「优秀回答范例」，
> 可作为追问质量评估（应变维度）的参考素材。
> 题库表中 `note` 列（如"高频考点""基础热身题"）可辅助判断题目权重。

## 三、其他约定

- 语音文件：`qa_list` 每项的 `audio_url` 是录音相对地址（如 `/uploads/12_ab3f9c2d.webm`，
  完整地址 = 服务地址 + url），可下载后做语音侧分析；该字段可能为 `null`（考生未录音）；
- 评分维度说明：后端数据库按岗位 5 维加权计算 `total_score`
  （权重表见第一节，单一事实源 `backend/app/core/evaluation_weights.py`，
  主后端与评估服务共用，无需双向同步），你返回的 `total_score` 与后端加权结果保持一致即可；
- 完整接口约定见 [API.md](API.md) 附录「P3：AI 评估」；
- 联调时后端 Swagger：http://localhost:8001/docs 。

有需要后端配合的字段或格式调整，随时提出。

## 四、你的服务已整合进仓库（2026-09-03 更新）

你上传的 `app.py` 与 `evaluation_prompts.py` 已按上文约定整合完毕，P1 侧改动如下：

| 项目 | 整合后状态 |
| :--- | :--- |
| 代码位置 | 仓库根目录 → `backend/evaluator/`（app.py + evaluation_prompts.py） |
| 服务端口 | 8001 → **8002**（8001 是主后端端口，同机不能共用；请勿改回） |
| 启动方式 | 由 `backend/start.py` 一键自动拉起（主后端退出时自动关闭）；手动启动：`cd backend && python evaluator/app.py` |
| API Key | 删除硬编码占位符，改为读环境变量/`backend/.env` 的 `LLM_API_KEY`（与主后端共享，填入即可生效；协作约定严禁提交 Key） |
| 岗位 code | `testing` → **`test_engineer`**，岗位名对齐数据库（后端/前端/测试开发工程师）；数据库新增岗位时无专属配置会自动走通用评估模板，不再 400 |
| 超时预算 | 你内部调 DeepSeek 25 秒，主后端对你 30 秒兜底（原来 15 秒会把真实评估挤掉） |
| 降级报告 | 默认报告按平均回答篇幅分档（58/68/78），不再固定 72 分 |
| 其他修复 | 修复了 Windows 控制台 GBK 编码导致 emoji print 崩溃、JSON 解析失败时兜底分支引用未初始化变量的两个 bug |

**你后续可以继续做的方向**（非本次整合范围）：
1. 用 `qa_list` 里的 `audio_url` 接真实语音分析（讯飞/阿里云 ASR），替换 `analyze_expression_simulate` 模拟值——当前 expression_score 是按回答长度模拟的，答辩时需说明；
2. 把题库得分点/参考答案（见本文档第二节）拼入评分 Prompt，提升评分可解释性；
3. `_speech_details` 字段主后端暂不落库，如需在报告中展示语音特征，找 P1 加 Report 表字段。
