<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../stores/app'
import type { Attachment } from '../types'

const app = useAppStore()
const textarea = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const attachments = ref<Attachment[]>([])
const uploading = ref(false)
const dragging = ref(false)

const canSend = computed(
  () => !app.streaming && (app.draft.trim().length > 0 || attachments.value.length > 0),
)

function resize() {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

async function submit() {
  if (!canSend.value) return
  const text = app.draft
  const files = [...attachments.value]
  app.draft = ''
  attachments.value = []
  await nextTick()
  resize()
  await app.send(text, files)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

async function pickFiles() {
  fileInput.value?.click()
}

async function handleFiles(files: FileList | null) {
  if (!files || !files.length) return
  uploading.value = true
  try {
    for (const file of Array.from(files).slice(0, 4)) {
      if (!file.type.startsWith('image/')) {
        app.toast('warning', `已跳过非图片文件：${file.name}`)
        continue
      }
      if (file.size > 8 * 1024 * 1024) {
        app.toast('warning', `图片超过 8MB：${file.name}`)
        continue
      }
      const res = await api.upload<{ attachment: Attachment }>(file)
      attachments.value.push(res.attachment)
    }
  } catch (e) {
    app.report(e)
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onDrop(e: DragEvent) {
  dragging.value = false
  handleFiles(e.dataTransfer?.files || null)
}

function removeAttachment(i: number) {
  attachments.value.splice(i, 1)
}
</script>

<template>
  <div class="composer-wrap">
    <div
      class="composer"
      :class="{ dragging }"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <div v-if="attachments.length" class="previews">
        <div v-for="(att, i) in attachments" :key="i" class="preview">
          <img :src="att.url" :alt="att.name" />
          <button class="remove" title="移除" @click="removeAttachment(i)">×</button>
        </div>
        <span v-if="uploading" class="uploading"><span class="spinner" /> 上传中…</span>
      </div>

      <textarea
        ref="textarea"
        v-model="app.draft"
        class="editor"
        rows="1"
        placeholder="问点什么，或者直接把报错、代码贴进来…"
        @input="resize"
        @keydown="onKeydown"
      />

      <div class="toolbar">
        <div class="left">
          <button class="btn btn-ghost btn-sm" title="上传图片（多模态）" @click="pickFiles">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <rect x="3" y="3" width="18" height="18" rx="3" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" stroke-linecap="round" />
            </svg>
            <span>图片</span>
          </button>
          <input
            ref="fileInput"
            type="file"
            accept="image/*"
            multiple
            hidden
            @change="handleFiles(($event.target as HTMLInputElement).files)"
          />

          <div class="mode-switch">
            <button :class="{ on: app.mode === 'agent' }" @click="app.mode = 'agent'">智能体</button>
            <button :class="{ on: app.mode === 'chat' }" @click="app.mode = 'chat'">快速对话</button>
          </div>
        </div>

        <div class="right">
          <span class="count" :class="{ warn: app.draft.length > 1800 }">{{ app.draft.length }}</span>
          <button v-if="app.streaming" class="btn btn-sm stop-btn" @click="app.stop()">
            <span class="stop-square" /> 停止
          </button>
          <button v-else class="send-btn" :disabled="!canSend" title="发送 (Enter)" @click="submit">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 19V5M5 12l7-7 7 7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </div>
    <div class="foot-hint">
      <span v-if="app.mode === 'agent'">🧠 智能体模式：先规划 → 再调工具 → 最后讲解，回答完成后可启动屏幕演示</span>
      <span v-else>⚡ 快速对话：直接调用模型，不做工具编排</span>
    </div>
  </div>
</template>

<style scoped>
.composer-wrap {
  padding: 6px 16px 14px;
  max-width: 860px;
  margin: 0 auto;
  width: 100%;
}
.composer {
  border-radius: 18px;
  background: var(--composer-bg);
  border: 1px solid var(--border);
  backdrop-filter: blur(18px);
  padding: 10px 12px 8px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.composer:focus-within {
  border-color: rgba(99, 102, 241, 0.45);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1), var(--shadow-lg);
}
.composer.dragging {
  border-color: var(--accent-2);
  background: rgba(34, 211, 238, 0.06);
}

.editor {
  width: 100%;
  min-height: 26px;
  max-height: 200px;
  padding: 6px 6px 4px;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  font-size: 14.5px;
  line-height: 1.65;
  color: var(--text-1);
}
.editor::placeholder {
  color: var(--text-3);
}

.previews {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 4px 4px 8px;
  flex-wrap: wrap;
}
.preview {
  position: relative;
  width: 54px;
  height: 54px;
  border-radius: 9px;
  overflow: hidden;
  border: 1px solid var(--border-strong);
}
.preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  line-height: 1;
  color: #fff;
  background: rgba(0, 0, 0, 0.6);
}
.uploading {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-3);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 4px;
}
.left,
.right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mode-switch {
  display: flex;
  padding: 2px;
  border-radius: 9px;
  background: var(--inset-bg);
  border: 1px solid var(--border);
}
.mode-switch button {
  padding: 4px 10px;
  border-radius: 7px;
  font-size: 11.5px;
  color: var(--text-3);
  transition: all 0.16s;
}
.mode-switch button.on {
  background: rgba(99, 102, 241, 0.24);
  color: var(--accent-ink);
}

.count {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--mono);
}
.count.warn {
  color: var(--warning);
}

.send-btn {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--grad-accent);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.32);
  transition: all 0.18s ease;
}
.send-btn:hover:not(:disabled) {
  filter: brightness(1.1);
  transform: translateY(-1px);
}
.send-btn:disabled {
  background: var(--elev-2);
  box-shadow: none;
  color: var(--text-3);
}

.stop-btn {
  color: var(--danger);
  border-color: rgba(248, 113, 113, 0.3);
}
.stop-square {
  width: 9px;
  height: 9px;
  border-radius: 2px;
  background: currentColor;
}

.foot-hint {
  text-align: center;
  font-size: 11px;
  color: var(--text-3);
  margin-top: 7px;
  height: 14px;
}
</style>