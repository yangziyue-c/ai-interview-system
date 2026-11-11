// src/api/settings.js
import { ref } from 'vue'
import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { mockDelay, getUserKey } from './_mock'

const SETTINGS_KEY = () => `mock_settings_${getUserKey()}`

const DEFAULT_SETTINGS = {
    default_position: '',
    voice_answer: true,
    auto_tts: true,
    body_language: true,
    report_preference: 'detailed',
    theme: 'system',
    career_anchor_result: null
}

// 全局响应式设置状态
export const globalSettings = ref({ ...DEFAULT_SETTINGS })

const readMockSettings = () => {
    try {
        const raw = localStorage.getItem(SETTINGS_KEY())
        if (!raw) return { ...DEFAULT_SETTINGS }
        return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) }
    } catch (e) {
        return { ...DEFAULT_SETTINGS }
    }
}

export const getSettings = async () => {
    if (USE_MOCK) {
        await mockDelay(200)
        const data = readMockSettings()
        globalSettings.value = data
        return data
    }
    const data = await request.get('/settings')
    globalSettings.value = { ...DEFAULT_SETTINGS, ...data }
    return globalSettings.value
}

export const updateSettings = async (partial) => {
    if (USE_MOCK) {
        await mockDelay(200)
        const current = readMockSettings()
        const next = { ...current }
        Object.keys(partial || {}).forEach((k) => {
            if (partial[k] !== null && partial[k] !== undefined) {
                next[k] = partial[k]
            }
        })
        localStorage.setItem(SETTINGS_KEY(), JSON.stringify(next))
        globalSettings.value = next
        return next
    }
    const data = await request.put('/settings', partial)
    globalSettings.value = { ...DEFAULT_SETTINGS, ...data }
    return globalSettings.value
}