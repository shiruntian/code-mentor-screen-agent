<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api/client'
import { useAppStore } from '../../stores/app'
import type { KnowledgeDoc } from '../../types'

const app = useAppStore()
const docs = ref<KnowledgeDoc[]>([])
const stats = ref<Record<string, any>>({})
const loading = ref(false)
const showForm = ref(false)
const form = ref({ title: '', content: '', tags: '', source: '', kind: 'doc', target: 'both' })
const saving = ref(false)
const query = ref('')
const hits = ref<any[]>([])
const searching = ref(false)
const reindexing = ref(false)

async function load() {
  loading.value = true
  try {
    const [list, stat] = await Promise.all([
      api.get<{ items: KnowledgeDoc[] }>('/api/knowledge'),
      api.get<Record<string, any>>('/api/knowledge/stats'),
    ])
    docs.value = list.items
    stats.value = stat
  } catch (e) {
    app.report(e)
  } finally {
    loading.value = false
  }
}

async function createDoc() {
  if (!form.value.title.trim() || form.value.content.trim().length < 10) {
    app.toast('warning', '标题必填，正文至少 10 个字')
    return
  }
  const kind = form.value.kind
  saving.value = true
  try {
    await api.post('/api/knowledge', {
      title: form.value.title.trim(),
      content: form.value.content,
      tags: form.value.tags || null,
      source: form.value.source || (kind === 'guide' ? '提示知识' : null),
      kind,
      target: form.value.target,
    })
    form.value = { title: '', content: '', tags: '', source: '', kind: 'doc', target: 'both' }
    showForm.value = false
    await load()
    app.toast(
      'success',
      kind === 'guide'
        ? form.value.kind === 'guide'
          ? '提示知识已保存，下一轮对话生效'
          : '提示知识已保存'
        : '文档已入库并完成向量化',
    )
  } catch (e) {
    app.report(e)
  } finally {
    saving.value = false
  }
}

async function removeDoc(id: number, title: string) {
  if (!window.confirm(`删除文档「${title}」？对应的向量也会一并删除。`)) return
  try {
    await api.del(`/api/knowledge/${id}`)
    await load()
  } catch (e) {
    app.report(e)
  }
}

async function search() {
  if (!query.value.trim()) return
  searching.value = true
  try {
    const res = await api.post<{ hits: any[] }>('/api/knowledge/search', {
      query: query.value.trim(),
      top_k: 4,
    })
    hits.value = res.hits
  } catch (e) {
    app.report(e)
  } finally {
    searching.value = false
  }
}

async function reindex() {
  reindexing.value = true
  try {
    await api.post('/api/knowledge/reindex')
    await load()
    app.toast('success', '索引已重建')
  } catch (e) {
    app.report(e)
  } finally {
    reindexing.value = false
  }
}

async function seed() {
  try {
    const res = await api.post<{ created: number }>('/api/knowledge/seed')
    await load()
    app.toast('success', `已导入 ${res.created} 篇内置文档`)
  } catch (e) {
    app.report(e)
  }
}

onMounted(load)
</script>

<template>
  <div class="pane scroll-y">
    <div class="stats">
      <div class="stat">
        <span class="v">{{ stats.documents ?? 0 }}</span>
        <span class="k">文档</span>
      </div>
      <div class="stat">
        <span class="v">{{ stats.chunks ?? 0 }}</span>
        <span class="k">切片</span>
      </div>
      <div class="stat">
        <span class="v">{{ stats.vector?.knowledge_points ?? 0 }}</span>
        <span class="k">向量点</span>
      </div>
    </div>
    <div class="vector-info">
      <span class="tag">Qdrant {{ stats.vector?.mode || '—' }}</span>
      <span class="tag tag-mute">{{ stats.vector?.embedder || '—' }} · {{ stats.vector?.dim || '—' }} 维</span>
      <span class="grow" />
      <button class="btn btn-sm btn-ghost" :disabled="reindexing" @click="reindex">
        {{ reindexing ? '重建中…' : '重建索引' }}
      </button>
    </div>

    <section class="section">
      <h3 class="sec-title">检索测试</h3>
      <div class="row">
        <input v-model="query" class="input" placeholder="输入问题，看能召回哪些片段" @keydown.enter="search" />
        <button class="btn btn-sm" :disabled="searching" @click="search">检索</button>
      </div>
      <div v-if="hits.length" class="hit-list">
        <div v-for="(h, i) in hits" :key="i" class="hit">
          <div class="hit-head">
            <span class="hit-title">{{ h.title }}</span>
            <span class="hit-score">{{ h.score }}</span>
          </div>
          <p class="hit-text">{{ String(h.text).slice(0, 180) }}</p>
        </div>
      </div>
      <div v-else-if="searching" class="empty-block">检索中…</div>
    </section>

    <section class="section">
      <div class="sec-head">
        <h3 class="sec-title" style="margin: 0">知识文档</h3>
        <span class="grow" />
        <button class="btn btn-sm btn-ghost" @click="seed">导入内置知识包</button>
        <button class="btn btn-sm" @click="showForm = !showForm">{{ showForm ? '取消' : '+ 新增' }}</button>
      </div>

      <div v-if="showForm" class="form-card">
        <div class="seg-row">
          <span class="seg-label">类型</span>
          <button class="seg" :class="{ on: form.kind === 'doc' }" @click="form.kind = 'doc'">📄 知识文档</button>
          <button class="seg" :class="{ on: form.kind === 'guide' }" @click="form.kind = 'guide'">🧭 提示知识</button>
        </div>
        <div v-if="form.kind === 'guide'" class="seg-row">
          <span class="seg-label">作用对象</span>
          <button class="seg" :class="{ on: form.target === 'chat' }" @click="form.target = 'chat'">对话</button>
          <button class="seg" :class="{ on: form.target === 'screen' }" @click="form.target = 'screen'">屏幕控制</button>
          <button class="seg" :class="{ on: form.target === 'both' }" @click="form.target = 'both'">两者</button>
        </div>
        <input
          v-model="form.title"
          class="input"
          :placeholder="form.kind === 'guide'
            ? '写成给模型的行为准则，例如：\n- 打开程序优先用 Win+R 输入路径\n- 点击前先确认窗口标题\n- 输入代码后按 Ctrl+S 保存'
            : '粘贴 Markdown 正文，支持代码块…'"
          rows="7"
          style="margin-top: 8px"
        />
        <p v-if="form.kind === 'guide'" class="form-tip">
          提示知识不会进向量库，而是每轮原样注入到对应智能体的系统提示词里，用来约束它的行为。
        </p>
        <button class="btn btn-primary btn-sm" style="margin-top: 8px; width: 100%" :disabled="saving" @click="createDoc">
          {{ saving ? '保存中…' : form.kind === 'guide' ? '保存提示知识' : '入库并向量化' }}
        </button>
      </div>

      <div v-if="loading" class="empty-block">加载中…</div>
      <div v-else-if="!docs.length" class="empty-block">知识库还是空的，可以「导入内置知识包」</div>
      <div v-else class="doc-list">
        <div v-for="d in docs" :key="d.id" class="doc">
          <div class="doc-head">
            <span class="doc-title ellipsis">{{ d.title }}</span>
            <button class="icon-btn del" @click="removeDoc(d.id, d.title)">×</button>
          </div>
          <div class="doc-meta">
            <span v-if="d.kind === 'guide'" class="tag tag-guide">
              提示 · {{ d.target === 'chat' ? '对话' : d.target === 'screen' ? '屏幕' : '两者' }}
            </span>
            <span>{{ d.char_count }} 字</span>
            <template v-if="d.kind !== 'guide'">
              <span class="sep">·</span>
              <span>{{ d.chunk_count }} 切片</span>
            </template>
            <span v-if="d.tags" class="tag tag-mute">{{ d.tags }}</span>
          </div>
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
}
.stat {
  flex: 1;
  padding: 10px 12px;
  border-radius: 11px;
  background: var(--elev-1);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat .v {
  font-size: 17px;
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
.vector-info {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.section {
  margin-top: 18px;
}
.sec-title {
  margin: 0 0 9px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  color: var(--text-3);
}
.sec-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 9px;
}

.hit-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.hit {
  padding: 9px 11px;
  border-radius: 9px;
  background: rgba(99, 102, 241, 0.07);
  border: 1px solid rgba(99, 102, 241, 0.18);
}
.hit-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.hit-title {
  font-size: 12px;
  color: var(--accent-ink);
}
.hit-score {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--accent-2);
}
.hit-text {
  margin: 5px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-2);
}

.form-card {
  padding: 12px;
  border-radius: 12px;
  background: var(--elev-1);
  border: 1px solid var(--border);
  margin-bottom: 10px;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.doc {
  padding: 9px 11px;
  border-radius: 10px;
  background: var(--elev-1);
  border: 1px solid var(--border);
}
.doc-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.doc-title {
  flex: 1;
  font-size: 12.5px;
  color: var(--text-1);
}
.doc-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 10.5px;
  color: var(--text-3);
}
.del {
  width: 20px;
  height: 20px;
  font-size: 14px;
  line-height: 1;
  color: var(--text-3);
}
.del:hover {
  color: var(--danger);
}
.empty-block {
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
  border: 1px dashed var(--border);
  border-radius: 11px;
}

.seg-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.seg-label {
  font-size: 11px;
  color: var(--text-3);
  margin-right: 2px;
}
.seg {
  padding: 4px 10px;
  border-radius: 7px;
  font-size: 11.5px;
  color: var(--text-2);
  background: var(--inset-bg);
  border: 1px solid var(--border);
}
.seg:hover {
  color: var(--text-1);
  border-color: var(--border-strong);
}
.seg.on {
  color: #fff;
  background: var(--grad-accent);
  border-color: transparent;
}
.form-tip {
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-3);
}
.tag-guide {
  color: var(--accent-ink-strong);
  background: rgba(99, 102, 241, 0.16);
  border: 1px solid rgba(99, 102, 241, 0.28);
}

</style>