import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { mockDelay } from './_mock'

const MAX_SIZE = 2 * 1024 * 1024  // 2MB

// 只放行 API.md 允许的三种图片格式
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

// 上传头像
export const uploadAvatar = async (file) => {
    if (!file) throw new Error('未选择文件')

    if (file.size > MAX_SIZE) {
        throw new Error('图片不能超过 2MB')
    }

    if (!ALLOWED_TYPES.includes(file.type)) {
        throw new Error('仅支持 JPG / PNG / WebP 格式')
    }

    if (USE_MOCK) {
        await mockDelay(500)
        return new Promise((resolve, reject) => {
            const reader = new FileReader()
            reader.onload = () => resolve({ url: reader.result })
            reader.onerror = () => reject(new Error('读取文件失败'))
            reader.readAsDataURL(file)
        })
    }

    const formData = new FormData()
    formData.append('file', file)
    const data = await request.post('/uploads/avatar', formData)

    return { url: data.url }
}