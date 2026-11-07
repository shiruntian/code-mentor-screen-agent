<script setup lang="ts">
import { useBrandingStore } from '../stores/branding'

const branding = useBrandingStore()
import { computed, ref } from 'vue'
import type { DemoInfo, Message, PlanStep } from '../types'
import { useUiStore } from '../stores/ui'
import MarkdownView from './MarkdownView.vue'
import { clockTime, shortModel } from '../utils/format'

const props = defineProps<{
  message: Message
  live?: boolean
  running?: boolean
  planStepStatus?: Record<number, 'running' | 'done' | 'failed'>
}>()
const emit = defineEmits<{ (e: 'start-demo', demo: DemoInfo): void }>()
const ui = useUiStore()

const showPlan = ref(true)
const showThought = ref(false)
const copied = ref(false)

const isUser = computed(() => props.message.role === 'user')
const plan = computed<PlanStep[]>(() => props.message.plan || [])
const demo = computed<DemoInfo | null>(() => (props.message.demo as DemoInfo) || null)
const attachments = computed(() => props.message.attachments || [])
const toolCalls = computed(() => props.message.tool_calls || [])

// 同名工具只显示一次（明细在右侧轨迹面板），失败状态优先保留
const uniqueToolCalls = computed(() => {
  const map = new Map<string, any>()
  for (const t of toolCalls.value) {
    const prev = map.get(t.name)
    if (!prev) map.set(t.name, t)
    else if (t.ok === false) map.set(t.name, t)
  }
  return [...map.values()]
})

function stepIcon(index: number): string {
  const status = props.planStepStatus?.[index]
  if (status === 'done') return '✓'
  if (status === 'running') return '…'
  if (status === 'failed') return '!'
  return String(index + 1)
}

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.message.content || '')
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    /* noop */
  }
}
</script>

<template>
  <div class="msg fade-up" :class="[isUser ? 'from-user' : 'from-ai']">
    <div class="avatar" :class="isUser ? 'user' : 'ai'">
      <span v-if="isUser">我</span>
      <img v-else-if="branding.logoUrl" :src="branding.logoUrl" alt="" class="avatar-img" />
        <span v-else>🐳</span>
    </div>

    <div class="body">
      <div class="meta">
        <span class="who">{{ isUser ? '学习者' : branding.name }}</span>
        <span v-if="!isUser && message.model" class="model-tag">{{ shortModel(message.model) }}</span>
        <span class="time">{{ clockTime(message.created_at) }}</span>
        <span v-if="message.latency_ms" class="latency">{{ (message.latency_ms / 1000).toFixed(1) }}s</span>
      </div>

      <!-- 用户消息 -->
      <template v-if="isUser">
        <div class="bubble user-bubble" :class="{ pending: message.pending }">
          <MarkdownView v-if="message.content" :content="message.content" />
          <div v-if="attachments.length" class="attachments">
            <button
              v-for="(att, i) in attachments"
              :key="i"
              type="button"
              class="thumb"
              :title="`${att.name}｜点击放大预览`"
              @click="ui.openLightbox(att.url, att.name)"
            >
              <img :src="att.url" :alt="att.name" />
              <span class="thumb-zoom">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                  <circle cx="11" cy="11" r="7" />
                  <path d="M20 20l-3.6-3.6M11 8v6M8 11h6" stroke-linecap="round" />
                </svg>
              </span>
            </button>
          </div>
        </div>
      </template>

      <!-- 助手消息 -->
      <template v-else>
        <div v-if="plan.length" class="plan-card">
          <button class="plan-head" @click="showPlan = !showPlan">
            <span class="plan-icon">◇</span>
            <span class="plan-title">任务规划</span>
            <span class="plan-count">{{ plan.length }} 步</span>
            <svg
              class="chev"
              :class="{ open: showPlan }"
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path d="M6 9l6 6 6-6" stroke-linecap="round" />
            </svg>
          </button>
          <ol v-show="showPlan" class="plan-steps">
            <li v-for="(step, i) in plan" :key="i" :class="planStepStatus?.[i] || ''">
              <span class="step-no">{{ stepIcon(i) }}</span>
              <span class="step-text">
                <span class="step-title">{{ step.title }}</span>
                <span v-if="step.tool" class="step-tool mono">{{ step.tool }}</span>
                <span v-if="step.detail" class="step-detail">{{ step.detail }}</span>
              </span>
            </li>
          </ol>
        </div>

        <div v-if="toolCalls.length" class="tool-row">
          <span v-for="(t, i) in uniqueToolCalls" :key="i" class="tool-chip" :class="{ fail: t.ok === false }">
            <span class="tool-dot" />
            {{ t.name }}
            <span v-if="t.ok === false" class="fail-text">失败</span>
          </span>
        </div>

        <div v-if="message.reasoning" class="thought">
          <button class="thought-toggle" @click="showThought = !showThought">
            {{ showThought ? '收起思考过程' : '查看思考过程' }}
          </button>
          <pre v-show="showThought" class="thought-body">{{ message.reasoning }}</pre>
        </div>

        <div class="bubble ai-bubble">
          <MarkdownView v-if="message.content" :content="message.content" />
          <span v-if="running" class="caret" />
          <div v-if="!message.content && running" class="thinking">
            <span class="spinner" /> 正在思考…
          </div>
        </div>

        <div v-if="demo" class="demo-card" :class="{ muted: !demo.available }">
          <div class="demo-emoji">🖥️</div>
          <div class="demo-main">
            <div class="demo-title">
              {{ demo.available ? '可以启动屏幕演示' : '本轮不提供屏幕演示' }}
            </div>
            <div class="demo-reason">{{ demo.reason }}</div>
            <ul v-if="demo.available && demo.steps.length" class="demo-steps">
              <li v-for="(s, i) in demo.steps.slice(0, 5)" :key="i">{{ s }}</li>
            </ul>
          </div>
          <button
            v-if="demo.available"
            class="btn btn-primary btn-sm demo-btn"
            @click="emit('start-demo', demo)"
          >
            ▶ 启动演示
          </button>
        </div>

        <div class="msg-actions">
          <button class="act" @click="copyContent">{{ copied ? '已复制' : '复制' }}</button>
          <span v-if="message.tokens" class="act-info">≈ {{ message.tokens }} tokens</span>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  gap: 12px;
  padding: 14px 0;
}
.avatar {
  width: 32px;
  height: 32px;
  min-width: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 600;
}
.avatar.user {
  background: rgba(148, 163, 184, 0.18);
  color: var(--text-1);
  border: 1px solid rgba(148, 163, 184, 0.25);
}
.avatar.ai {
  background: var(--grad-accent);
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.3);
  font-size: 15px;
  color: #fff;
}

.body {
  flex: 1;
  min-width: 0;
}
.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 11.5px;
  color: var(--text-3);
}
.who {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
}
.model-tag {
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.14);
  color: var(--accent-ink-strong);
  font-size: 10.5px;
}
.latency {
  color: rgba(52, 211, 153, 0.75);
}

.bubble {
  border-radius: 14px;
  padding: 12px 15px;
}
.user-bubble {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.16), rgba(34, 211, 238, 0.08));
  border: 1px solid rgba(99, 102, 241, 0.22);
}
.user-bubble.pending {
  opacity: 0.65;
}
.ai-bubble {
  background: var(--bubble-bg);
  border: 1px solid var(--border);
}

.attachments {
  display: flex;
  gap: 8px;
  margin-top: 9px;
  flex-wrap: wrap;
}
.thumb {
  position: relative;
  width: 92px;
  height: 92px;
  padding: 0;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border);
  display: block;
  cursor: zoom-in;
  transition: border-color 0.16s, transform 0.16s;
}
.thumb:hover {
  border-color: var(--accent-2);
  transform: translateY(-1px);
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb-zoom {
  position: absolute;
  left: 4px;
  bottom: 4px;
  width: 18px;
  height: 18px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  opacity: 0;
  transition: opacity 0.15s;
}
.thumb:hover .thumb-zoom {
  opacity: 1;
}

/* 计划 */
.plan-card {
  margin-bottom: 10px;
  border-radius: 12px;
  background: rgba(99, 102, 241, 0.07);
  border: 1px solid rgba(99, 102, 241, 0.2);
  overflow: hidden;
}
.plan-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  font-size: 12.5px;
  color: var(--accent-ink);
}
.plan-icon {
  color: var(--accent-2);
}
.plan-title {
  font-weight: 600;
}
.plan-count {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--elev-2);
  font-size: 10.5px;
  color: var(--text-2);
}
.chev {
  margin-left: auto;
  transition: transform 0.18s ease;
  color: var(--text-3);
}
.chev.open {
  transform: rotate(180deg);
}
.plan-steps {
  list-style: none;
  margin: 0;
  padding: 0 12px 10px;
}
.plan-steps li {
  display: flex;
  gap: 9px;
  padding: 5px 0;
  font-size: 12.5px;
  color: var(--text-2);
  transition: color 0.2s;
}
.plan-steps li.done {
  color: var(--text-1);
}
.step-no {
  width: 18px;
  height: 18px;
  min-width: 18px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 10.5px;
  background: var(--elev-2);
  color: var(--text-2);
}
.plan-steps li.done .step-no {
  background: rgba(52, 211, 153, 0.18);
  color: var(--success-ink);
}
.plan-steps li.running .step-no {
  background: rgba(34, 211, 238, 0.2);
  color: var(--accent-2);
}
.plan-steps li.failed .step-no {
  background: rgba(248, 113, 113, 0.2);
  color: var(--danger-ink);
}
.step-text {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
}
.step-title {
  color: inherit;
}
.step-tool {
  font-size: 10.5px;
  padding: 0 6px;
  border-radius: 4px;
  background: rgba(34, 211, 238, 0.12);
  color: var(--cyan-ink);
}
.step-detail {
  font-size: 11.5px;
  color: var(--text-3);
}

/* 工具 */
.tool-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 9px;
}
.tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  font-family: var(--mono);
  background: rgba(52, 211, 153, 0.08);
  border: 1px solid rgba(52, 211, 153, 0.22);
  color: var(--success-ink);
}
.tool-chip.fail {
  background: rgba(248, 113, 113, 0.1);
  border-color: rgba(248, 113, 113, 0.3);
  color: var(--danger-ink);
}
.tool-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
.fail-text {
  font-size: 10px;
  opacity: 0.8;
}

/* 思考 */
.thought {
  margin-bottom: 8px;
}
.thought-toggle {
  font-size: 11.5px;
  color: var(--text-3);
  padding: 2px 0;
}
.thought-toggle:hover {
  color: var(--accent-2);
}
.thought-body {
  margin: 6px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--inset-bg);
  border: 1px dashed var(--border);
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
  font-family: var(--font);
  max-height: 260px;
  overflow: auto;
}

.caret {
  display: inline-block;
  width: 7px;
  height: 15px;
  margin-left: 2px;
  background: var(--accent-2);
  border-radius: 1px;
  vertical-align: text-bottom;
  animation: blink 1s steps(2) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
}

/* 演示卡片 */
.demo-card {
  margin-top: 10px;
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 13px;
  background: linear-gradient(135deg, rgba(34, 211, 238, 0.1), rgba(99, 102, 241, 0.12));
  border: 1px solid rgba(34, 211, 238, 0.28);
}
.demo-card.muted {
  background: rgba(148, 163, 184, 0.05);
  border-color: var(--border);
  opacity: 0.75;
}
.demo-emoji {
  font-size: 20px;
  line-height: 1.2;
}
.demo-main {
  flex: 1;
  min-width: 0;
}
.demo-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
}
.demo-reason {
  font-size: 11.5px;
  color: var(--text-2);
  margin-top: 3px;
}
.demo-steps {
  margin: 7px 0 0;
  padding-left: 17px;
  font-size: 11.5px;
  color: var(--text-2);
  line-height: 1.7;
}
.demo-btn {
  align-self: center;
}

.msg-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  opacity: 0;
  transition: opacity 0.18s;
}
.msg:hover .msg-actions {
  opacity: 1;
}
.act {
  font-size: 11.5px;
  color: var(--text-3);
}
.act:hover {
  color: var(--accent-2);
}
.act-info {
  font-size: 11px;
  color: var(--text-3);
}

.avatar-img { width: 100%; height: 100%; object-fit: cover; border-radius: inherit; }
</style>