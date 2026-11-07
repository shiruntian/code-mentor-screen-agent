<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../../stores/app'
import { useUiStore } from '../../stores/ui'
import type { DemoInfo } from '../../types'

const app = useAppStore()
const ui = useUiStore()
const showReasoning = ref(false)

const running = computed(() => app.streaming)
const lastAssistant = computed(() => [...app.messages].reverse().find((m) => m.role === 'assistant') || null)

const plan = computed(() =>
  running.value && app.live.plan.length ? app.live.plan : lastAssistant.value?.plan || [],
)
const planStatus = computed(() => (running.value ? app.live.planStepStatus : {}))

const tools = computed(() => {
  if (running.value && app.live.tools.length) return app.live.tools
  const calls = lastAssistant.value?.tool_calls || []
  return calls.map((c, i) => ({
    callId: `hist-${i}`,
    name: c.name,
    label: c.name,
    args: c.args || {},
    status: (c.ok === false ? 'error' : 'ok') as 'running' | 'ok' | 'error',
    preview: undefined as string | undefined,
    error: c.error || null,
    elapsed: undefined as number | undefined,
  }))
})

const demo = computed<DemoInfo | null>(() =>
  running.value ? app.live.demo : (lastAssistant.value?.demo as DemoInfo) || app.live.demo || null,
)

const nodes = computed(() => app.live.nodes)
const noticeList = computed(() => app.live.notices)

const reasoning = computed(() => (running.value ? app.live.reasoning : lastAssistant.value?.reasoning || ''))

const metrics = computed(() => {
  if (running.value) {
    return {
      model: app.live.model || app.currentModel,
      latency: app.live.latency ? (app.live.latency / 1000).toFixed(1) : '进行中',
      tokens: '—',
    }
  }
  const m = lastAssistant.value
  return {
    model: m?.model || app.currentModel,
    latency: m?.latency_ms ? (m.latency_ms / 1000).toFixed(1) : '—',
    tokens: m?.tokens ? String(m.tokens) : '—',
  }
})

const toolIcon = (name: string) => {
  const map: Record<string, string> = {
    knowledge_search: '🔍',
    python_sandbox: '⌨️',
    remember_fact: '📌',
    recall_memory: '🧠',
    propose_screen_demo: '🖥️',
  }
  return map[name] || '🔧'
}
</script>

<template>
  <div class="pane scroll-y">
    <!-- 运行状态 -->
    <div class="status-card" :class="{ active: running }">
      <div class="row">
        <span class="pulse" :class="{ on: running }" />
        <span class="status-text">{{ running ? '智能体运行中' : '空闲' }}</span>
        <span class="grow" />
        <span class="tiny muted mono">{{ metrics.model }}</span>
      </div>
      <div class="metric-row">
        <div class="metric">
          <span class="metric-val">{{ metrics.latency }}<i v-if="metrics.latency !== '—'">s</i></span>
          <span class="metric-key">耗时</span>
        </div>
        <div class="metric">
          <span class="metric-val">{{ metrics.tokens }}</span>
          <span class="metric-key">tokens</span>
        </div>
        <div class="metric">
          <span class="metric-val">{{ tools.length }}</span>
          <span class="metric-key">工具调用</span>
        </div>
        <div class="metric">
          <span class="metric-val">{{ plan.length }}</span>
          <span class="metric-key">计划步骤</span>
        </div>
      </div>
    </div>

    <!-- 节点时间线 -->
    <section v-if="nodes.length" class="section">
      <h3 class="sec-title">执行链路 <span class="dim">LangGraph</span></h3>
      <div class="timeline">
        <div v-for="(n, i) in nodes" :key="i" class="tl-item" :class="n.status">
          <span class="tl-dot" />
          <span class="tl-label">{{ n.label }}</span>
          <span class="tl-state">{{ n.status === 'running' ? '进行中' : '完成' }}</span>
        </div>
      </div>
    </section>

    <!-- 计划 -->
    <section class="section">
      <h3 class="sec-title">任务规划</h3>
      <div v-if="!plan.length" class="empty-block">本轮还没有生成计划</div>
      <ol v-else class="plan-list">
        <li v-for="(s, i) in plan" :key="i" :class="planStatus[i] || ''">
          <span class="num">{{ i + 1 }}</span>
          <div class="plan-body">
            <div class="plan-title">{{ s.title }}</div>
            <div v-if="s.detail" class="plan-detail">{{ s.detail }}</div>
            <span v-if="s.tool" class="plan-tool mono">{{ s.tool }}</span>
          </div>
        </li>
      </ol>
    </section>

    <!-- 工具 -->
    <section class="section">
      <h3 class="sec-title">工具调用</h3>
      <div v-if="!tools.length" class="empty-block">本轮没有调用工具</div>
      <div v-else class="tool-list">
        <div v-for="t in tools" :key="t.callId" class="tool-item" :class="t.status">
          <span class="tool-ico">{{ toolIcon(t.name) }}</span>
          <div class="tool-body">
            <div class="tool-head">
              <span class="tool-name mono">{{ t.name }}</span>
              <span class="tool-state">
                <span v-if="t.status === 'running'" class="spinner" />
                <template v-else-if="t.status === 'ok'">✓</template>
                <template v-else>✕</template>
              </span>
              <span v-if="t.elapsed" class="tool-time">{{ t.elapsed }}ms</span>
            </div>
            <div v-if="t.error" class="tool-err">{{ t.error }}</div>
            <div v-else-if="t.preview" class="tool-preview">{{ String(t.preview).slice(0, 220) }}</div>
            <div v-else class="tool-args mono">{{ JSON.stringify(t.args).slice(0, 160) }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 通知 -->
    <section v-if="noticeList.length" class="section">
      <h3 class="sec-title">运行提示</h3>
      <div v-for="(n, i) in noticeList" :key="i" class="notice" :class="n.level">
        {{ n.message }}
      </div>
    </section>

    <!-- 思考过程 -->
    <section v-if="reasoning" class="section">
      <button class="sec-title toggle" @click="showReasoning = !showReasoning">
        思考过程 <span class="dim">{{ showReasoning ? '收起' : '展开' }}</span>
      </button>
      <pre v-show="showReasoning" class="reasoning">{{ reasoning }}</pre>
    </section>

    <!-- 演示 -->
    <section class="section">
      <h3 class="sec-title">屏幕演示可用性</h3>
      <div v-if="!demo" class="empty-block">回答完成后会在这里给出判定</div>
      <div v-else class="demo-judge" :class="{ ok: demo.available }">
        <div class="judge-head">
          <span class="judge-badge">{{ demo.available ? '可演示' : '不演示' }}</span>
          <span class="judge-score">相关度 {{ demo.score }} · {{ demo.source }}</span>
        </div>
        <p class="judge-reason">{{ demo.reason }}</p>
        <ul v-if="demo.available" class="judge-steps">
          <li v-for="(s, i) in demo.steps" :key="i">{{ s }}</li>
        </ul>
        <button
          v-if="demo.available"
          class="btn btn-primary btn-sm"
          style="margin-top: 8px"
          @click="ui.openScreen(demo, app.activeId)"
        >
          ▶ 启动屏幕演示
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pane {
  padding: 14px;
  height: 100%;
}
.section {
  margin-top: 18px;
}
.sec-title {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0 0 9px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  color: var(--text-3);
}
.sec-title .dim {
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
}
.toggle {
  width: 100%;
  justify-content: space-between;
}

.status-card {
  padding: 12px 14px;
  border-radius: 13px;
  background: var(--elev-1);
  border: 1px solid var(--border);
}
.status-card.active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.14), rgba(34, 211, 238, 0.07));
  border-color: rgba(99, 102, 241, 0.35);
}
.pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(148, 163, 184, 0.5);
}
.pulse.on {
  background: var(--accent-2);
  box-shadow: 0 0 0 0 rgba(34, 211, 238, 0.6);
  animation: pulseRing 1.6s infinite;
}
@keyframes pulseRing {
  0% {
    box-shadow: 0 0 0 0 rgba(34, 211, 238, 0.5);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(34, 211, 238, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(34, 211, 238, 0);
  }
}
.status-text {
  font-size: 12.5px;
  font-weight: 600;
}
.metric-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin-top: 12px;
}
.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.metric-val {
  font-size: 15px;
  font-weight: 650;
  font-family: var(--mono);
  color: var(--text-1);
}
.metric-val i {
  font-size: 10px;
  font-style: normal;
  color: var(--text-3);
  margin-left: 1px;
}
.metric-key {
  font-size: 10.5px;
  color: var(--text-3);
}

.timeline {
  position: relative;
  padding-left: 4px;
}
.tl-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
  font-size: 12px;
  color: var(--text-2);
}
.tl-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
}
.tl-item.done .tl-dot {
  background: var(--success);
}
.tl-item.running .tl-dot {
  background: var(--accent-2);
  animation: dotPulse 1.4s infinite;
}
.tl-label {
  flex: 1;
}
.tl-state {
  font-size: 10.5px;
  color: var(--text-3);
}

.plan-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.plan-list li {
  display: flex;
  gap: 9px;
  padding: 7px 0;
  border-bottom: 1px dashed rgba(120, 150, 200, 0.1);
}
.plan-list li:last-child {
  border-bottom: none;
}
.num {
  width: 19px;
  height: 19px;
  min-width: 19px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 10.5px;
  background: rgba(99, 102, 241, 0.16);
  color: var(--accent-ink-strong);
  margin-top: 1px;
}
.plan-list li.done .num {
  background: rgba(52, 211, 153, 0.18);
  color: var(--success-ink);
}
.plan-body {
  min-width: 0;
}
.plan-title {
  font-size: 12.5px;
  color: var(--text-1);
}
.plan-detail {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 2px;
  line-height: 1.6;
}
.plan-tool {
  display: inline-block;
  margin-top: 4px;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(34, 211, 238, 0.12);
  color: var(--cyan-ink);
}

.tool-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.tool-item {
  display: flex;
  gap: 9px;
  padding: 9px 11px;
  border-radius: 11px;
  background: var(--elev-1);
  border: 1px solid var(--border);
  border-left: 2px solid rgba(52, 211, 153, 0.5);
}
.tool-item.error {
  border-left-color: rgba(248, 113, 113, 0.7);
  background: rgba(248, 113, 113, 0.05);
}
.tool-item.running {
  border-left-color: var(--accent-2);
}
.tool-ico {
  font-size: 13px;
}
.tool-body {
  min-width: 0;
  flex: 1;
}
.tool-head {
  display: flex;
  align-items: center;
  gap: 7px;
}
.tool-name {
  font-size: 11.5px;
  color: var(--text-1);
}
.tool-state {
  font-size: 11px;
  color: var(--success);
}
.tool-item.error .tool-state {
  color: var(--danger);
}
.tool-time {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-3);
}
.tool-preview,
.tool-args {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-2);
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tool-err {
  margin-top: 4px;
  font-size: 11px;
  color: var(--danger-ink);
  line-height: 1.6;
}

.empty-block {
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
  border: 1px dashed var(--border);
  border-radius: 11px;
}

.notice {
  padding: 8px 11px;
  border-radius: 9px;
  font-size: 11.5px;
  line-height: 1.6;
  background: rgba(251, 191, 36, 0.08);
  border: 1px solid rgba(251, 191, 36, 0.22);
  color: var(--warn-ink);
  margin-bottom: 6px;
}
.notice.error {
  background: rgba(248, 113, 113, 0.08);
  border-color: rgba(248, 113, 113, 0.24);
  color: var(--danger-ink);
}

.reasoning {
  margin: 0;
  padding: 11px;
  border-radius: 10px;
  background: var(--inset-bg);
  border: 1px dashed var(--border);
  font-size: 11.5px;
  line-height: 1.75;
  color: var(--text-2);
  white-space: pre-wrap;
  font-family: var(--font);
  max-height: 300px;
  overflow: auto;
}

.demo-judge {
  padding: 12px;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.05);
  border: 1px solid var(--border);
}
.demo-judge.ok {
  background: linear-gradient(135deg, rgba(34, 211, 238, 0.08), rgba(99, 102, 241, 0.1));
  border-color: rgba(34, 211, 238, 0.3);
}
.judge-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.judge-badge {
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 11px;
  background: rgba(148, 163, 184, 0.15);
  color: var(--text-2);
}
.demo-judge.ok .judge-badge {
  background: rgba(34, 211, 238, 0.16);
  color: var(--cyan-ink);
}
.judge-score {
  font-size: 10.5px;
  color: var(--text-3);
}
.judge-reason {
  margin: 8px 0 0;
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text-2);
}
.judge-steps {
  margin: 7px 0 0;
  padding-left: 17px;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--text-2);
}
</style>