<template>
  <div
    class="main-layout"
    :class="{
      'is-desktop': isDesktop,
      'hide-tab': route.meta.hideTabBar
    }"
  >
    <aside v-if="isDesktop && !route.meta.hideTabBar" class="sidebar">
      <div class="sidebar-header">
        <AppIcon name="audio-lines" :size="24" class="sidebar-logo" />
        <span class="sidebar-title">AI 模拟面试</span>
      </div>

      <nav class="sidebar-nav dark-scrollbar">
        <div
          class="nav-item"
          :class="{ active: currentTab === 'interview' }"
          @click="switchTab('interview')"
        >
          <AppIcon name="message" :size="20" class="nav-icon" />
          <span class="nav-label">模拟面试</span>
        </div>

        <div
          class="nav-item"
          :class="{ active: currentTab === 'question-bank' }"
          @click="switchTab('question-bank')"
        >
          <AppIcon name="book" :size="20" class="nav-icon" />
          <span class="nav-label">题库中心</span>
        </div>

        <div
          class="nav-item"
          :class="{ active: currentTab === 'profile' }"
          @click="switchTab('profile')"
        >
          <AppIcon name="user" :size="20" class="nav-icon" />
          <span class="nav-label">个人中心</span>
        </div>
      </nav>

      <div class="sidebar-footer">
        <div class="sidebar-user" @click="goProfile">
          <div class="user-avatar">
            <img v-if="userInfo?.avatar_url" :src="currentUserAvatar" class="avatar-img" alt="" />
            <span v-else>{{ userInfo?.nickname?.charAt(0) || '?' }}</span>
          </div>
          <span class="user-name">{{ userInfo?.nickname || '用户' }}</span>
        </div>

        <button
          class="settings-btn"
          @click="openSettings"
          aria-label="设置"
        >
          <AppIcon name="settings" :size="18" />
        </button>
      </div>
    </aside>

    <div class="content-wrapper">
      <header v-if="!isDesktop && !route.meta.hideTabBar" class="header-bar">
        <div class="header-left">
          <AppIcon name="audio-lines" :size="22" class="header-icon" />
          <span class="app-title">AI 模拟面试</span>
        </div>

        <div class="header-right">
          <button
            class="header-avatar-btn"
            @click="goProfile"
            aria-label="个人中心"
          >
            <img
              v-if="userInfo?.avatar_url"
              :src="currentUserAvatar"
              class="header-avatar-img"
              alt=""
            />
            <span v-else>{{ userInfo?.nickname?.charAt(0) || '?' }}</span>
          </button>

          <button
            class="header-settings-btn"
            @click="openSettings"
            aria-label="设置"
          >
            <AppIcon name="settings" :size="20" />
          </button>
        </div>
      </header>

      <main class="content-area">
        <router-view />
      </main>

      <footer v-if="!isDesktop && !route.meta.hideTabBar" class="tab-bar">
        <div
          class="tab-item"
          :class="{ active: currentTab === 'interview' }"
          @click="switchTab('interview')"
        >
          <AppIcon name="message" :size="22" class="tab-icon" />
          <span class="tab-label">模拟面试</span>
        </div>

        <div class="divider"></div>

        <div
          class="tab-item"
          :class="{ active: currentTab === 'question-bank' }"
          @click="switchTab('question-bank')"
        >
          <AppIcon name="book" :size="22" class="tab-icon" />
          <span class="tab-label">题库中心</span>
        </div>

        <div class="divider"></div>

        <div
          class="tab-item"
          :class="{ active: currentTab === 'profile' }"
          @click="switchTab('profile')"
        >
          <AppIcon name="user" :size="22" class="tab-icon" />
          <span class="tab-label">个人中心</span>
        </div>
      </footer>

      <SettingsCard
        v-model="showSettings"
        :offset-top="settingsOffsetTop"
        :offset-bottom="settingsOffsetBottom"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import SettingsCard from '@/components/SettingsCard.vue'
import { getMe, currentUser as userInfo, currentUserAvatar } from '@/api/auth'

const router = useRouter()
const route = useRoute()

const isDesktop = useMediaQuery('(min-width: 1024px)')

const showSettings = ref(false)

const openSettings = () => {
  showSettings.value = true
}

// 遮罩上下偏移，避开顶栏和 tab 栏
const settingsOffsetTop = computed(() => {
  if (isDesktop.value) return '0'
  return route.meta.hideTabBar ? '0' : '56px'
})
const settingsOffsetBottom = computed(() => {
  if (isDesktop.value) return '0'
  return route.meta.hideTabBar ? '0' : '72px'
})

const currentTab = computed(() => {
  const path = route.path
  if (path.includes('/main/profile')) return 'profile'
  if (path.includes('/main/question-bank')) return 'question-bank'
  if (path.includes('/main/report') && route.query.fromHistory === 'true') {
    return 'profile'
  }
  return 'interview'
})

const switchTab = (tab) => {
  if (tab === currentTab.value) return
  router.push(`/main/${tab}`)
}

const goProfile = () => {
  if (currentTab.value === 'profile') return
  router.push('/main/profile')
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
/* 整体布局 */
.main-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background: var(--bg-page);
  font-family: var(--font-sans);
  overflow: hidden;
}

/* 顶部导航栏（移动端） */
.header-bar {
  flex-shrink: 0;
  height: 56px;
  padding: 0 var(--space-4);
  background: var(--gray-900);
  display: flex;
  align-items: center;
  justify-content: space-between;
  z-index: 10;
  border-bottom: 1px solid var(--gray-800);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.header-icon {
  color: var(--gray-50);
  flex-shrink: 0;
}

.app-title {
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--text-invert);
  letter-spacing: var(--tracking-tight);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.header-avatar-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: var(--gray-700);
  color: var(--gray-50);
  border: 1px solid var(--gray-600);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-bold);
  cursor: pointer;
  overflow: hidden;
  flex-shrink: 0;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out);
}

.header-avatar-btn:hover {
  background: var(--gray-600);
  border-color: var(--gray-500);
}

.header-avatar-btn:active {
  transform: scale(0.94);
}

.header-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.header-settings-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  color: var(--gray-400);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.header-settings-btn:hover {
  background: var(--gray-800);
  color: var(--gray-50);
}

.header-settings-btn:active {
  transform: scale(0.94);
}

/* 内容容器 */
.content-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
  position: relative;
}

.content-area {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-page);
  padding: var(--space-4) var(--space-4) 0;
}

.main-layout.hide-tab .content-area {
  padding: 0;
}

/* 底部 Tab 栏（移动端） */
.tab-bar {
  flex-shrink: 0;
  height: 72px;
  background: var(--gray-900);
  display: flex;
  align-items: stretch;
  justify-content: center;
  border-top: 1px solid var(--gray-800);
  padding: 0 var(--space-3);
}

.tab-item {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  user-select: none;
  border: none;
  background: transparent;
  color: var(--gray-400);
  gap: var(--space-1);
  padding: var(--space-2) var(--space-1);
  border-radius: var(--radius-lg);
  transition: color var(--duration-fast) var(--ease-out);
  position: relative;
}

.tab-item:hover { color: var(--text-invert); }
.tab-item.active { color: var(--text-invert); }
.tab-item.active .tab-label { font-weight: var(--font-semibold); }

.tab-icon { flex-shrink: 0; }

.tab-label {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  letter-spacing: var(--tracking-wide);
}

.divider {
  width: 1px;
  height: 32px;
  background: var(--gray-700);
  align-self: center;
  flex-shrink: 0;
  margin: 0 var(--space-1);
}

/* 桌面端 */
.main-layout.is-desktop {
  flex-direction: row;
}

.sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--gray-900);
  color: var(--text-invert);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--gray-800);
  position: relative;
  z-index: 10;
}

.sidebar-header {
  height: 64px;
  padding: 0 var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
  border-bottom: 1px solid var(--gray-800);
}

.sidebar-logo {
  color: var(--gray-50);
  flex-shrink: 0;
}

.sidebar-title {
  font-size: var(--text-base);
  font-weight: var(--font-bold);
  color: var(--text-invert);
  letter-spacing: var(--tracking-tight);
}

.sidebar-nav {
  flex: 1;
  padding: var(--space-4) var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--gray-400);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
  user-select: none;
  position: relative;
}

.nav-item:hover {
  background: var(--gray-800);
  color: var(--text-invert);
}

.nav-item.active {
  background: var(--gray-800);
  color: var(--text-invert);
  font-weight: var(--font-semibold);
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 60%;
  background: var(--gray-50);
  border-radius: 0 3px 3px 0;
}

.nav-icon { flex-shrink: 0; }
.nav-label { white-space: nowrap; }

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--gray-800);
  flex-shrink: 0;
}

.sidebar-user {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-1) var(--space-1);
  border-radius: var(--radius-md);
  cursor: pointer;
  min-width: 0;
  transition: background var(--duration-fast) var(--ease-out);
  user-select: none;
}

.sidebar-user:hover {
  background: var(--gray-800);
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  background: var(--gray-700);
  color: var(--text-invert);
  font-size: var(--text-xs);
  font-weight: var(--font-bold);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--gray-600);
  overflow: hidden;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.user-name {
  font-size: var(--text-sm);
  color: var(--gray-300);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.settings-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  color: var(--gray-400);
  cursor: pointer;
  flex-shrink: 0;
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.settings-btn:hover {
  background: var(--gray-800);
  color: var(--gray-50);
}

.settings-btn:active {
  transform: scale(0.94);
}

.main-layout.is-desktop .content-area {
  padding: var(--space-8) var(--space-12);
}

.main-layout.is-desktop.hide-tab .content-area {
  padding: 0;
}
</style>