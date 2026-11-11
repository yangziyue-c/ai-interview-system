// src/api/interview.js
import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { mockDelay, getUserKey } from './_mock'

const CURRENT_KEY = () => `mock_current_interview_${getUserKey()}`
const HISTORY_KEY = () => `historyList_${getUserKey()}`

const readCurrent = () => {
    try { return JSON.parse(localStorage.getItem(CURRENT_KEY()) || 'null') } catch (e) { return null }
}
const writeCurrent = (data) => { localStorage.setItem(CURRENT_KEY(), JSON.stringify(data)) }
const clearCurrent = () => { localStorage.removeItem(CURRENT_KEY()) }
const readHistory = () => {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY()) || '[]') } catch (e) { return [] }
}
const writeHistory = (list) => { localStorage.setItem(HISTORY_KEY(), JSON.stringify(list)) }

const QUESTION_BANK = {
    backend: ['请简单介绍一下你的项目经历。', '你用过 Spring Boot 吗？能说说它的核心原理吗？', 'MySQL 索引有哪些类型？什么情况下索引会失效？', '你如何处理高并发场景下的性能问题？', '描述一次你解决过的最有挑战性的技术问题。', '你对微服务架构有什么理解？', '你未来的职业规划是什么？'],
    frontend: ['请简单介绍一下你的前端开发经历。', 'Vue3 和 Vue2 有哪些主要区别？', '你如何优化前端页面加载速度？', '什么是闭包？在实际开发中有什么用？', '描述一次你遇到过的跨域问题及解决方案。', '你对前端工程化有什么理解？', '你未来的职业规划是什么？'],
    test_engineer: ['请简单介绍一下你的测试经历。', '你如何设计测试用例？', '自动化测试框架你用过哪些？', '如何测试一个登录页面？', '性能测试怎么做？', '你对持续集成有什么理解？', '你未来的职业规划是什么？'],
    algorithm: ['请简单介绍一下你的算法学习经历。', '常见排序算法的时间复杂度？', '过拟合怎么解决？', '你了解哪些机器学习模型？', '如何评估模型的好坏？', '特征工程你做过哪些？', '你未来的职业规划是什么？'],
    system_design: ['请简单介绍一下你设计过的系统。', '如何设计一个短链接系统？', '分布式系统如何保证一致性？', '缓存穿透、缓存击穿、缓存雪崩怎么解决？', '如何设计一个消息队列？', '微服务之间如何通信？', '你未来的职业规划是什么？']
}

const getQuestions = (position) => QUESTION_BANK[position] || QUESTION_BANK.backend

const generateMockReport = () => {
    const r = () => Math.floor(Math.random() * 30) + 65
    const tech = r(), logic = r(), expression = r(), adaptability = r(), match = r()
    const total = Math.round((tech + logic + expression + adaptability + match) / 5)
    let summary = ''
    if (total >= 85) summary = '表现非常出色！你展现了扎实的专业基础和优秀的沟通能力。'
    else if (total >= 70) summary = '表现良好！你具备较好的专业基础和发展潜力。'
    else summary = '表现一般。建议加强基础知识学习，多参与项目实践积累经验。'
    return { total_score: total, tech_score: tech, logic_score: logic, expression_score: expression, adaptability_score: adaptability, match_score: match, summary, strengths: ['技术基础较好', '逻辑清晰'].slice(0, 2), weaknesses: ['技术深度有待加强'].slice(0, 1), suggestions: ['针对薄弱技术点，每天花30分钟阅读技术文档或源码', '每周至少进行一次完整的模拟面试'] }
}

const buildFinishedRecord = (current, report) => ({
    id: current.id, position: current.position, status: 'finished', current_round: current.qa_records.length, created_at: current.qa_records[0].created_at, finished_at: new Date().toISOString(), total_score: report.total_score, qa_records: current.qa_records, ...report
})

export const getInterviews = async (options = {}) => {
    const { position } = options
    if (USE_MOCK) {
        await mockDelay()
        const all = readHistory()
        const filtered = position ? all.filter(i => i.position === position) : all
        const current = readCurrent()
        let currentItem = null
        if (current && (!position || current.position === position)) {
            currentItem = { id: current.id, position: current.position, status: 'in_progress', current_round: current.qa_records.length, created_at: current.qa_records[0].created_at, finished_at: null, total_score: null }
        }
        return currentItem ? [currentItem, ...filtered] : filtered
    }
    const params = {}
    if (position) params.position = position
    return request.get('/interviews', { params })
}

export const getInterviewDetail = async (interviewId) => {
    if (USE_MOCK) {
        await mockDelay()
        const list = readHistory()
        const found = list.find(i => String(i.id) === String(interviewId))
        if (!found) throw new Error('面试记录不存在')

        const qa_records = (found.qa_records || []).map((qa, idx) => ({
            ...qa,
            id: idx + 1,
            judge_band: idx === 1 ? 'degrade' : 'L1',
            needs_improvement: idx === 1 ? true : null
        }))
        return { ...found, qa_records }
    }
    return request.get(`/interviews/${interviewId}`)
}

export const startInterview = async (position, options = {}) => {
    const { restart = false } = options
    if (USE_MOCK) {
        await mockDelay()
        if (!restart) {
            const current = readCurrent()
            if (current && current.position === position) {
                return { interview: { id: current.id, status: 'in_progress', current_round: current.qa_records.length, position: current.position, qa_records: current.qa_records }, question: current.qa_records[current.qa_records.length - 1].question }
            }
        } else {
            clearCurrent()
        }
        const questions = getQuestions(position)
        const newInterview = { id: Date.now(), position, status: 'in_progress', qa_records: [{ round: 1, question: questions[0], answer: null, audio_url: null, created_at: new Date().toISOString() }] }
        writeCurrent(newInterview)
        return { interview: { id: newInterview.id, status: 'in_progress', current_round: 1, position, qa_records: newInterview.qa_records }, question: questions[0] }
    }
    return request.post('/interviews', { position })
}

export const submitAnswer = async (interviewId, payload) => {
    if (USE_MOCK) {
        await mockDelay(600)
        const current = readCurrent()
        if (!current || current.id !== interviewId) throw new Error('面试已失效')
        const questions = getQuestions(current.position)
        const pendingIdx = current.qa_records.findIndex(q => !q.answer)
        if (pendingIdx >= 0) {
            current.qa_records[pendingIdx].answer = payload.answer
            current.qa_records[pendingIdx].audio_url = payload.audioUrl || null
        }
        const answeredCount = current.qa_records.length
        if (answeredCount < questions.length) {
            const nextRound = answeredCount + 1
            const nextQuestion = questions[answeredCount]
            current.qa_records.push({ round: nextRound, question: nextQuestion, answer: null, audio_url: null, created_at: new Date().toISOString() })
            writeCurrent(current)
            return { finished: false, interview: { id: current.id, status: 'in_progress', current_round: nextRound }, next_question: nextQuestion, report: null }
        }
        const report = generateMockReport()
        const record = buildFinishedRecord(current, report)
        const history = readHistory()
        history.unshift(record)
        writeHistory(history)
        clearCurrent()
        return { finished: true, interview: { id: current.id, status: 'finished', current_round: questions.length }, next_question: null, report }
    }
    const body = { answer: payload.answer, audio_url: payload.audioUrl }
    if (payload.speech) body.speech = payload.speech
    return request.post(`/interviews/${interviewId}/answers`, body)
}

export const finishInterview = async (interviewId) => {
    if (USE_MOCK) {
        await mockDelay(500)
        const current = readCurrent()
        if (!current || current.id !== interviewId) throw new Error('面试已失效')
        const report = generateMockReport()
        const record = buildFinishedRecord(current, report)
        const history = readHistory()
        history.unshift(record)
        writeHistory(history)
        clearCurrent()
        return { interview: { id: current.id, status: 'finished', current_round: current.qa_records.length }, report }
    }
    return request.post(`/interviews/${interviewId}/finish`)
}

export const getTotalRounds = async () => {
    if (USE_MOCK) return 10
    const data = await request.get('/config')
    return data.total_rounds
}

export const checkInProgress = async () => {
    try {
        const list = await getInterviews()
        const inProgress = list.find(i => i.status === 'in_progress')
        return inProgress || null
    } catch (e) {
        console.warn('检查面试状态失败', e)
        return null
    }
}

export const getCurrentInterview = checkInProgress