// src/utils/request.js
import axios from 'axios'
import { showToast } from './toast'
import { API_BASE } from '@/config/env'

// Base URL 环境自适应
// 开发（vite dev server）连后端 8001
// 部署（构建产物放后端 static/）用相对路径，跟随当前域名

const request = axios.create({
    baseURL: API_BASE,
    timeout: 30000,
})

// 请求拦截器
request.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('token')
        if (token) {
            config.headers.Authorization = `Bearer ${token}`
        }

        // 长任务接口单独放宽超时（引擎模式下 /answers 需不少于 540 秒、/finish 需不少于 360 秒）
        const url = config.url || ''
        if (url.includes('/answers') || url.includes('/finish')) {
            config.timeout = 600000   // 10 分钟
        }

        return config
    },
    (error) => Promise.reject(error)
)

// 统一处理 40100（未登录 / token 过期）
const handleUnauthorized = (message) => {
    localStorage.removeItem('token')
    // hash 路由，路径必须带 #
    window.location.href = '/#/login'
    return Promise.reject(new Error(message || '请重新登录'))
}

// 响应拦截器
request.interceptors.response.use(
    (response) => {
        // blob 响应（文件下载）直接返回
        if (response.config.responseType === 'blob') {
            return response.data
        }

        const res = response.data

        if (res.code === 40100) {
            return handleUnauthorized(res.message)
        }

        if (res.code === 50300) {
            showToast(res.message || '服务暂时不可用，请稍后重试')
            return Promise.reject(new Error(res.message))
        }

        if (res.code !== 0) {
            showToast(res.message || '请求出错')
            return Promise.reject(new Error(res.message))
        }

        return res.data
    },
    (error) => {
        // HTTP 4xx/5xx 会走这里，需要从 error.response.data 再读一次业务码
        const res = error.response?.data

        if (res?.code === 40100) {
            return handleUnauthorized(res.message)
        }

        if (res?.code === 50300) {
            showToast(res.message || '服务暂时不可用，请稍后重试')
            return Promise.reject(new Error(res.message))
        }

        if (res && typeof res.code === 'number' && res.code !== 0) {
            showToast(res.message || '请求出错')
            return Promise.reject(new Error(res.message))
        }

        if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
            showToast('请求超时，请检查网络后重试')
        } else {
            showToast('网络连接失败，请检查后端服务是否启动')
        }
        return Promise.reject(error)
    }
)

export default request