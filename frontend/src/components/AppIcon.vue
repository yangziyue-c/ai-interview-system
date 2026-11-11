<template>
  <component
    :is="iconComponent"
    :size="size"
    :stroke-width="strokeWidth"
    :color="color"
    class="app-icon"
  />
</template>

<script setup>
import { computed } from 'vue'
import {
  Mic, AudioLines, FileText, ClipboardCheck, ShieldCheck, Lightbulb,
  Loader2, ChevronLeft, ChevronRight, X, Check, Coffee, Code2,
  TestTube, Cpu, Network, User, MessageSquare, Send, Play,
  RotateCcw, Home, LogOut, Settings, Eye, EyeOff, Award,
  TrendingUp, AlertCircle, CheckCircle2, Info, Plus, Trash2,
  Edit, Search, Filter, BarChart3, PieChart, Sparkles,
  BookOpen, GraduationCap, Briefcase, Clock, Calendar, Link, Copy,
  Bell, Palette, Volume2, VolumeX, Video, VideoOff,
  Server, Monitor, Bug, Brain, Layers
} from 'lucide-vue-next'

const props = defineProps({
  name: {
    type: String,
    required: true
  },
  size: {
    type: [Number, String],
    default: 20
  },
  strokeWidth: {
    type: [Number, String],
    default: 1.75
  },
  color: {
    type: String,
    default: 'currentColor'
  }
})

// 图标映射表：字符串名转组件
const iconMap = {
  mic: Mic,
  'audio-lines': AudioLines,
  file: FileText,
  'clipboard-check': ClipboardCheck,
  shield: ShieldCheck,
  lightbulb: Lightbulb,
  loading: Loader2,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  close: X,
  check: Check,
  coffee: Coffee,
  code: Code2,
  test: TestTube,
  cpu: Cpu,
  network: Network,
  user: User,
  message: MessageSquare,
  send: Send,
  play: Play,
  retry: RotateCcw,
  home: Home,
  logout: LogOut,
  settings: Settings,
  eye: Eye,
  'eye-off': EyeOff,
  award: Award,
  trending: TrendingUp,
  alert: AlertCircle,
  'check-circle': CheckCircle2,
  info: Info,
  plus: Plus,
  trash: Trash2,
  edit: Edit,
  search: Search,
  filter: Filter,
  'bar-chart': BarChart3,
  'pie-chart': PieChart,
  sparkles: Sparkles,
  book: BookOpen,
  graduation: GraduationCap,
  briefcase: Briefcase,
  clock: Clock,
  calendar: Calendar,
  link: Link,
  copy: Copy,
  bell: Bell,
  palette: Palette,
  'volume-2': Volume2,
  'volume-x': VolumeX,
  'video': Video,
  'video-off': VideoOff,
  // 岗位 / 区块图标
  server: Server,
  monitor: Monitor,
  bug: Bug,
  brain: Brain,
  layers: Layers
}

const iconComponent = computed(() => {
  const comp = iconMap[props.name]
  if (!comp) {
    console.warn(`[AppIcon] 未知图标名："${props.name}"，已回退到 "info"`)
    return Info
  }
  return comp
})
</script>

<style scoped>
.app-icon {
  display: inline-block;
  vertical-align: middle;
  flex-shrink: 0;
}

/* 加载图标旋转动画 */
.app-icon.lucide-loader-2,
:deep(.lucide-loader-2) {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
</style>