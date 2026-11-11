/**
 * 岗位图标配置
 *
 * 每个岗位对应一个 AppIcon 的 name。
 * 新增或修改岗位时，只需要改这个文件。
 */

export const JOB_ICONS = {
    backend: 'server',        // 服务器：后端开发
    frontend: 'monitor',      // 显示器：前端界面
    test_engineer: 'bug',     // 虫子：软件测试的经典符号
    algorithm: 'brain',       // 大脑：AI 与机器学习
    system_design: 'network'  // 网络拓扑：分布式系统设计
}

// 兜底图标
export const DEFAULT_JOB_ICON = 'file'

// 获取某个岗位的图标名
export const getJobIconName = (jobId) => {
    return JOB_ICONS[jobId] || DEFAULT_JOB_ICON
}

// 岗位中文名映射（供多个页面复用）
export const JOB_LABELS = {
    backend: 'Java 后端开发',
    frontend: 'Web 前端开发',
    test_engineer: '测试开发工程师',
    algorithm: '算法工程师',
    system_design: '系统设计工程师'
}

// 获取岗位中文名
export const getJobLabel = (jobId) => {
    return JOB_LABELS[jobId] || jobId || '未选择'
}