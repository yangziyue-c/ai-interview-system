// src/api/bodyLanguage.js
import request from '@/utils/request'
import { USE_MOCK } from './_config'

/**
 * 上传姿态关键点获取分析结果
 * 提供 interview_id 与 round 时后端会落库，仅转发时不落库
 * @param {Object} payload - { frames: [...], interview_id?, round? }
 */
export const analyzeBodyLanguage = async (payload) => {
    if (USE_MOCK) {
        return {
            available: true,
            score: null,
            confidence: 'low',
            quality_status: 'warming_up',
            metrics: { frame_count: payload?.frames?.length || 0 },
            notes: 'Mock 模式：未接入分析服务',
            stored: false
        }
    }

    try {
        return await request.post('/body-language/analyze', payload)
    } catch (e) {
        // 异常返回 null，避免打断前端的帧上传循环
        console.error('姿态分析失败', e)
        return null
    }
}