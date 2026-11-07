<script setup lang="ts">
import { useBrandingStore } from '../stores/branding'

const branding = useBrandingStore()
import { computed, nextTick, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { useUiStore } from '../stores/ui'
import { relativeTime } from '../utils/format'

const app = useAppStore()
const ui = useUiStore()
const editingId = ref<string | null>(null)
const editingTitle = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

const activeModelLabel = computed(() => {
  const cfg = app.activeConfig
  const info = app.activeProviderInfo
  if (!cfg || !info) return '未配置模型'
  return `${info.label.split(' ')[0]} · ${cfg.model || '默认'}`
})

async function startRename(id: string, title: string) {
  editingId.value = id
  editingTitle.value = title
  await nextTick()
  inputRef.value?.focus()
  inputRef.value?.select()
}

async function commitRename() {
  if (!editingId.value) return
  const id = editingId.value
  const title = editingTitle.value
  editingId.value = null
  if (title.trim()) await app.renameConversation(id, title)
}

function cancelRename() {
  editingId.value = null
}

async function remove(id: string, title: string) {
  if (window.confirm(`确定删除会话「${title}」吗？该会话的消息将永久删除。`)) {
    await app.deleteConversation(id)
  }
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="logo">
          <img v-if="branding.logoUrl" :src="branding.logoUrl" alt="logo" />
          <span v-else>🐳</span>
        </div>
      <div class="brand-text">
        <div class="name">{{ branding.name }}</div>
        <div class="sub">编程学习助手</div>
      </div>
      <button class="icon-btn" title="模型设置" @click="ui.openSettings()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3.05V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9v0a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1z" />
        </svg>
      </button>
    </div>

    <button class="new-chat" @click="app.newConversation()">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 5v14M5 12h14" stroke-linecap="round" />
      </svg>
      <span>新建对话</span>
    </button>

    <div class="list-head">
      <span>对话记录</span>
      <span class="count">{{ app.conversations.length }}</span>
    </div>

    <div class="conv-list scroll-y">
      <div v-if="app.conversations.length === 0" class="empty-side">
        还没有对话，<br />点上面的按钮开始吧
      </div>
      <div
        v-for="conv in app.conversations"
        :key="conv.id"
        class="conv"
        :class="{ active: conv.id === app.activeId }"
        @click="editingId !== conv.id && app.selectConversation(conv.id)"
      >
        <div class="conv-main">
          <input
            v-if="editingId === conv.id"
            ref="inputRef"
            v-model="editingTitle"
            class="rename-input"
            @click.stop
            @keydown.enter.prevent="commitRename"
            @keydown.esc.prevent="cancelRename"
            @blur="commitRename"
          />
          <template v-else>
            <div class="conv-title ellipsis">{{ conv.title }}</div>
            <div class="conv-meta">
              <span>{{ conv.message_count }} 条</span>
              <span class="sep">·</span>
              <span>{{ relativeTime(conv.updated_at) }}</span>
            </div>
          </template>
        </div>
        <div class="conv-actions" @click.stop>
          <button class="mini" title="重命名" @click="startRename(conv.id, conv.title)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          <button class="mini danger" title="删除" @click="remove(conv.id, conv.title)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <div class="sidebar-foot">
      <button class="model-chip" @click="ui.openSettings()">
        <span class="dot" :class="{ 'dot-pulse': app.streaming }" />
        <span class="ellipsis">{{ activeModelLabel }}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M6 9l6 6 6-6" stroke-linecap="round" />
        </svg>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
  border-right: 1px solid var(--border);
  backdrop-filter: blur(20px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 14px 12px;
}
.logo {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  font-size: 18px;
  background: var(--grad-accent);
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.35);
  overflow: hidden;
  flex: none;
}
.logo img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.brand-text .name {
  font-size: 14.5px;
  font-weight: 650;
  letter-spacing: 0.2px;
}
.brand-text .sub {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 1px;
}

.new-chat {
  margin: 4px 12px 12px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 11px;
  font-size: 13.5px;
  font-weight: 600;
  color: #fff;
  background: var(--grad-accent);
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.28);
  transition: all 0.18s ease;
}
.new-chat:hover {
  filter: brightness(1.08);
  transform: translateY(-1px);
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px 8px;
  font-size: 11px;
  letter-spacing: 0.8px;
  color: var(--text-3);
  text-transform: uppercase;
}
.count {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--elev-2);
  font-size: 10.5px;
}

.conv-list {
  flex: 1;
  padding: 0 8px 8px;
}
.empty-side {
  padding: 26px 14px;
  text-align: center;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-3);
}

.conv {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 10px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.16s ease;
  margin-bottom: 2px;
  border: 1px solid transparent;
}
.conv:hover {
  background: var(--elev-1);
}
.conv.active {
  background: linear-gradient(90deg, rgba(99, 102, 241, 0.18), rgba(34, 211, 238, 0.06));
  border-color: rgba(99, 102, 241, 0.28);
}
.conv-main {
  flex: 1;
  min-width: 0;
}
.conv-title {
  font-size: 13px;
  color: var(--text-1);
}
.conv-meta {
  margin-top: 3px;
  font-size: 11px;
  color: var(--text-3);
  display: flex;
  gap: 5px;
}
.conv-actions {
  display: none;
  gap: 2px;
}
.conv:hover .conv-actions {
  display: flex;
}
.mini {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  color: var(--text-3);
}
.mini:hover {
  background: var(--elev-3);
  color: var(--text-1);
}
.mini.danger:hover {
  color: var(--danger);
  background: rgba(248, 113, 113, 0.12);
}
.rename-input {
  width: 100%;
  background: var(--inset-bg);
  border: 1px solid rgba(99, 102, 241, 0.5);
  border-radius: 6px;
  padding: 4px 7px;
  font-size: 12.5px;
  outline: none;
}

.sidebar-foot {
  padding: 10px;
  border-top: 1px solid var(--border);
}
.model-chip {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  font-size: 12px;
  color: var(--text-2);
  background: var(--elev-1);
  border: 1px solid var(--border);
  transition: all 0.16s ease;
}
.model-chip:hover {
  background: var(--elev-2);
  color: var(--text-1);
}
</style>