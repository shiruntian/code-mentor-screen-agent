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

/** 自定义确认框（比 window.confirm 好看，也能截进文档） */
interface ConfirmState {
  icon: string
  title: string
  lines: string[]
  danger?: boolean
  okText: string
  run: () => Promise<void> | void
}
const confirmState = ref<ConfirmState | null>(null)
const confirmBusy = ref(false)

function ask(state: ConfirmState) {
  confirmState.value = state
}

function closeConfirm() {
  if (confirmBusy.value) return
  confirmState.value = null
}

async function runConfirm() {
  const state = confirmState.value
  if (!state || confirmBusy.value) return
  confirmBusy.value = true
  try {
    await state.run()
    confirmState.value = null
  } finally {
    confirmBusy.value = false
  }
}

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
  const conv = app.conversations.find((c) => c.id === id)
  const shots = conv?.screenshot?.bytes || 0
  const lines = ['该会话的所有消息将永久删除。']
  if (shots > 0) lines.push(`它的屏幕演示截图（${conv?.screenshot?.human}）也会一并删除。`)
  ask({
    icon: '🗑',
    title: `删除会话「${title}」？`,
    lines,
    danger: true,
    okText: '删除会话',
    run: () => app.deleteConversation(id),
  })
}

/** 只清截图，演示的文字记录和聊天消息都保留 */
function clearShots(conv: {
  id: string
  title: string
  screenshot?: { bytes: number; human: string; images: number; sessions: number }
}) {
  const shots = conv.screenshot
  if (!shots || shots.bytes <= 0) {
    app.toast('info', '这个会话没有截图可清理')
    return
  }
  ask({
    icon: '📷',
    title: `清理「${conv.title}」的屏幕演示截图？`,
    lines: [
      `释放 ${shots.human}（${shots.images} 张图，来自 ${shots.sessions} 次演示）。`,
      '聊天记录和演示的文字步骤都会保留，只是图片不能再查看。',
    ],
    okText: `清理 ${shots.human}`,
    run: () => app.clearConversationScreenshots(conv.id),
  })
}

/** 清掉所有没挂在任何对话上的演示截图（直接点「演示」开出来的） */
function clearOrphans() {
  const shots = app.screenshotOrphans
  if (!shots || shots.bytes <= 0) return
  ask({
    icon: '🧹',
    title: '清理未关联任何对话的演示截图？',
    lines: [
      `释放 ${shots.human}（${shots.images} 张图，${shots.sessions} 次演示）。`,
      '这些演示不是从对话里发起的，删掉不影响任何聊天记录。',
    ],
    okText: `清理 ${shots.human}`,
    run: () => app.clearOrphanScreenshots(),
  })
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
      <span class="head-right">
        <span v-if="app.screenshotTotal && app.screenshotTotal.bytes > 0" class="shots-total" :title="`截图总占用 ${app.screenshotTotal.human}（${app.screenshotTotal.images} 张）`">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="5" width="18" height="14" rx="2" />
            <circle cx="12" cy="12" r="3" />
          </svg>
          {{ app.screenshotTotal.human }}
        </span>
        <button
          v-if="app.screenshotOrphans && app.screenshotOrphans.bytes > 0"
          class="mini orphan-clean"
          :disabled="app.cleaningShots"
          :title="`有 ${app.screenshotOrphans.human} 截图不属于任何对话（直接点「演示」开出来的），点击清理`"
          @click.stop="clearOrphans"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
            <path d="M3 5.5h18v13H3z" stroke-linejoin="round" /><circle cx="8.2" cy="10.3" r="1.5" /><path d="M3.6 17.2l4.9-4.6 3.6 3.3" stroke-linecap="round" stroke-linejoin="round" /><path d="M4 3.6l16 16.8" stroke-linecap="round" />
          </svg>
        </button>
        <span class="count">{{ app.conversations.length }}</span>
      </span>
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
              <template v-if="conv.screenshot && conv.screenshot.bytes > 0">
                <span class="sep">·</span>
                <span
                  class="shot-badge"
                  :title="`屏幕演示截图 ${conv.screenshot.human}（${conv.screenshot.images} 张 / ${conv.screenshot.sessions} 次演示）`"
                >📷 {{ conv.screenshot.human }}</span>
              </template>
              <span class="sep">·</span>
              <span>{{ relativeTime(conv.updated_at) }}</span>
            </div>
          </template>
        </div>
        <div class="conv-actions" @click.stop>
          <button
            v-if="conv.screenshot && conv.screenshot.bytes > 0"
            class="mini shots"
            :disabled="app.cleaningShots"
            :title="`清理截图，释放 ${conv.screenshot.human}（聊天记录保留）`"
            @click="clearShots(conv)"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
              <path d="M3 5.5h18v13H3z" stroke-linejoin="round" /><circle cx="8.2" cy="10.3" r="1.5" /><path d="M3.6 17.2l4.9-4.6 3.6 3.3" stroke-linecap="round" stroke-linejoin="round" /><path d="M4 3.6l16 16.8" stroke-linecap="round" />
            </svg>
          </button>
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

    <!-- 确认弹窗（清理截图 / 删除会话）。
         必须传送到 body：侧边栏有 backdrop-filter，会变成 position:fixed 的包含块，
         留在里面会让遮罩只盖住侧边栏、弹窗也歪到左边。 -->
    <Teleport to="body">
      <div v-if="confirmState" class="confirm-mask" @click.self="closeConfirm">
        <div class="confirm-dialog" role="dialog" aria-modal="true">
          <div class="confirm-head">
            <span class="confirm-icon">{{ confirmState.icon }}</span>
            <p class="confirm-title">{{ confirmState.title }}</p>
          </div>
          <ul class="confirm-lines">
            <li v-for="(line, i) in confirmState.lines" :key="i">{{ line }}</li>
          </ul>
          <div class="confirm-actions">
            <button class="btn tiny" :disabled="confirmBusy" @click="closeConfirm">取消</button>
            <button
              class="btn tiny"
              :class="confirmState.danger ? 'btn-danger' : 'btn-primary'"
              :disabled="confirmBusy"
              @click="runConfirm"
            >
              {{ confirmBusy ? '处理中…' : confirmState.okText }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
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
.mini.shots:hover {
  color: #f0b429;
  background: rgba(240, 180, 41, 0.14);
}
.mini:disabled {
  opacity: 0.4;
  cursor: default;
}

/* 会话条目里的截图占用小徽标 */
.shot-badge {
  color: #f0b429;
  opacity: 0.85;
  white-space: nowrap;
}

/* 顶部：总占用 + 清理未关联 */
.head-right {
  display: flex;
  align-items: center;
  gap: 6px;
}
.shots-total {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10.5px;
  color: #f0b429;
  opacity: 0.8;
  font-variant-numeric: tabular-nums;
}
.orphan-clean {
  color: #f0b429;
  opacity: 0.75;
}
.orphan-clean:hover {
  opacity: 1;
  background: rgba(240, 180, 41, 0.16);
  color: #f0b429;
}

/* 确认弹窗 */
.confirm-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(3, 7, 18, 0.62);
  backdrop-filter: blur(3px);
  animation: confirmIn 0.14s ease-out;
}
@keyframes confirmIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
.confirm-dialog {
  width: min(440px, 92vw);
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px;
  border-radius: 16px;
  background: var(--dialog-bg);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow-lg);
}
.confirm-head {
  display: flex;
  gap: 10px;
  align-items: center;
}
.confirm-icon {
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 13px;
  background: rgba(245, 158, 11, 0.16);
}
.confirm-title {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.4;
}
.confirm-lines {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.75;
  color: var(--text-2);
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
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
