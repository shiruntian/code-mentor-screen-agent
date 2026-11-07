import { defineStore } from 'pinia'
import { api, subscribeScreen } from '../api/client'
import type { DemoInfo, ScreenSession, ScreenStepLog } from '../types'
import { useAppStore } from './app'

export interface ScreenEvent {
  type: string
  message?: string
  step?: number
  thought?: string
  action?: Record<string, unknown>
  detail?: string
  ok?: boolean
  screenshot?: string
  status?: string
}

export const useScreenStore = defineStore('screen', {
  state: () => ({
    session: null as ScreenSession | null,
    latestShot: '' as string,
    events: [] as ScreenEvent[],
    logs: [] as ScreenStepLog[],
    busy: false,
    error: '' as string,
    unsubscribe: null as null | (() => void),
  }),

  getters: {
    status(state): string {
      return state.session?.status || 'idle'
    },
    isRunning(): boolean {
      return this.status === 'running'
    },
    isPaused(): boolean {
      return this.status === 'paused'
    },
  },

  actions: {
    async create(demo: DemoInfo | null, conversationId: string | null, opts: { interval?: number; dryRun?: boolean } = {}) {
      this.busy = true
      this.error = ''
      try {
        const app = useAppStore()
        const session = await api.post<ScreenSession>('/api/screen/sessions', {
          conversation_id: conversationId,
          goal: demo?.goal || '跟着助手完成一次编程实操',
          steps: demo?.steps || [],
          interval_ms: opts.interval ?? app.settings?.runtime?.screen_interval_ms ?? 3000,
          dry_run: opts.dryRun ?? false,
        })
        this.session = session
        this.logs = []
        this.events = []
        this.latestShot = ''
        this.connect(session.id)
        return session
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e)
        throw e
      } finally {
        this.busy = false
      }
    },

    connect(sessionId: string) {
      this.disconnect()
      this.unsubscribe = subscribeScreen(sessionId, (event) => this.handleEvent(event as ScreenEvent))
    },

    disconnect() {
      this.unsubscribe?.()
      this.unsubscribe = null
    },

    handleEvent(event: ScreenEvent) {
      this.events.push(event)
      if (this.events.length > 200) this.events.splice(0, this.events.length - 200)
      switch (event.type) {
        case 'created':
        case 'status':
        case 'done':
        case 'error': {
          if (this.session) {
            this.session.status = (event.status as ScreenSession['status']) || this.session.status
          }
          if (event.type === 'error' && event.message) this.error = event.message
          break
        }
        case 'screenshot': {
          if (event.screenshot || event.url) this.latestShot = event.screenshot || (event as any).url
          break
        }
        case 'step': {
          if (event.screenshot) this.latestShot = event.screenshot
          this.logs.push({
            id: Date.now(),
            idx: event.step || this.logs.length + 1,
            thought: event.thought,
            action: event.action,
            status: event.ok ? 'done' : 'failed',
            detail: event.detail,
            screenshot: event.screenshot,
          })
          if (this.session) this.session.current_step = event.step || this.session.current_step
          break
        }
        default:
          break
      }
    },

    async start() {
      if (!this.session) return
      this.busy = true
      try {
        this.session = await api.post<ScreenSession>(`/api/screen/sessions/${this.session.id}/start`)
      } catch (e) {
        useAppStore().report(e)
      } finally {
        this.busy = false
      }
    },

    async pause() {
      if (!this.session) return
      try {
        this.session = await api.post<ScreenSession>(`/api/screen/sessions/${this.session.id}/pause`)
      } catch (e) {
        useAppStore().report(e)
      }
    },

    async resume() {
      if (!this.session) return
      try {
        this.session = await api.post<ScreenSession>(`/api/screen/sessions/${this.session.id}/resume`)
      } catch (e) {
        useAppStore().report(e)
      }
    },

    async stop() {
      if (!this.session) return
      try {
        this.session = await api.post<ScreenSession>(`/api/screen/sessions/${this.session.id}/stop`)
      } catch (e) {
        useAppStore().report(e)
      }
    },

    async setInterval(ms: number) {
      if (!this.session) return
      try {
        this.session = await api.patch<ScreenSession>(`/api/screen/sessions/${this.session.id}/interval`, {
          interval_ms: ms,
        })
      } catch (e) {
        useAppStore().report(e)
      }
    },

    async refresh() {
      if (!this.session) return
      try {
        this.session = await api.get<ScreenSession>(`/api/screen/sessions/${this.session.id}`)
        this.logs = this.session.steps_log || []
        const last = [...this.logs].reverse().find((l) => l.screenshot)
        if (last?.screenshot) this.latestShot = last.screenshot
      } catch {
        /* noop */
      }
    },

    reset() {
      this.disconnect()
      this.session = null
      this.latestShot = ''
      this.events = []
      this.logs = []
      this.error = ''
    },
  },
})