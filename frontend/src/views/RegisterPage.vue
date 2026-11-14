<template>
  <div class="register-page">
    <div class="register-card">
      <aside class="brand-panel">
        <div class="brand-icon">
          <AppIcon name="audio-lines" :size="28" />
        </div>
        <h1 class="brand-title">AI 模拟面试</h1>
        <p class="brand-subtitle">创建账号，开启你的面试练习之旅</p>

        <ul class="feature-list">
          <li>
            <AppIcon name="check" :size="16" />
            <span>语音 / 文字双模态作答</span>
          </li>
          <li>
            <AppIcon name="check" :size="16" />
            <span>岗位专属题库，精准出题</span>
          </li>
          <li>
            <AppIcon name="check" :size="16" />
            <span>5 维能力雷达，精准量化成长</span>
          </li>
          <li>
            <AppIcon name="check" :size="16" />
            <span>历史记录与成长曲线持续追踪</span>
          </li>
        </ul>
      </aside>

      <section class="form-panel">
        <header class="form-header">
          <h2 class="form-title">注册</h2>
          <p class="form-subtitle">填写信息，创建你的账号</p>
        </header>

        <form class="register-form" @submit.prevent="handleRegister">
          <div class="form-field">
            <label for="username">账号 <span class="required">*</span></label>
            <input
              id="username"
              type="text"
              v-model="form.username"
              placeholder="请输入账号"
              class="input"
              required
            />
          </div>

          <div class="form-field">
            <label for="password">密码 <span class="required">*</span></label>
            <div class="input-with-icon">
              <input
                id="password"
                :type="showPassword ? 'text' : 'password'"
                v-model="form.password"
                placeholder="请设置密码"
                class="input"
                required
              />
              <button
                type="button"
                class="input-icon-btn"
                @click="showPassword = !showPassword"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              >
                <AppIcon :name="showPassword ? 'eye-off' : 'eye'" :size="18" />
              </button>
            </div>
          </div>

          <div class="form-field">
            <label for="nickname">昵称 <span class="required">*</span></label>
            <input
              id="nickname"
              type="text"
              v-model="form.nickname"
              placeholder="请输入你的昵称"
              class="input"
              required
            />
          </div>

          <div class="form-field">
            <label for="studentId">学号 <span class="optional">（选填）</span></label>
            <input
              id="studentId"
              type="text"
              v-model="form.student_id"
              placeholder="请输入学号"
              class="input"
            />
          </div>

          <div class="form-field">
            <label for="targetPosition">目标岗位 <span class="required">*</span></label>
            <select
              id="targetPosition"
              v-model="form.target_position"
              class="input select"
              required
            >
              <option value="" disabled>请选择目标岗位</option>
              <option
                v-for="pos in positionOptions"
                :key="pos.code"
                :value="pos.code"
              >
                {{ pos.name }}
              </option>
            </select>
            <span class="field-hint">AI 面试官会按该岗位的考察重点出题</span>
          </div>

          <button type="submit" class="btn-primary" :disabled="loading">
            {{ loading ? '注册中...' : '立即注册' }}
          </button>
        </form>

        <p class="bottom-link">
          已有账号？<a @click="goLogin">去登录</a>
        </p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import { register } from '@/api/auth'
import { getPositions } from '@/api/position'
import { updateSettings } from '@/api/settings'
import { showToast } from '@/utils/toast'

const router = useRouter()

const form = ref({
  username: '',
  password: '',
  nickname: '',
  student_id: '',
  target_position: ''
})

const positionOptions = ref([])

const loading = ref(false)
const showPassword = ref(false)

const handleRegister = async () => {
  if (!form.value.username.trim()) { showToast('请输入账号'); return }
  if (!form.value.password.trim()) { showToast('请设置密码'); return }
  if (!form.value.nickname.trim()) { showToast('请输入昵称'); return }
  if (!form.value.target_position) { showToast('请选择目标岗位'); return }

  loading.value = true
  try {
    const { token, user } = await register({
      username: form.value.username,
      password: form.value.password,
      nickname: form.value.nickname,
      student_id: form.value.student_id || null,
      target_position: form.value.target_position
    })

    localStorage.setItem('token', token)
    localStorage.setItem('userInfo', JSON.stringify(user))

    // 同步目标岗位到默认岗位设置
    await updateSettings({ default_position: form.value.target_position }).catch(e => {
      console.warn('同步默认岗位失败', e)
    })

    loading.value = false
    showToast('注册成功，正在进入...')

    sessionStorage.removeItem('hasChosenModule')
    router.push('/launcher')
  } catch (e) {
    loading.value = false
    console.error('注册失败', e)
    showToast(e.message || '注册失败')
  }
}

const goLogin = () => {
  router.push('/login')
}

onMounted(async () => {
  try {
    positionOptions.value = await getPositions()
  } catch (e) {
    console.error('加载岗位列表失败', e)
    showToast('岗位列表加载失败，请刷新页面重试')
  }
})
</script>

<style scoped>
/* 页面容器 */
.register-page {
  width: 100vw;
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: var(--space-6) var(--space-4);
  box-sizing: border-box;
  background: var(--gray-950);
  font-family: var(--font-sans);
}

/* 白色大卡片 */
.register-card {
  width: 100%;
  max-width: 400px;
  display: grid;
  grid-template-columns: 1fr;
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.06),
    0 24px 48px rgba(0, 0, 0, 0.4);
  animation: fadeInUp 0.4s var(--ease-out);
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 品牌区 */
.brand-panel {
  padding: var(--space-10) var(--space-8) var(--space-5);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}

.brand-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-900);
  color: var(--gray-50);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-2);
}

.brand-title {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.brand-subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.feature-list {
  display: none;
  list-style: none;
  margin: 0;
  padding: 0;
  flex-direction: column;
  gap: var(--space-3);
}

.feature-list li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.feature-list li :deep(.app-icon) {
  color: var(--gray-400);
  flex-shrink: 0;
}

/* 表单区 */
.form-panel {
  padding: 0 var(--space-8) var(--space-8);
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.form-header {
  display: none;
  margin-bottom: var(--space-5);
}

.form-title {
  margin: 0 0 var(--space-1) 0;
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.form-subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

/* 表单 */
.register-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.form-field label {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--text-primary);
}

.required {
  color: var(--danger);
  font-weight: var(--font-semibold);
  margin-left: 2px;
}

.optional {
  color: var(--text-disabled);
  font-weight: var(--font-normal);
  font-size: var(--text-xs);
}

.input {
  width: 100%;
  padding: 10px var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  color: var(--text-primary);
  background: var(--bg-card);
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
  outline: none;
  box-sizing: border-box;
}

.input::placeholder {
  color: var(--text-disabled);
}

.input:focus {
  border-color: var(--gray-900);
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.06);
}

/* 隐藏浏览器原生的密码显示按钮 */
input[type="password"]::-ms-reveal { display: none; }
input[type="password"]::-ms-clear { display: none; }
input[type="password"]::-webkit-textfield-decoration-container { display: none; }

/* 带图标输入框 */
.input-with-icon {
  position: relative;
}

.input-with-icon .input {
  padding-right: 44px;
}

.input-icon-btn {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.input-icon-btn:hover {
  background: var(--gray-100);
  color: var(--text-primary);
}

/* 下拉框 */
.select {
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%2352525b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
  cursor: pointer;
}

.select:invalid {
  color: var(--text-disabled);
}

.select option {
  color: var(--text-primary);
}

.field-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  padding-left: 2px;
}

/* 主按钮 */
.btn-primary {
  margin-top: var(--space-2);
  padding: 11px var(--space-4);
  background: var(--gray-900);
  color: var(--text-invert);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
  letter-spacing: var(--tracking-wide);
}

.btn-primary:hover:not(:disabled) {
  background: var(--gray-800);
}

.btn-primary:active:not(:disabled) {
  background: var(--gray-950);
}

.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-primary:focus-visible {
  outline: 2px solid var(--gray-900);
  outline-offset: 2px;
}

/* 底部链接 */
.bottom-link {
  text-align: center;
  margin: var(--space-5) 0 0 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.bottom-link a {
  color: var(--text-primary);
  font-weight: var(--font-semibold);
  cursor: pointer;
  margin-left: 2px;
}

.bottom-link a:hover {
  text-decoration: underline;
}

/* 桌面端左右分栏 */
@media (min-width: 900px) {
  .register-page {
    padding: var(--space-8) var(--space-6);
  }

  .register-card {
    max-width: 940px;
    grid-template-columns: 1fr 1.15fr;
  }

  .brand-panel {
    padding: var(--space-12) var(--space-10);
    background: var(--gray-50);
    text-align: left;
    align-items: flex-start;
    justify-content: center;
    gap: var(--space-4);
    border-right: 1px solid var(--border-subtle);
  }

  .brand-icon {
    width: 48px;
    height: 48px;
    margin-bottom: 0;
  }

  .brand-title {
    font-size: 28px;
  }

  .brand-subtitle {
    font-size: var(--text-base);
    color: var(--text-secondary);
  }

  .feature-list {
    display: flex;
    margin-top: var(--space-4);
  }

  .form-panel {
    padding: var(--space-10) var(--space-10);
  }

  .form-header {
    display: block;
  }
}
</style>