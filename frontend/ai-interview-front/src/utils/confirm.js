import { reactive } from 'vue'

// 全局 confirm 状态
export const confirmState = reactive({
    visible: false,
    title: '',
    message: '',
    confirmText: '确定',
    cancelText: '取消',
    danger: false,
    resolve: null
})

/**
 * 弹出确认框
 * @param {object} options
 * @param {string} options.title - 标题
 * @param {string} options.message - 内容
 * @param {string} options.confirmText - 确认按钮文字
 * @param {string} options.cancelText - 取消按钮文字
 * @param {boolean} options.danger - 是否危险操作（红色按钮）
 * @returns {Promise<boolean>}
 */
export const confirmDialog = (options = {}) => {
    return new Promise((resolve) => {
        confirmState.visible = true
        confirmState.title = options.title || '提示'
        confirmState.message = options.message || ''
        confirmState.confirmText = options.confirmText || '确定'
        confirmState.cancelText = options.cancelText || '取消'
        confirmState.danger = options.danger || false
        confirmState.resolve = resolve
    })
}