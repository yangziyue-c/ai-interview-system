// src/composables/useCameraTracking.js
import { ref, onUnmounted, nextTick, watch } from 'vue'
import { analyzeBodyLanguage } from '@/api/bodyLanguage'

// MediaPipe 模块级单例，避免重复加载
let visionBundlePromise = null
let poseLandmarkerPromise = null

const loadVisionBundle = () => {
    if (window.Vision) return Promise.resolve(window.Vision)
    if (visionBundlePromise) return visionBundlePromise

    visionBundlePromise = new Promise((resolve, reject) => {
        const script = document.createElement('script')
        script.src = '/vendor/mediapipe/vision_bundle.js'
        script.onload = () => {
            if (window.Vision) resolve(window.Vision)
            else {
                visionBundlePromise = null
                reject(new Error('vision_bundle 加载后未暴露 Vision'))
            }
        }
        script.onerror = () => {
            visionBundlePromise = null
            reject(new Error('vision_bundle 加载失败'))
        }
        document.head.appendChild(script)
    })
    return visionBundlePromise
}

const createPoseLandmarker = async () => {
    if (poseLandmarkerPromise) return poseLandmarkerPromise

    poseLandmarkerPromise = (async () => {
        try {
            const Vision = await loadVisionBundle()
            const vision = await Vision.FilesetResolver.forVisionTasks(
                '/vendor/mediapipe/wasm'
            )
            const modelAssetPath = '/vendor/mediapipe/pose_landmarker_lite.task'
            const baseOptions = { modelAssetPath, delegate: 'GPU' }
            const options = {
                runningMode: 'VIDEO',
                numPoses: 1,
                minPoseDetectionConfidence: 0.5,
                minPosePresenceConfidence: 0.5,
                minTrackingConfidence: 0.5
            }
            try {
                return await Vision.PoseLandmarker.createFromOptions(vision, {
                    baseOptions, ...options
                })
            } catch (gpuErr) {
                // GPU 初始化失败时回退至 CPU
                console.warn('GPU 初始化失败，回退 CPU', gpuErr)
                return await Vision.PoseLandmarker.createFromOptions(vision, {
                    baseOptions: { ...baseOptions, delegate: 'CPU' },
                    ...options
                })
            }
        } catch (e) {
            poseLandmarkerPromise = null
            throw e
        }
    })()

    return poseLandmarkerPromise
}

export const useCameraTracking = () => {
    const videoRef = ref(null)
    const isTracking = ref(false)
    const isAnalyzing = ref(false)
    const analysis = ref(null)
    const error = ref('')

    let stream = null
    let landmarker = null
    let rafId = null
    let uploadTimer = null
    let lastVideoTime = -1
    let lastDetectAt = 0
    let frames = []

    // 实时读取面试上下文，防止轮次更新后获取到旧值
    let getContext = () => ({ interviewId: null, round: null })

    const MAX_FRAMES = 90
    const DETECT_INTERVAL_MS = 120
    const ANALYZE_INTERVAL_MS = 1500

    const bindStreamToVideo = async (videoEl) => {
        if (!videoEl || !stream) return
        if (videoEl.srcObject === stream) return
        try {
            videoEl.srcObject = stream
            await videoEl.play()
        } catch (e) {
            console.warn('绑定 video 流失败', e)
        }
    }

    watch(videoRef, async (newEl) => {
        if (!newEl || !stream) return
        await nextTick()
        await bindStreamToVideo(newEl)
    }, { flush: 'post' })

    const detectLoop = () => {
        if (!isTracking.value || !videoRef.value || !landmarker) return

        const video = videoRef.value
        const now = performance.now()

        if (
            video.readyState >= 2 &&
            video.currentTime !== lastVideoTime &&
            now - lastDetectAt >= DETECT_INTERVAL_MS
        ) {
            lastDetectAt = now
            lastVideoTime = video.currentTime
            try {
                const result = landmarker.detectForVideo(video, now)
                const landmarks = result?.landmarks?.[0]
                if (landmarks && landmarks.length) {
                    frames.push({
                        timestamp_ms: Math.round(now),
                        landmarks: landmarks.map(p => ({
                            x: p.x,
                            y: p.y,
                            z: p.z ?? 0,
                            visibility: p.visibility ?? 1
                        }))
                    })
                    if (frames.length > MAX_FRAMES) frames.shift()
                }
            } catch (e) {
                console.error('detectForVideo 失败', e)
            }
        }

        rafId = requestAnimationFrame(detectLoop)
    }

    const uploadFrames = async () => {
        if (!frames.length || isAnalyzing.value) return
        isAnalyzing.value = true
        const snapshot = frames.slice()
        frames = []
        try {
            const payload = { frames: snapshot }

            // 必须同时传入 interviewId 和 round 才落库
            const ctx = getContext()
            if (ctx.interviewId && ctx.round) {
                payload.interview_id = ctx.interviewId
                payload.round = ctx.round
            }

            const res = await analyzeBodyLanguage(payload)
            if (res) analysis.value = res
        } finally {
            isAnalyzing.value = false
        }
    }

    const start = async (options = {}) => {
        if (isTracking.value) return
        error.value = ''

        if (typeof options.getContext === 'function') {
            getContext = options.getContext
        }

        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 640 },
                    height: { ideal: 360 },
                    frameRate: { ideal: 15, max: 20 },
                    facingMode: 'user'
                },
                audio: false
            })

            isTracking.value = true
            await nextTick()
            await bindStreamToVideo(videoRef.value)
            landmarker = await createPoseLandmarker()

            detectLoop()
            uploadTimer = setInterval(uploadFrames, ANALYZE_INTERVAL_MS)
        } catch (e) {
            console.error('摄像头启动失败', e)
            error.value = e.message || '摄像头启动失败'
            stop()
        }
    }

    const stop = () => {
        isTracking.value = false
        if (rafId) { cancelAnimationFrame(rafId); rafId = null }
        if (uploadTimer) { clearInterval(uploadTimer); uploadTimer = null }
        if (stream) {
            stream.getTracks().forEach(t => t.stop())
            stream = null
        }
        if (videoRef.value) {
            videoRef.value.srcObject = null
        }
        frames = []
        lastVideoTime = -1
        lastDetectAt = 0
        analysis.value = null

        // 重置上下文，防止数据串台
        getContext = () => ({ interviewId: null, round: null })
    }

    onUnmounted(() => {
        stop()
    })

    return {
        videoRef,
        isTracking,
        isAnalyzing,
        analysis,
        error,
        start,
        stop
    }
}