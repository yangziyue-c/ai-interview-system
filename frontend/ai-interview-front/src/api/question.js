// src/api/question.js
import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { mockDelay } from './_mock'

// Mock 题库（15 题：5 岗位 × 3 难度）
const MOCK_QUESTIONS = [
    // 后端
    {
        id: 1, position_code: 'backend', question_no: 'JAVA_BACKEND-Q0001',
        category: '技术知识题', difficulty: 'easy', interview_stage: '开场热身',
        suggested_minutes: 2,
        question: 'JVM、JDK、JRE 三者有什么区别和联系？',
        keywords: 'JVM\nJDK\nJRE',
        exam_priority: '高频必考题',
        basic_score_points: 'JVM 是运行字节码的虚拟机；JRE 包含 JVM + 核心类库；JDK 包含 JRE + 开发工具。',
        advanced_score_points: '能说清三者包含关系，并举出 javac、jar 等具体工具。',
        follow_up_l1: '[追问] 你提到 JVM，能具体说说它在整个体系中的位置吗？',
        calibration_anchor: '[技术水平] 能准确阐述三者包含关系。'
    },
    {
        id: 2, position_code: 'backend', question_no: 'JAVA_BACKEND-Q0002',
        category: '技术知识题', difficulty: 'medium', interview_stage: '核心考察',
        suggested_minutes: 5,
        question: 'MySQL 索引有哪些类型？什么情况下索引会失效？',
        keywords: 'MySQL\n索引\nB+树',
        exam_priority: '高频必考题',
        basic_score_points: '能说出主键索引、唯一索引、普通索引、联合索引等基本分类。',
        advanced_score_points: '能举出索引失效的常见场景：字段类型转换、前置模糊、函数运算等。',
        follow_up_l1: '[追问] 为什么 MySQL 索引用 B+ 树而不是 B 树？',
        calibration_anchor: '[技术水平] 能举出至少 3 种索引失效场景。'
    },
    {
        id: 3, position_code: 'backend', question_no: 'JAVA_BACKEND-Q0003',
        category: '场景应用题', difficulty: 'hard', interview_stage: '深度压轴',
        suggested_minutes: 10,
        question: '如何设计一个支持千万级用户的短链接系统？',
        keywords: '短链接\n高并发\n分布式',
        exam_priority: '拓展题',
        basic_score_points: '能拆解出发号器、存储、跳转三个核心模块。',
        advanced_score_points: '能讨论发号策略、缓存设计、热点链接等进阶问题。',
        follow_up_l1: '[追问] 发号器怎么保证分布式环境下不重复？',
        calibration_anchor: '[技术水平] 能从容量、并发、可用性三个维度拆解。'
    },
    // 前端
    {
        id: 4, position_code: 'frontend', question_no: 'FRONTEND-Q0001',
        category: '技术知识题', difficulty: 'easy', interview_stage: '开场热身',
        suggested_minutes: 2,
        question: 'Vue3 和 Vue2 有哪些主要区别？',
        keywords: 'Vue3\nComposition API\nProxy',
        exam_priority: '高频必考题',
        basic_score_points: '能说出响应式原理从 Object.defineProperty 改为 Proxy。',
        advanced_score_points: '能补充 Composition API、Tree-shaking、Fragment 等改进。',
        follow_up_l1: '[追问] Proxy 相比 Object.defineProperty 有哪些优势？',
        calibration_anchor: '[技术水平] 能至少说出 3 项主要区别。'
    },
    {
        id: 5, position_code: 'frontend', question_no: 'FRONTEND-Q0002',
        category: '技术知识题', difficulty: 'medium', interview_stage: '核心考察',
        suggested_minutes: 5,
        question: '什么是闭包？在实际开发中有什么用？',
        keywords: '闭包\n作用域\n内存',
        exam_priority: '高频必考题',
        basic_score_points: '能说清闭包是"函数 + 其引用的外部变量"。',
        advanced_score_points: '能举例说明闭包在防抖、柯里化、模块封装中的应用。',
        follow_up_l1: '[追问] 闭包会带来内存泄漏吗？怎么避免？',
        calibration_anchor: '[技术水平] 能结合实际场景说明闭包用途。'
    },
    {
        id: 6, position_code: 'frontend', question_no: 'FRONTEND-Q0003',
        category: '场景应用题', difficulty: 'hard', interview_stage: '深度压轴',
        suggested_minutes: 10,
        question: '首屏加载 5 秒怎么优化？',
        keywords: '性能优化\n首屏\n懒加载',
        exam_priority: '拓展题',
        basic_score_points: '能说出减少资源体积、路由懒加载、CDN 等方向。',
        advanced_score_points: '能谈到 SSR、预渲染、关键 CSS 内联、资源优先级等进阶手段。',
        follow_up_l1: '[追问] 如何量化优化效果？',
        calibration_anchor: '[技术水平] 能分"资源、网络、渲染"三个方向分析。'
    },
    // 测试
    {
        id: 7, position_code: 'test_engineer', question_no: 'TEST-Q0001',
        category: '技术知识题', difficulty: 'easy', interview_stage: '开场热身',
        suggested_minutes: 2,
        question: '你如何设计一个登录页面的测试用例？',
        keywords: '测试用例\n登录',
        exam_priority: '高频必考题',
        basic_score_points: '能区分正常流、异常流、边界场景。',
        advanced_score_points: '能补充安全场景：SQL 注入、XSS、暴力破解。',
        follow_up_l1: '[追问] 如果需求没写清，你会怎么补全用例？',
        calibration_anchor: '[技术水平] 用例覆盖正常、异常、边界三类。'
    },
    {
        id: 8, position_code: 'test_engineer', question_no: 'TEST-Q0002',
        category: '技术知识题', difficulty: 'medium', interview_stage: '核心考察',
        suggested_minutes: 5,
        question: '自动化测试框架你用过哪些？如何选型？',
        keywords: '自动化测试\nSelenium\nPytest',
        exam_priority: '高频必考题',
        basic_score_points: '能列举常见框架及其适用场景。',
        advanced_score_points: '能从团队能力、项目特点、维护成本三个角度论证选型。',
        follow_up_l1: '[追问] UI 自动化的稳定性怎么保证？',
        calibration_anchor: '[技术水平] 能结合项目经验说明选型理由。'
    },
    {
        id: 9, position_code: 'test_engineer', question_no: 'TEST-Q0003',
        category: '场景应用题', difficulty: 'hard', interview_stage: '深度压轴',
        suggested_minutes: 10,
        question: '发现线上一个偶现 bug，你的排查思路是什么？',
        keywords: '偶现\n排查\n日志',
        exam_priority: '拓展题',
        basic_score_points: '能从日志、复现步骤、环境差异三方面入手。',
        advanced_score_points: '能谈到加监控、A/B 对比、灰度验证等系统性手段。',
        follow_up_l1: '[追问] 如果日志里找不到线索，怎么办？',
        calibration_anchor: '[技术水平] 排查思路有条理，先复现再定位。'
    },
    // 算法
    {
        id: 10, position_code: 'algorithm', question_no: 'ALGO-Q0001',
        category: '技术知识题', difficulty: 'easy', interview_stage: '开场热身',
        suggested_minutes: 2,
        question: '常见排序算法的时间复杂度分别是多少？',
        keywords: '排序\n时间复杂度',
        exam_priority: '高频必考题',
        basic_score_points: '能列出快排、归并、堆排序的 O(n log n) 及稳定性。',
        advanced_score_points: '能分析不同场景下的取舍（内存/稳定/最坏情况）。',
        follow_up_l1: '[追问] 快排的最坏情况怎么触发的？',
        calibration_anchor: '[技术水平] 至少说清 3 种排序的复杂度与稳定性。'
    },
    {
        id: 11, position_code: 'algorithm', question_no: 'ALGO-Q0002',
        category: '技术知识题', difficulty: 'medium', interview_stage: '核心考察',
        suggested_minutes: 5,
        question: '过拟合怎么解决？',
        keywords: '过拟合\n正则化\nDropout',
        exam_priority: '高频必考题',
        basic_score_points: '能说出数据增强、正则化、Dropout、早停等手段。',
        advanced_score_points: '能结合模型复杂度与数据量解释过拟合本质。',
        follow_up_l1: '[追问] L1 和 L2 正则化有什么区别？',
        calibration_anchor: '[技术水平] 能从数据和模型两个维度分析。'
    },
    {
        id: 12, position_code: 'algorithm', question_no: 'ALGO-Q0003',
        category: '场景应用题', difficulty: 'hard', interview_stage: '深度压轴',
        suggested_minutes: 10,
        question: '如何评估一个推荐系统的效果？',
        keywords: '推荐系统\n评估\nA/B 测试',
        exam_priority: '拓展题',
        basic_score_points: '能说出准确率、召回率、AUC 等离线指标。',
        advanced_score_points: '能补充线上 A/B 测试、CTR、留存率等业务指标。',
        follow_up_l1: '[追问] 离线指标好但线上效果差，怎么排查？',
        calibration_anchor: '[技术水平] 能区分离线指标与线上指标。'
    },
    // 系统设计
    {
        id: 13, position_code: 'system_design', question_no: 'SYS-Q0001',
        category: '技术知识题', difficulty: 'easy', interview_stage: '开场热身',
        suggested_minutes: 2,
        question: '什么是 CAP 理论？',
        keywords: 'CAP\n分布式',
        exam_priority: '高频必考题',
        basic_score_points: '能说清 C、A、P 三个字母的含义。',
        advanced_score_points: '能说明分布式系统为什么不能同时满足三者。',
        follow_up_l1: '[追问] 实际系统中如何在 C 和 A 之间取舍？',
        calibration_anchor: '[技术水平] 能准确解释三者含义与取舍。'
    },
    {
        id: 14, position_code: 'system_design', question_no: 'SYS-Q0002',
        category: '技术知识题', difficulty: 'medium', interview_stage: '核心考察',
        suggested_minutes: 5,
        question: '缓存穿透、缓存击穿、缓存雪崩分别是什么？如何解决？',
        keywords: '缓存\n穿透\n雪崩',
        exam_priority: '高频必考题',
        basic_score_points: '能区分三个概念的本质差异。',
        advanced_score_points: '能给出具体方案：布隆过滤器、互斥锁、过期时间加随机。',
        follow_up_l1: '[追问] 布隆过滤器有什么缺点？',
        calibration_anchor: '[技术水平] 三个概念能清晰区分。'
    },
    {
        id: 15, position_code: 'system_design', question_no: 'SYS-Q0003',
        category: '场景应用题', difficulty: 'hard', interview_stage: '深度压轴',
        suggested_minutes: 10,
        question: '设计一个支持百万并发的秒杀系统。',
        keywords: '秒杀\n高并发\n限流',
        exam_priority: '拓展题',
        basic_score_points: '能说清限流、削峰、异步处理三个核心思路。',
        advanced_score_points: '能展开讲排队、库存扣减、超卖防范等细节。',
        follow_up_l1: '[追问] 如何防止超卖？',
        calibration_anchor: '[技术水平] 能分层拆解，从接入层到数据层。'
    }
]

// mock 筛选逻辑
const filterMock = (params) => {
    let result = [...MOCK_QUESTIONS]

    if (params.position) {
        result = result.filter(q => q.position_code === params.position)
    }
    if (params.category) {
        result = result.filter(q => q.category === params.category)
    }
    if (params.difficulty) {
        result = result.filter(q => q.difficulty === params.difficulty)
    }
    if (params.stage) {
        result = result.filter(q => q.interview_stage === params.stage)
    }
    if (params.q) {
        const kw = params.q.toLowerCase()
        result = result.filter(q =>
            q.question.toLowerCase().includes(kw) ||
            (q.keywords || '').toLowerCase().includes(kw)
        )
    }

    return result
}

// 对外接口

export const getQuestions = async (params = {}) => {
    const { limit = 20, offset = 0 } = params

    if (USE_MOCK) {
        await mockDelay()
        const all = filterMock(params)
        const items = all.slice(offset, offset + limit)
        return { total: all.length, items }
    }

    // 显式构造干净参数：只包含有值的键
    const cleanParams = { limit, offset }
    if (params.position) cleanParams.position = params.position
    if (params.category) cleanParams.category = params.category
    if (params.difficulty) cleanParams.difficulty = params.difficulty
    if (params.stage) cleanParams.stage = params.stage
    if (params.q) cleanParams.q = params.q

    return request.get('/questions', { params: cleanParams })
}

export const getQuestionDetail = async (id) => {
    if (USE_MOCK) {
        await mockDelay(200)
        const found = MOCK_QUESTIONS.find(q => q.id === Number(id))
        if (!found) throw new Error('题目不存在')
        return found
    }

    return request.get(`/questions/${id}`)
}

export const CATEGORIES = ['技术知识题', '场景应用题', '项目经历题', '行为素质题']
export const DIFFICULTIES = [
    { code: 'easy', label: '简单' },
    { code: 'medium', label: '中等' },
    { code: 'hard', label: '困难' }
]
export const STAGES = ['开场热身', '核心考察', '深度压轴']