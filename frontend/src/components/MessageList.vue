<script setup lang="ts">
import { useBrandingStore } from '../stores/branding'

const branding = useBrandingStore()
import { computed, nextTick, ref, watch } from 'vue'
import { useAppStore } from '../stores/app'
import { useUiStore } from '../stores/ui'
import type { DemoInfo, Message } from '../types'
import MessageItem from './MessageItem.vue'

const app = useAppStore()
const ui = useUiStore()
const scroller = ref<HTMLElement | null>(null)
const atBottom = ref(true)

const liveMessage = computed<Message>(() => ({
  id: -1,
  role: 'assistant',
  content: app.live.content,
  plan: app.live.plan,
  demo: app.live.demo,
  reasoning: app.live.reasoning,
  attachments: [],
  tool_calls: app.live.tools.map((t) => ({
    name: t.name,
    ok: t.status === 'running' ? undefined : t.status === 'ok',
    args: t.args,
  })),
  provider: app.live.provider,
  model: app.live.model,
  latency_ms: app.live.latency,
  created_at: new Date(app.live.startedAt || Date.now()).toISOString(),
}))

const showLive = computed(
  () => app.streaming && (app.live.content.length > 0 || app.live.plan.length > 0 || app.live.tools.length > 0),
)

const suggestions = [
  {
    icon: '🧩',
    title: '讲清一个概念',
    text: 'Python 装饰器的本质是什么？给我一个能直接运行的例子',
  },
  { icon: '🐞', title: '帮我排查报错', text: '我的 FastAPI 报了 422 错误，怎么定位是哪个字段校验失败？' },
  { icon: '🗂️', title: '检索我的知识库', text: '根据知识库讲讲 RAG 的完整流程和 Qdrant 的作用' },
  { icon: '🖥️', title: '带着我动手做', text: '我想用 Vue3 写一个待办清单，第一步该怎么做？请给我可运行的代码' },
]

function onScroll() {
  const el = scroller.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 90
}

async function scrollToBottom(force = false) {
  if (!force && !atBottom.value) return
  await nextTick()
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => [app.messages.length, app.live.content.length, app.live.tools.length, app.live.plan.length],
  () => scrollToBottom(),
)
watch(
  () => app.activeId,
  () => scrollToBottom(true),
)

function startDemo(demo: DemoInfo) {
  ui.openScreen(demo, app.activeId)
}
</script>

<template>
  <div class="chat-view">
    <div ref="scroller" class="messages scroll-y" @scroll="onScroll">
      <div class="inner">
      <!-- 空状态 -->
      <div v-if="!app.hasMessages && !app.streaming" class="welcome">
        <div class="hero-glow" />
        <div class="hero">
          <div class="hero-badge">LangGraph · RAG · 多模态 · 屏幕演示</div>
          <h1>你好，我是 <span class="grad">{{ branding.name }}</span></h1>
          <p>一个会先拆解任务、再调用工具、最后讲课的编程学习智能体。<br />问概念、跑代码、查你的知识库，或者让我直接演示操作给你看。</p>
        </div>
        <div class="cards">
          <button v-for="s in suggestions" :key="s.title" class="card" @click="app.draft = s.text">
            <span class="card-icon">{{ s.icon }}</span>
            <span class="card-title">{{ s.title }}</span>
            <span class="card-text">{{ s.text }}</span>
          </button>
        </div>
        <div class="hint-row">
          <span class="hint-item">⌘ Enter 发送</span>
          <span class="hint-item">支持上传图片提问</span>
          <span class="hint-item">回答完成后可启动屏幕演示</span>
        </div>
      </div>

      <!-- 消息列表 -->
      <template v-else>
        <MessageItem
          v-for="msg in app.messages"
          :key="msg.id"
          :message="msg"
          @start-demo="startDemo"
        />
        <MessageItem
          v-if="showLive"
          :message="liveMessage"
          live
          :running="app.streaming"
          :plan-step-status="app.live.planStepStatus"
          @start-demo="startDemo"
        />
        <div v-else-if="app.streaming" class="waiting">
          <span class="spinner" />
          <span>{{ app.live.nodes.length ? '正在执行…' : '正在连接模型…' }}</span>
        </div>
      </template>
      </div>
    </div>

    <button v-if="!atBottom" class="to-bottom" @click="scrollToBottom(true)">↓ 回到底部</button>
  </div>
</template>

<style scoped>
.chat-view {
  flex: 1;
  min-height: 0;
  position: relative;
  display: flex;
}
.messages {
  flex: 1;
  min-height: 0;
  padding: 0 8px;
}
.inner {
  max-width: 820px;
  margin: 0 auto;
  padding: 10px 16px 24px;
}

/* 空状态 */
.welcome {
  position: relative;
  padding-top: 6vh;
}
.hero-glow {
  position: absolute;
  top: -60px;
  left: 50%;
  transform: translateX(-50%);
  width: 520px;
  height: 220px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.22), transparent 68%);
  filter: blur(28px);
  pointer-events: none;
}
.hero {
  position: relative;
  text-align: center;
  margin-bottom: 34px;
}
.hero-badge {
  display: inline-block;
  padding: 5px 13px;
  border-radius: 999px;
  font-size: 11.5px;
  letter-spacing: 0.4px;
  color: var(--accent-ink-strong);
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(99, 102, 241, 0.26);
  margin-bottom: 18px;
}
.hero h1 {
  font-size: 33px;
  font-weight: 700;
  margin: 0 0 14px;
  letter-spacing: -0.4px;
}
.grad {
  background: linear-gradient(120deg, #818cf8, #22d3ee 70%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero p {
  margin: 0;
  font-size: 14px;
  line-height: 1.85;
  color: var(--text-2);
}

.cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 11px;
}
.card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
  padding: 14px 16px;
  border-radius: 14px;
  text-align: left;
  background: var(--elev-1);
  border: 1px solid var(--border);
  transition: all 0.2s ease;
}
.card:hover {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.4);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}
.card-icon {
  font-size: 18px;
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
}
.card-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-3);
}

.hint-row {
  display: flex;
  justify-content: center;
  gap: 18px;
  margin-top: 26px;
  font-size: 11.5px;
  color: var(--text-3);
}

.waiting {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 16px 4px;
  color: var(--text-3);
  font-size: 13px;
}

.to-bottom {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 6;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--border-strong);
  backdrop-filter: blur(10px);
  box-shadow: var(--shadow-pop);
}

@media (max-width: 900px) {
  .cards {
    grid-template-columns: 1fr;
  }
}
</style>