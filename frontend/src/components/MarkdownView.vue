<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{ content: string }>()
const html = computed(() => renderMarkdown(props.content))

async function onClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!target?.classList?.contains('code-copy')) return
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
}
</script>

<template>
  <div class="markdown" @click="onClick" v-html="html" />
</template>