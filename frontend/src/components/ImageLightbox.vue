<script setup lang="ts">
/**
 * 图片放大预览（灯箱）。
 * - 点背景 / 按 Esc / 点 ✕ 关闭
 * - 滚轮缩放（0.4x ~ 5x），放大后可以拖动查看；双击复位
 * 由 ui store 的 lightbox 驱动，任何地方 ui.openLightbox(url) 即可。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()

const scale = ref(1)
const offset = ref({ x: 0, y: 0 })
const panning = ref(false)
const loaded = ref(false)
const failed = ref(false)
const dragging = ref(false)
let start = { x: 0, y: 0, ox: 0, oy: 0 }

const open = computed(() => !!ui.lightbox)
const name = computed(() => ui.lightbox?.name || '')
const url = computed(() => ui.lightbox?.url || '')

const transform = computed(
  () => `translate(${offset.value.x}px, ${offset.value.y}px) scale(${scale.value})`,
)
const canPan = computed(() => scale.value > 1.02)

function reset() {
  scale.value = 1
  offset.value = { x: 0, y: 0 }
  loaded.value = false
  failed.value = false
}

watch(
  () => ui.lightbox?.url,
  () => {
    reset()
    document.documentElement.style.overflow = ui.lightbox ? 'hidden' : ''
  },
)

function close() {
  document.documentElement.style.overflow = ''
  ui.closeLightbox()
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  const step = e.deltaY > 0 ? -0.12 : 0.12
  const next = Math.min(5, Math.max(0.4, scale.value + step))
  scale.value = Number(next.toFixed(2))
  if (scale.value <= 1) offset.value = { x: 0, y: 0 }
}

function onPointerDown(e: PointerEvent) {
  if (!canPan.value) return
  dragging.value = true
  panning.value = true
  start = { x: e.clientX, y: e.clientY, ox: offset.value.x, oy: offset.value.y }
  ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  offset.value = {
    x: start.ox + (e.clientX - start.x),
    y: start.oy + (e.clientY - start.y),
  }
}

function onPointerUp() {
  dragging.value = false
  panning.value = false
}

function onKey(e: KeyboardEvent) {
  if (!open.value) return
  if (e.key === 'Escape') {
    e.stopPropagation()
    close()
  } else if (e.key === '0' || e.key.toLowerCase() === 'r') {
    reset()
  }
}

document.addEventListener('keydown', onKey, true)
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey, true)
  document.documentElement.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <transition name="lb">
      <div v-if="open" class="lightbox" @click.self="close">
        <div class="lb-bar" @click.stop>
          <span class="lb-name ellipsis">{{ name || '图片预览' }}</span>
          <span class="lb-scale">{{ Math.round(scale * 100) }}%</span>
          <button class="lb-btn" title="复位（双击图片也可以）" @click="reset">复位</button>
          <a class="lb-btn" :href="url" target="_blank" rel="noopener" title="在新标签页打开原图">原图</a>
          <button class="lb-btn close" title="关闭（Esc）" @click="close">✕</button>
        </div>

        <div
          class="lb-stage"
          :class="{ panning, 'can-pan': canPan }"
          @wheel.prevent="onWheel"
          @dblclick="reset"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
        >
          <div v-if="!loaded && !failed" class="lb-loading"><span class="spinner" /> 加载中…</div>
          <div v-if="failed" class="lb-loading">图片加载失败（可能文件已被删除）</div>
          <img
            :src="url"
            :alt="name"
            class="lb-img"
            :style="{ transform }"
            draggable="false"
            @load="loaded = true"
            @error="failed = true"
            @click.stop
          />
        </div>

        <div class="lb-tip">滚轮缩放 · 放大后可拖动 · Esc 关闭</div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: flex;
  flex-direction: column;
  background: rgba(3, 6, 16, 0.9);
  backdrop-filter: blur(4px);
}
.lb-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 12.5px;
  color: #cbd5e1;
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(15, 23, 42, 0));
}
.lb-name {
  flex: 1;
  min-width: 0;
  max-width: 60vw;
}
.lb-scale {
  font-family: var(--mono);
  color: #94a3b8;
}
.lb-btn {
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 12px;
  color: #cbd5e1;
  background: rgba(148, 163, 184, 0.14);
  border: 1px solid rgba(148, 163, 184, 0.2);
  transition: background 0.15s;
}
.lb-btn:hover {
  background: rgba(148, 163, 184, 0.26);
  color: #fff;
}
.lb-btn.close {
  font-size: 13px;
}
.lb-stage {
  flex: 1;
  display: grid;
  place-items: center;
  overflow: hidden;
  cursor: default;
  touch-action: none;
}
.lb-stage.can-pan {
  cursor: grab;
}
.lb-stage.panning {
  cursor: grabbing;
}
.lb-img {
  max-width: 94vw;
  max-height: calc(100vh - 110px);
  border-radius: 8px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
  transition: transform 0.09s ease-out;
  transform-origin: center center;
  user-select: none;
}
.lb-stage.panning .lb-img {
  transition: none;
}
.lb-loading {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: #94a3b8;
}
.lb-tip {
  padding: 8px 0 12px;
  text-align: center;
  font-size: 11px;
  color: #64748b;
}
.lb-enter-active,
.lb-leave-active {
  transition: opacity 0.16s ease;
}
.lb-enter-from,
.lb-leave-to {
  opacity: 0;
}
</style>