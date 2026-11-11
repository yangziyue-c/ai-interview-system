import { ref, onMounted, onUnmounted } from 'vue'

/**
 * 响应式媒体查询 Hook
 * @param {string} query - CSS 媒体查询字符串，如 '(min-width: 1024px)'
 * @returns {Ref<boolean>} 响应式的布尔值，匹配时为 true
 *
 * @example
 * const isDesktop = useMediaQuery('(min-width: 1024px)')
 * // 模板中：<div v-if="isDesktop">...</div>
 */
export const useMediaQuery = (query) => {
    // 同步初始化，首次渲染即用正确值，避免首屏闪烁
    const matches = ref(
        typeof window !== 'undefined' ? window.matchMedia(query).matches : false
    )

    // 保存 MediaQueryList 实例的引用，用于卸载时清理
    let mediaQuery = null

    // 事件回调函数（单独定义，确保 addEventListener 和 removeEventListener 引用一致）
    const update = (e) => {
        matches.value = e.matches
    }

    onMounted(() => {
        // 创建 MediaQueryList 实例
        mediaQuery = window.matchMedia(query)
        // 保险：再次同步当前匹配状态（防止初始化到挂载期间窗口大小变化）
        matches.value = mediaQuery.matches
        // 监听后续变化
        mediaQuery.addEventListener('change', update)
    })

    onUnmounted(() => {
        // 组件卸载时移除监听，防止内存泄漏
        if (mediaQuery) {
            mediaQuery.removeEventListener('change', update)
        }
    })

    return matches
}