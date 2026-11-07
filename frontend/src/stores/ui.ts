import { defineStore } from 'pinia'
import type { DemoInfo } from '../types'

export type ThemeMode = 'light' | 'dark' | 'auto'
export type BgKind = 'none' | 'image' | 'video'

/** 图片放大预览的载荷 */
export interface LightboxImage {
  url: string
  name?: string
}

export interface BackgroundState {
  kind: BgKind
  url: string
  /** 媒体本身的高斯模糊，px */
  blur: number
  /** 压暗/压亮的遮罩强度，0~0.8 */
  dim: number
  /** 背景画面自身的不透明度 0~1 */
  mediaOpacity: number
  /** 左栏（会话列表）不透明度，0~0.95 */
  leftAlpha: number
  /** 右栏（智能体面板）不透明度，0~0.95 */
  rightAlpha: number
}

const STORAGE_KEY = 'cm-theme'
const BG_KEY = 'cm-bg'

const DEFAULT_BG: BackgroundState = {
  kind: 'none',
  url: '',
  blur: 14,
  dim: 0.5,
  mediaOpacity: 1,
  leftAlpha: 0.45,
  rightAlpha: 0.62,
}

function prefersLight(): boolean {
  return window.matchMedia('(prefers-color-scheme: light)').matches
}

function loadBackground(): BackgroundState {
  try {
    const raw = localStorage.getItem(BG_KEY)
    if (!raw) return { ...DEFAULT_BG }
    const parsed = JSON.parse(raw) as Partial<BackgroundState>
    const kind: BgKind =
      parsed.kind === 'image' || parsed.kind === 'video' ? parsed.kind : 'none'
    return {
      kind,
      url: typeof parsed.url === 'string' ? parsed.url : '',
      blur: typeof parsed.blur === 'number' ? parsed.blur : DEFAULT_BG.blur,
      dim: typeof parsed.dim === 'number' ? parsed.dim : DEFAULT_BG.dim,
      mediaOpacity:
        typeof parsed.mediaOpacity === 'number' ? parsed.mediaOpacity : DEFAULT_BG.mediaOpacity,
      leftAlpha:
        typeof parsed.leftAlpha === 'number'
          ? parsed.leftAlpha
          : typeof (parsed as any).panelAlpha === 'number'
            ? (parsed as any).panelAlpha
            : DEFAULT_BG.leftAlpha,
      rightAlpha:
        typeof parsed.rightAlpha === 'number'
          ? parsed.rightAlpha
          : typeof (parsed as any).panelAlpha === 'number'
            ? (parsed as any).panelAlpha
            : DEFAULT_BG.rightAlpha,
    }
  } catch {
    return { ...DEFAULT_BG }
  }
}

export const useUiStore = defineStore('ui', {
  state: () => ({
    settingsOpen: false,
    screenOpen: false,
    screenDemo: null as DemoInfo | null,
    screenConversationId: null as string | null,
    knowledgeOpen: false,

    // 外观：light / dark / auto（跟随系统，首次访问默认 auto）
    theme: 'auto' as ThemeMode,
    themeResolved: 'dark' as 'light' | 'dark',
    themeListenerBound: false,

    // 自定义背景：图片或循环视频
    background: { ...DEFAULT_BG } as BackgroundState,

    // 图片放大预览（null = 关着）
    lightbox: null as LightboxImage | null,
  }),

  getters: {
    isLight(state): boolean {
      return state.themeResolved === 'light'
    },
    /** 是否启用了自定义背景（决定面板是否走半透明模式） */
    hasBackground(state): boolean {
      return state.background.kind !== 'none' && !!state.background.url
    },
  },

  actions: {
    openSettings() {
      this.settingsOpen = true
    },
    closeSettings() {
      this.settingsOpen = false
    },
    openScreen(demo: DemoInfo | null, conversationId: string | null = null) {
      this.screenDemo = demo
      this.screenConversationId = conversationId
      this.screenOpen = true
    },
    closeScreen() {
      this.screenOpen = false
    },

    /** 打开图片放大预览 */
    openLightbox(url: string, name = '') {
      if (!url) return
      this.lightbox = { url, name }
    },
    closeLightbox() {
      this.lightbox = null
    },

    // ------------------------------------------------------------------ 主题
    initTheme() {
      const saved = localStorage.getItem(STORAGE_KEY)
      this.theme = saved === 'light' || saved === 'dark' || saved === 'auto' ? saved : 'auto'
      this.applyTheme()

      this.background = loadBackground()
      this.applyBackground()

      if (!this.themeListenerBound) {
        const mq = window.matchMedia('(prefers-color-scheme: light)')
        const onChange = () => {
          if (this.theme === 'auto') this.applyTheme()
        }
        if (mq.addEventListener) mq.addEventListener('change', onChange)
        else mq.addListener(onChange)
        this.themeListenerBound = true
      }
    },

    setTheme(mode: ThemeMode) {
      this.theme = mode
      localStorage.setItem(STORAGE_KEY, mode)
      this.applyTheme()
    },

    applyTheme() {
      const resolved: 'light' | 'dark' =
        this.theme === 'auto' ? (prefersLight() ? 'light' : 'dark') : this.theme
      this.themeResolved = resolved
      document.documentElement.dataset.theme = resolved
      document.documentElement.style.colorScheme = resolved
    },

    /** 一键在浅色 / 深色之间切换（跟随系统时按当前实际效果切换） */
    toggleTheme() {
      this.setTheme(this.themeResolved === 'dark' ? 'light' : 'dark')
    },

    // ------------------------------------------------------------------ 背景
    setBackground(patch: Partial<BackgroundState>) {
      this.background = { ...this.background, ...patch }
      if (!this.background.url) this.background.kind = 'none'
      localStorage.setItem(BG_KEY, JSON.stringify(this.background))
      this.applyBackground()
    },

    clearBackground() {
      this.background = { ...DEFAULT_BG }
      localStorage.removeItem(BG_KEY)
      this.applyBackground()
    },

    applyBackground() {
      const active = this.hasBackground
      const root = document.documentElement
      root.dataset.bg = active ? 'on' : ''
      root.style.setProperty('--bg-media-blur', `${this.background.blur}px`)
      root.style.setProperty('--bg-media-dim', String(this.background.dim))
      root.style.setProperty('--bg-media-opacity', String(this.background.mediaOpacity))
      root.style.setProperty('--panel-alpha-left', String(this.background.leftAlpha))
      root.style.setProperty('--panel-alpha-right', String(this.background.rightAlpha))
    },
  },
})