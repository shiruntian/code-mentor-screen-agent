<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import ChatHeader from './components/ChatHeader.vue'
import MessageList from './components/MessageList.vue'
import Composer from './components/Composer.vue'
import TaskBar from './components/TaskBar.vue'
import { useBrandingStore } from './stores/branding'
import { accentHex, applyAppearance, fontFamily, readAppearance } from './styles/appearance'
import { api } from './api/client'
import AgentPanel from './components/AgentPanel.vue'
import BackgroundLayer from './components/BackgroundLayer.vue'
import SettingsModal from './components/SettingsModal.vue'
import ScreenModal from './components/ScreenModal.vue'
import ImageLightbox from './components/ImageLightbox.vue'
import { useAppStore } from './stores/app'
import { useUiStore } from './stores/ui'

const app = useAppStore()
const branding = useBrandingStore()
branding.load()
applyAppearance()
const ui = useUiStore()

/** 把"界面主题 + 主题色 + 字体"同步给后端：屏幕演示的提问窗按这套配色画。 */
let syncTimer: number | undefined
function syncAskLook() {
  window.clearTimeout(syncTimer)
  syncTimer = window.setTimeout(async () => {
    try {
      const look = readAppearance()
      // 用户明确关掉「跟随界面」时不要覆盖他手填的配色
      if (app.settings?.runtime?.screen_ask_follow_ui === false) return
      await api.put('/api/settings', {
        screen_ask_theme: ui.themeResolved === 'light' ? 'light' : 'dark',
        screen_ask_accent: accentHex(look.accent),
        screen_ask_font: fontFamily(look.font),
      })
    } catch {
      /* 后端没起来时忽略 */
    }
  }, 400)
}

/** 拖到输入框以外的地方时，别让浏览器把图片当新页面打开（会丢掉整个应用） */
function guardFileDrop(e: DragEvent) {
  const hasFiles = Array.from(e.dataTransfer?.types || []).includes('Files')
  if (hasFiles) e.preventDefault()
}

onMounted(() => {
  ui.initTheme()
  app.boot()
  syncAskLook()
  window.addEventListener('cm-appearance', syncAskLook)
  window.addEventListener('dragover', guardFileDrop)
  window.addEventListener('drop', guardFileDrop)
})

onBeforeUnmount(() => {
  window.removeEventListener('cm-appearance', syncAskLook)
  window.removeEventListener('dragover', guardFileDrop)
  window.removeEventListener('drop', guardFileDrop)
})
</script>

<template>
  <BackgroundLayer />

  <div class="shell">
    <AppSidebar />

    <main class="workspace">
      <ChatHeader />
      <MessageList />
      <TaskBar />
      <Composer />
    </main>

    <AgentPanel v-if="app.panelOpen" />

    <!-- 后端不可达 -->
    <div v-if="app.bootError" class="boot-error">
      <div class="card">
        <h2>🐳 连不上后端服务</h2>
        <p>{{ app.bootError }}</p>
        <p class="hint">请在项目根目录执行：</p>
        <pre>cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000</pre>
        <button class="btn btn-primary" @click="app.boot()">重试连接</button>
      </div>
    </div>

    <SettingsModal v-if="ui.settingsOpen" />
    <ScreenModal v-if="ui.screenOpen" />
    <ImageLightbox />

    <!-- 全局提示 -->
    <div class="toasts">
      <transition-group name="slide">
        <div v-for="t in app.toasts" :key="t.id" class="toast" :class="t.type">
          <span class="t-icon">
            {{ t.type === 'success' ? '✓' : t.type === 'error' ? '✕' : t.type === 'warning' ? '!' : 'i' }}
          </span>
          <div class="t-body">
            <div class="t-msg">{{ t.message }}</div>
            <div v-if="t.hint" class="t-hint">{{ t.hint }}</div>
          </div>
          <button class="t-close" @click="app.dismissToast(t.id)">×</button>
        </div>
      </transition-group>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100%;
  overflow: hidden;
  position: relative;
  z-index: 1;
}
.workspace {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.boot-error {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  background: var(--overlay-solid);
}
.boot-error .card {
  width: min(520px, 92vw);
  padding: 26px;
  border-radius: 16px;
  background: var(--surface-2);
  border: 1px solid var(--border-strong);
  text-align: center;
}
.boot-error h2 {
  margin: 0 0 10px;
  font-size: 17px;
}
.boot-error p {
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.7;
}
.boot-error .hint {
  margin-top: 16px;
  text-align: left;
  color: var(--text-3);
}
.boot-error pre {
  text-align: left;
  padding: 12px;
  border-radius: 10px;
  background: var(--inset-bg);
  border: 1px solid var(--border);
  font-size: 11.5px;
  color: var(--accent-ink-strong);
  overflow-x: auto;
}

.toasts {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 120;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 360px;
}
.toast {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 11px 13px;
  border-radius: 12px;
  background: var(--toast-bg);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(14px);
}
.t-icon {
  width: 18px;
  height: 18px;
  min-width: 18px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 11px;
  background: rgba(99, 102, 241, 0.2);
  color: var(--accent-ink-strong);
}
.toast.success .t-icon {
  background: rgba(52, 211, 153, 0.2);
  color: var(--success-ink);
}
.toast.error .t-icon {
  background: rgba(248, 113, 113, 0.2);
  color: var(--danger-ink);
}
.toast.warning .t-icon {
  background: rgba(251, 191, 36, 0.2);
  color: var(--warn-ink);
}
.t-body {
  flex: 1;
  min-width: 0;
}
.t-msg {
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-1);
}
.t-hint {
  margin-top: 3px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-3);
}
.t-close {
  color: var(--text-3);
  font-size: 15px;
  line-height: 1;
}
.t-close:hover {
  color: var(--text-1);
}
</style>