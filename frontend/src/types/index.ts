export interface ScreenshotUsage {
  bytes: number
  images: number
  sessions: number
  shared: number
  human: string
}

export interface Conversation {
  id: string
  title: string
  provider?: string | null
  model?: string | null
  summary?: string | null
  message_count: number
  pinned: boolean
  created_at: string
  updated_at: string
  /** 该会话的屏幕演示截图占用（后端统计，sessions = 演示会话数） */
  screenshot?: ScreenshotUsage
}

export interface Attachment {
  url: string
  path: string
  name: string
  mime: string
  size: number
}

export interface PlanStep {
  title: string
  detail?: string
  tool?: string | null
}

export interface ToolCall {
  name: string
  args?: Record<string, unknown>
  ok?: boolean
  error?: string | null
}

export interface DemoInfo {
  available: boolean
  goal: string
  steps: string[]
  reason: string
  source: 'tool' | 'heuristic' | 'none'
  score: number
  signals?: Record<string, unknown>
}

export interface Message {
  id: number
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  reasoning?: string | null
  attachments: Attachment[]
  plan: PlanStep[]
  demo?: DemoInfo | null
  tool_calls: ToolCall[]
  tool_results?: unknown[]
  provider?: string | null
  model?: string | null
  tokens?: number
  latency_ms?: number
  error?: string | null
  created_at: string
  pending?: boolean
}

export interface ModelInfo {
  id: string
  label: string
  vision: boolean
  reasoning: boolean
  note: string
}

export interface ProviderInfo {
  id: string
  label: string
  base_url: string
  needs_key: boolean
  local: boolean
  doc: string
  embedding_model?: string | null
  models: ModelInfo[]
  vision_models: ModelInfo[]
}

export interface ProviderConfig {
  provider: string
  label: string
  configured: boolean
  has_key: boolean
  api_key_mask: string
  base_url: string
  model: string
  vision_model: string
  is_active: boolean
  needs_key: boolean
  updated_at?: string | null
}

export interface MemoryItem {
  id: number
  kind: string
  content: string
  tags?: string | null
  importance: number
  access_count: number
  indexed: boolean
  source_conversation?: string | null
  created_at: string
  score?: number
}

export interface KnowledgeDoc {
  id: number
  title: string
  source?: string | null
  tags?: string | null
  char_count: number
  chunk_count: number
  preview: string
  created_at: string
}

export interface ToolItem {
  callId: string
  name: string
  label: string
  args: Record<string, unknown>
  status: 'running' | 'ok' | 'error'
  preview?: string
  error?: string | null
  elapsed?: number
}

export interface NodeItem {
  node: string
  label: string
  status: 'running' | 'done'
  at: number
}

export interface LiveRun {
  running: boolean
  content: string
  reasoning: string
  planGoal: string
  plan: PlanStep[]
  planStepStatus: Record<number, 'running' | 'done' | 'failed'>
  nodes: NodeItem[]
  tools: ToolItem[]
  notices: { level: string; message: string }[]
  memoryRecall: MemoryItem[]
  memorySaved: MemoryItem[]
  demo: DemoInfo | null
  provider: string
  providerLabel: string
  model: string
  startedAt: number
  latency: number
}

export interface ScreenSession {
  id: string
  conversation_id?: string | null
  goal: string
  plan: string[]
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed'
  interval_ms: number
  max_steps: number
  current_step: number
  dry_run: boolean
  last_error?: string | null
  created_at?: string | null
  gui_available?: boolean
  steps_log?: ScreenStepLog[]
}

export interface ScreenStepLog {
  id: number
  idx: number
  thought?: string | null
  action?: Record<string, unknown> | null
  status: string
  detail?: string | null
  screenshot?: string | null
  created_at?: string | null
}