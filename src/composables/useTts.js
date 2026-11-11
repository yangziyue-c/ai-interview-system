// src/composables/useTts.js
import { ref } from 'vue'
import { synthesizeSpeech } from '@/api/tts'
import { showToast } from '@/utils/toast'

/**
 * TTS 播放控制（单例 audio 元素 + 序列号防竞态）
 * 用法：
 *   const { loading, playing, currentIdx, play, stop, dispose } = useTts()
 */
export const useTts = () => {
    const loading = ref(false)
    const playing = ref(false)
    const currentIdx = ref(-1)

    let audioEl = null
    let seq = 0

    const ensureAudio = () => {
        if (!audioEl) {
            audioEl = new Audio()
            audioEl.onended = () => {
                playing.value = false
                currentIdx.value = -1
            }
            audioEl.onerror = () => {
                playing.value = false
                currentIdx.value = -1
            }
        }
        return audioEl
    }

    const stop = () => {
        seq += 1
        if (audioEl) {
            audioEl.pause()
            audioEl.currentTime = 0
        }
        playing.value = false
        currentIdx.value = -1
        loading.value = false
    }

    /**
     * 播放某条消息的语音
     * @param {string} text
     * @param {number} index - 消息索引
     * @param {Object} options
     * @param {boolean} options.silent - 静默模式：失败时不弹 Toast
     */
    const play = async (text, index, options = {}) => {
        const { silent = false } = options

        if (playing.value && currentIdx.value === index) {
            stop()
            return
        }
        if (loading.value) return

        stop()
        const mySeq = ++seq
        loading.value = true
        currentIdx.value = index

        const url = await synthesizeSpeech(text)

        if (mySeq !== seq) return
        loading.value = false

        if (!url) {
            currentIdx.value = -1
            if (!silent) showToast('语音合成暂不可用')
            return
        }

        try {
            const audio = ensureAudio()
            audio.src = url
            await audio.play()
            playing.value = true
        } catch (e) {
            console.warn('TTS 播放失败', e)
            playing.value = false
            currentIdx.value = -1
            if (!silent) showToast('播放失败')
        }
    }

    const dispose = () => {
        stop()
        if (audioEl) {
            audioEl.src = ''
            audioEl = null
        }
    }

    return { loading, playing, currentIdx, play, stop, dispose }
}