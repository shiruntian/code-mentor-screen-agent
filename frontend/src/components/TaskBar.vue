<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { ref } from 'vue'
import { useAppStore } from '../stores/app'
import { api } from '../api/client'

const app = useAppStore()
const tasks = ref<TaskItem[]>([])
const collapsed = ref(false)

interface TaskItem {
  id: number
  idx: number
  title: string
  status: 'pending' | 'active' | 'done' | 'skipped'
}

const doneCount = computed(() => tasks.value.filter((t) => t.status === 'done').length)
const visible = computed(() => tasks.value.length > 0)

async function load() {
  const id = app.activeId
  if (!id) {
    tasks.value = []
    return
  }
  try {
    const res = await api.get<{ items: TaskItem[] }>(`/api/conversations/${id}/tasks`)
    tasks.value = res.items || []
  } catch {
    tasks.value = []
  }
}

async function mark(item: TaskItem, status: string) {
  const id = app.activeId
  if (!id) return
  try {
    await api.patch(`/api/conversations/${id}/tasks/${item.idx}`, { status })
    await load()
  } catch (e) {
    app.report(e)
  }
}

onMounted(load)
watch(() => app.activeId, load)
watch(() => app.messages.length, load)
</script>

<template>
  <div v-if="visible" class="task-bar">
    <button class="task-toggle" @click="collapsed = !collapsed">
      📋 任务清单 {{ doneCount }}/{{ tasks.length }}
      <span class="caret">{{ collapsed ? '▸' : '▾' }}</span>
    </button>
    <div v-show="!collapsed" class="task-items">
      <div
        v-for="t in tasks"
        :key="t.idx"
        class="task-item"
        :class="[t.status]"
        :title="t.status === 'done' ? '已完成' : '点击标记完成'"
        @click="t.status !== 'done' && mark(t, 'done')"
      >
        <span class="task-idx">{{ t.status === 'done' ? '✓' : t.idx }}</span>
        <span class="task-title ellipsis">{{ t.title }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-bar {
  max-width: 860px;
  margin: 0 auto 6px;
  padding: 0 20px;
}
.task-toggle {
  font-size: 12px;
  color: var(--text-3);
  background: none;
  padding: 4px 0;
}
.task-toggle:hover {
  color: var(--text-1);
}
.caret {
  margin-left: 4px;
}
.task-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--surface-2, rgba(127, 127, 127, 0.08));
  border: 1px solid var(--border);
  max-height: 150px;
  overflow-y: auto;
}
.task-item {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
  padding: 2px 0;
}
.task-item:hover {
  color: var(--text-1);
}
.task-item.active {
  color: var(--accent);
  font-weight: 600;
}
.task-item.done .task-title {
  text-decoration: line-through;
  opacity: 0.6;
}
.task-idx {
  width: 16px;
  text-align: center;
  flex: none;
  font-variant-numeric: tabular-nums;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
