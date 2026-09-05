"""
AI模拟面试与能力提升软件 - 评估服务（3号模块，独立进程）
负责：AI评估 & 报告生成
端口：8002（主后端在 8001，本服务仅供主后端内网调用，勿改回 8001）
接口：POST /evaluate

启动方式：
- 由 backend/start.py 自动拉起（推荐）
- 手动：cd backend && python evaluator/app.py
"""
import os
import sys
from pathlib import Path

# Windows 控制台默认 GBK 编码，print 含 emoji/生僻字会抛 UnicodeEncodeError；
# 统一把 stdout 重配置为 UTF-8（根因修复，勿改为删除 emoji 的绕过写法）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
from datetime import datetime

# 导入Prompt配置
from evaluation_prompts import get_evaluation_prompt, POSITION_CONFIG
from app.core.evaluation_weights import build_fallback_report, weights_for

app = Flask(__name__)
CORS(app)

# ============================================================
# 配置区域
# ============================================================

# 端口约定：主后端 8001，本服务 8002（同机部署）
EVALUATOR_PORT = 8002


def _load_api_key() -> str:
    """从环境变量 / backend/.env 读取 DeepSeek API Key

    协作约定：API Key 严禁硬编码提交（见 docs/COLLABORATION.md）。
    读取顺序：环境变量 DEEPSEEK_API_KEY > LLM_API_KEY > backend/.env 的 LLM_API_KEY
    （与主后端共享同一个 Key，填入 backend/.env 的 LLM_API_KEY 即可）。
    """
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    if key:
        return key
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("LLM_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


DEEPSEEK_API_KEY = _load_api_key()
DEEPSEEK_API_URL = os.environ.get(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
)

# ============================================================
# 核心评估接口
# ============================================================

@app.route('/evaluate', methods=['POST'])
def evaluate():
    """
    接收：{"position": "backend", "qa_list": [...]}
    返回：P3格式的评估报告
    """
    qa_list: list = []  # 提前初始化：JSON 解析失败等异常发生在赋值前时，兜底分支引用安全
    position = ""  # 同上：except 分支 get_default_report(qa_list, position) 需要引用
    try:
        data = request.get_json()

        # 1. 校验参数
        if not data or 'qa_list' not in data:
            return jsonify({"error": "缺少 qa_list 参数"}), 400
        
        position = data.get('position', 'backend')
        qa_list = data.get('qa_list', [])

        # 岗位由主后端数据库动态下发：未知 code 时评估使用通用模板兜底（不拒绝）
        # 仅当岗位缺失或为空时返回 400
        if not isinstance(position, str) or not position.strip():
            return jsonify({"error": "position 参数缺失"}), 400

        if len(qa_list) == 0:
            return jsonify({"error": "qa_list 不能为空"}), 400
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始评估 - 岗位：{position}，问答数：{len(qa_list)}")
        
        # 2. 构建对话文本
        dialogue_text = build_dialogue_text(qa_list)
        
        # 3. 获取评估Prompt
        prompt = get_evaluation_prompt(position, dialogue_text)
        
        # 4. 调用大模型生成评估报告
        report = call_llm_for_evaluation(prompt)
        
        # 5. 模拟语音特征附加信息（不参与表达评分，见 analyze_expression_simulate 说明）
        speech_result = analyze_expression_simulate(qa_list)

        # 6. 合并报告（表达分以 LLM 评估为准，total 按岗位权重确定性重算）
        final_report = merge_report(report, speech_result, position)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 评估完成 - 总分：{final_report.get('total_score', 'N/A')}")
        
        return jsonify(final_report)
        
    except Exception as e:
        print(f"评估失败：{e}")
        return jsonify(get_default_report(qa_list, position)), 500


# ============================================================
# 辅助函数
# ============================================================

def build_dialogue_text(qa_list):
    """将qa_list拼接成对话文本（带轮次标记，帮助模型理解追问链）"""
    dialogue = ""
    for qa in qa_list:
        round_no = qa.get("round")
        tag = f"（第{round_no}轮）" if round_no is not None else ""
        dialogue += f"面试官{tag}：{qa.get('question', '')}\n"
        dialogue += f"候选人：{qa.get('answer', '')}\n"
    return dialogue


# 报告字段契约：单一字典（默认值），校验补齐与默认值查询都从它派生
_SCORE_FIELDS = ('total_score', 'tech_score', 'logic_score',
                 'expression_score', 'adaptability_score', 'match_score')
_REPORT_FIELDS = {
    'total_score': 75.0,
    'tech_score': 75.0,
    'logic_score': 75.0,
    'expression_score': 75.0,
    'adaptability_score': 75.0,
    'match_score': 75.0,
    'summary': '评估服务暂时部分异常，这是系统生成的默认报告。请稍后重新尝试面试获取更精准的评估。',
    'strengths': ['完成了面试流程', '回答有一定条理'],
    'weaknesses': ['评估系统暂时无法详细分析部分维度'],
    'suggestions': ['建议重新尝试面试', '或联系技术支持']
}


def call_llm_for_evaluation(prompt):
    """调用DeepSeek API生成评估报告"""
    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是一位客观严谨的技术面试评估专家，只输出JSON格式数据，不包含任何其他文字。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"}
            },
            # 主后端对评估的兜底超时为 30 秒，这里必须小于它：
            # 超时后返回默认报告(200)，保证主后端在 30 秒内总能拿到结果
            timeout=25
        )
        
        if response.status_code != 200:
            print(f"API调用失败，状态码：{response.status_code}")
            print(f"返回内容：{response.text}")
            return get_default_report()
        
        result = response.json()
        content = result['choices'][0]['message']['content']
        content = clean_json_content(content)
        report = json.loads(content)
        
        # 校验补齐：键缺失 / 值为 null / 分数非 0~100 数值（bool/Infinity/NaN 均非法）→ 补默认值
        # （下游 merge_report 与主后端直接消费，此处保证契约完整）
        if not isinstance(report, dict):
            print(f"⚠️ 大模型返回非对象 JSON（{type(report).__name__}），使用默认报告")
            return get_default_report()
        for field, default in _REPORT_FIELDS.items():
            value = report.get(field)
            if field in _SCORE_FIELDS:
                is_valid = (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and 0 <= value <= 100  # NaN/±inf 比较均为 False，一并拦截
                )
            else:
                is_valid = value is not None
            if not is_valid:
                print(f"⚠️ 大模型返回字段缺失或越界：{field}，使用默认值")
                report[field] = default

        return report

    except requests.exceptions.Timeout:
        print("⚠️ 大模型调用超时（30秒），使用默认报告")
        return get_default_report()
    except Exception as e:
        print(f"⚠️ 大模型调用异常：{e}")
        import traceback
        traceback.print_exc()  # 保留堆栈便于排障，不要吞掉编程错误
        return get_default_report()


def analyze_expression_simulate(qa_list):
    """
    表达附加信息 - 模拟版本（真实 ASR 接入前的占位）

    只产出语音特征的模拟参考（语速/流畅度/自信度，simulated=True 供前端识别），
    不再产出/覆盖表达分：表达分以 LLM 按对话文本评估为准——评分标准奖励
    「语言简洁精准」，而按回答字数的启发式与它方向相反（精炼作答会被误判低分），
    故移除覆盖逻辑。接入真实 ASR 后，再由语音特征替代 LLM 文本评估
    （届时在 merge_report 恢复覆盖）。
    """
    # avg_len 口径与共享契约 build_fallback_report（evaluation_weights.py）一致：
    # 空答跳过、长度按 strip 后字符累计，避免代码块换行缩进使篇幅虚高
    total_chars = 0
    total_answers = 0
    for qa in qa_list:
        answer = qa.get('answer', '')
        if answer.strip():
            total_chars += len(answer.strip())
            total_answers += 1

    avg_len = total_chars / max(total_answers, 1)

    if avg_len > 50:
        speed = "正常"
        fluency = "良好"
        confidence = "自信"
    elif avg_len > 20:
        speed = "正常"
        fluency = "一般"
        confidence = "一般"
    else:
        speed = "偏慢"
        fluency = "一般"
        confidence = "略显紧张"

    return {
        "simulated": True,  # 模拟参考值，非真实语音分析结果
        "speech_details": {
            "speed": speed,
            "fluency": fluency,
            "confidence": confidence,
            "avg_answer_length": round(avg_len, 1)
        }
    }


def merge_report(llm_report, expr_result, position):
    """合并大模型评估结果与语音分析附加信息（5 维）

    表达分以 LLM 文本评估为准（不再被模拟语音分覆盖——按字数的启发式与
    「简洁精准」评分标准方向相反，见 analyze_expression_simulate 说明；
    接入真实 ASR 后恢复语音覆盖）。total_score 不信任 LLM 心算值，
    用最终 5 维按岗位权重重新计算（与共享契约 build_fallback_report 同口径），
    保证报告内部恒满足 total_score = Σ(维度分 × 权重)。
    """
    # 字段完整性由 call_llm_for_evaluation 的契约校验保证，这里直接取值
    report = {
        "tech_score": llm_report['tech_score'],
        "logic_score": llm_report['logic_score'],
        "expression_score": llm_report['expression_score'],
        "adaptability_score": llm_report['adaptability_score'],
        "match_score": llm_report['match_score'],
        "summary": llm_report['summary'],
        "strengths": llm_report['strengths'],
        "weaknesses": llm_report['weaknesses'],
        "suggestions": llm_report['suggestions'],
        "_speech_details": expr_result.get('speech_details', {})
    }
    # 权重单一事实源 app/core/evaluation_weights.py，未知岗位自动用通用权重兜底
    w = weights_for(position)
    report["total_score"] = round(
        report["tech_score"] * w["tech"]
        + report["logic_score"] * w["logic"]
        + report["expression_score"] * w["expression"]
        + report["adaptability_score"] * w["adaptability"]
        + report["match_score"] * w["match"],
        1,
    )
    return report


def clean_json_content(text):
    """去除Markdown标记"""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def get_default_value(field):
    """获取默认字段值（由单一契约字典 _REPORT_FIELDS 派生）"""
    return _REPORT_FIELDS.get(field, 'N/A')


def get_default_report(qa_list=None, position=""):
    """降级默认报告：按平均回答篇幅分档（分档口径与主后端 Mock 共用）

    position 用于 5 维加权；未知岗位回退通用权重。
    """
    return build_fallback_report(position, qa_list or [], summary_prefix="评估服务暂时不可用")


# ============================================================
# 健康检查
# ============================================================

@app.route('/health', methods=['GET'])
def health():
    """服务健康检查"""
    return jsonify({
        "status": "healthy",
        "service": "AI Evaluator",
        "supported_positions": list(POSITION_CONFIG.keys()),
        "api_key_configured": bool(DEEPSEEK_API_KEY)
    })


@app.route('/positions', methods=['GET'])
def get_positions():
    """获取支持的岗位列表（供前端/1号调用）"""
    return jsonify({
        "positions": [
            {"key": key, "name": config['name']} 
            for key, config in POSITION_CONFIG.items()
        ]
    })


# ============================================================
# 启动服务
# ============================================================

if __name__ == '__main__':
    print("=" * 60)
    print("AI 模拟面试 - 评估服务 (3号模块)")
    print("=" * 60)
    print(f"支持的岗位：{', '.join([config['name'] for config in POSITION_CONFIG.values()])}")
    print(f"API Key 配置状态：{'✅ 已配置' if DEEPSEEK_API_KEY else '❌ 未配置（评估将返回降级报告）'}")
    print("=" * 60)
    print("服务启动中...")
    print(f"请访问 http://localhost:{EVALUATOR_PORT}/health 检查服务状态")
    print(f"评估接口：POST http://localhost:{EVALUATOR_PORT}/evaluate")
    print("=" * 60)
    # debug=False：本服务由 start.py 子进程管理，reloader 会产生额外子进程导致无法正常退出
    app.run(host='0.0.0.0', port=EVALUATOR_PORT, debug=False)
