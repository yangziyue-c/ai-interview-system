import { buildAssetUrl } from '@/config/env'

// 资源路径转完整 URL，内部委托 env.js 的 buildAssetUrl
export const resolveAssetUrl = (url) => buildAssetUrl(url)

// 模拟网络延迟
export const mockDelay = (ms = 400) => new Promise(r => setTimeout(r, ms))

// 读本地用户信息
export const readLocalUser = () => {
    try {
        const stored = localStorage.getItem('userInfo')
        return stored ? JSON.parse(stored) : null
    } catch (e) {
        return null
    }
}

// 写本地用户信息
export const writeLocalUser = (user) => {
    localStorage.setItem('userInfo', JSON.stringify(user))
}

// 按用户名隔离的 key
export const getUserKey = () => {
    const user = readLocalUser()
    return user?.username || 'guest'
}

// mock 用户数据库
export const readMockUsers = () => {
    try {
        return JSON.parse(localStorage.getItem('mock_users') || '{}')
    } catch (e) {
        return {}
    }
}

export const writeMockUsers = (users) => {
    localStorage.setItem('mock_users', JSON.stringify(users))
}