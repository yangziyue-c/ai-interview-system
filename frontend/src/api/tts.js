// src/api/tts.js
import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { buildAssetUrl } from '@/config/env'

const MAX_TEXT_LENGTH = 800

// 后端返回的相对路径要拼成完整地址
// request.js 的 baseURL 带 /api/v1，但静态文件在 /uploads 下，不能直接用 baseURL

/**
 * 合成语音
 * 后端：POST /uploads/audio/tts
 * 请求：{ text, voice }
 * 响应：{ url, content_type, bytes, chars }
 *
 * @param {string} text  - 要朗读的文本（超过 800 字自动截断）
 * @param {string} voice - 音色 ID，留空用引擎默认
 * @returns {Promise<string|null>} 音频 URL；失败返回 null
 */
export const synthesizeSpeech = async (text, voice = '') => {
    let trimmed = (text || '').trim()
    if (!trimmed) return null

    if (trimmed.length > MAX_TEXT_LENGTH) {
        trimmed = trimmed.slice(0, MAX_TEXT_LENGTH)
    }

    if (USE_MOCK) {
        console.warn('[mock] TTS 未接入')
        return null
    }

    try {
        const data = await request.post('/uploads/audio/tts', {
            text: trimmed,
            voice
        })
        return buildAssetUrl(data?.url)
    } catch (e) {
        // 50300（引擎不可用）会走这里，静默降级，不播报
        console.error('TTS 合成失败', e)
        return null
    }
}