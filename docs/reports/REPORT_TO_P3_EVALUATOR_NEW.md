# 给 3 号（评估）· 评估服务 V5 增强说明（含示范代码，backend/evaluator_new/）

> 🧭 **先明确一个定位：`backend/evaluator_new/` 是 「示范代码」。**
>
> 它是 1 号为了让 V5 的**单题校准锚点**能真正喂进评分而做的**最小侵入参考实现**
> （相对你的原版，全量改动只有 `build_dialogue_text` 一个函数）——**没有重写评估服务**。
>
> | 你可以 | 说明 |
> |---|---|
> | **直接跑** | 由 `start.py` 自动拉起（8002）；有 6 个回归用例守着「不传素材时与原版逐字一致」 |
> | **照它改** | 第 4 节列了 5 个拓展方向（校验素材收益 / 逐题诊断 / 接真实 ASR / 素材缓存 / 加岗位同步点） |
> | **整个推翻** | 只要满足 `POST /evaluate` 契约（5 维分数 + 文本字段），主后端一行都不用动 |
>
> ⚠️ 唯一需要守住的边界：主后端只校验 **5 维分数**（`ai_evaluator.py::_is_valid_score_report`）——
> **新增字段随便加，但这 5 个字段名不能改**。除此之外，Prompt 模板、评分细则、输出结构都由你定。
> 原版 `backend/evaluator/` 也仍然保留着，随时可切回。

---

> 背景：知识库由 V4 换代到 V5（`backend/rag/数据/*-v5.json`，5012 题 / 5 岗位）。
> V5 每题带三个**为评估准备**的字段：`basic_score_points`（基础得分点）、
> `advanced_score_points`（进阶得分点）、`calibration_anchor`（**单题校准锚点**）。
> 1 号据此为评估服务做了一个**最小侵入的增强版**，落在 **`backend/evaluator_new/`**。
>
> 本文回答四件事：**为什么改 / 为什么这么改 / 具体怎么用 / 之后怎么拓展**。

---

## 一、为什么改（V4 时代评估的短板）

原评估服务（`backend/evaluator/app.py`）的输入只有两样：**岗位 code + 对话文本**。

```
POST /evaluate  {"position": "backend", "qa_list": [{round, question, answer}]}
   → build_dialogue_text()  拼成纯对话
   → get_evaluation_prompt() 套 Prompt 模板
   → LLM 打分（5 维）
```

**短板**：LLM 只能凭对话"就事论事"地打分，**不知道每道题的考察意图**。
同一个考生答同一段话，在"这道题只要求说清概念"和"这道题要求讲透原理边界"两种情形下
应得的分是不同的，但原实现无法区分——**评估与题目脱钩**。

**V5 恰好补上了这块**（真实数据示例）：

```
【单题校准锚点】
[技术水平] 能准确阐述JVM、JDK的核心概念与原理边界，能结合「JVM、JDK、JRE 三者有什么区别
          和联系？」的实际场景展开分析，回答有深度而非泛泛而谈。
[岗位匹配度] 能体现Java 后端开发工程师对JVM等技术栈的掌握深度，能联系实际项目经验
          说明其应用价值与工程考量。
```

这正是"这道题该考什么、答到什么程度算好"的判分标准，评估侧不用可惜。

---

## 二、为什么这么改（三条设计约束）

### 2.1 只改一处函数，Prompt 模板与评分逻辑零改动

**改动仅 `build_dialogue_text()` 一个函数**：把素材拼进对话文本。

```python
def build_dialogue_text(qa_list):
    dialogue = ""
    for qa in qa_list:
        dialogue += f"面试官{tag}：{qa.get('question', '')}\n"
        dialogue += f"候选人：{qa.get('answer', '')}\n"
        materials = qa.get("materials") or {}          # ← 唯一新增
        refs = [...]                                    # 有值才拼
        if refs:
            dialogue += "【本题评分参考】" + "；".join(refs) + "\n"
    return dialogue
```

**为什么不动 Prompt 模板**（`evaluation_prompts.py` 逐字未改）：
- 模板里有大量岗位专属的评分细则，是 3 号的核心工作，改它风险高；
- 素材作为"对话文本的一部分"注入，LLM 同样能读到，**效果等价而侵入最小**；
- 3 号后续要调整模板时，不受本次改动牵扯。

### 2.2 依赖倒置：素材由调用方提供，评估服务保持无状态

**素材不是评估服务去查库取的，而是主后端查好传进来的。**

```
主后端 app/adapters/ai_evaluator.py
   ├─ _attach_materials(qa_list)  ← 按题干从 questions 表精确匹配取素材
   └─ POST /evaluate {position, qa_list: [{..., materials: {...}}]}
```

**为什么这样分工**：
- 评估服务**不引入数据库依赖**（它现在只 import 标准库 + requests + flask），
  保持"纯计算服务"的定位，可独立部署、独立扩缩容；
- 题库是主后端的领域，题目素材的来源口径由主后端统一把关；
- 3 号调试时不需要准备数据库。

### 2.3 向后兼容：不传 materials 时输出逐字一致

```python
qa = [{"round": 1, "question": "Q", "answer": "A"}]
build_dialogue_text(qa)
# == "面试官（第1轮）：Q\n候选人：A\n"   ← 与 3 号原版完全一致
```

有 6 个回归用例守护这条约束（`tests/test_evaluator_new.py`），
其中包含「多轮无素材」「空 materials」「materials=None」等边界。

**意义**：主后端未匹配到题目（Mock/LLM 现场生成的题、题库换代前的历史会话）时，
评估行为与旧版**完全一样**——增强是纯增量的，不会让任何既有场景变差。

---

## 三、具体怎么用

### 3.1 目录与启动

```
backend/evaluator_new/
├── app.py                 ← 复制自 evaluator/app.py，仅 build_dialogue_text 增强 + docstring
└── evaluation_prompts.py  ← 逐字复制，未改
```

**由 `start.py` 自动拉起**（已切换）：

```python
evaluator = subprocess.Popen([str(python), "evaluator_new/app.py"], cwd=str(BASE_DIR))
```

手动启动：`cd backend && python evaluator_new/app.py`（端口仍 8002）。

> 原 `backend/evaluator/` **保留不动**（3 号成果留档）。若要切回原版，
> 把 `start.py` 那行的路径改回 `evaluator/app.py` 即可。

### 3.2 接口契约（唯一变化：qa 项多了可选 `materials`）

```jsonc
POST http://localhost:8002/evaluate
{
  "position": "backend",
  "qa_list": [
    {
      "round": 1,
      "question": "JVM、JDK、JRE 三者有什么区别和联系？",
      "answer": "JVM 是虚拟机……",
      "audio_url": null,
      "materials": {                                  // 可选，主后端自动附加
        "basic_score_points": "JVM 是运行字节码的虚拟机\nJRE 包含 JVM 和核心类库",
        "advanced_score_points": "JDK 包含 JRE 和开发工具",
        "calibration_anchor": "[技术水平] 能准确阐述概念与原理边界\n[岗位匹配度] …"
      }
    }
  ]
}
```

**返回格式完全不变**（5 维分数 + summary/strengths/weaknesses/suggestions）。

> 旧版评估服务（`evaluator/app.py`）会**忽略** `materials` 字段——所以主后端可以放心
> 无条件附加，两个版本都能跑。

### 3.3 自测

```bash
cd backend
<ai_interview 的 python.exe> -m pytest tests/test_evaluator_new.py -q    # 6 个用例
<ai_interview 的 python.exe> -m pytest -q                                # 全量 62 个
```

**效果验证**（需配置 `LLM_API_KEY`）：

```bash
# 不传素材（对照）与传素材（增强）各跑一次，比较 5 维分数的合理性
curl -X POST http://localhost:8002/evaluate -H "Content-Type: application/json" \
  -d '{"position":"backend","qa_list":[{"round":1,"question":"…","answer":"…"}]}'
```

---

## 四、教程：之后怎么改

> **这一节是给你的动手教程**——每条都写明**现状 → 怎么改 → 注意什么**。
> 改动集中在 `evaluator_new/` 内部时基本不影响主后端；唯一跨模块的边界是
> **5 维分数字段名不能改**（主后端 `_is_valid_score_report` 依赖它）。

### 拓展 1：校验素材是否真的提升了评分质量

**现状**：增强的收益是**假设**的（LLM 能按题评分），未做 A/B 量化。

**做法**：构造若干「答案相同、题目不同」的对照样本（如一段泛泛而谈的答案，
分别配一道 easy 概念题和一道 hard 原理题），对同一份答案跑两次评估：
- 期望：hard 题的 `tech_score` 显著低于 easy 题（因为校准锚点要求更高）
- 若两次分数接近，说明素材没起作用，需检查 Prompt 里素材是否被 LLM 读到

### 拓展 2：按题输出诊断（而非只有 5 个总维度）

**现状**：素材注入了，但输出仍是整场面试的 5 维总分。

**可探索**：让 LLM 对**每道题**给一个「本题得分 + 依据」，前端展示成"逐题诊断"。
- 改 `_REPORT_FIELDS` 加一个 `per_question` 数组字段（注意保持 5 维契约不变，
  主后端 `ai_evaluator.py::_is_valid_score_report` 只校验 5 维分数，新增字段不影响兼容）
- Prompt 模板需加输出要求（这属于 3 号的领域，改动前建议先小样本试）

### 拓展 3：接入真实 ASR，恢复语音覆盖

`analyze_expression_simulate` 目前是占位（只产出 `simulated=True` 的参考信息，
不覆盖表达分——3 号注释里说明了原因：按字数的启发式与「简洁精准」的评分标准方向相反）。

接入真实语音特征后，在 `merge_report` 恢复覆盖表达分。

### 拓展 4：素材的缓存与降级策略

`_attach_materials`（主后端侧）当前是"每场评估查一次题库"，5 题一份 SQL。
- 若评估并发升高，可加题目级 LRU 缓存（题库是静态数据，变更只发生在导入时）
- 素材匹配是**题干精确匹配**；若将来题库题干措辞变动，历史会话会匹配不上 →
  退化为原行为（不报错）。若希望历史会话也能吃到素材，正解是给 `qa_records`
  加 `question_no` 列（出题时落库），而不是放宽匹配（包含匹配会误配）

### 拓展 5：新增岗位时的同步点

新增岗位要改三处（否则 `tests/test_api.py::test_weights_match_csv` 会挂）：
1. `评估维度.csv` 加列
2. `app/core/evaluation_weights.py` 的 `POSITION_CONFIG` 加权重
3. `scripts/import_question_bank.py` 的 `POSITION_MAP` 加映射

评估服务本身**无需改动**（它从 `POSITION_CONFIG` 读权重，未知岗位自动用通用权重兜底）。

---

## 五、与 3 号原版的差异一览（回归时对照）

| 环节 | `backend/evaluator/`（原版） | `backend/evaluator_new/`（增强版） |
|---|---|---|
| 接口路径 / 端口 | `POST /evaluate`，8002 | **相同** |
| 请求字段 | `position` + `qa_list` | 相同 **+ 可选 `materials`** |
| 返回字段 | 5 维分数 + 文本字段 | **相同**（逐字不变） |
| `build_dialogue_text` | 纯对话 | 有素材时追加「【本题评分参考】」行 |
| `evaluation_prompts.py` | — | **逐字未改** |
| 评分逻辑 / 权重 / 兜底 | — | **完全相同** |
| 无素材时的行为 | — | **与原版逐字一致**（6 个回归用例守护） |

---

**有疑问或要改评估逻辑，直接动 `backend/evaluator_new/`（该目录已移交 3 号）。**
原 `backend/evaluator/` 保留留档；确认新版稳定后可删除，或把 `start.py` 切回原版。
