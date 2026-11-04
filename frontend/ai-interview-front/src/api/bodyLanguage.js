// src/api/bodyLanguage.js
import request from '@/utils/request'
import { USE_MOCK } from './_config'

/**
 * 上传姿态关键点，拿分析结果
 *
 * 后端：POST /body-language/analyze
 * 请求：{ frames: [{ timestamp_ms, landmarks: [{x, y, z?, visibility?}] }] }
 * 响应：引擎原样 data
 *
 * @param {Object} payload - { frames: [...] }
 * @returns {Promise<Object|null>} data；失败返回 null
 */
export const analyzeBodyLanguage = async (payload) => {
    if (USE_MOCK) {
        return {
            available: true,
            score: null,
            confidence: 'low',
            quality_status: 'warming_up',
            metrics: { frame_count: payload?.frames?.length || 0 },
            notes: 'Mock 模式：未接入分析服务'
        }
    }

    try {
        return await request.post('/body-language/analyze', payload)
    } catch (e) {
        console.error('姿态分析失败', e)
        return null
    }
}