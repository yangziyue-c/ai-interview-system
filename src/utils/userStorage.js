/**
 * 用户级存储工具
 *
 * 核心作用：按用户名区分 localStorage 的 key，实现多用户数据隔离
 *
 * 例如：
 *   用户 zhangsan 的历史存到 localStorage.historyList_zhangsan
 *   用户 lisi 的历史存到 localStorage.historyList_lisi
 *
 * 本文件已弃用，无引用，保留作历史参考
 */

// 获取当前登录用户的 key 后缀
export const getCurrentUserKey = () => {
    try {
        const stored = localStorage.getItem('userInfo')
        if (!stored) return 'guest'
        const user = JSON.parse(stored)
        return user.username || 'guest'
    } catch (e) {
        return 'guest'
    }
}

// 面试历史记录

// 读取当前用户的历史记录
export const getUserHistory = () => {
    const key = `historyList_${getCurrentUserKey()}`
    const stored = localStorage.getItem(key)
    if (!stored) return []
    try {
        const list = JSON.parse(stored)
        return Array.isArray(list) ? list : []
    } catch (e) {
        console.error('解析历史记录失败:', e)
        return []
    }
}

// 保存当前用户的历史记录
export const setUserHistory = (list) => {
    const key = `historyList_${getCurrentUserKey()}`
    localStorage.setItem(key, JSON.stringify(list))
}

// 面试草稿（断点续答）

// 草稿过期时间：24 小时
const DRAFT_EXPIRE_MS = 24 * 60 * 60 * 1000

// 生成草稿的存储 key
const getDraftKey = (jobId) => {
    return `draft_${getCurrentUserKey()}_${jobId}`
}

/**
 * 保存面试草稿
 * @param {string} jobId - 岗位代码
 * @param {object} data - 草稿数据 { jobId, jobName, messages, currentRound }
 */
export const setDraft = (jobId, data) => {
    const key = getDraftKey(jobId)
    const payload = {
        ...data,
        savedAt: Date.now()
    }
    try {
        localStorage.setItem(key, JSON.stringify(payload))
    } catch (e) {
        console.error('保存草稿失败:', e)
    }
}

/**
 * 读取面试草稿
 * @param {string} jobId - 岗位代码
 * @returns {object|null} 草稿数据，无草稿或已过期则返回 null
 */
export const getDraft = (jobId) => {
    const key = getDraftKey(jobId)
    const stored = localStorage.getItem(key)
    if (!stored) return null

    try {
        const draft = JSON.parse(stored)

        // 检查是否过期
        if (Date.now() - (draft.savedAt || 0) > DRAFT_EXPIRE_MS) {
            localStorage.removeItem(key)
            console.log('草稿已过期，自动清除')
            return null
        }

        // 校验必要字段
        if (!draft.messages || !Array.isArray(draft.messages) || draft.messages.length === 0) {
            localStorage.removeItem(key)
            return null
        }

        return draft
    } catch (e) {
        console.error('读取草稿失败:', e)
        localStorage.removeItem(key)
        return null
    }
}

/**
 * 清除面试草稿
 * @param {string} jobId - 岗位代码
 */
export const clearDraft = (jobId) => {
    const key = getDraftKey(jobId)
    localStorage.removeItem(key)
}