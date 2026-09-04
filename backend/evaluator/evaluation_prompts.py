"""
AI模拟面试与能力提升软件 - 评估模块 Prompt 配置
负责：3号 - AI评估 & 报告生成
版本：v1.2
更新日期：2026-09-04

v1.2 变更：评分维度由 4 维扩展为 5 维（新增「应变能力」），
权重与维度定义源自团队《评估维度.csv》。

使用方式：
    from evaluation_prompts import get_evaluation_prompt, POSITION_CONFIG

    # 获取指定岗位的评估Prompt
    prompt = get_evaluation_prompt("backend", dialogue_text)

    # dialogue_text 格式：
    # 面试官：xxx\n候选人：xxx\n面试官：xxx\n候选人：xxx\n...

岗位 code 约定：
    岗位由主后端数据库 positions 表动态维护（当前：backend / frontend / test_engineer，
    另有 2 个预留位）。本文件的岗位 code 必须与数据库一致；
    数据库新增岗位时，若此处没有专属配置，评估自动使用通用模板兜底（不会 400）。
"""

import json
import sys
from pathlib import Path

# 本文件可能被 evaluator/app.py 导入，也可能被独立运行（__main__ 自测）：
# 确保 backend 目录在 sys.path，以便 import app.core 共享契约模块
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.evaluation_weights import (  # noqa: E402
    GENERIC_POSITION as _SHARED_GENERIC,
    POSITION_CONFIG as _SHARED_POSITION_CONFIG,
)

# ============================================================
# 岗位配置
# ============================================================
# 权重单一事实源在 app/core/evaluation_weights.py（源自团队《评估维度.csv》，
# 2026-09-04 定稿，5 维：技术水平/逻辑思维/沟通表达/应变能力/岗位匹配度）。
# 主后端 Mock 评分经该模块的 weights_for() 派生，修改权重只动那一处；
# tests/test_api.py 的 test_weights_match_csv 机器校验 CSV ↔ 代码一致性。
# 本文件只在其上叠加 Prompt 专属素材（key_points / position_desc）。
# ============================================================

_KEY_POINTS = {
    "backend": """Java基础（集合/并发/JVM）、Spring生态（IOC/AOP/事务）、MySQL数据库（索引/事务隔离/MVCC）、
Redis与缓存、分布式与微服务架构、系统设计与方案选型、排障Debug、编码与算法、
项目实践深挖、岗位软技能（故障应急响应意识）""",
    "frontend": """JavaScript/TypeScript基础（闭包/原型链/异步编程）、CSS布局（BFC/Flex/Grid）、
Vue.js/React框架原理（响应式/虚拟DOM）、浏览器渲染机制与网络协议、
前端性能优化（关键渲染路径/代码分割）、前端工程化（Webpack/Vite）与前端安全、
编码与算法、项目实践深挖、岗位软技能（用户体验意识）""",
    "test_engineer": """测试理论与方法（黑盒/白盒/等价类/边界值）、测试用例设计、
接口测试与自动化测试（Pytest/Selenium）、性能测试（压测指标/瓶颈分析）、
安全测试（OWASP Top 10）、CI/CD与DevOps、Linux/SQL基础、
编码与算法（测试脚本开发）、项目实践深挖、岗位软技能（质量风险预判）""",
}

_POSITION_DESCS = {
    "backend": "后端开发工程师，要求扎实的Java语言基础，熟悉Spring Boot/Cloud生态，掌握MySQL等关系型数据库，了解分布式系统和微服务架构，具备良好的系统设计、问题排查与编码能力。",
    "frontend": "前端开发工程师，要求扎实的HTML/CSS/JavaScript基础，熟悉至少一种主流框架（Vue/React），了解前端工程化和性能优化，具备良好的用户体验意识和跨端兼容性处理能力。",
    "test_engineer": "测试开发工程师，要求掌握软件测试理论和方法，熟悉自动化测试框架和工具，具备接口测试和性能测试经验，了解安全测试基本概念，有良好的质量意识和Bug追踪能力。",
}

POSITION_CONFIG = {
    code: {**config, "key_points": _KEY_POINTS.get(code, ""), "position_desc": _POSITION_DESCS.get(code, "")}
    for code, config in _SHARED_POSITION_CONFIG.items()
}

# 通用兜底配置：数据库新增岗位（如预留位启用）但尚无专属配置时使用
GENERIC_POSITION = {
    **_SHARED_GENERIC,
    "key_points": "暂无专属考察点配置，请按岗位通用能力（基础功底、问题分析、实践经验、沟通表达）综合评估",
    "position_desc": "该岗位暂无专属描述，请按候选人回答的专业性、条理性和与问题本身的契合度进行客观评估。",
}

# 无专属优秀范例时的说明（拼入 Prompt）
GENERIC_EXAMPLES_NOTE = "（该岗位暂无精选高分范例，请严格按各维度评分标准评估。）"


# ============================================================
# 优秀回答范例（从5号的Excel中精选）
# ============================================================

EXCELLENT_EXAMPLES = {
    "backend": """
【范例1 - HashMap原理】
问题：请简述Java中HashMap的底层数据结构，以及JDK 1.8对其做了哪些优化？
优秀回答：HashMap在JDK 1.7中采用数组+链表实现，通过键的hashCode计算数组下标，哈希冲突时使用链表存储。
JDK 1.8引入了红黑树优化：当链表长度超过8且数组长度达到64时，链表会转化为红黑树，将查询时间复杂度从O(n)降至O(log n)。
此外，1.8在扩容时采用高低位拆分法，避免了1.7中多线程环境下的死循环问题，同时使用尾插法替代头插法，保证了元素的相对顺序。
评分理由：准确描述了数据结构演变，说明了红黑树转换条件，对比了1.7和1.8的差异，技术深度充足。

【范例2 - Spring IOC】
问题：请解释Spring IOC容器的核心工作原理，Bean的生命周期包含哪些关键步骤？
优秀回答：Spring IOC通过反射机制将对象的创建和依赖关系交由容器管理，实现控制反转和依赖注入。
Bean生命周期关键步骤包括：实例化（通过构造器或工厂方法创建对象）、属性填充（依赖注入）、
Aware接口回调（如BeanNameAware）、BeanPostProcessor前置处理、初始化（执行init-method或@PostConstruct）、
BeanPostProcessor后置处理（AOP代理在此生成）、使用阶段、销毁（执行destroy-method或@PreDestroy）。
整个过程由BeanFactory或ApplicationContext驱动。
评分理由：完整描述了IOC原理和Bean生命周期各阶段，提到了AOP代理生成时机，体现了对Spring底层机制的理解。
""",
    "frontend": """
【范例1 - BFC】
问题：请简述CSS中BFC（块级格式化上下文）的概念，以及它在实际开发中有哪些应用场景？
优秀回答：BFC是一个独立的渲染区域，内部元素的布局不会影响外部元素，反之亦然。
触发BFC的条件包括：根元素、浮动元素、绝对/固定定位元素、display为inline-block/flex/grid、overflow不为visible等。
应用场景主要有：清除浮动以解决父元素高度塌陷问题；防止margin重叠（折叠）；
用于自适应两栏布局，避免文字环绕浮动元素。
评分理由：准确定义了BFC概念，完整列举了触发条件和应用场景，体现了解决实际布局问题的能力。

【范例2 - 闭包】
问题：JavaScript中的闭包是什么？请举例说明闭包的常见用途及可能带来的问题。
优秀回答：闭包是指一个函数能够访问其词法作用域外部变量的能力，通常表现为函数嵌套时内部函数引用了外部函数的变量。
常见用途包括：数据私有化（模拟私有变量）、函数柯里化、防抖节流等。
但闭包也会导致内存无法被及时回收，如果使用不当容易造成内存泄漏。例如在循环中绑定事件时未正确处理变量作用域，
或者闭包引用的DOM节点未释放，都会导致内存问题。因此使用闭包时需注意及时解除引用。
评分理由：清晰解释了闭包原理，列举了多种用途，同时指出了内存泄漏风险及解决方案，展现了全面的理解。
""",
    "test_engineer": """
【范例1 - 黑盒白盒测试】
问题：请简述黑盒测试和白盒测试的区别，并列举黑盒测试的常用方法。
优秀回答：黑盒测试将软件视为黑盒子，只关注输入和输出，不考虑内部实现逻辑，主要验证功能是否符合需求。
白盒测试则关注代码内部的逻辑结构和执行路径，验证代码覆盖率和逻辑正确性。
黑盒测试常用方法包括：等价类划分（将输入数据分为有效等价类和无效等价类）、边界值分析（关注输入输出的边界值）、
判定表（分析条件组合与对应动作）、因果图（分析输入条件与输出结果的因果关系）、状态迁移（分析系统状态转换）、错误推测（基于经验推测可能出错的地方）。
白盒测试常用方法包括语句覆盖、判定覆盖、条件覆盖、路径覆盖等。
评分理由：清晰对比了两种测试方法，完整列举了黑盒测试的各种方法，对测试理论有扎实的理解。

【范例2 - 接口测试流程】
问题：如何进行API接口测试？请描述接口测试的完整流程和常用工具。
优秀回答：接口测试完整流程包括：1）需求分析：理解接口文档，明确输入输出和业务逻辑；
2）测试用例设计：功能测试（正常/异常参数）、边界值、安全性（SQL注入、XSS）、权限控制、数据一致性；
3）测试数据准备：构造各种测试数据集；
4）脚本编写：使用Postman进行手动测试，Requests+Pytest编写自动化脚本；
5）执行与断言：检查HTTP状态码、响应体、响应时间、数据库状态；
6）结果分析：生成测试报告，跟踪Bug。
常用工具包括Postman（接口调试和冒烟测试）、JMeter（性能测试）、Requests+Pytest（自动化测试）、Mock服务（处理第三方依赖）。
评分理由：完整描述了接口测试全流程，从需求到报告形成闭环，工具选型合理，体现了系统性的测试思维。
"""
}


# ============================================================
# Prompt 模板
# ============================================================

def build_position_prompt(position_key, dialogue_text):
    """
    根据岗位和对话内容，构建完整的评估Prompt

    参数：
        position_key: 岗位 code（如 backend / frontend / test_engineer），
                      由主后端数据库动态下发；未知 code 自动使用通用模板兜底
        dialogue_text: 格式为 "面试官：xxx\n候选人：xxx\n面试官：xxx\n候选人：xxx\n..."

    返回：
        完整的Prompt字符串，可直接发送给DeepSeek API
    """
    # 岗位由主后端数据库 positions 表动态维护：无专属配置时用通用模板兜底，绝不抛错
    config = POSITION_CONFIG.get(position_key)
    if config is None:
        config = {**GENERIC_POSITION, "name": f"「{position_key}」岗位"}

    # 从配置中提取权重（5 维：技术/逻辑/表达/应变/匹配）
    wt = config["weight_tech"]
    wl = config["weight_logic"]
    we = config["weight_expression"]
    wa = config["weight_adaptability"]
    wm = config["weight_match"]

    # 获取对应的优秀范例（无专属范例时给说明文字）
    examples = EXCELLENT_EXAMPLES.get(position_key, GENERIC_EXAMPLES_NOTE)
    
    prompt = f"""你是一位资深的技术面试评估专家，有10年以上的一线互联网公司面试官经验。你精通{config['name']}岗位的能力评估，擅长从候选人的回答中精准识别技术深度、逻辑严谨性和沟通表达能力。

【任务】
根据候选人在模拟面试中的完整问答记录，对其表现进行多维度量化评估，输出结构化的JSON报告。

【岗位信息】
岗位名称：{config['name']}
岗位要求：{config['position_desc']}
核心考察点：{config['key_points']}

【面试问答记录】
{dialogue_text}

【各维度评分标准】

1. tech_score（技术正确性与深度，权重{wt}%，0-100分）：
   - 90-100分：回答完全正确，理解底层原理，能举一反三，有实际项目经验支撑
   - 70-89分：回答基本正确，知识掌握扎实，但缺乏深度原理剖析
   - 50-69分：回答有部分错误或遗漏，概念理解不够准确
   - 0-49分：回答错误或答非所问，技术概念混淆

2. logic_score（逻辑思维严谨性，权重{wl}%，0-100分）：
   - 90-100分：回答结构清晰，分层递进，因果逻辑严密
   - 70-89分：回答有条理，思路基本清晰，偶尔有跳跃
   - 50-69分：逻辑不够清晰，前后有矛盾或重复
   - 0-49分：逻辑混乱，无法理解表达的重点

3. expression_score（表达沟通能力，权重{we}%，0-100分）：
   - 90-100分：语言简洁精准，术语使用得当，表述流畅自然
   - 70-89分：表达清楚，能传递核心信息，略有冗余
   - 50-69分：表达含糊，用词不够准确，需要反复解释
   - 0-49分：表达困难，无法清晰传达意图

4. adaptability_score（应变能力，权重{wa}%，0-100分）：
   - 90-100分：面对追问反应敏捷，能迅速调整思路、举一反三，抗压能力强
   - 70-89分：能跟上追问节奏，补充说明基本到位，偶有迟疑
   - 50-69分：追问时思路调整缓慢，出现明显卡顿或重复表述
   - 0-49分：面对追问慌乱无措，答非所问或无法应对

5. match_score（岗位匹配度，权重{wm}%，0-100分）：
   - 90-100分：回答深度契合岗位要求，展现出扎实的岗位核心能力
   - 70-89分：基本符合岗位要求，有相关知识和经验
   - 50-69分：与岗位要求部分匹配，有知识缺口
   - 0-49分：回答与岗位要求关联度低

【优秀回答范例参考】
以下是该岗位的高分回答特征，请以此为标准进行评分：
{examples}

【评分注意事项】
1. 如果候选人的回答少于20个字，或明显答非所问，该题对应维度直接判为低分（<40分），并在weaknesses中注明"回答质量不足，建议补充相关知识"。
2. total_score为综合总分，由各维度加权计算得出，不要直接填写平均值。
3. 优缺点和建议要具体、有针对性，避免泛泛而谈。
4. strengths至少列出2条，weaknesses至少列出1条，suggestions至少列出2条。

【输出要求】
请严格按照以下JSON格式输出评估报告，不要包含任何其他解释性文字或Markdown标记。这是硬性要求，你的回复中只能包含纯JSON数据。

{{
    "total_score": 84.5,
    "tech_score": 88.0,
    "logic_score": 83.0,
    "expression_score": 80.0,
    "adaptability_score": 82.0,
    "match_score": 87.0,
    "summary": "综合评语：概括整体表现，总字数控制在80-120字之间",
    "strengths": ["优点1：具体描述候选人的亮点表现", "优点2", "优点3"],
    "weaknesses": ["不足1：具体描述需要改进的地方", "不足2"],
    "suggestions": [
        "改进建议1：针对不足1给出可操作的学习建议，推荐具体学习资源",
        "改进建议2：针对不足2给出具体的学习方向和练习建议",
        "改进建议3：通用提升建议"
    ]
}}"""
    
    return prompt


# ============================================================
# 题库素材说明（供评分 Prompt 参考）
# ============================================================

# 抽题由后端开发 B（AI专项1）的面试官对话逻辑负责：
# 从 questions 表按岗位/阶段/难度抽题，约定见 docs/REPORT_TO_P2.md。
# 评分可用素材（得分点三段加权 / 参考答案 / 追问触发条件 / 优秀回答范例）
# 见 docs/QUESTION_BANK_REVIEW_V13.md 与 docs/REPORT_TO_P3.md。


# ============================================================
# 对外接口
# ============================================================

def get_evaluation_prompt(position_key, dialogue_text):
    """
    统一接口：获取指定岗位的评估Prompt

    参数：
        position_key: 岗位 code（数据库动态下发，未知 code 用通用模板兜底）
        dialogue_text: 面试对话全文

    返回：
        完整的评估Prompt字符串
    """
    return build_position_prompt(position_key, dialogue_text)


def get_position_list():
    """获取所有支持的岗位列表"""
    return list(POSITION_CONFIG.keys())


def get_position_config(position_key):
    """获取指定岗位的配置信息"""
    return POSITION_CONFIG.get(position_key, None)


# ============================================================
# 测试代码（运行时可验证配置是否正确）
# ============================================================

if __name__ == "__main__":
    # 模拟对话数据
    test_dialogue = """面试官：请做一下自我介绍
候选人：我是XX大学计算机专业2025届毕业生，主修Java后端开发，有3个完整的项目经历，包括一个基于Spring Cloud的电商项目。

面试官：请简述Java中HashMap的底层数据结构
候选人：HashMap在JDK 1.7中采用数组+链表实现，JDK 1.8引入了红黑树优化，当链表长度超过8且数组长度达到64时转换为红黑树，查询复杂度从O(n)降至O(log n)。"""
    
    # 测试三个岗位
    for key in POSITION_CONFIG.keys():
        print(f"=" * 60)
        print(f"岗位：{POSITION_CONFIG[key]['name']}")
        print(f"=" * 60)
        prompt = get_evaluation_prompt(key, test_dialogue)
        print(prompt)
        print("\n\n")
    
    # 打印配置摘要
    print("=" * 60)
    print("配置摘要（权重可在此调整）")
    print("=" * 60)
    for key, config in POSITION_CONFIG.items():
        print(
            f"{config['name']}：技术{config['weight_tech']}% / 逻辑{config['weight_logic']}% / "
            f"表达{config['weight_expression']}% / 应变{config['weight_adaptability']}% / "
            f"匹配{config['weight_match']}%"
        )
