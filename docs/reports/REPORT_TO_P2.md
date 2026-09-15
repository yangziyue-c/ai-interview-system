# 致 P2（后端开发 B / AI专项1）的工作汇报

> 来自 P1（后端）。本文档汇总与你对接相关的后端最新变化、题库 v13 新格式与选题约定。
> **重要分工变化（2026-09-04）**：面试官对话逻辑由你负责，出题不再走 AI 生成，
> 题目从已入库的面试题库（`questions` 表）中抽取；追问按题库的「追问触发条件」生成。
>
> **2026-09-14 起题库已换代到 V5**（`backend/rag/数据/*-v5.json`，5012 题 / 5 岗位）：
> V4 的追问素材挤在一个字段里，原算法的 119 行解析层整体失效、L1 触发命中率仅 66%、
> 收尾题池因 V5 无「收尾交流」阶段而取不到题。1 号据此做了适配实现，
> 最新说明（含教程）见 [REPORT_TO_P2_INTERVIEWER_NEW.md](REPORT_TO_P2_INTERVIEWER_NEW.md)
> （为什么改 / 为什么这么改 / 具体怎么用 / 教程：之后怎么改）。
> 算法速览与旧版差异见 [backend/interviewer_new/README.md](../../backend/interviewer_new/README.md)。
>
> `backend/interviewer_new/` 是「示范代码」，可在此基础上修改。
> 它有一组单元测试（`tests/test_question_bank.py`）与效果回归脚本
> （`scripts/simulate_interview.py`）可当基线；只要 `pick_next` 的签名不变，
> 集成层（`app/adapters/ai_interviewer.py`）一行都不用动，也可以整个推翻重写。
>
> 外部独立服务（下文第一节）已降为**扩展位**：仅当题库策略未命中
> （如新岗位在题库无题）时，主后端才会调用 `AI_INTERVIEWER_URL`。

## 一、后端对接接口（扩展位，接口不变）

> 2026-09-06 起：出题已由主项目内的题库策略（`backend/interviewer_new/`）直接完成，
> 主后端仅在题库策略未命中时调用外部服务。以下契约不变，供扩展位服务对接：

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
后端已改为岗位表动态维护，**2026-09-14 起开放 5 个**：
`backend` / `frontend` / `test_engineer` / `algorithm` / `system_design`（清单可能调整）。
你收到的 `position` 永远是岗位 code，请按 code 过滤题库，不要写死岗位列表。
约定 15 秒内未返回 / 非 2xx / 未配置 URL 时，后端自动降级为内置 Mock 题库，
流程不中断，你的服务可以放心迭代。

## 二、题库格式（本节为 **V4 口径**，V5 已换代，见开头的换代说明）

> **V5 现状速览**：5012 题 / 5 岗位（backend 2146 + frontend 734 + test_engineer 667 +
> algorithm 655 + system_design 810），19 列；追问已拆成 `follow_up_l1` / `l2` / `l3`
> 三个独立字段且格式 100% 规整，不再需要任何文本解析（V4 那 119 行解析层已整体作废）。
> 字段规范与算法适配见 [REPORT_TO_P2_INTERVIEWER_NEW.md](REPORT_TO_P2_INTERVIEWER_NEW.md)；
> 数据生产口径见 [REPORT_TO_P5.md](REPORT_TO_P5.md)。**以下 V4 内容仅作回滚参考。**

题库同学已交付题库文件（`题库/*.xlsx`，**V4 换代版**：已开放岗位共 451 题，
backend 151 + frontend 150 + test_engineer 150），
P1 已将其导入 `questions` 表（导入脚本：`backend/scripts/import_question_bank.py`，幂等可重跑）。
你不需要自己解析 xlsx，通过题库 API 查库即可：

```
GET /api/v1/questions?position=backend&category=技术知识&difficulty=easy&stage=开场热身&limit=20
```

> 鉴权与其他接口一致：先 `POST /api/v1/auth/register` 注册一个服务账号
> （如 username=`p2_service`），拿 token 后请求头带 `Authorization: Bearer <token>`。
> 接口字段与过滤参数完整说明见 [API.md](../API.md) 第 5 章。

表结构（V4：xlsx 16 列 + 导入剥离的 1 个软技能标签列；V4 相比 v13：
大类由 5 类拆为 6 类、新增第 16 列 `expression_points` 表达评估要点）：

| 字段 | 说明 | 对你的用途 |
| :--- | :--- | :--- |
| position_code | backend / frontend / test_engineer | 选题过滤（首要条件） |
| question_no | tech_001 / scene_012 / code_003 / project_001 / behavior_001 | 唯一标识（岗位内唯一） |
| category | 技术知识 / 系统设计题 / 场景题 / 编码与算法 / 项目深挖 / 行为面试 | 检索维度 |
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
| expression_points | 表达评估要点（V4 新增） | 评分素材（给 P3），选题无关 |

### 追问触发条件（v13 升级为四层结构）

451 题全部具备，每行四层结构，用空行/标记分隔：

```
【L1-触发追问】根据候选人回答中的关键词触发
  ① 若提到"hashCode" → 追问：HashMap中key的hash计算过程
  ② 若提到"String" → 追问：String为什么设计为不可变
  ③ 若回答笼统/缺乏细节 → 追问：能否结合你实际项目中的经验……

【L2-递进追问】在L1基础上进一步深入，考察实践深度
  ① 承接L1-①深入 → 追问：在实际项目中这个知识点是如何应用的？……

【L3-极限追问】仅当候选人 L1 和 L2 回答流畅准确时使用，考察知识融会贯通
  → 极限场景：假设你需要设计……请从三个维度阐述。

【降级策略】当候选人回答困难或明显不熟悉时使用
  → 那我们先从更基础的角度看——你能简单说一下这个概念的基本定义吗？
```

**建议的追问生成逻辑**：把候选人上一轮答案与 L1 触发条件匹配（关键词/语义），
命中"若提到 X"则用对应追问；均未命中则用"若回答笼统/缺乏细节"兜底；再没有时
按 L2/L3/降级策略随候选人水平递进。

## 三、抽题策略约定（V4 口径；V5 的执行版已落在 `backend/interviewer_new/`）

> **V5 的关键差异**：收尾题不再按 `interview_stage=收尾交流` 取（V5 只有 3 个阶段，
> 没有「收尾交流」），改为按 `category=行为素质题` 建池。核心节奏（1 开场 + 6 追问 = 7 轮）不变。

后端流程：1 道开场题（round=1）+ 6 道追问（round=2~7），共 7 轮。

- **开场题（round=1）**：`interview_stage=开场热身` 且 `difficulty=easy` 池中抽取
  （每岗 21 题，实测；开场题只问一轮，不做锚点追问）；
- **追问（round=2~5）**：按上一节的「追问触发条件」驱动，
  结合对话历史（`history` 字段）生成；选新题时优先 `核心考察` → `深度考察` 逐层递进；
- **收尾（round=6/7，强制）**：最后两轮必为 `interview_stage=收尾交流` 池的题
  （每岗 15 道，如"你还有什么想问我的吗？"）。真实题库每题都带非空追问计划，
  不强制收尾则追问链会一直延伸到最后一轮。

## 四、其他约定

- **你的算法执行版位置**：`backend/interviewer_new/question_bank.py`（**示范代码，可在此基础上修改**；
  修改算法只动该目录，修改指南与踩坑清单见 backend/interviewer_new/README.md
  与 [REPORT_TO_P2_INTERVIEWER_NEW.md](REPORT_TO_P2_INTERVIEWER_NEW.md) 第四节的教程；
  测试 `cd backend && pytest` 共 68 个用例）；
- 题库数据源已换代：现为 `backend/rag/数据/*-v5.json`（仓库根 `题库/` 的 V4 xlsx 已于 2026-09-14 删除，需要回看时从 Git 历史取）；
- 后端完整接口约定见 [API.md](../API.md) 附录「P2：AI 面试官」；
- 联调时后端 Swagger：http://localhost:8001/docs 。

有需要后端配合的字段或格式调整，随时提出。
