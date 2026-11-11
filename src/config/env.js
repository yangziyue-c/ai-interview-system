// src/config/env.js
// 集中管理环境变量，其他模块统一从这里读

export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export const ASSET_BASE = import.meta.env.VITE_ASSET_BASE || ''

/**
 * 把相对路径拼成完整 URL
 * 用于后端返回的静态资源路径（/uploads/xxx）
 * @param {string} path
 * @returns {string}
 */
export const buildAssetUrl = (path) => {
    if (!path) return ''
    if (
        path.startsWith('http://') ||
        path.startsWith('https://') ||
        path.startsWith('data:')
    ) {
        return path
    }
    return `${ASSET_BASE}${path}`
}