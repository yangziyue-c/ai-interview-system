/**
 * Vosk 模型全局单例
 *
 * Vosk 中文模型约 40MB，加载需要 5-10 秒，用单例缓存避免重复加载。
 * Model 为全局资源，应用关闭才释放；Recognizer 为会话级资源，
 * 每次录音新建，用完 remove()。
 */

let modelInstance = null
let loadingPromise = null

/**
 * 获取 Vosk 模型（单例）
 * 首次调用加载模型，后续调用返回缓存或正在加载的 Promise。
 */
export const getVoskModel = async () => {
    if (modelInstance) {
        return modelInstance
    }

    if (loadingPromise) {
        return loadingPromise
    }

    loadingPromise = (async () => {
        try {
            console.log('开始加载 Vosk 模型（全局单例）...')
            const Vosk = await import('vosk-browser')
            const model = await Vosk.createModel('/model.tar.gz')
            modelInstance = model
            console.log('Vosk 模型加载成功（后续进入秒开）')
            return model
        } catch (error) {
            loadingPromise = null
            console.error('Vosk 模型加载失败:', error)
            throw error
        }
    })()

    return loadingPromise
}

// 查询模型是否已加载完成
export const isVoskModelLoaded = () => {
    return modelInstance !== null
}