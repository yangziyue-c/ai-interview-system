"""示范作答：按题库得分点让大模型写一份优秀的考生回答

输入是题库 V5 的评分素材（基础得分点 / 进阶得分点 / 单题校准锚点）与考生
原回答。输出是一份**独立完整**的示范作答，不是对原回答的逐句改写——后者的
上限就是考生自己的表达，补不出得分点里他没提到的内容。

素材缺失时调用方不该走到这里：题库反查不到题，就没有依据生成。
"""
from app.adapters.llm import chat

# 示范作答的写作口径。刻意要求「不编造项目」：题库得分点里的例子是通用的，
# 模型若替考生编一段大厂经历，考生照着背反而会在追问里露馅。
_SYSTEM_PROMPT = """你是一位资深的技术面试官，正在为一道面试题撰写示范作答。

写作要求：
1. 以考生第一人称作答，像在面试现场说话，不要写成教科书条目；
2. 先给一句结论，再分点展开，最后用一句话收束；
3. 必须覆盖「基础得分点」的全部要点；「进阶得分点」能自然融入就融入，不硬凑；
4. 长度 300~500 字，用短标题或换行分段，便于阅读；
5. 不编造具体公司名、项目名或数字；需要举例时用通用的技术场景；
6. 不要出现「得分点」「评分标准」「参考答案」这类字样，也不要给自己打分；
7. 只输出示范作答正文，不要任何前后缀说明。
"""


async def generate_sample_answer(
    *,
    position_label: str,
    question: str,
    candidate_answer: str,
    basic_points: str,
    advanced_points: str,
    calibration_anchor: str,
) -> str:
    """生成一份示范作答；LLM 不可用时抛 LLMError（由 API 层转 503）"""
    user_prompt = f"""岗位：{position_label}
面试题：{question}

基础得分点：
{basic_points or "（题库未提供）"}

进阶得分点：
{advanced_points or "（题库未提供）"}

单题校准锚点（评分口径，仅供你判断「答到什么深度算好」，不要复述）：
{calibration_anchor or "（题库未提供）"}

考生原回答（仅供了解他漏了什么，不要逐句改写，也不要评价他）：
{candidate_answer or "（未作答）"}

请写一份示范作答。"""
    return await chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )
