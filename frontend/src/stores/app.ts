import { defineStore } from 'pinia'
import { api, ApiError, streamSSE } from '../api/client'
import type {
  Conversation,
  DemoInfo,
  LiveRun,
  MemoryItem,
  Message,
  ProviderConfig,
  ProviderInfo,
  ScreenshotUsage,
} from '../types'

function emptyLive(): LiveRun {
  return {
    running: false,
    content: '',
    reasoning: '',
    planGoal: '',
    plan: [],
    planStepStatus: {},
    nodes: [],
    tools: [],
    notices: [],
    memoryRecall: [],
    memorySaved: [],
    demo: null,
    provider: '',
    providerLabel: '',
    model: '',
    startedAt: 0,
    latency: 0,
  }
}

export interface Toast {
  id: number
  type: 'info' | 'success' | 'error' | 'warning'
  message: string
  hint?: string
}

export const useAppStore = defineStore('app', {
  state: () => ({
    booted: false,
    bootError: '' as string,
    health: null as Record<string, any> | null,

    // 模型
    catalog: [] as ProviderInfo[],
    providers: [] as ProviderConfig[],
    activeProvider: '' as string,
    // 运行时从各供应商 /models 拉到的真实模型列表
    modelsByProvider: {} as Record<
      string,
      { id: string; label: string; vision?: boolean; reasoning?: boolean; note?: string; curated?: boolean }[]
    >,
    modelsMeta: {} as Record<string, { source: string; message: string; count: number }>,
    modelsLoading: '' as string,

    // 会话
    conversations: [] as Conversation[],
    activeId: null as string | null,
    messages: [] as Message[],
    loadingMessages: false,
    /** 全库截图占用（含没挂到会话上的演示记录） */
    screenshotTotal: null as ScreenshotUsage | null,
    screenshotOrphans: null as ScreenshotUsage | null,
    cleaningShots: false,

    // 交互
    mode: 'agent' as 'agent' | 'chat',
    draft: '',
    streaming: false,
    live: emptyLive(),
    abortCtrl: null as AbortController | null,

    panelOpen: true,
    panelTab: 'trace' as 'trace' | 'memory' | 'knowledge' | 'screen',

    settings: null as Record<string, any> | null,
    toasts: [] as Toast[],
    toastSeq: 0,
  }),

  getters: {
    activeConversation(state): Conversation | null {
      return state.conversations.find((c) => c.id === state.activeId) || null
    },
    activeProviderInfo(state): ProviderInfo | null {
      return state.catalog.find((p) => p.id === state.activeProvider) || null
    },
    modelOptions(state): { id: string; label: string; note?: string; vision?: boolean; reasoning?: boolean }[] {
      const info = state.catalog.find((p) => p.id === state.activeProvider)
      if (!info) return []
      return [...info.models, ...info.vision_models].map((m) => ({
        id: m.id,
        label: m.label,
        note: m.note,
        vision: m.vision,
        reasoning: m.reasoning,
      }))
    },
    /** 某供应商的可用模型：优先用服务端拉到的，未拉取时退回内置推荐 */
    modelsFor(state) {
      return (provider: string) => {
        const remote = state.modelsByProvider[provider]
        if (remote && remote.length) return remote
        const info = state.catalog.find((p) => p.id === provider)
        if (!info) return []
        return [...info.models, ...info.vision_models].map((m) => ({ ...m, curated: true }))
      }
    },
    activeConfig(state): ProviderConfig | null {
      return state.providers.find((p) => p.provider === state.activeProvider) || null
    },
    currentModel(state): string {
      // Pinia 的 getter 里拿不到另一个 getter（state 里只有 state），这里自己查一次
      const cfg = state.providers.find((p) => p.provider === state.activeProvider)
      return cfg?.model || ''
    },
    hasMessages(state): boolean {
      return state.messages.length > 0
    },
  },

  actions: {
    // ------------------------------------------------------------------ 启动
    async boot() {
      this.bootError = ''
      try {
        const [health, providers, convs, settings] = await Promise.all([
          api.get<any>('/api/health'),
          api.get<any>('/api/providers'),
          api.get<{
            items: Conversation[]
            screenshot_total?: ScreenshotUsage
            screenshot_orphans?: ScreenshotUsage
          }>('/api/conversations'),
          api.get<any>('/api/settings'),
        ])
        this.health = health
        this.catalog = providers.catalog
        this.providers = providers.configs
        this.activeProvider = providers.active || providers.configs[0]?.provider || ''
        this.conversations = convs.items
        this.screenshotTotal = convs.screenshot_total || null
        this.screenshotOrphans = convs.screenshot_orphans || null
        this.settings = settings
        this.booted = true
        // 后台拉一次模型列表，让顶栏/设置里的候选是最新的
        void this.loadProviderModels(this.activeProvider)
      } catch (e) {
        this.bootError = e instanceof Error ? e.message : String(e)
        this.toast('error', `无法连接后端：${this.bootError}`, '请确认后端已在 127.0.0.1:8000 启动')
      }
    },

    async refreshHealth() {
      try {
        this.health = await api.get('/api/health')
      } catch {
        /* noop */
      }
    },

    // ------------------------------------------------------------------ 模型
    async refreshProviders() {
      const data = await api.get<any>('/api/providers')
      this.catalog = data.catalog
      this.providers = data.configs
      if (data.active) this.activeProvider = data.active
    },

    /**
     * 启用某个供应商。extras 里有 api_key / model 时会一并落库再启用，
     * 避免出现「测试连接成功但没保存」→「设为当前模型却提示未配置 Key」。
     */
    async activateProvider(
      provider: string,
      model?: string,
      extras: { api_key?: string; base_url?: string; model?: string; vision_model?: string } = {},
    ) {
      try {
        const body: Record<string, unknown> = { ...extras }
        if (model) body.model = model
        if (body.api_key !== undefined && !String(body.api_key || '').trim()) delete body.api_key
        await api.post(`/api/providers/${provider}/activate`, Object.keys(body).length ? body : undefined)
        this.activeProvider = provider
        await this.refreshProviders()
        void this.loadProviderModels(provider)
        const cfg = this.providers.find((p) => p.provider === provider)
        this.toast('success', `已切换到 ${cfg?.label || provider}`)
        return true
      } catch (e) {
        this.report(e)
        return false
      }
    },

    async switchModel(model: string) {
      if (!this.activeProvider) return
      try {
        await api.put(`/api/providers/${this.activeProvider}`, { model })
        await this.refreshProviders()
      } catch (e) {
        this.report(e)
      }
    },

    async saveProvider(provider: string, payload: Record<string, unknown>) {
      const saved = await api.put<any>(`/api/providers/${provider}`, payload)
      await this.refreshProviders()
      return saved
    },

    async testProvider(provider: string, payload: Record<string, unknown>) {
      return await api.post<any>(`/api/providers/${provider}/test`, payload)
    },

    /** 拉取某供应商真实可用的模型（opts 里可带还没保存的 Key / Base URL） */
    async loadProviderModels(
      provider: string,
      opts: { refresh?: boolean; apiKey?: string; baseUrl?: string } = {},
    ) {
      if (!provider) return null
      this.modelsLoading = provider
      try {
        const res = await api.post<any>(`/api/providers/${provider}/models`, {
          api_key: opts.apiKey || undefined,
          base_url: opts.baseUrl || undefined,
          refresh: !!opts.refresh,
        })
        this.modelsByProvider[provider] = res.models || []
        this.modelsMeta[provider] = {
          source: res.source,
          message: res.message,
          count: res.count ?? 0,
        }
        return res
      } catch (e) {
        this.report(e)
        return null
      } finally {
        if (this.modelsLoading === provider) this.modelsLoading = ''
      }
    },

    // ------------------------------------------------------------------ 会话
    async loadConversations() {
      const data = await api.get<{
        items: Conversation[]
        screenshot_total?: ScreenshotUsage
        screenshot_orphans?: ScreenshotUsage
      }>('/api/conversations')
      this.conversations = data.items
      this.screenshotTotal = data.screenshot_total || null
      this.screenshotOrphans = data.screenshot_orphans || null
    },

    /** 删掉某个会话的屏幕演示截图（聊天消息和演示文字记录都保留） */
    async clearConversationScreenshots(id: string) {
      if (this.cleaningShots) return
      this.cleaningShots = true
      try {
        const data = await api.del<{ freed_bytes: number; freed_human: string; images: number }>(
          `/api/conversations/${id}/screenshots`,
        )
        await this.loadConversations()
        if (data.freed_bytes > 0) {
          this.toast('success', `已清理 ${data.freed_human}（${data.images} 张截图）`, '演示的文字记录保留')
        } else {
          this.toast('info', '这个会话没有可清理的截图')
        }
      } catch (e) {
        this.report(e)
      } finally {
        this.cleaningShots = false
      }
    },

    /** 删掉没挂到任何会话上的演示截图（直接点「演示」开出来的那些） */
    async clearOrphanScreenshots() {
      if (this.cleaningShots) return
      this.cleaningShots = true
      try {
        const data = await api.del<{ freed_bytes: number; freed_human: string; sessions: number }>(
          '/api/screenshots/orphans',
        )
        await this.loadConversations()
        if (data.freed_bytes > 0) {
          this.toast('success', `已清理 ${data.freed_human}`, `${data.sessions} 个未关联任何对话的演示记录`)
        } else {
          this.toast('info', '没有未关联的演示截图')
        }
      } catch (e) {
        this.report(e)
      } finally {
        this.cleaningShots = false
      }
    },

    newConversation() {
      this.activeId = null
      this.messages = []
      this.live = emptyLive()
    },

    async selectConversation(id: string) {
      if (this.activeId === id) return
      this.activeId = id
      this.live = emptyLive()
      await this.loadMessages(id)
    },

    async loadMessages(id: string) {
      this.loadingMessages = true
      try {
        const data = await api.get<Conversation & { messages: Message[] }>(`/api/conversations/${id}`)
        if (this.activeId === id) {
          this.messages = data.messages
          const idx = this.conversations.findIndex((c) => c.id === id)
          if (idx >= 0) this.conversations[idx] = { ...this.conversations[idx], ...data }
        }
      } catch (e) {
        this.report(e)
      } finally {
        this.loadingMessages = false
      }
    },

    async renameConversation(id: string, title: string) {
      const clean = title.trim()
      if (!clean) return
      try {
        const updated = await api.patch<Conversation>(`/api/conversations/${id}`, { title: clean })
        const idx = this.conversations.findIndex((c) => c.id === id)
        if (idx >= 0) this.conversations[idx] = { ...this.conversations[idx], ...updated }
      } catch (e) {
        this.report(e)
      }
    },

    async deleteConversation(id: string) {
      try {
        const data = await api.del<{ screenshots?: { freed_bytes: number; freed_human: string } }>(
          `/api/conversations/${id}`,
        )
        this.conversations = this.conversations.filter((c) => c.id !== id)
        if (this.activeId === id) {
          this.activeId = null
          this.messages = []
        }
        const freed = data?.screenshots?.freed_bytes || 0
        this.toast(
          'success',
          '会话已删除',
          freed > 0 ? `同时清掉了 ${data.screenshots!.freed_human} 演示截图` : undefined,
        )
        // 截图统计变了，顺手刷新一下侧边栏的占用
        void this.loadConversations().catch(() => undefined)
      } catch (e) {
        this.report(e)
      }
    },

    async clearMessages(id: string) {
      try {
        await api.del(`/api/conversations/${id}/messages`)
        if (this.activeId === id) this.messages = []
        this.toast('success', '已清空当前会话的消息')
      } catch (e) {
        this.report(e)
      }
    },

    // ------------------------------------------------------------------ 发送
    async send(content: string, attachments: Message['attachments'] = []) {
      const text = content.trim()
      if (this.streaming || (!text && attachments.length === 0)) return

      this.streaming = true
      this.live = emptyLive()
      this.live.running = true
      this.live.startedAt = Date.now()
      this.live.provider = this.activeProvider
      this.live.providerLabel = this.activeProviderInfo?.label || ''

      this.messages.push({
        id: -Date.now(),
        role: 'user',
        content: text,
        attachments,
        plan: [],
        demo: null,
        tool_calls: [],
        created_at: new Date().toISOString(),
        pending: true,
      })

      const ctrl = new AbortController()
      this.abortCtrl = ctrl
      let failed = ''
      try {
        await streamSSE(
          '/api/chat',
          {
            conversation_id: this.activeId,
            content: text,
            attachments,
            mode: this.mode,
            provider: this.activeProvider || undefined,
          },
          (event) => this.handleEvent(event),
          ctrl.signal,
        )
        failed = this.live.notices.find((n) => n.level === 'error')?.message || ''
      } catch (e) {
        if ((e as Error).name === 'AbortError') {
          this.toast('warning', '已停止生成')
        } else {
          failed = e instanceof Error ? e.message : String(e)
          this.toast('error', failed, e instanceof ApiError ? e.hint : undefined)
        }
      } finally {
        const wasRunning = this.live.running
        this.streaming = false
        this.abortCtrl = null
        this.live.running = false
        if (this.activeId) {
          await this.loadMessages(this.activeId)
        }
        await this.loadConversations().catch(() => {})
        if (failed) {
          this.live.notices.push({ level: 'error', message: failed })
        }
        if (wasRunning) this.refreshHealth().catch(() => {})
      }
    },

    stop() {
      this.abortCtrl?.abort()
      this.abortCtrl = null
    },

    handleEvent(event: Record<string, any>) {
      switch (event.type) {
        case 'start': {
          this.activeId = event.conversation_id
          this.live.provider = event.provider
          this.live.providerLabel = event.provider_label || event.provider
          this.live.model = event.model
          const existing = this.conversations.find((c) => c.id === event.conversation_id)
          if (!existing) {
            this.conversations.unshift({
              id: event.conversation_id,
              title: event.title,
              message_count: 1,
              pinned: false,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            })
          } else if (event.title) {
            existing.title = event.title
          }
          break
        }
        case 'node': {
          const label = event.label || event.node
          const idx = this.live.nodes.findIndex((n) => n.node === event.node && n.status === 'running')
          if (event.status === 'running') {
            this.live.nodes.push({ node: event.node, label, status: 'running', at: Date.now() })
          } else if (idx >= 0) {
            this.live.nodes[idx].status = 'done'
          } else {
            // 后端 done 事件不带 label 时，保留已有的中文标签
            const doneIdx = [...this.live.nodes].reverse().findIndex((n) => n.node === event.node)
            if (doneIdx >= 0) {
              const real = this.live.nodes.length - 1 - doneIdx
              if (event.label) this.live.nodes[real].label = event.label
              this.live.nodes[real].status = 'done'
            }
          }
          break
        }
        case 'plan': {
          this.live.plan = event.steps || []
          this.live.planGoal = event.goal || ''
          this.live.planStepStatus = {}
          break
        }
        case 'plan_step': {
          this.live.planStepStatus[event.index] = event.status
          break
        }
        case 'tool_start': {
          this.live.tools.push({
            callId: event.call_id || `${event.name}-${Date.now()}`,
            name: event.name,
            label: event.label || event.name,
            args: event.args || {},
            status: 'running',
          })
          break
        }
        case 'tool_end': {
          const tool =
            this.live.tools.find((t) => t.callId === event.call_id) ||
            [...this.live.tools].reverse().find((t) => t.name === event.name && t.status === 'running')
          if (tool) {
            tool.status = event.ok ? 'ok' : 'error'
            tool.preview = event.preview
            tool.error = event.error
            tool.elapsed = event.elapsed_ms
          }
          break
        }
        case 'thought': {
          this.live.reasoning += event.text || ''
          break
        }
        case 'token': {
          this.live.content += event.text || ''
          break
        }
        case 'notice': {
          this.live.notices.push({ level: event.level || 'info', message: event.message })
          if (event.level === 'error') this.toast('error', event.message)
          break
        }
        case 'memory_recall': {
          this.live.memoryRecall = event.items || []
          break
        }
        case 'memory_saved': {
          this.live.memorySaved = [...this.live.memorySaved, ...(event.items || [])]
          break
        }
        case 'demo': {
          this.live.demo = event as DemoInfo
          break
        }
        case 'done': {
          this.live.running = false
          this.live.latency = event.latency_ms || Date.now() - this.live.startedAt
          if (event.conversation_id) this.activeId = event.conversation_id
          break
        }
        case 'error': {
          this.live.running = false
          this.live.notices.push({ level: 'error', message: event.message })
          this.toast('error', event.message, event.hint)
          break
        }
        default:
          break
      }
    },

    // ------------------------------------------------------------------ 交互
    togglePanel(tab?: typeof this.panelTab) {
      if (tab) {
        this.panelTab = tab
        this.panelOpen = true
      } else {
        this.panelOpen = !this.panelOpen
      }
    },

    toast(type: Toast['type'], message: string, hint?: string) {
      const id = ++this.toastSeq
      this.toasts.push({ id, type, message, hint })
      setTimeout(() => this.dismissToast(id), 4600)
    },

    dismissToast(id: number) {
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },

    report(e: unknown) {
      if (e instanceof ApiError) {
        this.toast('error', e.message, e.hint)
      } else {
        this.toast('error', e instanceof Error ? e.message : String(e))
      }
    },
  },
})