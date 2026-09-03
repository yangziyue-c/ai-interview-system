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
        
        # 5. 补充表达分析（语音特征）
        expression_result = analyze_expression_simulate(qa_list)
        
        # 6. 合并报告
        final_report = merge_report(report, expression_result, position)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 评估完成 - 总分：{final_report.get('total_score', 'N/A')}")
        
        return jsonify(final_report)
        
    except Exception as e:
        print(f"评估失败：{e}")
        return jsonify(get_default_report(qa_list)), 500


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
        
        # 验证必要字段
        required_fields = ['total_score', 'tech_score', 'logic_score', 
                          'expression_score', 'match_score', 'summary', 
                          'strengths', 'weaknesses', 'suggestions']
        for field in required_fields:
            if field not in report:
                print(f"⚠️ 大模型返回缺少字段：{field}，使用默认值")
                report[field] = get_default_value(field)
        
        return report
        
    except requests.exceptions.Timeout:
        print("⚠️ 大模型调用超时（30秒），使用默认报告")
        return get_default_report()
    except Exception as e:
        print(f"⚠️ 大模型调用异常：{e}")
        return get_default_report()


def analyze_expression_simulate(qa_list):
    """
    表达分析 - 模拟版本
    后续可升级为真实ASR（讯飞/阿里云/百度等）
    """
    total_chars = 0
    total_answers = 0
    for qa in qa_list:
        answer = qa.get('answer', '')
        total_chars += len(answer)
        if answer.strip():
            total_answers += 1
    
    avg_len = total_chars / max(total_answers, 1)
    
    if avg_len > 50:
        expr_score = 82
        speed = "正常"
        fluency = "良好"
        confidence = "自信"
    elif avg_len > 20:
        expr_score = 70
        speed = "正常"
        fluency = "一般"
        confidence = "一般"
    else:
        expr_score = 55
        speed = "偏慢"
        fluency = "一般"
        confidence = "略显紧张"
    
    return {
        "expression_score": expr_score,
        "speech_details": {
            "speed": speed,
            "fluency": fluency,
            "confidence": confidence,
            "avg_answer_length": round(avg_len, 1)
        }
    }


def merge_report(llm_report, expr_result, position):
    """合并大模型评估结果和语音分析结果"""
    # 最终表达分：使用语音分析的结果
    final_expression = expr_result.get('expression_score', 75)
    
    report = {
        "total_score": llm_report.get('total_score', 75.0),
        "tech_score": llm_report.get('tech_score', 75.0),
        "logic_score": llm_report.get('logic_score', 75.0),
        "expression_score": final_expression,
        "match_score": llm_report.get('match_score', 75.0),
        "summary": llm_report.get('summary', '表现中规中矩，建议加强练习。'),
        "strengths": llm_report.get('strengths', ['回答问题有一定条理', '具备基本的技术知识']),
        "weaknesses": llm_report.get('weaknesses', ['部分回答可以更加深入', '表达能力有提升空间']),
        "suggestions": llm_report.get('suggestions', [
            '建议多练习技术深度问题的回答',
            '可以参考岗位要求进行针对性学习',
            '建议录制自己的回答回听，提升表达流畅度'
        ]),
        "_speech_details": expr_result.get('speech_details', {})
    }
    
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
    """获取默认字段值"""
    defaults = {
        'total_score': 75.0,
        'tech_score': 75.0,
        'logic_score': 75.0,
        'expression_score': 75.0,
        'match_score': 75.0,
        'summary': '评估服务暂时部分异常，这是系统生成的默认报告。请稍后重新尝试面试获取更精准的评估。',
        'strengths': ['完成了面试流程', '回答有一定条理'],
        'weaknesses': ['评估系统暂时无法详细分析部分维度'],
        'suggestions': ['建议重新尝试面试', '或联系技术支持']
    }
    return defaults.get(field, 'N/A')


def get_default_report(qa_list=None):
    """降级默认报告：按平均回答篇幅分档，避免所有失败都返回相同分数"""
    qa_list = qa_list or []
    answered = [qa.get("answer", "") for qa in qa_list if (qa.get("answer") or "").strip()]
    avg_len = sum(len(a) for a in answered) / len(answered) if answered else 0
    if avg_len >= 60:
        score, comment = 78.0, "回答较充实"
    elif avg_len >= 20:
        score, comment = 68.0, "回答篇幅适中"
    else:
        score, comment = 58.0, "回答偏简略"
    return {
        "total_score": score,
        "tech_score": score,
        "logic_score": score,
        "expression_score": score,
        "match_score": score,
        "summary": f"评估服务暂时不可用，系统已按回答篇幅生成临时报告（{comment}）。请稍后重试或联系技术支持。",
        "strengths": ["完成了面试流程", "展示了基本的技术认知"],
        "weaknesses": ["评估服务暂时无法详细分析", "建议在服务恢复后重新面试"],
        "suggestions": ["重新尝试面试", "或联系技术支持获取帮助"]
    }


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
