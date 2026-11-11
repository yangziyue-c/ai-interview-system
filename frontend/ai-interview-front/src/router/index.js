// src/router/index.js
import { createRouter, createWebHashHistory } from 'vue-router'

// 路由懒加载：每个页面单独打包
// 首屏只加载当前页面，其他页面按需加载
const LoginPage = () => import('@/views/LoginPage.vue')
const RegisterPage = () => import('@/views/RegisterPage.vue')
const LauncherPage = () => import('@/views/LauncherPage.vue')
const MainLayout = () => import('@/views/MainLayout.vue')
const InterviewHall = () => import('@/views/InterviewHall.vue')
const InterviewDetail = () => import('@/views/InterviewDetail.vue')
const InterviewRoom = () => import('@/views/InterviewRoom.vue')
const CareerAnchor = () => import('@/views/CareerAnchor.vue')
const ReportPage = () => import('@/views/ReportPage.vue')
const QaHistoryPage = () => import('@/views/QaHistoryPage.vue')
const QuestionBank = () => import('@/views/QuestionBank.vue')
const ProfilePage = () => import('@/views/ProfilePage.vue')
const ResumePage = () => import('@/views/ResumePage.vue')
const ShareReportPage = () => import('@/views/ShareReportPage.vue')
const NotFound = () => import('@/views/NotFound.vue')

const routes = [
    {
        path: '/',
        redirect: '/login'
    },
    {
        path: '/login',
        component: LoginPage,
        meta: { title: '登录' }
    },
    {
        path: '/register',
        component: RegisterPage,
        meta: { title: '注册' }
    },
    {
        path: '/launcher',
        component: LauncherPage,
        meta: { title: '选择模块' }
    },
    {
        path: '/share/:code',
        component: ShareReportPage,
        meta: { title: '分享报告' }
    },
    {
        path: '/main',
        component: MainLayout,
        redirect: '/main/interview',
        children: [
            {
                path: 'interview',
                component: InterviewHall,
                meta: { title: '岗位大厅' }
            },
            {
                path: 'interview/detail',
                component: InterviewDetail,
                meta: { title: '岗位详情' }
            },
            {
                path: 'interview/room',
                component: InterviewRoom,
                meta: { title: '面试对话室', hideTabBar: true }
            },
            {
                path: 'career-anchor',
                component: CareerAnchor,
                meta: { title: '岗位倾向速测', hideTabBar: true }
            },
            {
                path: 'question-bank',
                component: QuestionBank,
                meta: { title: '题库中心' }
            },
            {
                path: 'report',
                component: ReportPage,
                meta: { title: '面试报告', hideTabBar: true }
            },
            {
                path: 'qa-history',
                component: QaHistoryPage,
                meta: { title: '问答记录', hideTabBar: true }
            },
            {
                path: 'resume',
                component: ResumePage,
                meta: { title: '我的简历', hideTabBar: true }
            },
            {
                path: 'profile',
                component: ProfilePage,
                meta: { title: '个人中心' }
            }
        ]
    },
    {
        path: '/:pathMatch(.*)*',
        name: 'NotFound',
        component: NotFound,
        meta: { title: '页面不存在' }
    }
]

const router = createRouter({
    history: createWebHashHistory(),
    routes
})

// 根据路由 meta 更新 document.title
const APP_TITLE = 'AI 模拟面试'

router.afterEach((to) => {
    const pageTitle = to.meta?.title
    document.title = pageTitle ? `${pageTitle} · ${APP_TITLE}` : APP_TITLE
})

// 路由守卫
const PUBLIC_PAGES = ['/login', '/register']
const LAUNCHER_PAGE = '/launcher'

router.beforeEach((to, from, next) => {
    if (to.name === 'NotFound') {
        return next()
    }

    if (to.path.startsWith('/share/')) {
        return next()
    }

    const token = localStorage.getItem('token')
    const isPublicPage = PUBLIC_PAGES.includes(to.path)

    if (!token && !isPublicPage) {
        return next('/login')
    }

    if (token && isPublicPage) {
        sessionStorage.removeItem('hasChosenModule')
        return next(LAUNCHER_PAGE)
    }

    if (token && !isPublicPage) {
        const hasChosen = sessionStorage.getItem('hasChosenModule') === 'true'

        if (hasChosen && to.path === LAUNCHER_PAGE) {
            return next('/main/interview')
        }

        if (!hasChosen && to.path !== LAUNCHER_PAGE) {
            return next(LAUNCHER_PAGE)
        }
    }

    next()
})

export default router
