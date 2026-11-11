// src/api/report.js
import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { mockDelay, getUserKey } from './_mock'

const HISTORY_KEY = () => `historyList_${getUserKey()}`

const readHistory = () => {
    try {
        return JSON.parse(localStorage.getItem(HISTORY_KEY()) || '[]')
    } catch (e) {
        return []
    }
}

// mock 工具：判断这场面试是否评分不完整

const EXPECTED_ROUNDS = 10

const checkPartial = (record) => {
    const notes = []

    const qaRecords = record.qa_records || record.qaList || []
    const actualRounds = qaRecords.length

    if (actualRounds > 0 && actualRounds < EXPECTED_ROUNDS) {
        notes.push(`只问了 ${actualRounds}/${EXPECTED_ROUNDS} 题`)
    }

    const dims = ['tech_score', 'logic_score', 'expression_score', 'adaptability_score', 'match_score']
    const nullDims = dims.filter(k => record[k] === null || record[k] === undefined)
    if (nullDims.length > 0) {
        notes.push(`${nullDims.length} 个维度未评出`)
    }

    if (record.total_score === null || record.total_score === undefined) {
        notes.push('总分未生成')
    }

    return {
        partial: notes.length > 0,
        notes
    }
}

// 对外接口

// 获取报告详情
export const getReport = async (interviewId) => {
    if (USE_MOCK) {
        await mockDelay()
        const list = readHistory()
        const found = list.find(i => String(i.id) === String(interviewId))
        if (!found) throw new Error('报告不存在')

        const { partial } = checkPartial(found)

        return {
            interview_id: found.id,
            position: found.position,
            total_score: found.total_score,
            tech_score: found.tech_score,
            logic_score: found.logic_score,
            expression_score: found.expression_score,
            adaptability_score: found.adaptability_score,
            match_score: found.match_score,
            summary: found.summary,
            strengths: found.strengths || [],
            weaknesses: found.weaknesses || [],
            suggestions: found.suggestions || [],
            created_at: found.finished_at,
            partial,
            rounds: (found.qa_records || found.qaList || []).length
        }
    }

    return request.get(`/reports/${interviewId}`)
}

// 成长曲线
export const getGrowth = async (options = {}) => {
    const { position, engine } = options

    if (USE_MOCK) {
        await mockDelay()
        const list = readHistory()
        const filtered = position ? list.filter(i => i.position === position) : list
        const recent5 = filtered.slice(0, 5).reverse()
        return recent5.map(i => ({
            interview_id: i.id,
            position: i.position,
            finished_at: i.finished_at,
            total_score: i.total_score
        }))
    }

    const params = {}
    if (position) params.position = position
    if (engine) params.engine = engine

    return request.get('/reports/growth', { params })
}

// 最新建议
export const getLatestReport = async () => {
    if (USE_MOCK) {
        await mockDelay()
        const list = readHistory()
        if (list.length === 0) return null

        const latest = list[0]
        return {
            interview_id: latest.id,
            position: latest.position,
            finished_at: latest.finished_at,
            total_score: latest.total_score,
            suggestions: latest.suggestions || []
        }
    }

    return request.get('/reports/latest')
}

// 生成分享链接
export const shareReport = async (interviewId) => {
    if (USE_MOCK) {
        await mockDelay(300)
        const history = readHistory()
        const found = history.find(i => String(i.id) === String(interviewId))
        if (!found) throw new Error('报告不存在')

        const code = Math.random().toString(36).substring(2, 10) +
            Math.random().toString(36).substring(2, 10)
        const expiresAt = Date.now() + 7 * 24 * 60 * 60 * 1000

        localStorage.setItem(`mock_share_${code}`, JSON.stringify({
            ...found,
            expiresAt
        }))

        return {
            share_code: code,
            share_url: `${window.location.origin}/#/share/${code}`,
            expires_at: new Date(expiresAt).toISOString()
        }
    }

    return request.post(`/reports/${interviewId}/share`)
}

// 凭分享码读取报告
export const getSharedReport = async (code) => {
    if (USE_MOCK) {
        await mockDelay(400)
        const raw = localStorage.getItem(`mock_share_${code}`)
        if (!raw) throw new Error('链接不存在或已过期')

        let data
        try {
            data = JSON.parse(raw)
        } catch (e) {
            throw new Error('链接不存在或已过期')
        }

        if (data.expiresAt && Date.now() > data.expiresAt) {
            localStorage.removeItem(`mock_share_${code}`)
            throw new Error('链接不存在或已过期')
        }

        return {
            interview_id: data.id,
            position: data.position,
            total_score: data.total_score,
            tech_score: data.tech_score,
            logic_score: data.logic_score,
            expression_score: data.expression_score,
            adaptability_score: data.adaptability_score,
            match_score: data.match_score,
            summary: data.summary,
            strengths: data.strengths || [],
            weaknesses: data.weaknesses || [],
            suggestions: data.suggestions || [],
            created_at: data.finished_at,
            partial: false
        }
    }

    return request.get(`/share/${code}`)
}

// 学习计划
// 后端字段：knowledge_points[].name / advice / hit_count / practice_minutes
// 页面字段：knowledge_points[].title / suggestion / question_count / total_minutes

const mapStudyPlanItem = (raw) => ({
    title: raw.name || '',
    suggestion: raw.advice || '',
    question_count: raw.hit_count || 0,
    // 用 ?? 而不是 ||：0 是合法值，不该被 || 吃掉
    total_minutes: raw.practice_minutes ?? raw.total_minutes ?? 0,
    priority: raw.priority || '',
    sources: raw.sources || [],
    practice_questions: raw.practice_questions || []
})

export const getStudyPlan = async (options = {}) => {
    const { interviewId, position, recent } = options

    if (USE_MOCK) {
        await mockDelay()
        const list = readHistory()

        if (interviewId) {
            const found = list.find(i => String(i.id) === String(interviewId))
            if (!found) {
                return { notice: '', knowledge_points: [], positions: [], pending_minutes: 0 }
            }

            const qaRecords = found.qaList || found.qa_records || []
            const knowledgePoints = qaRecords.slice(0, 3).map((qa, idx) => ({
                title: `知识点 ${idx + 1}`,
                suggestion: '针对该知识点，建议先阅读技术文档理解原理，再结合实际项目练习。',
                question_count: 3 + idx,
                total_minutes: (3 + idx) * 5
            }))

            return {
                notice: '',
                knowledge_points: knowledgePoints,
                positions: [],
                pending_minutes: 0
            }
        }

        return { notice: '', knowledge_points: [], positions: [], pending_minutes: 0 }
    }

    const params = {}
    if (interviewId) params.interview_id = interviewId
    if (position) params.position = position
    if (recent) params.recent = recent

    const data = await request.get('/reports/study-plan', { params })

    return {
        notice: data.notice || '',
        knowledge_points: (data.knowledge_points || []).map(mapStudyPlanItem),
        positions: data.positions || [],
        pending_minutes: data.pending_minutes || 0
    }
}

// 成长档案
export const getArchive = async (options = {}) => {
    const { position } = options

    if (USE_MOCK) {
        await mockDelay()
        return {
            available: false,
            notice: '暂无成长档案（Mock 模式）'
        }
    }

    const params = {}
    if (position) params.position = position

    return request.get('/reports/archive', { params })
}