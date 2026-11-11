// src/api/resume.js
import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { mockDelay, getUserKey } from './_mock'

const RESUME_KEY = () => `mock_resume_${getUserKey()}`

const readResume = () => {
    try {
        return JSON.parse(localStorage.getItem(RESUME_KEY()) || 'null')
    } catch (e) {
        return null
    }
}

const writeResume = (data) => {
    localStorage.setItem(RESUME_KEY(), JSON.stringify(data))
}

// 字段映射：后端字段名转页面字段名
// 后端：id / original_filename / created_at
// 页面：resume_id / file_name / uploaded_at
const mapResume = (raw) => {
    if (!raw) return null
    return {
        resume_id: raw.id,
        file_name: raw.original_filename,
        file_size: raw.file_size,
        file_type: raw.file_type,
        uploaded_at: raw.created_at,
        parse_status: raw.parse_status,
        parse_message: raw.parse_message,
        suggested: raw.suggested || {},
        suggested_notes: raw.suggested_notes || {},
        text_preview: raw.text_preview || ''
    }
}

// 上传简历

export const uploadResume = async (file) => {
    if (USE_MOCK) {
        await mockDelay(800)

        const lowerName = file.name.toLowerCase()
        let parse_status = 'parsed'
        let parse_message = ''
        let suggested = { nickname: null, student_id: null, target_position: null }
        let suggested_notes = {}
        let text_preview = ''

        if (file.type.startsWith('image/')) {
            parse_status = 'image_pending'
            parse_message = '原件已保存，图片识别能力后续接入'
        } else if (lowerName.endsWith('.pdf')) {
            const r = Math.random()
            if (r < 0.7) {
                parse_status = 'parsed'
                const nameMatch = file.name.match(/^([^\-_.\s]+)/)
                suggested = {
                    nickname: nameMatch ? nameMatch[1] : '张三',
                    student_id: '2026' + String(Math.floor(Math.random() * 9000) + 1000),
                    target_position: 'backend'
                }
                suggested_notes = {
                    nickname: `据文档首行推测：${suggested.nickname}（请核对）`,
                    student_id: `命中「学号」标签：${suggested.student_id}`,
                    target_position: '据文档关键词推测：Java 后端'
                }
                text_preview = '这是简历全文的前 300 字预览（mock 数据）……'
            } else if (r < 0.85) {
                parse_status = 'no_text_layer'
                parse_message = '这是扫描件 PDF，暂无法提取文字'
            } else if (r < 0.95) {
                parse_status = 'garbled'
                parse_message = 'PDF 字体编码不支持，暂无法提取文字'
            } else {
                parse_status = 'failed'
                parse_message = '文件解析失败，请检查文件格式或手动填写'
            }
        } else {
            parse_status = 'failed'
            parse_message = '文件解析失败，请检查文件格式'
        }

        const resume = {
            resume_id: Date.now(),
            file_name: file.name,
            file_size: file.size,
            file_type: file.type,
            uploaded_at: new Date().toISOString(),
            parse_status,
            parse_message,
            suggested,
            suggested_notes,
            text_preview
        }

        writeResume(resume)
        return resume
    }

    // 真接口：拉回后做映射
    const formData = new FormData()
    formData.append('file', file)
    const data = await request.post('/resumes', formData)
    return mapResume(data)
}

// 获取最近一份

export const getLatestResume = async () => {
    if (USE_MOCK) {
        await mockDelay(200)
        return readResume()
    }
    const data = await request.get('/resumes/latest')
    return mapResume(data)
}

// 按 id 读历史

export const getResume = async (resumeId) => {
    if (USE_MOCK) {
        await mockDelay(200)
        return readResume()
    }
    const data = await request.get(`/resumes/${resumeId}`)
    return mapResume(data)
}

// 下载原件（必须带 token，用 blob）

export const downloadResume = async (resumeId, fileName) => {
    if (USE_MOCK) {
        throw new Error('演示模式暂不支持下载原件')
    }

    const blob = await request.get(`/resumes/${resumeId}/file`, {
        responseType: 'blob'
    })

    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fileName || 'resume'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
}