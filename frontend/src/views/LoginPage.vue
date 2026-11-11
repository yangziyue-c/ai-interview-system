<template>
  <div class="login-page">
    <div class="login-card">
      <aside class="brand-panel">
        <div class="brand-icon">
          <AppIcon name="audio-lines" :size="28" />
        </div>
        <h1 class="brand-title">AI 模拟面试</h1>
        <p class="brand-subtitle">登录账号，开启智能面试练习</p>

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
          <h2 class="form-title">登录</h2>
          <p class="form-subtitle">欢迎回来，请填写账号信息</p>
        </header>

        <form class="login-form" @submit.prevent="handleLogin">
          <div class="form-field">
            <label for="username">账号</label>
            <input
              id="username"
              type="text"
              v-model="form.username"
              placeholder="请输入账号"
              class="input"
              autocomplete="username"
              required
            />
          </div>

          <div class="form-field">
            <label for="password">密码</label>
            <div class="input-with-icon">
              <input
                id="password"
                :type="showPassword ? 'text' : 'password'"
                v-model="form.password"
                placeholder="请输入密码"
                class="input"
                autocomplete="current-password"
                required
                @keyup.enter="handleLogin"
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

          <button type="submit" class="btn-primary" :disabled="loading">
            {{ loading ? '登录中...' : '登 录' }}
          </button>
        </form>

        <p class="bottom-link">
          还没有账号？<a @click="goRegister">立即注册</a>
        </p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { login } from '@/api/auth'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import { showToast } from '@/utils/toast'

const router = useRouter()

const form = ref({
  username: '',
  password: ''
})
const loading = ref(false)
const showPassword = ref(false)

const handleLogin = async () => {
  if (!form.value.username.trim() || !form.value.password.trim()) {
    showToast('请输入账号和密码')
    return
  }

  loading.value = true
  try {
    const { token, user } = await login(form.value.username, form.value.password)

    localStorage.setItem('token', token)
    localStorage.setItem('userInfo', JSON.stringify(user))

    sessionStorage.removeItem('hasChosenModule')
    router.push('/launcher')
  } catch (e) {
    console.error('登录失败', e)
    showToast(e.message || '登录失败，请重试')
  } finally {
    loading.value = false
  }
}

const goRegister = () => {
  router.push('/register')
}
</script>

<style scoped>
/* 页面容器 */
.login-page {
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
.login-card {
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
  padding: var(--space-10) var(--space-8) var(--space-6);
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
  margin-bottom: var(--space-6);
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

/* 表单字段 */
.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
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
input[type="password"]::-ms-reveal {
  display: none;
}
input[type="password"]::-ms-clear {
  display: none;
}
input[type="password"]::-webkit-textfield-decoration-container {
  display: none;
}

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
  .login-page {
    padding: var(--space-8) var(--space-6);
  }

  .login-card {
    max-width: 900px;
    grid-template-columns: 1fr 1fr;
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
    padding: var(--space-12) var(--space-10);
  }

  .form-header {
    display: block;
  }
}
</style>