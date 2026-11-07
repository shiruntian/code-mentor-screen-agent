<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../stores/app'
import { useScreenStore } from '../stores/screen'
import { useUiStore } from '../stores/ui'
import { relativeTime } from '../utils/format'

const ui = useUiStore()
const screen = useScreenStore()
const app = useAppStore()

const pending = ref(false)
const interval = ref(app.settings?.runtime?.screen_interval_ms || 5000)
const dryRun = ref(false)
const intervalDirty = ref(false)
const captureMs = ref(Number(app.settings?.runtime?.screen_capture_ms || 200))

async function applyCapture() {
  const value = Math.max(150, Math.min(5000, Number(captureMs.value) || 500))
  captureMs.value = value
  try {
    const res = await api.put<any>('/api/settings', {
      ...(app.settings?.runtime || {}),
      screen_capture_ms: value,
    })
    app.settings = { ...(app.settings || {}), runtime: res.runtime }
    app.toast('success', `画面采样间隔已设为 ${(value / 1000).toFixed(2)}s`)
  } catch (e) {
    app.report(e)
  }
}
const confirmReal = ref(false)
const imeGuard = ref(app.settings?.runtime?.screen_ime_guard ?? true)

/** 输入法保护开关：演示时把前台窗口输入法临时切英文，结束自动还原 */
async function toggleImeGuard() {
  try {
    const res = await api.put<any>('/api/settings', { screen_ime_guard: imeGuard.value })
    app.settings = { ...(app.settings || {}), runtime: res.runtime }
    app.toast(
      imeGuard.value ? 'success' : 'info',
      imeGuard.value ? '演示时会自动切英文输入法' : '已关闭输入法自动切换',
    )
  } catch (e) {
    imeGuard.value = !imeGuard.value
    app.report(e)
  }
}

const status = computed(() => screen.session?.status || 'idle')
const statusLabel = computed(() => {
  const map: Record<string, string> = {
    idle: '待启动',
    running: '演示中',
    paused: '已暂停',
    completed: '已完成',
    failed: '已失败',
  }
  return map[status.value] || status.value
})

const canStart = computed(() => ['idle', 'completed', 'failed'].includes(status.value))
const timeline = computed(() => [...screen.logs].reverse())

const readyDemo = computed(() => ui.screenDemo)

async function launch() {
  if (!readyDemo.value && !screen.session) {
    app.toast('warning', '请先让智能体给出一段可执行的回答')
    return
  }
  pending.value = true
  try {
    if (!dryRun.value && !confirmReal.value) {
      confirmReal.value = true
      pending.value = false
      return
    }
    if (!screen.session || ['completed', 'failed'].includes(status.value)) {
      await screen.create(readyDemo.value, ui.screenConversationId, {
        interval: interval.value,
        dryRun: dryRun.value,
      })
      confirmReal.value = false
    }
    await screen.start()
  } catch (e) {
    app.report(e)
  } finally {
    pending.value = false
  }
}

const askText = ref('')

async function sendAnswer(text: string) {
  const value = (text || '').trim()
  if (!value) return
  try {
    await api.post(`/api/screen/sessions/${screen.session.id}/answer`, { answer: value })
    askText.value = ''
    await screen.refresh?.()
  } catch (e) {
    app.report(e)
  }
}

async function pause() {
  await screen.pause()
}

async function resume() {
  await screen.resume()
}

async function stop() {
  await screen.stop()
}

async function restart() {
  await screen.stop()
  screen.reset()
  confirmReal.value = false
}

function onIntervalInput(e: Event) {
  interval.value = Number((e.target as HTMLInputElement).value)
  intervalDirty.value = true
}

async function applyInterval() {
  if (!screen.session) return
  await screen.setInterval(interval.value)
  intervalDirty.value = false
}

function actionName(log: any): string {
  const a = log?.action
  if (!a) return log?.status || '—'
  return String(a.type || a.kind || 'action')
}

function actionText(log: any): string {
  const a = log?.action || {}
  if (a.text) return `「${String(a.text).slice(0, 40)}」`
  if (a.path) return String(a.path)
  if (a.keys) return String(a.keys)
  if (a.key) return String(a.key)
  if (a.x !== undefined && a.y !== undefined) return `(${Math.round(Number(a.x))}, ${Math.round(Number(a.y))})`
  if (a.line) return `第 ${a.line} 行`
  return ''
}

function close() {
  ui.closeScreen()
}

/** 把动作 JSON 转成时间线里的一行可读文本 */
function actionLabel(action: Record<string, any> | null | undefined): string {
  if (!action) return ''
  const kind = String(action.type || '')
  if (kind === 'hotkey') return `组合键 · ${(action.keys || []).join('+')}`
  if (kind === 'key') return `按键 · ${action.key}`
  if (kind === 'type') return `输入 · “${String(action.text || '').slice(0, 30)}”`
  if (kind === 'sequence') return `批量 · ${(action.actions || []).length} 个动作`
  if (kind === 'scroll') return `滚轮 · ${action.amount}`
  if (kind === 'wait') return `等待 · ${action.seconds}s`
  if (kind === 'drag') return `拖动 · (${Math.round(action.x)},${Math.round(action.y)}) → (${Math.round(action.to_x)},${Math.round(action.to_y)})`
  if (action.x !== undefined && action.y !== undefined) {
    return `${kind} · (${Math.round(action.x)}, ${Math.round(action.y)})`
  }
  return kind
}

watch(
  () => screen.session?.interval_ms,
  (v) => {
    if (v && !intervalDirty.value) interval.value = v
  },
)

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

const lessons = ref<any[]>([])
const lessonsOpen = ref(false)

/** 经验库：屏幕演示学到的「哪些做法有效 / 无效」，也包含用户在对话里教过的快捷键 */
async function loadLessons() {
  try {
    const res = await api.get<any>('/api/screen/lessons?limit=12')
    lessons.value = res.items || []
  } catch {
    lessons.value = []
  }
}

async function clearLessons() {
  try {
    await api.del('/api/screen/lessons')
    lessons.value = []
    app.toast('info', '经验库已清空')
  } catch (e) {
    app.report(e)
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  if (screen.session) screen.connect(screen.session.id)
  loadLessons()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div class="overlay" @click.self="close">
    <div class="console">
      <header class="head">
        <div class="head-left">
          <span class="emoji">🖥️</span>
          <div>
            <div class="title">屏幕演示控制台</div>
            <div class="sub">
              <span class="badge" :class="`b-${status}`">{{ statusLabel }}</span>
              <span class="tiny muted">每 {{ (interval / 1000).toFixed(1) }}s 问一次模型（画面采样 {{ (captureMs / 1000).toFixed(1) }}s）</span>
            </div>
          </div>
        </div>
        <button class="icon-btn" @click="close">✕</button>
      </header>

      <div v-if="readyDemo" class="goal-bar">
        <span class="goal-label">演示目标</span>
        <span class="goal-text">{{ readyDemo.goal }}</span>
      </div>

      <div v-if="screen.session?.status === 'failed' && screen.session?.last_error" class="fail-bar">
        <b>演示失败：</b>{{ screen.session.last_error }}
        <span class="fail-hint">修好原因后点「重新开始」即可</span>
      </div>

      <div v-if="screen.session?.pending_question" class="ask-bar">
        <div class="ask-q">🤔 {{ screen.session.pending_question.question }}</div>
        <div class="ask-row">
          <button
            v-for="opt in screen.session.pending_question.options || []"
            :key="opt"
            class="ask-opt"
            @click="sendAnswer(opt)"
          >
            {{ opt }}
          </button>
          <input
            v-model="askText"
            class="input ask-input"
            placeholder="或直接输入内容后回车"
            @keydown.enter="sendAnswer(askText)"
          />
          <button class="btn btn-sm btn-primary" :disabled="!askText.trim()" @click="sendAnswer(askText)">
            提交
          </button>
        </div>
      </div>

      <div class="body">
        <!-- 左侧：实时画面 -->
        <div class="viewer">
          <div v-if="screen.latestShot" class="shot">
            <img :src="screen.latestShot" alt="屏幕画面" />
            <div class="shot-overlay">
              <span class="live-dot" :class="{ on: status === 'running' }" />
              <span>{{ status === 'running' ? '实时识别中' : statusLabel }}</span>
              <span class="grow" />
              <span class="step-badge">
                第 {{ screen.session?.current_step || 0 }} / {{ screen.session?.max_steps || 0 }} 步
              </span>
            </div>
          </div>
          <div v-else class="placeholder">
            <div class="ph-emoji">📷</div>
            <p>启动后这里会显示实时屏幕画面</p>
            <p class="tiny">AI 每秒截屏 → 视觉模型识别 → 决策下一步鼠标键盘动作</p>
          </div>

          <div class="controls">
            <button
              v-if="canStart"
              class="btn btn-primary"
              :disabled="pending"
              @click="launch"
            >
              <span v-if="pending" class="spinner" />
              ▶ {{ confirmReal ? '确认开始（会真实控制鼠标）' : '启动演示' }}
            </button>
            <template v-else>
              <button v-if="status === 'running'" class="btn" @click="pause">⏸ 暂停</button>
              <button v-else-if="status === 'paused'" class="btn btn-primary" @click="resume">▶ 继续（从第 {{ screen.session?.current_step }} 步）</button>
              <button class="btn btn-danger" @click="stop">■ 结束</button>
            </template>
            <button v-if="screen.session" class="btn btn-sm" @click="restart">重新开始</button>
            <span class="grow" />
            <label class="dry-toggle" title="演练模式只识别不操作">
              <input v-model="dryRun" type="checkbox" :disabled="!canStart" />
              <span>演练模式</span>
            </label>
          </div>

          <div class="interval-row">
            <span class="ir-label">决策间隔</span>
            <input
              type="range"
              min="800"
              max="10000"
              step="200"
              :value="interval"
              @input="onIntervalInput"
            />
            <span class="ir-val mono">{{ (interval / 1000).toFixed(1) }}s</span>
        </div>

        <div class="interval-row capture-row">
          <span class="ir-label">采样间隔</span>
          <input
            v-model.number="captureMs"
            class="input cap-input"
            type="number"
            min="100"
            max="5000"
            step="50"
            @change="applyCapture"
          />
          <span class="tiny muted">毫秒 · 抓帧节奏，只影响「多久看一眼」</span>
          <span class="ir-val mono">{{ (captureMs / 1000).toFixed(1) }}s</span>
            <button v-if="intervalDirty" class="btn btn-sm" @click="applyInterval">应用</button>
          </div>

          <label class="guard-row">
            <input v-model="imeGuard" type="checkbox" @change="toggleImeGuard" />
            <span class="guard-text">
              演示时自动切英文输入法
              <span class="tiny muted">
                · 防止全角/丢字，结束自动还原
              </span>
            </span>
          </label>

          <p class="safety">
            ⚠️ 会真实操作鼠标键盘；<b>鼠标移到左上角</b>或按 <b>Ctrl+Alt+Shift+F12</b> 立即停止。
          </p>



        </div>

        <!-- 右侧：操作时间线 -->
        <aside class="timeline">
          <div class="tl-head">
            <span class="tl-title">操作时间线</span>
            <span class="grow" />
            <span class="tiny muted">{{ screen.logs.length }} 步</span>
          </div>

          <div v-if="!screen.logs.length" class="tl-empty">
            还没有操作记录。启动演示后，每一轮的思考与动作会实时出现在这里。
          </div>

          <div v-else ref="tlList" class="tl-list">
            <div v-for="(log, i) in screen.logs" :key="i" class="tl-item" :class="{ fail: log.ok === false }">
              <div class="tl-n">{{ log.n ?? i + 1 }}</div>
              <div class="tl-body">
                <p class="tl-thought">{{ log.thought || '（无思考内容）' }}</p>
                <div class="tl-act">
                  <span class="tl-kind mono">{{ actionName(log) }}</span>
                  <span class="tl-detail mono">{{ log.detail || actionText(log) }}</span>
                </div>
              </div>
              <img v-if="log.screenshot" class="tl-thumb" :src="log.screenshot" alt="" />
            </div>
          </div>

          <div v-if="screen.session?.last_error" class="tl-err">{{ screen.session.last_error }}</div>
        </aside>
      </div>

      <footer class="foot">
        <span class="tiny muted">会话 <span class="mono">{{ screen.session?.id?.slice(0, 10) || '—' }}</span></span>
        <span class="grow" />
        <span class="tiny muted">{{ screen.session?.created_at ? relativeTime(screen.session.created_at) : '' }}</span>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--overlay-bg);
  backdrop-filter: blur(6px);
}
.console {
  width: min(1120px, 96vw);
  height: min(760px, 92vh);
  display: flex;
  flex-direction: column;
  border-radius: 18px;
  background: var(--console-bg);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 16px;
  border-bottom: 1px solid var(--border);
}
.head-left {
  display: flex;
  align-items: center;
  gap: 11px;
}
.emoji {
  font-size: 20px;
}
.title {
  font-size: 14px;
  font-weight: 650;
}
.sub {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
}
.badge {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10.5px;
  background: rgba(148, 163, 184, 0.16);
  color: var(--text-2);
}
.b-running {
  background: rgba(52, 211, 153, 0.16);
  color: var(--success-ink);
}
.b-paused {
  background: rgba(251, 191, 36, 0.16);
  color: var(--warn-ink);
}
.b-failed {
  background: rgba(248, 113, 113, 0.16);
  color: var(--danger-ink);
}

.goal-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: rgba(99, 102, 241, 0.07);
  border-bottom: 1px solid var(--border);
}
.goal-label {
  font-size: 10.5px;
  color: var(--text-3);
  letter-spacing: 0.5px;
}
.goal-text {
  font-size: 12px;
  color: var(--accent-ink);
}

.body {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 380px;
  min-height: 0;
}

.viewer {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
}
.shot {
  position: relative;
  flex: none;
  min-height: 0;
  aspect-ratio: 16 / 10;
  max-height: 62vh;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border-strong);
  background: #05080f;
}
.shot img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.shot-overlay {
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 11px;
  border-radius: 9px;
  background: rgba(5, 10, 20, 0.72);
  backdrop-filter: blur(8px);
  font-size: 11px;
  color: var(--text-2);
}
.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
}
.live-dot.on {
  background: var(--danger);
  animation: dotPulse 1.1s infinite;
}
.step-badge {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--accent-2);
}

.placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 12px;
  border: 1px dashed var(--border-strong);
  color: var(--text-3);
  background: var(--elev-1);
}
.ph-emoji {
  font-size: 32px;
  opacity: 0.55;
}
.placeholder p {
  margin: 0;
  font-size: 12.5px;
}

.controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dry-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-2);
  cursor: pointer;
}
.dry-toggle input {
  accent-color: var(--accent);
}

.interval-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ir-label {
  font-size: 11.5px;
  color: var(--text-3);
}
.interval-row input[type='range'] {
  flex: 1;
  accent-color: var(--accent);
}
.ir-val {
  font-size: 11.5px;
  color: var(--accent-2);
  min-width: 38px;
}

.safety {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.7;
  color: var(--text-3);
}
.safety b {
  color: var(--warning);
}
.cap-hint {
  margin: 0;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 10.5px;
  line-height: 1.7;
  color: var(--text-2);
  background: rgba(99, 102, 241, 0.07);
  border: 1px solid rgba(99, 102, 241, 0.16);
}
.guard-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 11.5px;
  color: var(--text-2);
  background: rgba(52, 211, 153, 0.06);
  border: 1px solid rgba(52, 211, 153, 0.18);
  cursor: pointer;
}
.guard-row input {
  margin-top: 2px;
  accent-color: var(--success);
}
.guard-text {
  line-height: 1.65;
}
.guard-text .tiny {
  display: block;
  margin-top: 1px;
}

.lessons {
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-2);
  font-size: 11.5px;
  color: var(--text-2);
}
.lessons summary {
  padding: 8px 10px;
  cursor: pointer;
  font-weight: 600;
  color: var(--text-1);
  list-style: none;
}
.lessons summary::-webkit-details-marker {
  display: none;
}
.lessons summary .tiny {
  display: block;
  font-weight: 400;
  margin-top: 2px;
}
.lessons ul {
  margin: 0;
  padding: 0 10px 8px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 5px;
  max-height: 150px;
  overflow: auto;
}
.lessons li {
  display: flex;
  align-items: center;
  gap: 6px;
  line-height: 1.5;
}
.lessons .method {
  flex: 1;
  color: var(--text-1);
  font-family: var(--mono, monospace);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lessons .badge {
  flex: none;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 10px;
  line-height: 1.5;
}
.lessons .badge.ok {
  color: var(--success);
  background: rgba(52, 211, 153, 0.14);
}
.lessons .badge.bad {
  color: var(--danger);
  background: rgba(248, 113, 113, 0.14);
}
.lessons .empty {
  padding: 0 10px 8px;
  margin: 0;
}
.lessons button {
  margin: 0 10px 8px;
}

.timeline-wrap {
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.tl-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 8px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-2);
}
.tl {
  flex: 1;
  padding: 0 10px 10px;
}
.tl-empty {
  padding: 30px 12px;
  text-align: center;
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-3);
}
.tl-row {
  display: flex;
  gap: 9px;
  padding: 9px 8px;
  border-radius: 10px;
  margin-bottom: 6px;
  background: var(--elev-1);
  border: 1px solid var(--border);
  border-left: 2px solid rgba(52, 211, 153, 0.5);
}
.tl-row.failed {
  border-left-color: var(--danger);
  background: rgba(248, 113, 113, 0.05);
}
.tl-idx {
  width: 20px;
  height: 20px;
  min-width: 20px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 10px;
  font-family: var(--mono);
  background: rgba(99, 102, 241, 0.16);
  color: var(--accent-ink-strong);
}
.tl-main {
  flex: 1;
  min-width: 0;
}
.tl-thought {
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-1);
}
.tl-detail {
  margin-top: 3px;
  font-size: 10.5px;
  color: var(--text-3);
  word-break: break-all;
}
.tl-action {
  margin-top: 3px;
  font-size: 10px;
  color: var(--cyan-ink);
}
.tl-thumb {
  width: 42px;
  height: 30px;
  object-fit: cover;
  border-radius: 5px;
  border: 1px solid var(--border);
}
.tl-err {
  margin: 0 14px 12px;
  padding: 8px 11px;
  border-radius: 9px;
  font-size: 11px;
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.24);
  color: var(--danger-ink);
}

.foot {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  border-top: 1px solid var(--border);
}

@media (max-width: 980px) {
  .body {
    grid-template-columns: 1fr;
  }
  .timeline-wrap {
    border-left: none;
    border-top: 1px solid var(--border);
    max-height: 240px;
  }
}

.fail-bar {
  margin: 10px 22px 0;
  padding: 9px 14px;
  border-radius: 10px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--danger-ink, #ff5f6d);
  background: rgba(255, 95, 109, 0.1);
  border: 1px solid rgba(255, 95, 109, 0.28);
}
.fail-hint {
  margin-left: 8px;
  color: var(--text-3);
}


.ask-bar {
  margin: 10px 22px 0;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.3);
}
.ask-q {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}
.ask-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.ask-opt {
  padding: 5px 12px;
  border-radius: 8px;
  font-size: 12px;
  background: var(--surface-2, rgba(255, 255, 255, 0.1));
  border: 1px solid var(--border);
  color: var(--text-1);
}
.ask-opt:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.ask-input {
  flex: 1;
  min-width: 180px;
}


.capture-row {
  margin-top: 6px;
}
.cap-input {
  width: 88px;
  padding: 3px 8px;
  font-size: 12px;
}


/* 能力提示可能与下一行重叠：改成自适应高度 + 明确行高 */
.cap-hint {
  height: auto;
  max-height: none;
  line-height: 1.75;
  margin: 8px 0 10px;
  padding: 8px 12px;
  overflow: visible;
  white-space: normal;
  word-break: break-word;
}
.guard-row {
  margin-top: 6px;
  align-items: flex-start;
}
.guard-text {
  line-height: 1.7;
}


.timeline {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border-left: 1px solid var(--border);
  background: var(--panel-bg, transparent);
}
.tl-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--border);
}
.tl-title { font-size: 13px; font-weight: 600; }
.tl-empty {
  padding: 16px 14px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-3);
}
.tl-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tl-item {
  display: grid;
  grid-template-columns: 26px 1fr auto;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 10px;
  background: var(--inset-bg);
  border: 1px solid var(--border);
}
.tl-item.fail { border-color: rgba(244, 63, 94, 0.45); }
.tl-n {
  width: 22px; height: 22px; border-radius: 7px;
  display: grid; place-items: center;
  font-size: 11px; font-weight: 600;
  background: var(--grad-accent); color: #fff;
}
.tl-body { min-width: 0; }
.tl-thought {
  margin: 0 0 5px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tl-act { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tl-kind {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 6px;
  background: rgba(99, 102, 241, 0.14);
  color: var(--accent);
}
.tl-detail {
  font-size: 10.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 150px;
}
.tl-thumb {
  width: 54px; height: 34px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--border);
}


.safety {
  font-size: 11.5px;
  line-height: 1.6;
  margin: 2px 0 0;
  color: var(--text-3);
}
.guard-row { margin: 2px 0; }
.body { min-height: 0; }

</style>