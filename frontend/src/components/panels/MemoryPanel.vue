<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api/client'
import { useAppStore } from '../../stores/app'
import type { MemoryItem } from '../../types'
import { relativeTime } from '../../utils/format'

const app = useAppStore()
const items = ref<MemoryItem[]>([])
const stats = ref<{ total: number; by_kind: Record<string, number> }>({ total: 0, by_kind: {} })
const loading = ref(false)
const newContent = ref('')
const newKind = ref('fact')
const recallQuery = ref('')
const recallResults = ref<MemoryItem[]>([])
const recalling = ref(false)
const adding = ref(false)

const KIND_LABEL: Record<string, string> = {
  fact: '事实',
  preference: '偏好',
  profile: '画像',
  goal: '目标',
  skill: '技能',
}

async function load() {
  loading.value = true
  try {
    const data = await api.get<{ items: MemoryItem[]; stats: typeof stats.value }>('/api/memory')
    items.value = data.items
    stats.value = data.stats
  } catch (e) {
    app.report(e)
  } finally {
    loading.value = false
  }
}

async function add() {
  if (newContent.value.trim().length < 2) return
  adding.value = true
  try {
    await api.post('/api/memory', { content: newContent.value.trim(), kind: newKind.value })
    newContent.value = ''
    await load()
    app.toast('success', '已写入长期记忆')
  } catch (e) {
    app.report(e)
  } finally {
    adding.value = false
  }
}

async function remove(id: number) {
  try {
    await api.del(`/api/memory/${id}`)
    await load()
  } catch (e) {
    app.report(e)
  }
}

async function recall() {
  if (!recallQuery.value.trim()) return
  recalling.value = true
  try {
    const data = await api.post<{ items: MemoryItem[] }>('/api/memory/recall', {
      query: recallQuery.value.trim(),
      top_k: 5,
    })
    recallResults.value = data.items
  } catch (e) {
    app.report(e)
  } finally {
    recalling.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="pane scroll-y">
    <div class="stats">
      <div class="stat">
        <span class="v">{{ stats.total }}</span>
        <span class="k">长期记忆</span>
      </div>
      <div v-for="(count, kind) in stats.by_kind" :key="kind" class="stat small">
        <span class="v">{{ count }}</span>
        <span class="k">{{ KIND_LABEL[kind] || kind }}</span>
      </div>
    </div>

    <section class="section">
      <h3 class="sec-title">召回测试 <span class="dim">向量语义搜索</span></h3>
      <div class="row">
        <input
          v-model="recallQuery"
          class="input"
          placeholder="例如：我喜欢用什么技术栈？"
          @keydown.enter="recall"
        />
        <button class="btn btn-sm" :disabled="recalling" @click="recall">
          <span v-if="recalling" class="spinner" />
          <span v-else>召回</span>
        </button>
      </div>
      <div v-if="recallResults.length" class="recall-list">
        <div v-for="r in recallResults" :key="r.id" class="recall-item">
          <span class="score">{{ (r.score ?? 0).toFixed(2) }}</span>
          <span class="recall-text">{{ r.content }}</span>
        </div>
      </div>
    </section>

    <section class="section">
      <h3 class="sec-title">新增记忆</h3>
      <textarea v-model="newContent" class="textarea" placeholder="例如：学习者是前端，正在学 Vue3 组合式 API" />
      <div class="row" style="margin-top: 8px">
        <select v-model="newKind" class="select" style="width: 120px">
          <option v-for="(label, kind) in KIND_LABEL" :key="kind" :value="kind">{{ label }}</option>
        </select>
        <button class="btn btn-primary btn-sm grow" :disabled="adding || newContent.trim().length < 2" @click="add">
          {{ adding ? '保存中…' : '写入长期记忆' }}
        </button>
      </div>
    </section>

    <section class="section">
      <h3 class="sec-title">记忆列表</h3>
      <div v-if="loading" class="empty-block">加载中…</div>
      <div v-else-if="!items.length" class="empty-block">还没有长期记忆，聊几轮后会自动抽取</div>
      <div v-else class="mem-list">
        <div v-for="m in items" :key="m.id" class="mem-item">
          <div class="mem-head">
            <span class="tag">{{ KIND_LABEL[m.kind] || m.kind }}</span>
            <span class="tiny muted">{{ relativeTime(m.created_at) }} · 命中 {{ m.access_count }} 次</span>
            <button class="icon-btn del" title="删除" @click="remove(m.id)">×</button>
          </div>
          <p class="mem-content">{{ m.content }}</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pane {
  padding: 14px;
  height: 100%;
}
.stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.stat {
  flex: 1;
  min-width: 74px;
  padding: 10px 12px;
  border-radius: 11px;
  background: var(--elev-1);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat .v {
  font-size: 18px;
  font-weight: 650;
  font-family: var(--mono);
  background: var(--stat-grad);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.stat .k {
  font-size: 10.5px;
  color: var(--text-3);
}
.stat.small .v {
  font-size: 14px;
  background: none;
  color: var(--text-1);
}

.section {
  margin-top: 18px;
}
.sec-title {
  display: flex;
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
  text-transform: none;
  letter-spacing: 0;
}

.recall-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.recall-item {
  display: flex;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 9px;
  background: rgba(34, 211, 238, 0.06);
  border: 1px solid rgba(34, 211, 238, 0.18);
  font-size: 11.5px;
  line-height: 1.6;
}
.score {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--cyan-ink);
}
.recall-text {
  color: var(--text-2);
}

.mem-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mem-item {
  padding: 10px 12px;
  border-radius: 11px;
  background: var(--elev-1);
  border: 1px solid var(--border);
}
.mem-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mem-head .tiny {
  flex: 1;
}
.del {
  width: 22px;
  height: 22px;
  font-size: 15px;
  line-height: 1;
  color: var(--text-3);
}
.del:hover {
  color: var(--danger);
  background: rgba(248, 113, 113, 0.12);
}
.mem-content {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-1);
}

.empty-block {
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
  border: 1px dashed var(--border);
  border-radius: 11px;
}
</style>