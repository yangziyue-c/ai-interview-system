import { reactive } from 'vue'

// 全局 Toast 状态（响应式）
export const toastState = reactive({
    visible: false,
    text: '',
    timer: null
})

/**
 * 显示 Toast
 * @param {string} text - 提示文本
 * @param {number} duration - 显示时长（毫秒）
 */
export const showToast = (text, duration = 1800) => {
    if (toastState.timer) clearTimeout(toastState.timer)
    toastState.text = text
    toastState.visible = true
    toastState.timer = setTimeout(() => {
        toastState.visible = false
        toastState.timer = null
    }, duration)
}

/**
 * 手动隐藏 Toast（一般不用，showToast 会自动关）
 */
export const hideToast = () => {
    if (toastState.timer) clearTimeout(toastState.timer)
    toastState.visible = false
    toastState.timer = null
}