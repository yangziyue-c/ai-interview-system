<template>
  <div class="notfound-page">
    <div class="notfound-card">
      <div class="brand-icon">
        <AppIcon name="alert" :size="28" />
      </div>

      <p class="error-code">404</p>
      <h2 class="error-title">页面走丢了</h2>
      <p class="error-desc">
        你访问的页面不存在，或链接已经失效。
      </p>

      <div class="action-buttons">
        <button class="btn btn-secondary" @click="goBack">返回上一页</button>
        <button class="btn btn-primary" @click="goHome">返回首页</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'

const router = useRouter()

const goHome = () => {
  const token = localStorage.getItem('token')
  router.push(token ? '/main/interview' : '/login')
}

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
  } else {
    goHome()
  }
}
</script>

<style scoped>
/* 页面容器 */
.notfound-page {
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

/* 卡片 */
.notfound-card {
  width: 100%;
  max-width: 380px;
  padding: var(--space-10) var(--space-8) var(--space-8);
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  text-align: center;
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.06),
    0 24px 48px rgba(0, 0, 0, 0.4);
  animation: fadeInUp 0.4s var(--ease-out);
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 图标容器 */
.brand-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto var(--space-5);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-900);
  color: var(--gray-50);
  border-radius: var(--radius-lg);
}

/* 404 数字 */
.error-code {
  margin: 0;
  font-size: 56px;
  font-weight: var(--font-bold);
  line-height: 1;
  letter-spacing: -0.04em;
  color: var(--text-primary);
}

.error-title {
  margin: var(--space-3) 0 var(--space-2) 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.error-desc {
  margin: 0 0 var(--space-6) 0;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-tertiary);
}

/* 按钮组 */
.action-buttons {
  display: flex;
  gap: var(--space-2);
}

.btn {
  flex: 1;
  padding: 11px var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}

.btn:active {
  transform: scale(0.98);
}

.btn-primary {
  background: var(--gray-900);
  color: var(--text-invert);
  border: 1px solid var(--gray-900);
}

.btn-primary:hover {
  background: var(--gray-800);
  border-color: var(--gray-800);
}

.btn-secondary {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.btn-secondary:hover {
  border-color: var(--border-strong);
  background: var(--gray-50);
}
</style>