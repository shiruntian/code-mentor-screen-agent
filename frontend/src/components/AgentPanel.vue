<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '../stores/app'
import TracePanel from './panels/TracePanel.vue'
import MemoryPanel from './panels/MemoryPanel.vue'
import KnowledgePanel from './panels/KnowledgePanel.vue'
import ScreenPanel from './panels/ScreenPanel.vue'

const app = useAppStore()

const tabs = [
  { id: 'trace', label: '轨迹', icon: '◈' },
  { id: 'memory', label: '记忆', icon: '🧠' },
  { id: 'knowledge', label: '知识库', icon: '📚' },
  { id: 'screen', label: '演示', icon: '🖥️' },
] as const

const dragging = ref(false)

function startResize(e: MouseEvent) {
  dragging.value = true
  const startX = e.clientX
  const startW = (document.querySelector('.agent-panel') as HTMLElement)?.offsetWidth || 372
  const onMove = (ev: MouseEvent) => {
    const w = Math.min(560, Math.max(300, startW - (ev.clientX - startX)))
    document.documentElement.style.setProperty('--panel-w', `${w}px`)
  }
  const onUp = () => {
    dragging.value = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
</script>

<template>
  <aside class="agent-panel" :class="{ dragging }">
    <div class="resizer" @mousedown.prevent="startResize" />
    <div class="tabs">
      <button
        v-for="t in tabs"
        :key="t.id"
        class="tab"
        :class="{ on: app.panelTab === t.id }"
        @click="app.panelTab = t.id"
      >
        <span class="ico">{{ t.icon }}</span>
        <span>{{ t.label }}</span>
      </button>
      <button class="icon-btn close" title="收起面板" @click="app.panelOpen = false">×</button>
    </div>

    <div class="content">
      <TracePanel v-if="app.panelTab === 'trace'" />
      <MemoryPanel v-else-if="app.panelTab === 'memory'" />
      <KnowledgePanel v-else-if="app.panelTab === 'knowledge'" />
      <ScreenPanel v-else />
    </div>
  </aside>
</template>

<style scoped>
.agent-panel {
  width: var(--panel-w);
  min-width: var(--panel-w);
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
  border-left: 1px solid var(--border);
  backdrop-filter: blur(18px);
  position: relative;
}
.agent-panel.dragging {
  user-select: none;
}
.resizer {
  position: absolute;
  left: -3px;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  z-index: 5;
}
.resizer:hover {
  background: rgba(99, 102, 241, 0.3);
}

.tabs {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 10px 10px 0;
  border-bottom: 1px solid var(--border);
}
.tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 8px 10px;
  border-radius: 9px 9px 0 0;
  font-size: 12px;
  color: var(--text-3);
  position: relative;
  transition: color 0.16s;
}
.tab .ico {
  font-size: 12px;
}
.tab:hover {
  color: var(--text-1);
}
.tab.on {
  color: var(--text-1);
  background: var(--elev-2);
}
.tab.on::after {
  content: '';
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: -1px;
  height: 2px;
  border-radius: 2px;
  background: var(--grad-accent);
}
.close {
  margin-left: auto;
  font-size: 17px;
  line-height: 1;
}
.content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>