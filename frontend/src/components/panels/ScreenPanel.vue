<script setup lang="ts">
import { computed } from 'vue'
import { useScreenStore } from '../../stores/screen'
import { useUiStore } from '../../stores/ui'
import { useAppStore } from '../../stores/app'

const screen = useScreenStore()
const ui = useUiStore()
const app = useAppStore()

const statusText = computed(() => {
  const map: Record<string, string> = {
    idle: '未启动',
    running: '演示中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
  }
  return map[screen.session?.status || 'idle'] || '未启动'
})

const statusClass = computed(() => `st-${screen.session?.status || 'idle'}`)

const lastStep = computed(() => [...screen.logs].reverse()[0] || null)
</script>

<template>
  <div class="pane scroll-y">
    <div v-if="!screen.session" class="empty-state">
      <div class="big-emoji">🖥️</div>
      <h3>还没有屏幕演示</h3>
      <p>
        在智能体模式下问一个「需要动手做」的问题（例如让 AI 给你一段可运行的代码），<br />
        回答完成后，消息下方会出现「启动屏幕演示」按钮。
      </p>
      <div class="rules">
        <div class="rule"><span>①</span> 只有真实可操作的编程内容才会弹出入口</div>
        <div class="rule"><span>②</span> 启动/暂停完全由你手动控制</div>
        <div class="rule"><span>③</span> 暂停会记录当前步骤，恢复后从这里继续</div>
      </div>
    </div>

    <template v-else>
      <div class="status-card" :class="statusClass">
        <div class="row">
          <span class="status-dot" />
          <span class="status-text">{{ statusText }}</span>
          <span class="grow" />
          <span class="tiny mono muted">{{ screen.session.id.slice(0, 8) }}</span>
        </div>
        <div class="goal">{{ screen.session.goal }}</div>
        <div class="progress">
          <div class="bar">
            <div
              class="fill"
              :style="{ width: `${Math.min(100, (screen.session.current_step / Math.max(1, screen.session.max_steps)) * 100)}%` }"
            />
          </div>
          <span class="steps">{{ screen.session.current_step }} / {{ screen.session.max_steps }}</span>
        </div>
      </div>

      <div v-if="screen.latestShot" class="shot-preview">
        <img :src="screen.latestShot" alt="最新截图" />
        <span class="shot-label">最新屏幕</span>
      </div>

      <div v-if="lastStep" class="last-step">
        <div class="ls-head">
          <span class="tag">第 {{ lastStep.idx }} 步</span>
          <span class="tiny muted">{{ lastStep.status === 'done' ? '已执行' : '失败' }}</span>
        </div>
        <p class="ls-thought">{{ lastStep.thought || '—' }}</p>
        <p class="ls-detail mono">{{ lastStep.detail }}</p>
      </div>

      <div v-if="screen.error" class="err-block">{{ screen.error }}</div>

      <div class="actions">
        <button class="btn btn-primary btn-sm grow" @click="ui.openScreen(null, app.activeId)">
          打开演示控制台
        </button>
        <button class="btn btn-sm" @click="screen.refresh()">刷新</button>
      </div>

      <div class="meta-grid">
        <div class="m">
          <span class="mk">识别间隔</span>
          <span class="mv">{{ (screen.session.interval_ms / 1000).toFixed(1) }}s</span>
        </div>
        <div class="m">
          <span class="mk">模式</span>
          <span class="mv">{{ screen.session.dry_run ? '演练' : '真实控制' }}</span>
        </div>
        <div class="m">
          <span class="mk">日志步数</span>
          <span class="mv">{{ screen.logs.length }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pane {
  padding: 14px;
  height: 100%;
}
.empty-state {
  text-align: center;
  padding: 26px 10px;
}
.big-emoji {
  font-size: 34px;
  margin-bottom: 10px;
}
.empty-state h3 {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
}
.empty-state p {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.8;
  color: var(--text-3);
}
.rules {
  margin-top: 18px;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rule {
  display: flex;
  gap: 8px;
  padding: 8px 11px;
  border-radius: 9px;
  background: var(--elev-1);
  border: 1px solid var(--border);
  font-size: 11.5px;
  color: var(--text-2);
  line-height: 1.6;
}
.rule span {
  color: var(--accent-2);
}

.status-card {
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--elev-1);
  border: 1px solid var(--border);
}
.status-card.st-running {
  background: linear-gradient(135deg, rgba(52, 211, 153, 0.12), rgba(34, 211, 238, 0.07));
  border-color: rgba(52, 211, 153, 0.3);
}
.status-card.st-paused {
  background: rgba(251, 191, 36, 0.08);
  border-color: rgba(251, 191, 36, 0.28);
}
.status-card.st-failed {
  background: rgba(248, 113, 113, 0.08);
  border-color: rgba(248, 113, 113, 0.28);
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
}
.st-running .status-dot {
  background: var(--success);
  animation: dotPulse 1.4s infinite;
}
.st-paused .status-dot {
  background: var(--warning);
}
.st-failed .status-dot {
  background: var(--danger);
}
.status-text {
  font-size: 12.5px;
  font-weight: 600;
}
.goal {
  margin-top: 8px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-2);
}
.progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}
.bar {
  flex: 1;
  height: 5px;
  border-radius: 999px;
  background: var(--elev-2);
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: 999px;
  background: var(--grad-accent);
  transition: width 0.4s ease;
}
.steps {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-3);
}

.shot-preview {
  position: relative;
  margin-top: 12px;
  border-radius: 11px;
  overflow: hidden;
  border: 1px solid var(--border-strong);
}
.shot-preview img {
  width: 100%;
  display: block;
}
.shot-label {
  position: absolute;
  left: 8px;
  bottom: 8px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
}

.last-step {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 11px;
  background: var(--elev-1);
  border: 1px solid var(--border);
}
.ls-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ls-thought {
  margin: 7px 0 3px;
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text-1);
}
.ls-detail {
  margin: 0;
  font-size: 10.5px;
  color: var(--text-3);
}

.err-block {
  margin-top: 10px;
  padding: 9px 11px;
  border-radius: 9px;
  font-size: 11.5px;
  line-height: 1.6;
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.24);
  color: var(--danger-ink);
}

.actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 7px;
  margin-top: 12px;
}
.m {
  padding: 9px;
  border-radius: 9px;
  background: var(--elev-1);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.mk {
  font-size: 10px;
  color: var(--text-3);
}
.mv {
  font-size: 12px;
  font-family: var(--mono);
}
</style>