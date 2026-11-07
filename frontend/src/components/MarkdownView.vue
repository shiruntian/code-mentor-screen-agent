<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown'
import { useUiStore } from '../stores/ui'

const props = defineProps<{ content: string }>()
const html = computed(() => renderMarkdown(props.content))
const ui = useUiStore()

async function onClick(event: MouseEvent) {
  const target = event.target as HTMLElement

  // ① 代码块的一键复制
  if (target?.classList?.contains('code-copy')) {
    const code = decodeURIComponent(target.dataset.code || '')
    try {
      await navigator.clipboard.writeText(code)
      const original = target.textContent
      target.textContent = '已复制'
      target.classList.add('copied')
      setTimeout(() => {
        target.textContent = original || '复制'
        target.classList.remove('copied')
      }, 1400)
    } catch {
      /* 剪贴板权限被拒时静默失败 */
    }
    return
  }

  // ② 点正文里的图片放大预览（模型回答里带 ![]() 的情况）
  if (target?.tagName === 'IMG') {
    const img = target as HTMLImageElement
    event.preventDefault()
    ui.openLightbox(img.currentSrc || img.src, img.alt || '正文图片')
  }
}
</script>

<template>
  <div class="markdown" @click="onClick" v-html="html" />
</template>

<style scoped>
.markdown :deep(img) {
  cursor: zoom-in;
  max-width: 100%;
  border-radius: 8px;
}
</style>