import request from '@/utils/request'
import { USE_MOCK } from './_config'
import { mockDelay } from './_mock'

// mock 岗位数据（岗位名与 code 跟 API.md 2.1 一致，
// 让 mock 模式下看到的内容接近真接口返回）
const MOCK_POSITIONS = [
    {
        code: 'backend',
        name: '后端开发工程师',
        description: '负责服务端架构与业务逻辑开发，考察编程语言、数据库、并发与系统设计能力。',
        tech_stack: ['Java', 'Python', 'MySQL', 'Redis', 'Spring Boot'],
        focus: ['数据结构与算法', '数据库', '并发编程', '分布式系统']
    },
    {
        code: 'frontend',
        name: '前端开发工程师',
        description: '负责前端页面开发与交互实现，考察框架原理、性能优化与工程化能力。',
        tech_stack: ['HTML/CSS', 'JavaScript', 'TypeScript', 'Vue3', 'React'],
        focus: ['CSS 布局', 'JavaScript 核心', '前端框架', '性能优化']
    },
    {
        code: 'test_engineer',
        name: '测试开发工程师',
        description: '负责自动化测试与质量保障体系建设。',
        tech_stack: ['Python', 'Selenium', 'Pytest', 'CI/CD'],
        focus: ['测试用例设计', '自动化框架', '性能测试']
    },
    {
        code: 'algorithm',
        name: '算法工程师',
        description: '负责算法模型的设计、训练与优化。',
        tech_stack: ['Python', 'PyTorch', 'NumPy', '机器学习'],
        focus: ['算法基础', '模型调优', '工程落地']
    },
    {
        code: 'system_design',
        name: '系统设计工程师',
        description: '负责大型分布式系统的架构设计。',
        tech_stack: ['分布式系统', '微服务', '消息队列', '数据库设计'],
        focus: ['架构设计', '容量规划', '高可用方案']
    }
]

// 缓存：一次拉取，多处使用
let cachedPositions = null

// 获取岗位列表
export const getPositions = async () => {
    if (cachedPositions) return cachedPositions

    if (USE_MOCK) {
        await mockDelay()
        cachedPositions = MOCK_POSITIONS
        return cachedPositions
    }

    cachedPositions = await request.get('/positions')
    return cachedPositions
}

// 按 code 拿岗位中文名（用于历史列表显示）
export const getPositionName = (code) => {
    if (!cachedPositions) return code
    const pos = cachedPositions.find(p => p.code === code)
    return pos?.name || code
}

// 清缓存（登出时调）
export const clearPositionCache = () => {
    cachedPositions = null
}