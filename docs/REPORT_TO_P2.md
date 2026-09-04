# 致 P2（后端开发 B / AI专项1）的工作汇报

> 来自 P1（后端）。本文档汇总与你对接相关的后端最新变化、题库 v13 新格式与选题约定。
> **重要分工变化（2026-09-04）**：面试官对话逻辑由你负责，**出题不再走 AI 生成**，
> 题目从已入库的面试题库（`questions` 表）中抽取；追问按题库的「追问触发条件」生成。

## 一、后端对接接口（不变 + 一处重要变化）

后端调用你的服务（配置 `backend/.env` 的 `AI_INTERVIEWER_URL` 后生效）：

```
POST {你的服务}/generate
```

```json
{
  "position": "backend",        // 岗位 code —— 注意：已从固定两个枚举改为动态下发
  "round": 2,                   // 当前是第几题（1 开场题，2~7 追问）
  "is_follow_up": true,         // 是否为追问
  "history": [                  // 完整对话历史（含本轮之前的问答）
    { "role": "interviewer", "content": "请先做个自我介绍……" },
    { "role": "candidate", "content": "我来自……" }
  ]
}
```

期望返回：`{ "question": "你下一题的题目文本" }`

**重要变化：岗位不再只有 backend / frontend 两个枚举。**
后端已改为岗位表动态维护（预留 5 个岗位位），岗位清单可能调整。你收到的
`position` 永远是岗位 **code**（当前可能值：`backend` / `frontend` / `test_engineer`），
**请按 code 过滤题库，不要写死岗位列表**。约定 15 秒内未返回 / 非 2xx / 未配置 URL 时，
后端自动降级为内置 Mock 题库，保证流程不中断——你的服务可以放心迭代。

## 二、题库 v13 新格式（已入库，直接查库/API，无需解析 xlsx）

题库同学已交付 v13 个性化内容版（3 岗位 × 150 题，共 450 题），
P1 已将其导入 `questions` 表（导入脚本：`backend/scripts/import_question_bank.py`，幂等可重跑）。
**你不需要自己解析 xlsx**，通过题库 API 查库即可：

```
GET /api/v1/questions?position=backend&category=技术知识&difficulty=easy&stage=开场热身&limit=20
```

> 鉴权与其他接口一致：先 `POST /api/v1/auth/register` 注册一个服务账号
> （如 username=`p2_service`），拿 token 后请求头带 `Authorization: Bearer <token>`。
> 接口字段与过滤参数完整说明见 [API.md](API.md) 第 5 章。

表结构（15 列 + 1 个剥离列，与 xlsx 对应）：

| 字段 | 说明 | 对你的用途 |
| :--- | :--- | :--- |
| position_code | backend / frontend / test_engineer | 选题过滤（首要条件） |
| question_no | tech_001 / scene_012 / code_003 / project_001 / behavior_001 | 唯一标识（岗位内唯一） |
| category | 技术知识 / 场景与设计 / 编码与算法 / 项目深挖 / 行为面试 | 检索维度 |
| sub_category | 如 Java基础、排障Debug、测试用例设计 | 检索维度 |
| difficulty | easy / medium / hard | 选题策略（见下） |
| question | 题干（**已剥离软技能标签**，可直接读给候选人） | 出题文本 |
| soft_skill_tag | 剥离出的「岗位软技能考察」标签（如"故障应急响应意识"） | 仅作选题/追问参考，勿读给候选人 |
| score_points | `【basic 0.3】…【core 0.5】…【advanced 0.2】…` 三段加权合计 1.0 | 可作评分 Prompt 上下文（给 P3） |
| follow_up_triggers | **追问生成核心依据**（见下） | 追问生成 |
| reference_answer | 完整参考答案 | Prompt 参考 |
| note | 如"高频考点""适合面试开场" | 选题参考 |
| interview_stage | 开场热身 / 核心考察 / 深度考察 / 收尾交流 | 选题策略（见下） |
| stage_order | 1~4 | 同上 |
| suggested_minutes | 3~12 | 仅参考，与后端轮次无关 |
| alternative_directions | 替代回答方向（如"方向1：从XX角度展开……"） | 追问素材 |
| excellent_example | 优秀回答范例 | 可作评分对照 |

### 追问触发条件（重点，v13 升级为四层结构）

450 题全部具备，每行四层结构，用空行/标记分隔：

```
【L1-触发追问】根据候选人回答中的关键词触发
  ① 若提到"hashCode" → 追问：HashMap中key的hash计算过程
  ② 若提到"String" → 追问：String为什么设计为不可变
  ③ 若回答笼统/缺乏细节 → 追问：能否结合你实际项目中的经验……

【L2-深入追问】候选人对 L1 回答准确时进一步考察原理/边界
  ① 深入原理 → ……  ② 深入应用 → ……

【L3-极限追问】仅当候选人 L1 和 L2 回答流畅准确时使用，考察知识融会贯通
  → 综合场景：假设你需要设计……请从三个维度阐述。

【降级策略】当候选人回答困难或明显不熟悉时使用
  → 那我们先从更基础的角度看——你能简单说一下这个概念的基本定义吗？
```

**建议的追问生成逻辑**：把候选人上一轮答案与 L1 触发条件做匹配（关键词/语义），
命中"若提到 X"则用对应追问；均未命中则用"若回答笼统/缺乏细节"兜底；再没有时
按 L2/L3/降级策略随候选人水平递进。

## 三、抽题策略约定（开场 vs 追问 vs 收尾）

后端流程：**1 道开场题（round=1）+ 6 道追问（round=2~7），共 7 轮**。

- **开场题（round=1）**：`interview_stage=开场热身` 且 `difficulty=easy` 池中抽取
  （每岗 26 题，`note` 含"适合面试开场"的优先）；
- **追问（round=2~7）**：按上一节的「追问触发条件」驱动，
  结合对话历史（`history` 字段）生成；选新题时优先 `核心考察` → `深度考察` 逐层递进；
- **收尾**：`interview_stage=收尾交流` 池为 15 道行为面试题（如"你还有什么想问我的吗？"），
  可作为最后 1~2 轮的选题来源。

## 四、其他约定

- 题库文件保留在仓库根目录 `题库/`（P5 更新后重跑导入脚本即可同步到库）；
- 后端完整接口约定见 [API.md](API.md) 附录「P2：AI 面试官」；
- 联调时后端 Swagger：http://localhost:8001/docs 。

有需要后端配合的字段或格式调整，随时提出。
