"""
AI模拟面试与能力提升软件 - 评估服务（3号模块）
负责：AI评估 & 报告生成
端口：8001
接口：POST /evaluate
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
import re
from datetime import datetime

# 导入Prompt配置
from evaluation_prompts import get_evaluation_prompt, POSITION_CONFIG

app = Flask(__name__)
CORS(app)

# ============================================================
# 配置区域
# ============================================================

# ✅ 已填入你的 DeepSeek API Key
DEEPSEEK_API_KEY = "sk-3ae5f*****7a14"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# 1号后端的地址（用于获取面试详情等）
BACKEND_URL = "http://localhost:8000"

# ============================================================
# 核心评估接口
# ============================================================

@app.route('/evaluate', methods=['POST'])
def evaluate():
    """
    接收：{"position": "backend", "qa_list": [...]}
    返回：P3格式的评估报告
    """
    try:
        data = request.get_json()
        
        # 1. 校验参数
        if not data or 'qa_list' not in data:
            return jsonify({"error": "缺少 qa_list 参数"}), 400
        
        position = data.get('position', 'backend')
        qa_list = data.get('qa_list', [])
        
        # 校验岗位是否支持
        if position not in POSITION_CONFIG:
            return jsonify({"error": f"不支持的岗位：{position}。支持的岗位：{list(POSITION_CONFIG.keys())}"}), 400
        
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
        return jsonify(get_default_report()), 500


# ============================================================
# 辅助函数
# ============================================================

def build_dialogue_text(qa_list):
    """将qa_list拼接成对话文本"""
    dialogue = ""
    for qa in qa_list:
        dialogue += f"面试官：{qa.get('question', '')}\n"
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
            timeout=30
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


def get_default_report():
    """降级默认报告"""
    return {
        "total_score": 72.0,
        "tech_score": 72.0,
        "logic_score": 72.0,
        "expression_score": 72.0,
        "match_score": 72.0,
        "summary": "评估服务暂时不可用，这是系统生成的默认报告。请稍后重试或联系技术支持。",
        "strengths": ["完成了面试流程", "展示了基本的技术认知"],
        "weaknesses": ["评估系统暂时无法详细分析", "建议在服务恢复后重新面试"],
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
        "api_key_configured": True
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
    print(f"API Key 配置状态：✅ 已配置")
    print("=" * 60)
    print("服务启动中...")
    print(f"请访问 http://localhost:8001/health 检查服务状态")
    print(f"评估接口：POST http://localhost:8001/evaluate")
    print("=" * 60)
    app.run(host='0.0.0.0', port=8001, debug=True)
