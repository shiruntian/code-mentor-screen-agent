<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { useUiStore } from '../stores/ui'
import { shortModel } from '../utils/format'

const app = useAppStore()
const ui = useUiStore()
const menuOpen = ref(false)

const title = computed(() => app.activeConversation?.title || '新对话')
const subtitle = computed(() => {
  const cfg = app.activeConfig
  if (!cfg) return '未配置模型'
  const info = app.activeProviderInfo
  return `${info?.label || cfg.provider} · ${app.mode === 'agent' ? '智能体编排' : '快速对话'}`
})

const providerOptions = computed(() =>
  app.providers.map((p) => ({
    value: p.provider,
    label: `${p.label}${p.has_key ? '' : p.needs_key ? '（未配置）' : ''}`,
  })),
)

const modelOptions = computed(() => {
  const list = app.modelsFor(app.activeProvider) || []
  return list.map((m) => ({
    value: m.id,
    label: `${m.label || m.id}${m.vision ? ' · 视觉' : ''}`,
  }))
})

const modelsMeta = computed(() => app.modelsMeta[app.activeProvider] || null)

async function refreshModels() {
  await app.loadProviderModels(app.activeProvider, { refresh: true })
}

function toggleMenu() {
  menuOpen.value = !menuOpen.value
  if (menuOpen.value && !app.modelsByProvider[app.activeProvider]) {
    void app.loadProviderModels(app.activeProvider)
  }
}

async function onProviderChange(e: Event) {
  const provider = (e.target as HTMLSelectElement).value
  if (provider === app.activeProvider) return
  await app.activateProvider(provider)
}

async function onModelChange(e: Event) {
  const model = (e.target as HTMLSelectElement).value
  await app.switchModel(model)
}
</script>

<template>
  <header class="chat-header">
    <div class="left">
      <div class="titles">
        <div class="title ellipsis">{{ title }}</div>
        <div class="subtitle">{{ subtitle }}</div>
      </div>
    </div>

    <div class="right">
      <div class="model-picker">
        <button class="picker-btn" :class="{ open: menuOpen }" @click="toggleMenu">
          <span class="spark" />
          <span class="ellipsis">{{ shortModel(app.currentModel) }}</span>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <path d="M6 9l6 6 6-6" stroke-linecap="round" />
          </svg>
        </button>

        <transition name="slide">
          <div v-if="menuOpen" class="picker-menu" @click.stop>
            <div class="field">
              <label>模型供应商</label>
              <select class="select" :value="app.activeProvider" @change="onProviderChange">
                <option v-for="p in providerOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </div>
            <div class="field">
              <label>模型</label>
              <select class="select" :value="app.currentModel" @change="onModelChange">
                <option v-for="m in modelOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
              </select>
            </div>
            <div class="model-source">
              <span class="tiny muted ellipsis">
                {{ app.modelsLoading === app.activeProvider ? '正在获取模型列表…' : modelsMeta?.message || '候选来自内置推荐' }}
              </span>
              <button
                class="btn btn-sm btn-ghost"
                :disabled="app.modelsLoading === app.activeProvider"
                @click="refreshModels"
              >
                刷新列表
              </button>
            </div>
            <div class="picker-foot">
              <span class="tiny muted ellipsis">{{ app.activeProviderInfo?.base_url }}</span>
              <button class="btn btn-sm btn-ghost" @click="menuOpen = false; ui.openSettings()">
                配置密钥 →
              </button>
            </div>
          </div>
        </transition>
      </div>

      <button
        class="icon-btn theme-btn"
        :title="ui.isLight ? '切换到深色主题' : '切换到浅色主题'"
        @click="ui.toggleTheme()"
      >
        <svg
          v-if="ui.isLight"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
        >
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <svg
          v-else
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
        >
          <circle cx="12" cy="12" r="4.2" />
          <path
            d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5 5l1.4 1.4M17.6 17.6L19 19M19 5l-1.4 1.4M6.4 17.6L5 19"
            stroke-linecap="round"
          />
        </svg>
      </button>

      <button
        class="icon-btn"
        :class="{ on: app.panelOpen }"
        title="智能体面板"
        @click="app.togglePanel()"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <rect x="3" y="4" width="18" height="16" rx="3" />
          <path d="M15 4v16" />
        </svg>
      </button>
    </div>

    <div v-if="menuOpen" class="overlay" @click="menuOpen = false" />
  </header>
</template>

<style scoped>
.chat-header {
  height: 60px;
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 18px;
  border-bottom: 1px solid var(--border);
  background: var(--header-bg);
  backdrop-filter: blur(14px);
  position: relative;
  z-index: 20;
}
.titles {
  min-width: 0;
}
.title {
  font-size: 14.5px;
  font-weight: 600;
}
.subtitle {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 2px;
}
.right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-picker {
  position: relative;
}
.picker-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  max-width: 240px;
  padding: 7px 11px;
  border-radius: 10px;
  font-size: 12.5px;
  color: var(--text-2);
  background: var(--elev-1);
  border: 1px solid var(--border);
  transition: all 0.16s;
}
.picker-btn:hover,
.picker-btn.open {
  background: var(--elev-2);
  color: var(--text-1);
  border-color: var(--border-strong);
}
.spark {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--grad-accent);
  box-shadow: 0 0 8px rgba(99, 102, 241, 0.8);
}

.picker-menu {
  position: absolute;
  top: 44px;
  right: 0;
  width: 292px;
  padding: 14px;
  border-radius: 14px;
  background: var(--surface-2);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(20px);
  z-index: 40;
}
.field + .field {
  margin-top: 10px;
}
.field label {
  display: block;
  font-size: 11px;
  color: var(--text-3);
  margin-bottom: 5px;
  letter-spacing: 0.3px;
}
.picker-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.model-source {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
}
.model-source .tiny {
  flex: 1;
  min-width: 0;
  line-height: 1.5;
}

.overlay {
  position: fixed;
  inset: 0;
  z-index: 10;
}

.icon-btn.on {
  background: rgba(99, 102, 241, 0.18);
  color: var(--accent-ink);
}
</style>