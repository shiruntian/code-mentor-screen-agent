<script setup lang="ts">
import { computed } from 'vue'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()

const url = computed(() => ui.background.url)
const isVideo = computed(() => ui.background.kind === 'video')
</script>

<template>
  <div v-if="ui.hasBackground" class="bg-layer" aria-hidden="true">
    <video
      v-if="isVideo"
      :key="url"
      class="bg-media"
      :src="url"
      autoplay
      loop
      muted
      playsinline
      preload="auto"
    />
    <img v-else :key="url" class="bg-media" :src="url" alt="" />
    <div class="bg-scrim" />
  </div>
</template>

<style scoped>
.bg-layer {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
  background: var(--bg-0);
}

.bg-media {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* 稍微放大，避免模糊后边缘露出底色 */
  transform: scale(1.06);
  filter: blur(var(--bg-media-blur, 12px)) saturate(115%);
  opacity: var(--bg-media-opacity, 1);
}

.bg-scrim {
  position: absolute;
  inset: 0;
  background: rgba(4, 8, 18, var(--bg-media-dim, 0.38));
}

html[data-theme='light'] .bg-scrim {
  background: rgba(248, 250, 253, var(--bg-media-dim, 0.38));
}
</style>