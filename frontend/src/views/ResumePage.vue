<template>
  <div class="resume-page" :class="{ 'is-desktop': isDesktop }">
    <div class="page-header">
      <button class="back-btn" @click="goBack">
        <AppIcon name="chevron-left" :size="18" />
        <span>返回</span>
      </button>
      <h1 class="page-title">我的简历</h1>
      <div class="header-spacer"></div>
    </div>

    <div v-if="loading" class="state-card">
      <AppIcon name="loading" :size="28" class="spin" />
      <p>正在加载...</p>
    </div>

    <div v-else-if="resume" class="resume-section">
      <div class="resume-card">
        <div class="file-header">
          <div class="file-icon">
            <AppIcon name="file" :size="24" />
          </div>
          <div class="file-detail">
            <p class="file-name">{{ resume.file_name }}</p>
            <p class="file-meta">
              {{ formatSize(resume.file_size) }} · {{ formatDate(resume.uploaded_at) }}
            </p>
          </div>
        </div>

        <div class="parse-status" :class="statusClass">
          <AppIcon :name="statusIcon" :size="14" />
          <span>{{ statusText }}</span>
        </div>

        <div v-if="resume.text_preview" class="text-preview-wrap">
          <button class="text-preview-toggle" @click="showPreview = !showPreview">
            <AppIcon name="file" :size="14" />
            <span>{{ showPreview ? '收起原文预览' : '查看原文预览' }}</span>
          </button>
          <div v-if="showPreview" class="text-preview-content">
            {{ resume.text_preview }}
          </div>
        </div>

        <div class="resume-actions">
          <button class="btn btn-secondary" @click="handleDownload" :disabled="downloading">
            <AppIcon name="file" :size="14" />
            <span>{{ downloading ? '下载中...' : '下载原件' }}</span>
          </button>
          <button class="btn btn-secondary" @click="triggerUpload">
            <AppIcon name="edit" :size="14" />
            <span>重新上传</span>
          </button>
        </div>
      </div>

      <button class="upload-cta" @click="triggerUpload">
        <AppIcon name="plus" :size="16" />
        <span>上传新简历</span>
      </button>
    </div>

    <div v-else class="empty-section">
      <div class="empty-icon-wrap">
        <AppIcon name="file" :size="40" />
      </div>
      <h2 class="empty-title">还没有上传简历</h2>
      <p class="empty-desc">
        上传 PDF 简历，AI 会自动识别你的昵称、学号、目标岗位
      </p>
      <button class="btn btn-primary empty-btn" @click="triggerUpload">
        <AppIcon name="plus" :size="16" />
        <span>选择文件上传</span>
      </button>
      <p class="empty-hint">支持 PDF / JPG / PNG / WEBP，不超过 10MB</p>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      accept=".pdf,image/jpeg,image/jpg,image/png,image/webp"
      style="display: none"
      @change="handleFileChange"
    />

    <div v-if="uploading" class="upload-overlay">
      <div class="upload-box">
        <AppIcon name="loading" :size="32" class="spin" />
        <p>正在上传并识别...</p>
      </div>
    </div>

    <div v-if="showParseModal" class="modal-overlay" @click.self="closeParseModal">
      <div class="modal-card">
        <div class="modal-icon-wrap">
          <AppIcon name="check-circle" :size="28" />
        </div>
        <h3 class="modal-title">识别成功</h3>
        <p class="modal-desc">我们识别到以下信息，是否填入你的资料？</p>

        <div class="suggested-list">
          <div v-if="parseResult.suggested.nickname" class="suggested-item">
            <div class="suggested-row">
              <span class="suggested-label">昵称</span>
              <span class="suggested-value">{{ parseResult.suggested.nickname }}</span>
            </div>
            <p v-if="parseResult.suggested_notes?.nickname" class="suggested-note">
              {{ parseResult.suggested_notes.nickname }}
            </p>
          </div>

          <div v-if="parseResult.suggested.student_id" class="suggested-item">
            <div class="suggested-row">
              <span class="suggested-label">学号</span>
              <span class="suggested-value">{{ parseResult.suggested.student_id }}</span>
            </div>
            <p v-if="parseResult.suggested_notes?.student_id" class="suggested-note">
              {{ parseResult.suggested_notes.student_id }}
            </p>
          </div>

          <div v-if="parseResult.suggested.target_position" class="suggested-item">
            <div class="suggested-row">
              <span class="suggested-label">目标岗位</span>
              <span class="suggested-value">{{ getPositionName(parseResult.suggested.target_position) }}</span>
            </div>
            <p v-if="parseResult.suggested_notes?.target_position" class="suggested-note">
              {{ parseResult.suggested_notes.target_position }}
            </p>
          </div>
        </div>

        <div class="modal-buttons">
          <button class="btn-cancel" @click="closeParseModal">稍后再说</button>
          <button class="btn-confirm" @click="applySuggested" :disabled="applying">
            {{ applying ? '填入中...' : '填入我的资料' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { uploadResume, getLatestResume, downloadResume } from '@/api/resume'
import { updateMe } from '@/api/auth'
import { getPositionName, getPositions } from '@/api/position'
import { showToast } from '@/utils/toast'

const router = useRouter()
const isDesktop = useMediaQuery('(min-width: 1024px)')

const loading = ref(true)
const resume = ref(null)
const uploading = ref(false)
const downloading = ref(false)

const fileInputRef = ref(null)
const showParseModal = ref(false)
const parseResult = ref(null)
const applying = ref(false)

const showPreview = ref(false)

const statusClass = computed(() => {
  const s = resume.value?.parse_status
  if (s === 'parsed') return 'status-success'
  if (s === 'image_pending') return 'status-info'
  if (s === 'failed') return 'status-danger'
  return 'status-warning'
})

const statusIcon = computed(() => {
  const s = resume.value?.parse_status
  if (s === 'parsed') return 'check-circle'
  if (s === 'failed') return 'alert'
  return 'info'
})

const statusText = computed(() => {
  const s = resume.value?.parse_status
  if (s === 'parsed') return '识别成功，可填入资料'
  if (s === 'no_text_layer') return '扫描件 PDF，暂无法提取文字'
  if (s === 'garbled') return 'PDF 字体编码不支持，暂无法提取文字'
  if (s === 'image_pending') return '原件已保存，识别能力后续接入'
  if (s === 'failed') return '文件解析失败，请手动填写'
  return resume.value?.parse_message || '未知状态'
})

const formatSize = (bytes) => {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

const formatDate = (val) => {
  if (!val) return ''
  const d = new Date(val)
  if (isNaN(d.getTime())) return val
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  })
}

const goBack = () => {
  router.push('/main/profile')
}

const triggerUpload = () => {
  if (uploading.value) return
  fileInputRef.value?.click()
}

const handleFileChange = async (e) => {
  const file = e.target.files?.[0]
  if (!file) return

  const MAX = 10 * 1024 * 1024
  if (file.size > MAX) {
    showToast('文件不能超过 10MB')
    fileInputRef.value.value = ''
    return
  }

  const lower = file.name.toLowerCase()
  const isPdf = lower.endsWith('.pdf')
  const isImg = /\.(jpe?g|png|webp)$/.test(lower)
  if (!isPdf && !isImg) {
    showToast('仅支持 PDF / JPG / PNG / WEBP')
    fileInputRef.value.value = ''
    return
  }

  uploading.value = true
  try {
    const result = await uploadResume(file)
    resume.value = result
    showPreview.value = false
    uploading.value = false

    if (
      result.parse_status === 'parsed' &&
      result.suggested &&
      (result.suggested.nickname || result.suggested.student_id || result.suggested.target_position)
    ) {
      parseResult.value = result
      showParseModal.value = true
    } else if (result.parse_status !== 'parsed') {
      showToast(result.parse_message || '上传成功')
    } else {
      showToast('上传成功')
    }
  } catch (err) {
    uploading.value = false
    console.error('上传失败', err)
    showToast(err.message || '上传失败')
  } finally {
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
}

const closeParseModal = () => {
  if (applying.value) return
  showParseModal.value = false
  parseResult.value = null
}

const applySuggested = async () => {
  const s = parseResult.value?.suggested || {}
  const payload = {}
  if (s.nickname) payload.nickname = s.nickname
  if (s.student_id) payload.student_id = s.student_id
  if (s.target_position) payload.target_position = s.target_position

  if (Object.keys(payload).length === 0) {
    showToast('没有可填入的信息')
    return
  }

  applying.value = true
  try {
    await updateMe(payload)
    applying.value = false
    showParseModal.value = false
    parseResult.value = null
    showToast('已填入资料')
  } catch (err) {
    applying.value = false
    console.error('填入失败', err)
    showToast('填入失败，请稍后重试')
  }
}

const handleDownload = async () => {
  if (!resume.value || downloading.value) return
  downloading.value = true
  try {
    await downloadResume(resume.value.resume_id, resume.value.file_name)
    showToast('开始下载')
  } catch (err) {
    console.error('下载失败', err)
    showToast(err.message || '下载失败')
  } finally {
    downloading.value = false
  }
}

onMounted(async () => {
  const [, resumeData] = await Promise.all([
    getPositions(),
    getLatestResume().catch(e => {
      console.error('加载简历失败', e)
      return null
    })
  ])
  resume.value = resumeData
  loading.value = false
})
</script>

<style scoped>
/* 容器 */
.resume-page {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 var(--space-1) var(--space-5);
  font-family: var(--font-sans);
}

/* 顶部返回栏 */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) 0 var(--space-4);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2) var(--space-1) var(--space-1);
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.back-btn:hover {
  color: var(--text-primary);
  background: var(--gray-100);
}

.page-title {
  margin: 0;
  font-size: var(--text-base);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.header-spacer {
  width: 60px;
}

/* 加载态 */
.state-card {
  padding: var(--space-12) var(--space-5);
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
}

.state-card p {
  margin: var(--space-3) 0 0 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.spin {
  color: var(--text-tertiary);
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 空状态 */
.empty-section {
  padding: var(--space-12) var(--space-6);
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  animation: fadeInUp 0.35s var(--ease-out);
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.empty-icon-wrap {
  width: 72px;
  height: 72px;
  margin: 0 auto var(--space-5);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  color: var(--text-tertiary);
  border-radius: var(--radius-lg);
}

.empty-title {
  margin: 0 0 var(--space-2) 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--text-primary);
}

.empty-desc {
  margin: 0 0 var(--space-6) 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  line-height: var(--leading-relaxed);
}

.empty-btn {
  margin: 0 auto var(--space-4);
}

.empty-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-disabled);
}

/* 简历卡片 */
.resume-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  animation: fadeInUp 0.35s var(--ease-out);
}

.resume-card {
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.file-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.file-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  flex-shrink: 0;
}

.file-detail {
  flex: 1;
  min-width: 0;
}

.file-name {
  margin: 0 0 2px 0;
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  word-break: break-all;
}

.file-meta {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.parse-status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
}

.status-success {
  background: var(--success-bg);
  color: var(--success);
}

.status-warning {
  background: var(--warning-bg);
  color: var(--warning);
}

.status-info {
  background: var(--gray-100);
  color: var(--text-secondary);
}

.status-danger {
  background: var(--danger-bg);
  color: var(--danger);
}

.text-preview-wrap {
  border-top: 1px solid var(--border-subtle);
  padding-top: var(--space-3);
}

.text-preview-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-2);
  background: transparent;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.text-preview-toggle:hover {
  border-color: var(--gray-900);
  color: var(--text-primary);
  background: var(--gray-50);
}

.text-preview-content {
  margin-top: var(--space-3);
  padding: var(--space-3);
  background: var(--gray-50);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}

.resume-actions {
  display: flex;
  gap: var(--space-2);
}

.upload-cta {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-4);
  background: transparent;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.upload-cta:hover {
  border-color: var(--gray-900);
  color: var(--text-primary);
  background: var(--gray-50);
}

/* 通用按钮 */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 11px var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}

.btn:active:not(:disabled) { transform: scale(0.98); }

.btn-primary {
  background: var(--gray-900);
  color: var(--text-invert);
  border: 1px solid var(--gray-900);
}

.btn-primary:hover { background: var(--gray-800); border-color: var(--gray-800); }

.btn-secondary {
  flex: 1;
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.btn-secondary:hover:not(:disabled) {
  border-color: var(--border-strong);
  background: var(--gray-50);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 上传中遮罩 */
.upload-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: fadeIn 0.2s var(--ease-out);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.upload-box {
  padding: var(--space-8) var(--space-10);
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  text-align: center;
  box-shadow: var(--shadow-xl);
}

.upload-box .spin {
  color: var(--text-primary);
}

.upload-box p {
  margin: var(--space-3) 0 0 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

/* 识别结果弹窗 */
.modal-overlay {
  position: fixed;
  inset: 0;
  padding: var(--space-5);
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
  box-sizing: border-box;
  animation: fadeIn 0.2s var(--ease-out);
}

.modal-card {
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

.modal-icon-wrap {
  width: 56px;
  height: 56px;
  margin: 0 auto var(--space-4);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--success-bg);
  color: var(--success);
  border-radius: var(--radius-full);
}

.modal-title {
  margin: 0 0 var(--space-1) 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--text-primary);
}

.modal-desc {
  margin: 0 0 var(--space-5) 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.suggested-list {
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.suggested-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.suggested-item:not(:last-child) {
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-subtle);
}

.suggested-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--text-sm);
}

.suggested-label {
  color: var(--text-tertiary);
}

.suggested-value {
  color: var(--text-primary);
  font-weight: var(--font-medium);
}

.suggested-note {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: var(--leading-normal);
}

.modal-buttons {
  display: flex;
  gap: var(--space-2);
}

.btn-cancel,
.btn-confirm {
  flex: 1;
  padding: 11px var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out);
}

.btn-cancel {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.btn-cancel:hover {
  background: var(--gray-50);
  border-color: var(--border-strong);
}

.btn-confirm {
  background: var(--gray-900);
  color: var(--text-invert);
  border: 1px solid var(--gray-900);
}

.btn-confirm:hover:not(:disabled) { background: var(--gray-800); }
.btn-confirm:disabled { opacity: 0.5; cursor: not-allowed; }

/* 桌面端 */
@media (min-width: 1024px) {
  .resume-page {
    max-width: 800px;
    padding: 0 0 var(--space-12);
  }

  .page-title {
    font-size: var(--text-lg);
  }

  .empty-section {
    padding: var(--space-16) var(--space-8);
  }

  .modal-card {
    width: 400px;
  }
}
</style>