// src/api/careerAnchor.js
import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { mockDelay } from './_mock'

const MOCK_QUESTIONS = {
    total: 20,
    questions: [
        { id: "q1", category: "interest", role: "backend", text: "我喜欢把业务规则拆成清晰的数据模型和接口边界。" },
        { id: "q2", category: "interest", role: "frontend", text: "我愿意反复打磨页面交互、视觉细节和操作路径。" },
        { id: "q3", category: "interest", role: "test_engineer", text: "我喜欢提前设计异常场景和验收标准。" },
        { id: "q4", category: "interest", role: "system_design", text: "我喜欢权衡模块边界、容量、扩展性和可用性。" },
        { id: "q5", category: "interest", role: "algorithm", text: "我愿意用数据和实验判断一个方案是否真的有效。" },
        { id: "q6", category: "interest", role: "backend", text: "看到一套服务稳定支撑高并发请求，我会很有成就感。" },
        { id: "q7", category: "interest", role: "frontend", text: "我享受把复杂功能整理成清晰、顺手的界面。" },
        { id: "q8", category: "interest", role: "test_engineer", text: "我愿意追查偶现问题，直到它能够稳定复现。" },
        { id: "q9", category: "interest", role: "system_design", text: "我对多个服务如何协作、部署和承受流量很感兴趣。" },
        { id: "q10", category: "interest", role: "algorithm", text: "我喜欢研究模型、特征或指标为什么发生变化。" },
        { id: "q11", category: "ability", role: "backend", text: "我能独立设计数据表、接口和基本的登录权限。" },
        { id: "q12", category: "ability", role: "frontend", text: "我能独立完成响应式页面、组件交互和状态联动。" },
        { id: "q13", category: "ability", role: "test_engineer", text: "我能独立设计测试用例、自动化脚本和回归检查。" },
        { id: "q14", category: "ability", role: "system_design", text: "我能拆分模块、画架构图并说明部署方案。" },
        { id: "q15", category: "ability", role: "algorithm", text: "我能完成数据清洗、模型训练和基本效果评估。" },
        { id: "q16", category: "ability", role: "backend", text: "遇到数据库异常、并发或消息堆积时，我知道从哪里排查。" },
        { id: "q17", category: "ability", role: "frontend", text: "遇到渲染、兼容性或网络请求问题时，我能定位到具体环节。" },
        { id: "q18", category: "ability", role: "test_engineer", text: "我能复现环境差异、边界输入和偶现缺陷。" },
        { id: "q19", category: "ability", role: "system_design", text: "我能分析服务依赖、资源瓶颈和扩展方案。" },
        { id: "q20", category: "ability", role: "algorithm", text: "遇到指标异常时，我能判断是数据、特征还是训练过程的问题。" }
    ],
    interest_ratings: [
        { value: 1, label: "完全不符合" },
        { value: 2, label: "不太符合" },
        { value: 3, label: "一般或不确定" },
        { value: 4, label: "比较符合" },
        { value: 5, label: "非常符合" }
    ],
    ability_ratings: [
        { value: 1, label: "目前做不到" },
        { value: 2, label: "需要较多帮助" },
        { value: 3, label: "基本了解，但不够独立" },
        { value: 4, label: "基本可以独立完成" },
        { value: 5, label: "能够稳定独立完成" }
    ]
}

const MOCK_POSITIONS = {
    backend: '后端开发工程师',
    frontend: '前端开发工程师',
    test_engineer: '测试开发工程师',
    algorithm: '算法工程师',
    system_design: '系统设计工程师'
}

const buildMockCareerResult = (answers) => {
    const codes = Object.keys(MOCK_POSITIONS)
    const interest = Object.fromEntries(codes.map(code => [code, 0]))
    const ability = Object.fromEntries(codes.map(code => [code, 0]))
    MOCK_QUESTIONS.questions.forEach((question, index) => {
        const bucket = question.category === 'interest' ? interest : ability
        bucket[question.role] += answers[index]
    })
    const normalize = raw => (raw - 6) / 4
    const scores = codes.map(code => {
        const interestNorm = normalize(interest[code])
        const abilityNorm = normalize(ability[code])
        const composite = interestNorm * 0.6 + abilityNorm * 0.4
        return {
            position: code,
            name: MOCK_POSITIONS[code],
            interest_raw: interest[code],
            ability_raw: ability[code],
            interest_norm: interestNorm,
            ability_norm: abilityNorm,
            composite,
            index: Math.round((composite + 1) * 50)
        }
    }).sort((a, b) =>
        b.composite - a.composite ||
        b.ability_norm - a.ability_norm ||
        b.interest_norm - a.interest_norm
    )
    let difference = 0
    let pairCount = 0
    codes.forEach(code => {
        ;['interest', 'ability'].forEach(category => {
            const values = []
            MOCK_QUESTIONS.questions.forEach((question, index) => {
                if (question.role === code && question.category === category) {
                    values.push(answers[index])
                }
            })
            if (values.length === 2) {
                difference += Math.abs(values[0] - values[1])
                pairCount += 1
            }
        })
    })
    const consistency = pairCount
        ? Math.round((1 - difference / (pairCount * 4)) * 100)
        : 0
    const margin = scores[0].index - scores[1].index
    const ambiguous = margin < 5
    const shortlist = scores.slice(0, 2).map(({ position, name, index }) => ({
        position, name, index
    }))
    return {
        decision: ambiguous ? 'ambiguous' : 'clear',
        recommended: ambiguous ? null : {
            position: scores[0].position,
            name: scores[0].name,
            index: scores[0].index,
            reason: '当前兴趣与能力自评更支持这个方向。'
        },
        shortlist,
        alternatives: scores.slice(1, 3).map(({ position, name, index }) => ({
            position, name, index
        })),
        scores,
        consistency_percent: consistency,
        confidence: ambiguous ? '低' : margin >= 10 ? '高' : '中',
        margin,
        title: ambiguous ? '方向暂不明确' : scores[0].name,
        narrative: ambiguous
            ? '当前前两个方向比较接近，建议分别体验后再决定。'
            : `当前更支持「${scores[0].name}」，建议先用模拟面试验证。`,
        signal_label: ambiguous ? '各方向区分度不足' : '存在相对更接近的方向',
        signal_narrative: ambiguous
            ? '主次分差较小，本次结果只适合作为初步线索。'
            : '主次方向有一定区分度，可结合项目经历进一步验证。',
        guide: ambiguous
            ? `可以先体验「${shortlist[0].name}」或「${shortlist[1].name}」。`
            : `可以先用「${scores[0].name}」开始一场模拟面试。`
    }
}

/**
 * 获取职业锚定测试题目
 */
export const getCareerAnchorQuestions = async () => {
    if (USE_MOCK) {
        await mockDelay(400)
        return MOCK_QUESTIONS
    }
    return request.get('/career-anchor/questions')
}

/**
 * 提交答案获取推荐岗位
 * @param {Array<number>} answers - 长度为 20 的数组，每项 1~5
 */
export const submitCareerAnchor = async (answers) => {
    if (USE_MOCK) {
        await mockDelay(800)
        return buildMockCareerResult(answers)
    }
    return request.post('/career-anchor/submit', { answers })
}
