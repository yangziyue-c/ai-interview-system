import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

// 引入设计系统变量
import './styles/tokens.css'

// 从 localStorage 恢复登录态（在挂载前执行一次）
import { initAuth } from './api/auth'

initAuth()

const app = createApp(App)
app.use(router)
app.mount('#app')