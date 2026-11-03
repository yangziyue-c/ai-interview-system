<template>
  <div class="launcher-page" :class="{ 'is-desktop': isDesktop }">
    <header class="topbar">
      <button class="icon-btn" @click="openSettings" aria-label="设置">
        <AppIcon name="settings" :size="20" />
      </button>

      <div class="user-info">
        <span class="user-name">{{ userInfo?.nickname || '用户' }}</span>
        <div class="user-avatar">
          <img v-if="userInfo?.avatar_url" :src="currentUserAvatar" class="avatar-img" alt="" />
          <span v-else>{{ userInfo?.nickname?.charAt(0) || '?' }}</span>
        </div>
      </div>
    </header>

    <section class="hero">
      <h1 class="hero-title">AI 模拟面试系统</h1>
      <p class="hero-subtitle">欢迎您，请选择要进入的模块</p>
    </section>

    <div class="card-grid">
      <div class="feature-card" @click="choose('/main/interview')">
        <div class="card-icon">
          <AppIcon name="mic" :size="28" />
        </div>
        <div class="card-body">
          <h3 class="card-title">实战演练</h3>
          <p class="card-desc">与 AI 面试官实时对话，模拟真实面试</p>
        </div>
        <AppIcon name="chevron-right" :size="18" class="card-arrow" />
      </div>

      <div class="feature-card" @click="choose('/main/question-bank')">
        <div class="card-icon">
          <AppIcon name="book" :size="28" />
        </div>
        <div class="card-body">
          <h3 class="card-title">精选题库</h3>
          <p class="card-desc">浏览岗位题库，针对性练习</p>
        </div>
        <AppIcon name="chevron-right" :size="18" class="card-arrow" />
      </div>

      <div class="feature-card" @click="choose('/main/profile')">
        <div class="card-icon">
          <AppIcon name="trending" :size="28" />
        </div>
        <div class="card-body">
          <h3 class="card-title">历史记录</h3>
          <p class="card-desc">查看过往面试成绩与成长曲线</p>
        </div>
        <AppIcon name="chevron-right" :size="18" class="card-arrow" />
      </div>
    </div>

    <SettingsCard v-model="showSettings" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import SettingsCard from '@/components/SettingsCard.vue'
import { getMe, currentUser as userInfo, currentUserAvatar } from '@/api/auth'
import { showToast } from '@/utils/toast'

const router = useRouter()
const isDesktop = useMediaQuery('(min-width: 1024px)')

const showSettings = ref(false)

const choose = (path) => {
  sessionStorage.setItem('hasChosenModule', 'true')
  router.push(path)
}

const openSettings = () => {
  const token = localStorage.getItem('token')
  if (!token) {
    showToast('尚未登录')
    return
  }
  showSettings.value = true
}

onMounted(async () => {
  try {
    await getMe()
  } catch (e) {
    console.error('获取用户信息失败', e)
  }
})
</script>

<style scoped>
/* 页面容器 */
.launcher-page {
  min-height: 100vh;
  padding: var(--space-5) var(--space-4);
  background: var(--bg-page);
  font-family: var(--font-sans);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  position: relative;
}

/* 顶部栏 */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--space-4);
}

.icon-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.icon-btn:hover {
  color: var(--text-primary);
  border-color: var(--border-strong);
  background: var(--gray-50);
}

.icon-btn:active {
  transform: scale(0.96);
}

.user-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.user-name {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
}

.user-avatar {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-full);
  background: var(--gray-900);
  color: var(--text-invert);
  font-size: var(--text-sm);
  font-weight: var(--font-bold);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* Hero 区 */
.hero {
  text-align: center;
  padding: var(--space-8) 0 var(--space-10);
}

.hero-title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.hero-subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

/* 功能卡片 */
.card-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.feature-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.feature-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.feature-card:active {
  transform: translateY(0);
  background: var(--gray-50);
}

.card-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  color: var(--text-primary);
  border-radius: var(--radius-lg);
  flex-shrink: 0;
  transition: background var(--duration-fast) var(--ease-out);
}

.feature-card:hover .card-icon {
  background: var(--gray-200);
}

.card-body {
  flex: 1;
  min-width: 0;
}

.card-title {
  margin: 0 0 var(--space-1) 0;
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.card-desc {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  line-height: var(--leading-normal);
}

.card-arrow {
  color: var(--text-disabled);
  flex-shrink: 0;
  transition: color var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.feature-card:hover .card-arrow {
  color: var(--text-primary);
  transform: translateX(2px);
}

/* 桌面端 */
.launcher-page.is-desktop {
  padding: var(--space-6) var(--space-8);
}

.launcher-page.is-desktop .topbar {
  max-width: 960px;
  width: 100%;
  margin: 0 auto;
}

.launcher-page.is-desktop .hero {
  padding: var(--space-12) 0 var(--space-12);
}

.launcher-page.is-desktop .hero-title {
  font-size: var(--text-3xl);
}

.launcher-page.is-desktop .hero-subtitle {
  font-size: var(--text-base);
}

.launcher-page.is-desktop .card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-5);
  max-width: 960px;
  width: 100%;
  margin: 0 auto;
}

.launcher-page.is-desktop .feature-card {
  flex-direction: column;
  align-items: flex-start;
  padding: var(--space-8) var(--space-6) var(--space-6);
  gap: var(--space-4);
  min-height: 220px;
}

.launcher-page.is-desktop .card-icon {
  width: 64px;
  height: 64px;
}

.launcher-page.is-desktop .card-title {
  font-size: var(--text-lg);
}

.launcher-page.is-desktop .card-body {
  flex: 1;
}

.launcher-page.is-desktop .card-arrow {
  align-self: flex-start;
}
</style>