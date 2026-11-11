import request from '@/utils/request'
import { ref, computed } from 'vue'
import { buildAssetUrl } from '@/config/env'
import { USE_MOCK } from './_config'
import {
    mockDelay,
    readLocalUser,
    writeLocalUser,
    readMockUsers,
    writeMockUsers
} from './_mock'

// 全局共享的当前用户信息
export const currentUser = ref(null)

// 头像完整 URL（后端返回相对路径，前端渲染需拼接完整地址）
export const currentUserAvatar = computed(
    () => buildAssetUrl(currentUser.value?.avatar_url)
)

// 从 localStorage 恢复用户信息
export const initAuth = () => {
    try {
        const raw = localStorage.getItem('userInfo')
        if (raw) currentUser.value = JSON.parse(raw)
    } catch (e) {
        currentUser.value = null
    }
}

// 内部工具：更新共享 state + localStorage
const setUser = (user) => {
    currentUser.value = user
    if (user) {
        localStorage.setItem('userInfo', JSON.stringify(user))
    } else {
        localStorage.removeItem('userInfo')
    }
}

// getMe 缓存时间戳
let meCacheTime = 0
const ME_CACHE_TTL = 30 * 1000   // 30 秒

// 登录
export const login = async (username, password) => {
    if (USE_MOCK) {
        await mockDelay()
        const users = readMockUsers()
        const record = users[username]

        if (!record) {
            throw new Error('账号不存在，请先注册')
        }
        if (record.password !== password) {
            throw new Error('密码错误')
        }

        setUser(record.user)
        return { token: 'mock-token-' + Date.now(), user: record.user }
    }

    const data = await request.post('/auth/login', { username, password })
    setUser(data.user)
    return { token: data.access_token, user: data.user }
}

// 注册
export const register = async (payload) => {
    if (USE_MOCK) {
        await mockDelay(600)
        const users = readMockUsers()

        if (users[payload.username]) {
            throw new Error('账号已存在')
        }

        const user = {
            id: Date.now(),
            username: payload.username,
            nickname: payload.nickname,
            student_id: payload.student_id || null,
            target_position: payload.target_position,
            avatar_url: null
        }

        users[payload.username] = { user, password: payload.password }
        writeMockUsers(users)
        setUser(user)

        return { token: 'mock-token-' + Date.now(), user }
    }

    const data = await request.post('/auth/register', payload)
    setUser(data.user)
    return { token: data.access_token, user: data.user }
}

// 获取当前用户（/auth/me 的响应 data 直接就是 user 对象）
// 带缓存：30 秒内复用，force=true 可强制刷新
export const getMe = async (force = false) => {
    const now = Date.now()
    if (!force && currentUser.value && now - meCacheTime < ME_CACHE_TTL) {
        return currentUser.value
    }

    let user
    if (USE_MOCK) {
        await mockDelay(200)
        user = readLocalUser()
    } else {
        user = await request.get('/auth/me')
    }

    setUser(user)
    meCacheTime = now
    return user
}

// 更新用户资料
export const updateMe = async (payload) => {
    if (USE_MOCK) {
        await mockDelay()
        const current = readLocalUser()
        if (!current) throw new Error('未登录')

        const updated = { ...current, ...payload }
        setUser(updated)

        const users = readMockUsers()
        if (users[current.username]) {
            users[current.username].user = updated
            writeMockUsers(users)
        }

        meCacheTime = Date.now()
        return updated
    }

    const updated = await request.put('/auth/me', payload)
    setUser(updated)
    meCacheTime = Date.now()
    return updated
}

// 清空用户状态（登出时调）
export const clearMeCache = () => {
    setUser(null)
    meCacheTime = 0
}