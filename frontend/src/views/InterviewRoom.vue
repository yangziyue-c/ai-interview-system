<template>
  <div class="room-container" :class="{ 'is-desktop': isDesktop }">
    <div class="room-header">
      <button class="back-btn" @click="confirmExit">
        <AppIcon name="chevron-left" :size="18" />
        <span>返回</span>
      </button>
      <span class="room-title">{{ jobName }}</span>

      <div class="room-header-right">
        <button
          class="voice-toggle-btn"
          :class="{ active: autoPlayVoice }"
          @click="toggleAutoPlayVoice"
          :aria-label="autoPlayVoice ? '关闭自动播报' : '开启自动播报'"
          :title="autoPlayVoice ? '自动播报已开' : '自动播报已关'"
        >
          <AppIcon :name="autoPlayVoice ? 'volume-2' : 'volume-x'" :size="16" />
        </button>

        <span class="round-info" :class="{ finished: isFinished }">
          {{ isFinished ? '面试结束' : `第 ${currentRound} 题` }}
        </span>
      </div>
    </div>

    <div class="room-body">
      <div class="chat-area">
        <div class="message-list" ref="messageListRef">
          <div
            v-for="(msg, index) in messages"
            :key="index"
            class="message-wrapper"
            :style="{ animationDelay: (0.05 + index * 0.05) + 's' }"
          >
            <div v-if="msg.role === 'assistant'" class="message assistant">
              <div class="avatar avatar-ai">
                <AppIcon name="audio-lines" :size="18" />
              </div>
              <div class="bubble ai-bubble">{{ msg.content }}</div>
              <button
                v-if="!isFinished"
                class="tts-btn"
                :class="{ playing: ttsPlaying && ttsCurrentIdx === index }"
                :disabled="ttsLoading"
                @click="ttsPlay(msg.content, index)"
                :aria-label="ttsPlaying && ttsCurrentIdx === index ? '停止朗读' : '朗读'"
              >
                <AppIcon
                  :name="ttsLoading && ttsCurrentIdx === index ? 'loading' : 'volume-2'"
                  :size="14"
                  :class="{ spin: ttsLoading && ttsCurrentIdx === index }"
                />
              </button>
            </div>
            <div v-else class="message user">
              <div class="bubble user-bubble">{{ msg.content }}</div>
              <div class="avatar avatar-user">
                <AppIcon name="user" :size="18" />
              </div>
            </div>
          </div>

          <div v-if="isThinking" class="message-wrapper" style="animation-delay: 0s;">
            <div class="message assistant">
              <div class="avatar avatar-ai">
                <AppIcon name="audio-lines" :size="18" />
              </div>
              <div class="bubble ai-bubble thinking-dots">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>

        <div class="input-area">
          <div class="input-row">
            <input
              type="text"
              v-model="inputText"
              :placeholder="isRecording ? '录音中，请先点击结束录音...' : '输入你的回答...'"
              class="input-field"
              @keyup.enter="sendMessage"
              :disabled="isThinking || isFinished || isRecording"
            />
            <button
              class="send-btn"
              @click="sendMessage"
              :disabled="!inputText.trim() || isThinking || isFinished || isRecording || isUploading"
            >
              发送
            </button>
          </div>

          <div v-if="!modelLoaded" class="interim-hint">
            <AppIcon name="loading" :size="14" />
            <span>语音模型加载中，请稍候...</span>
          </div>
          <div v-else-if="isRecording" class="interim-hint recording">
            <span class="recording-dot"></span>
            <span>正在录音{{ interimText ? '：' + interimText : '...' }}</span>
          </div>
          <div v-else-if="isRecognizing" class="interim-hint">
            <AppIcon name="loading" :size="14" />
            <span>正在识别...</span>
          </div>
          <div v-else-if="isUploading" class="interim-hint">
            <AppIcon name="loading" :size="14" />
            <span>音频上传中...</span>
          </div>

          <div class="action-row">
            <button
              class="voice-btn"
              :class="{ recording: isRecording }"
              @click="toggleRecording"
              :disabled="isThinking || isFinished || !modelLoaded || isRecognizing || !voiceAnswerEnabled"
              :title="voiceAnswerEnabled ? '' : '设置中已关闭语音作答'"
            >
              <AppIcon name="mic" :size="16" />
              <span>
                {{ isRecording
                  ? '点击结束'
                  : (voiceAnswerEnabled ? '点击说话' : '语音已关闭') }}
              </span>
            </button>
            <button
              class="camera-btn"
              :class="{ active: isCameraTracking }"
              @click="toggleCamera"
              :disabled="isFinished || !bodyLanguageEnabled"
              :title="bodyLanguageEnabled ? '' : '设置中已关闭体态分析'"
            >
              <AppIcon :name="isCameraTracking ? 'video-off' : 'video'" :size="16" />
              <span>
                {{ isCameraTracking
                  ? '关闭摄像头'
                  : (bodyLanguageEnabled ? '开启摄像头' : '体态已关闭') }}
              </span>
            </button>
            <button
              class="end-btn"
              @click="endInterview"
              :disabled="isFinished || isRecording"
            >
              <AppIcon name="close" :size="16" />
              <span>结束面试</span>
            </button>
          </div>

          <div
            v-if="!isDesktop && isCameraTracking"
            class="camera-pip"
            :class="{ 'camera-pip-expanded': cameraExpanded }"
            @click="cameraExpanded = !cameraExpanded"
          >
            <video ref="cameraVideoRef" class="camera-pip-video" muted playsinline></video>

            <div v-if="cameraExpanded" class="camera-pip-info">
              <CameraStatus :analysis="cameraAnalysis" />
            </div>

            <button
              class="camera-pip-close"
              @click.stop="toggleCamera"
              aria-label="关闭摄像头"
            >
              <AppIcon name="close" :size="12" />
            </button>
          </div>
        </div>
      </div>

      <aside v-if="isDesktop" class="status-panel dark-scrollbar">
        <div v-if="isCameraTracking" class="status-card camera-card">
          <h4 class="status-title">摄像头追踪</h4>
          <div class="camera-preview">
            <video ref="cameraVideoRef" class="camera-video" muted playsinline></video>
          </div>
          <CameraStatus :analysis="cameraAnalysis" />
        </div>

        <div class="status-card">
          <h4 class="status-title">面试进度</h4>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
          </div>
          <!-- 修复：如果 totalRounds 尚未加载完毕（为 0），则只显示第 N 题 -->
          <p class="progress-text">
            第 {{ currentRound }} 
            <template v-if="totalRounds > 0"> / {{ totalRounds }}</template> 题
          </p>
        </div>

        <div class="status-card">
          <h4 class="status-title">已完成回答</h4>
          <div v-if="userAnswers.length === 0" class="empty-answers">
            还没有回答
          </div>
          <div v-else class="answer-list">
            <div v-for="(item, idx) in userAnswers" :key="idx" class="answer-item">
              <span class="answer-num">Q{{ idx + 1 }}</span>
              <span class="answer-text">{{ item }}</span>
            </div>
          </div>
        </div>

        <div class="status-card status-tip">
          <AppIcon name="lightbulb" :size="16" />
          <p>语音或文字回答都可以，AI 会根据你的回答追问。</p>
        </div>
      </aside>
    </div>

    <div v-if="showResumeDialog" class="resume-overlay">
      <div class="resume-dialog">
        <div class="resume-icon">
          <AppIcon name="file" :size="28" />
        </div>
        <h3 class="resume-title">发现未完成的面试</h3>
        <p class="resume-desc">是否继续上次的面试？</p>

        <div class="resume-info">
          <div class="info-row">
            <span class="info-label">岗位</span>
            <span class="info-value">{{ jobName }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">进度</span>
            <span class="info-value">第 {{ pendingRound }} 题</span>
          </div>
        </div>

        <div class="resume-buttons">
          <button class="btn-restart" @click="restartFromDialog" :disabled="resumeLoading">
            {{ resumeLoading ? '处理中...' : '重新开始' }}
          </button>
          <button class="btn-resume" @click="resumeFromDialog" :disabled="resumeLoading">
            {{ resumeLoading ? '处理中...' : '继续面试' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import { getVoskModel } from '@/utils/voskSingleton'
import request from '@/utils/request'
import AppIcon from '@/components/AppIcon.vue'
import CameraStatus from '@/components/CameraStatus.vue'
import {
  startInterview,
  submitAnswer,
  finishInterview,
  getTotalRounds,
  getCurrentInterview,
  getInterviewDetail
} from '@/api/interview'
import { getSettings, updateSettings } from '@/api/settings'
import { useTts } from '@/composables/useTts'
import { useCameraTracking } from '@/composables/useCameraTracking'
import { confirmDialog } from '@/utils/confirm'
import { showToast } from '@/utils/toast'
import { USE_MOCK } from '@/api/_config'

const router = useRouter()
const route = useRoute()

const isDesktop = useMediaQuery('(min-width: 1024px)')

const fromProfile = computed(() => route.query.from === 'profile')

const position = ref(route.query.position || '')
const jobName = ref(route.query.name || '未命名岗位')

const interviewId = ref(null)
const messages = ref([])
const currentRound = ref(0)
const totalRounds = ref(0) // 修改：默认设为 0，等待接口返回真实轮数
const isThinking = ref(false)
const isFinished = ref(false)
const inputText = ref('')
const messageListRef = ref(null)

const isRecording = ref(false)
const isRecognizing = ref(false)
const modelLoaded = ref(false)
const interimText = ref('')

const isUploading = ref(false)
const audioUrl = ref('')
const audioChunks = ref([])
const speechData = ref(null)

const showResumeDialog = ref(false)
const pendingInterview = ref(null)
const pendingRound = ref(1)
const resumeLoading = ref(false)

const cameraExpanded = ref(false)

const AUTOPLAY_KEY = 'interview_autoplay_voice'
const autoPlayVoice = ref(localStorage.getItem(AUTOPLAY_KEY) !== 'false')
const voiceAnswerEnabled = ref(true)
const bodyLanguageEnabled = ref(true)

const loadSettings = async () => {
  try {
    const s = await getSettings()
    voiceAnswerEnabled.value = s.voice_answer !== false
    bodyLanguageEnabled.value = s.body_language !== false
    autoPlayVoice.value = s.auto_tts !== false
    localStorage.setItem(AUTOPLAY_KEY, autoPlayVoice.value ? 'true' : 'false')
  } catch (e) {
    console.warn('加载用户设置失败，使用本地默认值', e)
  }
}

const toggleAutoPlayVoice = () => {
    autoPlayVoice.value = !autoPlayVoice.value
    localStorage.setItem(AUTOPLAY_KEY, autoPlayVoice.value ? 'true' : 'false')

    if (!autoPlayVoice.value && ttsPlaying.value) {
        ttsStop()
    }

    updateSettings({ auto_tts: autoPlayVoice.value }).catch((e) => {
        console.warn('同步自动播报设置失败', e)
    })
}

const {
  loading: ttsLoading,
  playing: ttsPlaying,
  currentIdx: ttsCurrentIdx,
  play: ttsPlay,
  stop: ttsStop,
  dispose: ttsDispose
} = useTts()

const {
  videoRef: cameraVideoRef,
  isTracking: isCameraTracking,
  analysis: cameraAnalysis,
  start: startCamera,
  stop: stopCamera
} = useCameraTracking()

const toggleCamera = () => {
  if (!bodyLanguageEnabled.value) {
    showToast('设置中已关闭体态分析')
    return
  }
  if (isCameraTracking.value) {
    stopCamera()
  } else {
    startCamera({
      getContext: () => ({
        interviewId: interviewId.value,
        round: currentRound.value
      })
    })
  }
}

let model = null
let recognizer = null
let audioContext = null
let mediaStream = null
let sourceNode = null
let processorNode = null
let mediaRecorder = null

const progressPercent = computed(() => {
  if (isFinished.value) return 100
  if (totalRounds.value === 0) return 0
  const finished = Math.max(0, currentRound.value - 1)
  return Math.min(100, Math.round((finished / totalRounds.value) * 100))
})

const userAnswers = computed(() => {
  return messages.value
    .filter(m => m.role === 'user')
    .map(m => m.content.length > 15 ? m.content.slice(0, 15) + '...' : m.content)
})

const downsampleBuffer = (inputData, inputRate, outputRate) => {
  if (inputRate === outputRate) return inputData
  const ratio = inputRate / outputRate
  const newLength = Math.round(inputData.length / ratio)
  const result = new Float32Array(newLength)
  let offsetBuffer = 0
  for (let i = 0; i < newLength; i++) {
    const nextOffsetBuffer = Math.round((i + 1) * ratio)
    let accum = 0
    let count = 0
    for (let j = offsetBuffer; j < nextOffsetBuffer && j < inputData.length; j++) {
      accum += inputData[j]
      count++
    }
    result[i] = count > 0 ? accum / count : 0
    offsetBuffer = nextOffsetBuffer
  }
  return result
}

const scrollToBottom = async () => {
  await nextTick()
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

const addMessage = (role, content) => {
  if (role === 'assistant' && ttsPlaying.value) {
    ttsStop()
  }

  messages.value.push({ role, content })

  if (role === 'assistant' && autoPlayVoice.value && !isFinished.value) {
    const newIndex = messages.value.length - 1
    nextTick(() => {
      ttsPlay(content, newIndex, { silent: true })
    })
  }

  scrollToBottom()
}

const rebuildMessages = (qaRecords) => {
  const msgs = []
  qaRecords.forEach(qa => {
    msgs.push({ role: 'assistant', content: qa.question })

    const turns = qa.engine_turns || []

    if (turns.length) {
      turns.forEach(t => {
        if (t.answer) msgs.push({ role: 'user', content: t.answer })
        if (t.reply) msgs.push({ role: 'assistant', content: t.reply })
      })
    } else if (qa.answer) {
      msgs.push({ role: 'user', content: qa.answer })
    }
  })
  messages.value = msgs
}

const beginInterview = async (restart = false) => {
  try {
    const { interview, question } = await startInterview(position.value, { restart })

    interviewId.value = interview.id
    currentRound.value = interview.current_round

    if (interview.qa_records && interview.qa_records.length > 0) {
      rebuildMessages(interview.qa_records)
    } else {
      messages.value = [{ role: 'assistant', content: question }]
      if (autoPlayVoice.value) {
        nextTick(() => {
          ttsPlay(question, 0, { silent: true })
        })
      }
    }

    scrollToBottom()
  } catch (e) {
    console.error('开始面试失败', e)
    showToast(e.message || '开始面试失败，请稍后重试')
    setTimeout(() => router.replace('/main/interview'), 1500)
  }
}

const resumeFromDialog = async () => {
  const current = pendingInterview.value
  if (!current) return

  resumeLoading.value = true
  try {
    let detail
    if (USE_MOCK) {
      detail = current
    } else {
      detail = await getInterviewDetail(current.id)
    }

    const records = detail.qa_records || []

    if (records.length === 0) {
      showToast('这场面试没有有效记录，正在重新开始...')

      if (!USE_MOCK) {
        try {
          await finishInterview(detail.id)
        } catch (e) {
          console.warn('清理空会话失败', e)
        }
      }

      showResumeDialog.value = false
      pendingInterview.value = null
      await beginInterview(true)
      return
    }

    interviewId.value = detail.id
    currentRound.value = detail.current_round || 1
    rebuildMessages(records)
    scrollToBottom()

    showResumeDialog.value = false
    pendingInterview.value = null
  } catch (e) {
    console.error('恢复面试失败', e)
    showToast(e.message || '恢复面试失败，请重试')
  } finally {
    resumeLoading.value = false
  }
}

const restartFromDialog = async () => {
  const old = pendingInterview.value
  if (!old) return

  resumeLoading.value = true
  try {
    if (!USE_MOCK) {
      if (old.current_round <= 1) {
        showToast('旧面试尚未作答，请先答一题或选择继续')
        return
      }
      await finishInterview(old.id)
    }

    showResumeDialog.value = false
    pendingInterview.value = null
    await beginInterview(true)
  } catch (e) {
    console.error('重新开始失败', e)
    showToast(e.message || '重新开始失败，请重试')
  } finally {
    resumeLoading.value = false
  }
}

const sendMessage = async () => {
  if (isRecording.value || isUploading.value) return
  const text = inputText.value.trim()
  if (!text || isThinking.value || isFinished.value) return

  addMessage('user', text)
  inputText.value = ''
  const answerAudioUrl = audioUrl.value
  const answerSpeech = speechData.value
  isThinking.value = true

  try {
    const res = await submitAnswer(interviewId.value, {
      answer: text,
      audioUrl: answerAudioUrl,
      speech: answerSpeech
    })

    audioUrl.value = ''
    speechData.value = null
    isThinking.value = false

    if (res.finished) {
      isFinished.value = true
      addMessage('assistant', '面试结束，感谢你的参与！正在生成评估报告...')
      setTimeout(() => {
        router.push({
          path: '/main/report',
          query: {
            recordId: res.interview.id,
            fromHistory: fromProfile.value ? 'true' : 'false'
          }
        })
      }, 1500)
    } else {
      currentRound.value = res.interview.current_round
      addMessage('assistant', res.next_question)
    }
  } catch (e) {
    isThinking.value = false
    console.error('提交答案失败', e)
    showToast(e.message || '提交失败，请重试')
  }
}

const endInterview = async () => {
  if (isRecording.value || isFinished.value) return

  if (userAnswers.value.length === 0) {
    showToast('请先回答至少一道题再结束面试')
    return
  }

  const ok = await confirmDialog({
    title: '结束面试',
    message: '确定要结束当前面试吗？结束后将生成评估报告。',
    confirmText: '结束面试',
    cancelText: '再想想',
    danger: true
  })
  if (!ok) return

  try {
    isThinking.value = true
    const res = await finishInterview(interviewId.value)
    isThinking.value = false
    isFinished.value = true
    addMessage('assistant', '面试已结束，正在生成评估报告...')
    setTimeout(() => {
      router.push({
        path: '/main/report',
        query: {
          recordId: res.interview.id,
          fromHistory: fromProfile.value ? 'true' : 'false'
        }
      })
    }, 1000)
  } catch (e) {
    isThinking.value = false
    console.error('结束面试失败', e)
    showToast(e.message || '结束失败，请重试')
  }
}

const confirmExit = async () => {
  if (messages.value.length > 0 && !isFinished.value) {
    const ok = await confirmDialog({
      title: '退出面试',
      message: '确定要退出面试吗？进度已自动保存，下次可继续。',
      confirmText: '退出',
      cancelText: '继续作答'
    })
    if (!ok) return
  }

  if (fromProfile.value) {
    router.push('/main/profile')
  } else {
    router.push('/main/interview')
  }
}

const initVosk = async () => {
  try {
    model = await getVoskModel()
    modelLoaded.value = true
  } catch (error) {
    console.error('Vosk 模型加载失败:', error)
  }
}

const startRecording = async () => {
  if (!modelLoaded.value || isThinking.value || isFinished.value) return
  if (!voiceAnswerEnabled.value) {
    showToast('设置中已关闭语音作答')
    return
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
        sampleRate: 16000
      }
    })

    audioChunks.value = []
    audioUrl.value = ''
    speechData.value = null
    try {
      mediaRecorder = new MediaRecorder(mediaStream, {
        mimeType: 'audio/webm;codecs=opus',
        audioBitsPerSecond: 24000
      })
      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunks.value.push(e.data)
      }
      mediaRecorder.start()
    } catch (e) {
      console.error('MediaRecorder 启动失败:', e)
    }

    audioContext = new AudioContext()
    const actualRate = audioContext.sampleRate
    recognizer = new model.KaldiRecognizer(16000)

    recognizer.on('result', (message) => {
      const text = (message.result.text || '').replace(/\s+/g, '')
      if (text) {
        inputText.value = inputText.value ? `${inputText.value}${text}` : text
      }
      interimText.value = ''
      isRecognizing.value = false
    })

    recognizer.on('partialresult', (message) => {
      interimText.value = message.result.partial
    })

    sourceNode = audioContext.createMediaStreamSource(mediaStream)
    processorNode = audioContext.createScriptProcessor(4096, 1, 1)

    processorNode.onaudioprocess = (event) => {
      if (!recognizer || !isRecording.value) return
      const inputData = event.inputBuffer.getChannelData(0)
      try {
        const downsampled = downsampleBuffer(inputData, actualRate, 16000)
        const buffer = audioContext.createBuffer(1, downsampled.length, 16000)
        buffer.copyToChannel(downsampled, 0)
        recognizer.acceptWaveform(buffer)
      } catch (err) {
        console.error('acceptWaveform 失败:', err)
      }
    }

    sourceNode.connect(processorNode)
    processorNode.connect(audioContext.destination)

    isRecording.value = true
    interimText.value = ''
    inputText.value = ''
  } catch (error) {
    console.error('麦克风访问失败:', error)
    showToast('无法访问麦克风，请检查浏览器权限设置')
  }
}

const stopRecording = () => {
  if (!isRecording.value) return
  isRecording.value = false
  isRecognizing.value = true

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.onstop = async () => {
      const blob = new Blob(audioChunks.value, { type: 'audio/webm' })

      if (USE_MOCK) {
        const url = URL.createObjectURL(blob)
        window.__debugAudioUrl = url
        window.__debugAudioBlob = blob
        console.log('[mock] 跳过音频上传，大小:', blob.size, 'bytes')
        audioUrl.value = ''
        return
      }

            isUploading.value = true
      try {
        const formData = new FormData()
        formData.append('file', blob, `recording_${Date.now()}.webm`)
        const data = await request.post('/uploads/audio/asr', formData)

        if (data.text) {
          inputText.value = data.text
        }

        audioUrl.value = data.url || ''
        const { text, url, ...speech } = data
        speechData.value = Object.keys(speech).length > 0 ? speech : null
      } catch (e) {
        console.warn('ASR 转写失败:', e.message)
        audioUrl.value = ''
        speechData.value = null
        // 降级逻辑：判断是否是 503（离线模式）
        if (e.message?.includes('50300') || e.message?.includes('离线') || e.message?.includes('不可用')) {
          showToast('当前为离线模式，请使用文字作答')
        } else {
          showToast('语音转写失败，将以文本形式提交')
        }
      } finally {
        isUploading.value = false
      }
    }
    mediaRecorder.stop()
    mediaRecorder = null
  }

  if (sourceNode) { sourceNode.disconnect(); sourceNode = null }
  if (processorNode) { processorNode.disconnect(); processorNode = null }
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop())
    mediaStream = null
  }
  if (recognizer) {
    try { recognizer.retrieveFinalResult() } catch (e) {}
  }
  setTimeout(() => {
    if (audioContext) { audioContext.close(); audioContext = null }
  }, 200)
  setTimeout(() => {
    if (isRecognizing.value) {
      isRecognizing.value = false
      interimText.value = ''
    }
  }, 2000)
}

const toggleRecording = () => {
  if (isRecording.value) stopRecording()
  else startRecording()
}

onMounted(async () => {
  if (!position.value) {
    console.warn('缺少岗位参数，跳回岗位大厅')
    router.replace('/main/interview')
    return
  }

  await loadSettings()

  try {
    totalRounds.value = await getTotalRounds()
  } catch (e) {
    console.error('获取配置失败', e)
  }

  const current = await getCurrentInterview()

  if (current && current.position === position.value) {
    pendingInterview.value = current
    pendingRound.value = current.current_round || 1
    showResumeDialog.value = true
  } else {
    await beginInterview(true)
  }

  initVosk()
})

onUnmounted(() => {
  stopRecording()
  stopCamera()
  ttsDispose()
  if (recognizer) {
    try { recognizer.remove() } catch (e) {}
    recognizer = null
  }
})
</script>

<style scoped>
/* 容器 */
.room-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-card);
  overflow: hidden;
  font-family: var(--font-sans);
}

/* 顶部信息栏 */
.room-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--gray-900);
  border-bottom: 1px solid var(--gray-800);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2) var(--space-1) var(--space-1);
  background: transparent;
  border: none;
  color: var(--gray-400);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
  flex-shrink: 0;
}

.back-btn:hover {
  color: var(--gray-50);
  background: var(--gray-800);
}

.room-title {
  flex: 1;
  text-align: center;
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--gray-50);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.room-header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.voice-toggle-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: 1px solid var(--gray-700);
  border-radius: var(--radius-sm);
  color: var(--gray-300);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.voice-toggle-btn:hover {
  border-color: var(--gray-500);
  color: var(--gray-50);
  background: var(--gray-800);
}

.voice-toggle-btn:active {
  transform: scale(0.94);
}

.voice-toggle-btn.active {
  background: var(--gray-800);
  border-color: var(--gray-500);
  color: var(--gray-50);
}

.voice-toggle-btn.active:hover {
  background: var(--gray-700);
  border-color: var(--gray-400);
}

.round-info {
  flex-shrink: 0;
  padding: 3px var(--space-3);
  background: var(--gray-800);
  color: var(--gray-50);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  border-radius: var(--radius-full);
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.round-info.finished {
  background: var(--gray-700);
  color: var(--gray-400);
}

/* 主体区域 */
.room-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

/* 消息列表 */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  background: var(--gray-200);
}

.message-wrapper {
  display: flex;
  flex-direction: column;
  opacity: 0;
  animation: fadeInUp 0.3s var(--ease-out) forwards;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

.message {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  max-width: 85%;
}

.message.user {
  align-self: flex-end;
  flex-direction: row;
}

.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-default);
}

.avatar-ai {
  background: var(--bg-card);
  color: var(--text-primary);
}

.avatar-user {
  background: var(--gray-900);
  color: var(--text-invert);
  border-color: var(--gray-900);
}

.bubble {
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  word-break: break-word;
  border-radius: var(--radius-lg);
}

.ai-bubble {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
  border-top-left-radius: var(--radius-sm);
}

.user-bubble {
  background: var(--gray-900);
  color: var(--text-invert);
  border-top-right-radius: var(--radius-sm);
}

/* TTS 朗读按钮 */
.tts-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  align-self: flex-start;
  margin-top: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
  cursor: pointer;
  opacity: 0.6;
  transition: opacity var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.tts-btn:hover:not(:disabled) {
  opacity: 1;
  background: var(--bg-card);
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.tts-btn:active:not(:disabled) {
  transform: scale(0.94);
}

.tts-btn:disabled {
  cursor: not-allowed;
  opacity: 0.8;
}

.tts-btn.playing {
  opacity: 1;
  background: var(--gray-900);
  border-color: var(--gray-900);
  color: var(--text-invert);
}

.tts-btn.playing:hover {
  background: var(--gray-800);
  border-color: var(--gray-800);
}

.tts-btn .spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.thinking-dots {
  display: flex;
  gap: 4px;
  padding: var(--space-3) var(--space-4);
  min-width: 52px;
  justify-content: center;
}

.thinking-dots span {
  width: 6px;
  height: 6px;
  background: var(--text-disabled);
  border-radius: var(--radius-full);
  animation: dotBounce 1.2s var(--ease-in-out) infinite;
}

.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotBounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-6px); opacity: 1; }
}

/* 输入区 */
.input-area {
  position: relative;
  flex-shrink: 0;
  padding: var(--space-3) var(--space-4) var(--space-4);
  background: var(--gray-900);
  border-top: 1px solid var(--gray-800);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.input-row {
  display: flex;
  gap: var(--space-2);
}

.input-field {
  flex: 1;
  min-width: 0;
  padding: 10px var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: var(--bg-card);
  outline: none;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
  box-sizing: border-box;
}

.input-field::placeholder {
  color: var(--text-disabled);
}

.input-field:focus {
  border-color: var(--gray-500);
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.12);
}

.input-field:disabled {
  background: var(--gray-100);
  color: var(--text-disabled);
  cursor: not-allowed;
}

.send-btn {
  flex-shrink: 0;
  padding: 10px var(--space-5);
  background: var(--gray-50);
  color: var(--gray-900);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}

.send-btn:hover:not(:disabled) {
  background: var(--gray-200);
}

.send-btn:active:not(:disabled) {
  background: var(--gray-300);
}

.send-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* 操作按钮行 */
.action-row {
  display: flex;
  gap: var(--space-2);
}

.voice-btn,
.camera-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 10px;
  background: transparent;
  border: 1px solid var(--gray-700);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--gray-300);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.voice-btn:hover:not(:disabled),
.camera-btn:hover:not(:disabled) {
  border-color: var(--gray-500);
  color: var(--gray-50);
  background: var(--gray-800);
}

.voice-btn:disabled,
.camera-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.voice-btn.recording {
  border-color: var(--danger);
  background: rgba(220, 38, 38, 0.15);
  color: #fca5a5;
}

.voice-btn.recording:hover {
  background: rgba(220, 38, 38, 0.25);
}

.camera-btn.active {
  border-color: var(--gray-50);
  background: var(--gray-800);
  color: var(--gray-50);
}

.end-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 10px var(--space-4);
  background: var(--danger);
  border: 1px solid var(--danger);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: #ffffff;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--duration-fast) var(--ease-out);
}

.end-btn:hover:not(:disabled) {
  background: var(--danger-hover);
  border-color: var(--danger-hover);
}

.end-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 状态提示行 */
.interim-hint {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px var(--space-1);
  font-size: var(--text-xs);
  color: var(--gray-400);
}

.interim-hint.recording {
  color: #fca5a5;
  font-weight: var(--font-medium);
}

.recording-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  background: #fca5a5;
  border-radius: var(--radius-full);
  flex-shrink: 0;
  animation: recordingDotPulse 1s var(--ease-in-out) infinite;
}

@keyframes recordingDotPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
}

/* 移动端摄像头画中画 */
.camera-pip {
  position: absolute;
  right: var(--space-3);
  bottom: 100%;
  margin-bottom: var(--space-2);
  width: 100px;
  height: 75px;
  background: var(--gray-800);
  border: 1px solid var(--gray-700);
  border-radius: var(--radius-md);
  overflow: hidden;
  z-index: 20;
  cursor: pointer;
  transition: width 0.2s var(--ease-out),
              height 0.2s var(--ease-out);
}

.camera-pip-expanded {
  width: 180px;
  height: 200px;
}

.camera-pip-video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}

.camera-pip-info {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: var(--space-2);
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(2px);
  font-size: 10px;
  color: #ffffff;
  max-height: 60%;
  overflow-y: auto;
}

.camera-pip-close {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: rgba(0, 0, 0, 0.6);
  color: #ffffff;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.camera-pip-close:hover {
  background: rgba(220, 38, 38, 0.85);
}

/* 桌面端 */
.room-container.is-desktop {
  height: 100%;
}

.room-container.is-desktop .room-body {
  flex-direction: row;
}

.room-container.is-desktop .message {
  max-width: 70%;
}

.status-panel {
  width: 280px;
  flex-shrink: 0;
  padding: var(--space-4);
  background: var(--bg-card);
  border-left: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  overflow-y: auto;
}

.status-card {
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.status-title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  letter-spacing: var(--tracking-wide);
  text-transform: uppercase;
}

.progress-bar {
  width: 100%;
  height: 6px;
  background: var(--gray-200);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: var(--space-2);
}

.progress-fill {
  height: 100%;
  background: var(--gray-900);
  border-radius: var(--radius-full);
  transition: width var(--duration-slow) var(--ease-out);
}

.progress-text {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  text-align: center;
}

.empty-answers {
  padding: var(--space-3) 0;
  font-size: var(--text-xs);
  color: var(--text-disabled);
  text-align: center;
}

.answer-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 240px;
  overflow-y: auto;
}

.answer-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--gray-50);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
}

.answer-num {
  flex-shrink: 0;
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.answer-text {
  color: var(--text-tertiary);
  word-break: break-word;
}

.status-tip {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  background: var(--warning-bg);
  border-color: var(--warning);
}

.status-tip :deep(.app-icon) {
  color: var(--warning);
  flex-shrink: 0;
  margin-top: 2px;
}

.status-tip p {
  margin: 0;
  font-size: var(--text-xs);
  line-height: var(--leading-relaxed);
  color: var(--text-primary);
}

/* 摄像头预览（桌面端右侧面板内） */
.camera-card {
  padding: var(--space-3);
}

.camera-preview {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  background: var(--gray-800);
  border-radius: var(--radius-sm);
  overflow: hidden;
  margin-bottom: var(--space-2);
}

.camera-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}

/* 恢复面试弹窗 */
.resume-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-5);
  box-sizing: border-box;
  animation: fadeIn 0.2s var(--ease-out);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.resume-dialog {
  width: 360px;
  max-width: 100%;
  padding: var(--space-8) var(--space-6) var(--space-6);
  background: var(--gray-200);
  border-radius: var(--radius-xl);
  text-align: center;
  box-shadow: var(--shadow-xl);
  animation: scaleIn 0.25s var(--ease-out);
}

@keyframes scaleIn {
  from { transform: scale(0.96); opacity: 0; }
  to   { transform: scale(1); opacity: 1; }
}

.resume-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto var(--space-4);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  border-radius: var(--radius-lg);
  color: var(--text-primary);
}

.resume-title {
  margin: 0 0 var(--space-1) 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--text-primary);
}

.resume-desc {
  margin: 0 0 var(--space-5) 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.resume-info {
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  text-align: left;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) 0;
  font-size: var(--text-sm);
}

.info-row:not(:last-child) {
  border-bottom: 1px solid var(--border-subtle);
}

.info-label {
  color: var(--text-tertiary);
}

.info-value {
  color: var(--text-primary);
  font-weight: var(--font-medium);
}

.resume-buttons {
  display: flex;
  gap: var(--space-3);
}

.btn-restart,
.btn-resume {
  flex: 1;
  padding: 11px var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.btn-restart:disabled,
.btn-resume:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-restart {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.btn-restart:hover:not(:disabled) {
  border-color: var(--border-strong);
  background: var(--gray-50);
}

.btn-resume {
  background: var(--gray-900);
  color: var(--text-invert);
  border: 1px solid var(--gray-900);
}

.btn-resume:hover:not(:disabled) {
  background: var(--gray-800);
  border-color: var(--gray-800);
}

.btn-restart:active:not(:disabled),
.btn-resume:active:not(:disabled) {
  transform: scale(0.98);
}
</style>