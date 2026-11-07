<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { applyAppearance, readAppearance } from '../styles/appearance'
import { useAppStore } from '../stores/app'
import { useUiStore } from '../stores/ui'

const app = useAppStore()
const ui = useUiStore()

const tab = ref<'providers' | 'appearance' | 'runtime' | 'editors' | 'env' | 'about'>('providers')
const selected = ref<string>(app.activeProvider || 'deepseek')
const form = reactive({
  api_key: '',
  base_url: '',
  model: '',
  vision_model: '',
})
const saving = ref(false)
const testing = ref(false)
const testResult = ref<{ ok: boolean; message: string } | null>(null)
const ollamaModels = ref<string[]>([])
const scanning = ref(false)

const rt = () => app.settings?.runtime || {}
const runtime = reactive({
  agent_max_iterations: rt().agent_max_iterations ?? 6,
  screen_interval_ms: rt().screen_interval_ms ?? 5000,
  screen_max_steps: rt().screen_max_steps ?? 40,
  screen_dry_run: rt().screen_dry_run ?? false,
  short_term_window: rt().short_term_window ?? 12,
  screen_ime_guard: rt().screen_ime_guard ?? true,
  screen_type_mode: rt().screen_type_mode ?? 'clipboard',
  agent_tool_rounds: rt().agent_tool_rounds ?? 1,
  agent_budget_s: rt().agent_budget_s ?? 90,
  agent_fast_lane: rt().agent_fast_lane ?? true,
  planner_max_tokens: rt().planner_max_tokens ?? 500,
  llm_disable_thinking: rt().llm_disable_thinking ?? false,
  agent_screen_tool: rt().agent_screen_tool ?? true,
  agent_fs_tool: rt().agent_fs_tool ?? true,
  fs_roots: rt().fs_roots ?? '',
  fs_max_entries: rt().fs_max_entries ?? 200,
  fs_allow_all_drives: rt().fs_allow_all_drives ?? true,
  fs_search_budget_s: rt().fs_search_budget_s ?? 8,
  screen_retro: rt().screen_retro ?? true,
  screen_share_chat_model: rt().screen_share_chat_model ?? false,
  screen_model_override: rt().screen_model_override ?? '',
  screen_mode: rt().screen_mode ?? 'demo',
  env_download_dir: rt().env_download_dir ?? 'D:/Downloads/setup',
  env_install_root: rt().env_install_root ?? 'D:/DevEnv',
  editor_install_root: rt().editor_install_root ?? 'D:/DevEnv/editors',
  screen_capture_ms: rt().screen_capture_ms ?? 200,
  screen_skip_unchanged: rt().screen_skip_unchanged ?? true,
  screen_image_max_width: rt().screen_image_max_width ?? 1568,
  screen_image_quality: rt().screen_image_quality ?? 85,
  screen_zoom_max: rt().screen_zoom_max ?? 3,
  screen_panic_hotkey: rt().screen_panic_hotkey ?? 'ctrl+alt+shift+f12',
  screen_panic_enabled: rt().screen_panic_enabled ?? true,
})
const runtimeSaved = ref(false)

// ------------------------------------------------------------------ 背景
const bgInput = ref<HTMLInputElement | null>(null)
const bgUploading = ref(false)
const library = ref<any[]>([])
const previewSize = ref<'thumb' | 'large'>('thumb')

async function loadLibrary() {
  try {
    const res = await api.get<any>('/api/backgrounds')
    library.value = res.items || []
  } catch {
    library.value = []
  }
}

function applyLibraryItem(item: any) {
  ui.setBackground({ kind: item.kind === 'video' ? 'video' : 'image', url: item.url })
}

async function deleteLibraryItem(item: any, e: Event) {
  e.stopPropagation()
  try {
    await api.del(`/api/backgrounds/${item.name}`)
    if (ui.background.url === item.url) ui.clearBackground()
    await loadLibrary()
  } catch (err) {
    app.report(err)
  }
}

/** 预览用：和在页面上看到的效果一致（模糊 + 遮罩 + 画面不透明度） */
const previewStyle = computed(() => ({
  filter: `blur(${Math.min(ui.background.blur, 20)}px) saturate(115%)`,
  opacity: ui.background.mediaOpacity,
}))
const previewScrim = computed(() => {
  const d = ui.background.dim
  return ui.themeResolved === 'light'
    ? `rgba(248, 250, 253, ${d})`
    : `rgba(4, 8, 18, ${d})`
})

function pickBgType(kind: 'image' | 'video') {
  if (ui.background.kind === kind) return
  if (!ui.background.url) {
    app.toast('info', kind === 'video' ? '先选一个视频文件或填 URL' : '先选一张图片或填 URL')
    bgInput.value?.click()
    return
  }
  ui.setBackground({ kind })
}

async function onBgFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  bgUploading.value = true
  try {
    const res = await api.uploadBackground<any>(file)
    ui.setBackground({ kind: res.kind === 'video' ? 'video' : 'image', url: res.url })
    app.toast('success', res.kind === 'video' ? '视频背景已启用' : '图片背景已启用')
    await loadLibrary()
  } catch (err) {
    app.report(err)
  } finally {
    bgUploading.value = false
    input.value = ''
  }
}

function onBgUrl(e: Event) {
  const url = (e.target as HTMLInputElement).value.trim()
  if (!url) return
  const isVideo = /\.(mp4|webm)(\?.*)?$/i.test(url)
  ui.setBackground({ url, kind: isVideo ? 'video' : 'image' })
}

function onBgBlur(e: Event) {
  ui.setBackground({ blur: Number((e.target as HTMLInputElement).value) })
}

function onBgDim(e: Event) {
  ui.setBackground({ dim: Number((e.target as HTMLInputElement).value) / 100 })
}

function onLeftAlpha(e: Event) {
  ui.setBackground({ leftAlpha: Number((e.target as HTMLInputElement).value) / 100 })
}

function onRightAlpha(e: Event) {
  ui.setBackground({ rightAlpha: Number((e.target as HTMLInputElement).value) / 100 })
}

function onMediaOpacity(e: Event) {
  ui.setBackground({ mediaOpacity: Number((e.target as HTMLInputElement).value) / 100 })
}

const info = computed(() => app.catalog.find((p) => p.id === selected.value) || null)
const config = computed(() => app.providers.find((p) => p.provider === selected.value) || null)
const isActive = computed(() => config.value?.is_active === true)
/** 表单里是否有还没落库的改动（尤其是刚输入的 Key） */
const dirty = computed(() => {
  if (form.api_key.trim()) return true
  const c = config.value
  if (!c) return false
  return (
    (form.base_url || '') !== (c.base_url || '') ||
    (form.model || '') !== (c.model || '') ||
    (form.vision_model || '') !== (c.vision_model || '')
  )
})

const modelOptions = computed(() => app.modelsFor(selected.value) || [])
const modelsMeta = computed(() => app.modelsMeta[selected.value] || null)

function syncForm() {
  form.api_key = ''
  form.base_url = config.value?.base_url || info.value?.base_url || ''
  form.model = config.value?.model || modelOptions.value[0]?.id || ''
  form.vision_model = config.value?.vision_model || info.value?.vision_models[0]?.id || ''
  testResult.value = null
}

watch(selected, () => {
  syncForm()
  void app.loadProviderModels(selected.value)
})
onMounted(() => {
  syncForm()
  void app.loadProviderModels(selected.value)
  loadLibrary()
})

/** 拉取该供应商真实可用的模型（会带上还没保存的 Key / URL） */
async function refreshModels() {
  const res = await app.loadProviderModels(selected.value, {
    refresh: true,
    apiKey: form.api_key.trim() || undefined,
    baseUrl: form.base_url || undefined,
  })
  if (res) app.toast(res.source === 'remote' ? 'success' : 'warning', res.message)
}

/** 选到多模态模型时，自动把它填成视觉模型 */
function onModelInput() {
  const found = modelOptions.value.find((m) => m.id === form.model)
  if (found?.vision && !form.vision_model) form.vision_model = form.model
}

async function save(): Promise<boolean> {
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      base_url: form.base_url,
      model: form.model,
      vision_model: form.vision_model || null,
    }
    if (form.api_key.trim()) payload.api_key = form.api_key.trim()
    await app.saveProvider(selected.value, payload)
    form.api_key = ''
    form.base_url = config.value?.base_url || form.base_url
    form.model = config.value?.model || form.model
    form.vision_model = config.value?.vision_model || ''
    testResult.value = null
    app.toast('success', `${info.value?.label} 配置已保存到本地`)
    return true
  } catch (e) {
    app.report(e)
    return false
  } finally {
    saving.value = false
  }
}

/** 一步搞定：把当前表单（含刚输入的 Key）一起提交并启用，杜绝「测试成功但没保存」 */
async function saveAndActivate() {
  saving.value = true
  try {
    const ok = await app.activateProvider(selected.value, undefined, {
      api_key: form.api_key.trim() || undefined,
      base_url: form.base_url || undefined,
      model: form.model || undefined,
      vision_model: form.vision_model || undefined,
    })
    if (ok) {
      form.api_key = ''
      testResult.value = null
      await app.refreshProviders()
    }
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  testResult.value = null
  try {
    const res = await app.testProvider(selected.value, {
      api_key: form.api_key.trim() || undefined,
      base_url: form.base_url,
      model: form.model,
    })
    testResult.value = res
    if (res.models?.length) ollamaModels.value = res.models
    // 测试通过且输入框里有新 Key：顺手保存，避免用户以为已经存好了
    if (res.ok && form.api_key.trim()) {
      const saved = await save()
      if (saved) testResult.value = { ok: true, message: `${res.message}（配置已保存）` }
    }
  } catch (e) {
    testResult.value = { ok: false, message: e instanceof Error ? e.message : String(e) }
  } finally {
    testing.value = false
  }
}

async function clearKey() {
  if (!window.confirm('确定清除已保存的 API Key 吗？')) return
  try {
    await api.del(`/api/providers/${selected.value}/key`)
    await app.refreshProviders()
    form.api_key = ''
    app.toast('success', 'Key 已清除')
  } catch (e) {
    app.report(e)
  }
}

async function scanOllama() {
  scanning.value = true
  try {
    const res = await api.get<{ models: string[]; ok: boolean }>('/api/providers/ollama/models')
    ollamaModels.value = res.models
    if (!res.models.length) {
      app.toast('warning', '未探测到 Ollama 模型', '先运行 ollama pull qwen2.5:7b')
    }
  } catch (e) {
    app.report(e)
  } finally {
    scanning.value = false
  }
}

async function saveRuntime() {
  try {
    const res = await api.put<any>('/api/settings', runtime)
    app.settings = { ...(app.settings || {}), runtime: res.runtime }
    runtimeSaved.value = true
    setTimeout(() => (runtimeSaved.value = false), 1800)
    app.toast('success', '运行参数已保存')
  } catch (e) {
    app.report(e)
  }
}


// ---------------- 风格：主题色 / 代码高亮 / 字体 ----------------
const accent = ref(localStorage.getItem('cm-accent') || 'indigo')
const codeTheme = ref(localStorage.getItem('cm-code-theme') || 'auto')
const fontFamily = ref(localStorage.getItem('cm-font') || 'system')
const animOn = ref(readAppearance().anim)

function toggleAnim() {
  applyAppearance({ anim: animOn.value })
}

function applyAccent() {
  applyAppearance({ accent: accent.value })
  app.toast('success', '主题色已保存')
}

function applyCodeTheme() {
  applyAppearance({ codeTheme: codeTheme.value })
  app.toast('success', '代码高亮已切换')
}

function applyFont() {
  applyAppearance({ font: fontFamily.value })
  app.toast('success', '字体已应用')
}

// ---------------- 环境检测 / 一键安装 ----------------
interface EnvItem {
  id: string; name: string; kind: string; desc: string
  installed: boolean; path: string; version: string
  recommend: { version?: string; install?: string; url?: string; zip_url?: string; subdir?: string }
  note?: string
  auto_install: boolean
  install_kind: 'winget' | 'zip' | ''
  manual_cmd: string
}

type InstallStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled'
type StageKey = 'prepare' | 'download' | 'install' | 'extract' | 'path' | 'verify' | 'done'

interface EnvJob {
  id: string
  tool_id: string
  tool_name: string
  kind: string
  command: string
  status: InstallStatus
  stage: StageKey
  exit_code: number | null
  add_path: boolean
  install_dir: string
  elapsed_s: number
  since: number
  total: number
  log: string[]
  result: {
    installed?: boolean
    version?: string
    path?: string
    path_dirs?: string[]
    hint?: string
  }
}

const envItems = ref<EnvItem[]>([])
const envLoading = ref(false)
const envSummary = ref({ total: 0, installed: 0, missing: 0 })
const envWinget = ref(true)
const envInstallRoot = ref('')
const pathsOpen = ref(false)

/** 二次确认单独弹窗（不再挤在卡片里），为空表示没开 */
const confirmTool = ref<EnvItem | null>(null)
/** 手动安装弹窗：官网链接 + 命令（可复制 / 可运行） */
const manualTool = ref<EnvItem | null>(null)
/** 弹窗里的勾选项：默认勾上（装完直接能用是最省心的默认值） */
const installAddPath = ref(true)

const job = ref<EnvJob | null>(null)
const jobLog = ref<string[]>([])
const jobSince = ref(0)
const jobLogEl = ref<HTMLElement | null>(null)
const jobPanelEl = ref<HTMLElement | null>(null)
/** 详细日志默认收起：进度用阶段条 + 一行小字表达 */
const showLog = ref(false)
/** 点了取消但后台还没停（下载线程要等下一个数据块才会发现）：按钮先给个反馈 */
const canceling = ref(false)
let jobTimer: number | undefined

const jobBusy = computed(
  () => !!job.value && (job.value.status === 'pending' || job.value.status === 'running'),
)
const JOB_STATUS: Record<InstallStatus, string> = {
  pending: '排队中',
  running: '安装中',
  succeeded: '安装成功',
  failed: '安装失败',
  canceled: '已取消',
}

/** 阶段计划：权重决定进度条各段占比（winget 装完才落地，zip 能边下边涨） */
interface StageDef { key: StageKey; label: string; weight: number }
const STAGE_PLANS: Record<string, StageDef[]> = {
  zip: [
    { key: 'prepare', label: '准备', weight: 6 },
    { key: 'download', label: '下载', weight: 50 },
    { key: 'extract', label: '解压', weight: 14 },
    { key: 'path', label: 'PATH', weight: 20 },
    { key: 'verify', label: '验证', weight: 10 },
  ],
  winget: [
    { key: 'prepare', label: '准备', weight: 6 },
    { key: 'install', label: '安装', weight: 70 },
    { key: 'path', label: 'PATH', weight: 14 },
    { key: 'verify', label: '验证', weight: 10 },
  ],
}

/** 下载阶段从日志里读百分比，让进度条真的在动 */
function downloadPercent(current: EnvJob): number {
  const source = jobLog.value.length ? jobLog.value : current.log || []
  for (let i = source.length - 1; i >= 0; i--) {
    const m = /下载进度\s*(\d+)%/.exec(source[i])
    if (m) return Math.min(100, Number(m[1]))
  }
  return 0
}

const jobPlan = computed<StageDef[]>(() => STAGE_PLANS[job.value?.kind || 'winget'] || STAGE_PLANS.winget)

const jobProgress = computed(() => {
  const current = job.value
  const plan = jobPlan.value
  const totalWeight = plan.reduce((n, s) => n + s.weight, 0)
  if (!current) {
    return { percent: 0, segments: [] as { key: StageKey; label: string; fill: number; state: string }[], caption: '' }
  }
  const finished = current.status === 'succeeded'
  let index = plan.findIndex((s) => s.key === current.stage)
  if (finished) index = plan.length
  if (index < 0) index = 0

  const passed = plan.slice(0, index).reduce((n, s) => n + s.weight, 0)
  const stageWeight = plan[index]?.weight || 0
  let sub = 0
  if (!finished && (plan[index]?.key === 'download' || plan[index]?.key === 'install')) {
    sub = downloadPercent(current) / 100
  }
  const filled = finished ? totalWeight : passed + stageWeight * sub
  const percent = Math.max(0, Math.min(100, Math.round((filled / totalWeight) * 100)))

  const segments = plan.map((stage, i) => {
    const start = plan.slice(0, i).reduce((n, s) => n + s.weight, 0)
    const fill = Math.max(0, Math.min(1, (filled - start) / stage.weight))
    const state =
      i < index
        ? 'done'
        : i === index
          ? current.status === 'failed'
            ? 'fail'
            : current.status === 'canceled'
              ? 'stop'
              : 'now'
          : 'idle'
    return { key: stage.key, label: stage.label, fill, state }
  })

  return { percent, segments, caption: '' }
})

/** 当前进度：一行小字（最新的那行输出，或结论） */
const jobCaption = computed(() => {
  const current = job.value
  if (!current) return ''
  if (current.status === 'succeeded') {
    return current.result?.version ? `完成 · ${current.result.version}` : '安装完成'
  }
  if (current.status === 'failed') {
    return `失败 · ${current.result?.hint || lastLogLine.value || '请看详细日志'}`
  }
  if (current.status === 'canceled') return '已取消'
  const line = lastLogLine.value
  const stageLabel = jobPlan.value.find((s) => s.key === current.stage)?.label || ''
  if (!line) return `${stageLabel || '进行中'}…`
  return line.length > 78 ? `${line.slice(0, 78)}…` : line
})

const lastLogLine = computed(() => {
  const lines = jobLog.value.length ? jobLog.value : job.value?.log || []
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = (lines[i] || '').trim()
    if (line && !line.startsWith('$ ')) return line
  }
  return ''
})

const confirmCmd = computed(() => {
  const tool = confirmTool.value
  if (!tool) return ''
  if (tool.install_kind === 'zip') return `下载 ${tool.recommend?.zip_url || '官方压缩包'}`
  return tool.recommend?.install || tool.manual_cmd || ''
})

const confirmDir = computed(() => {
  const tool = confirmTool.value
  if (!tool) return ''
  const rec = tool.recommend as { subdir?: string; pkg?: string } | undefined
  const sub = rec?.subdir || tool.id
  const root = (envInstallRoot.value || runtime.env_install_root || '').replace(/[\\/]+$/, '')
  return `${root}/${sub}`
})

async function loadEnv() {
  envLoading.value = true
  try {
    const res = await api.get<any>('/api/env/probe')
    envItems.value = res.items || []
    envSummary.value = { total: res.total, installed: res.installed, missing: res.missing }
    envWinget.value = res.winget !== false
    envInstallRoot.value = res.install_root || ''
  } catch (e) {
    app.report(e)
  } finally {
    envLoading.value = false
  }
}

/** 点「一键安装」→ 弹二次确认（PATH 勾选默认打开） */
function askInstall(it: EnvItem) {
  if (!it.auto_install) {
    openManual(it)
    return
  }
  if (jobBusy.value) {
    app.toast('warning', '已有安装任务在跑', '同一时间只跑一个，避免两个安装程序抢 PATH')
    return
  }
  installAddPath.value = true
  confirmTool.value = it
}

function closeConfirm() {
  confirmTool.value = null
}

/** 点「手动安装」→ 弹窗：官网链接 + 命令（一键复制 / 一键运行）+ 步骤 */
function openManual(it: EnvItem) {
  installAddPath.value = true
  manualTool.value = it
}

function closeManual() {
  manualTool.value = null
}

const manualCmd = computed(() => {
  const tool = manualTool.value
  if (!tool) return ''
  return tool.manual_cmd || tool.recommend?.install || ''
})

/** 手动安装弹窗里的「一键运行」：命令由服务端工具表决定，前端只传 tool_id */
async function runManual() {
  const tool = manualTool.value
  if (!tool) return
  if (!tool.auto_install) {
    app.toast('warning', `${tool.name} 没有可自动运行的安装命令`, '请用「一键复制」贴到终端里手动执行')
    return
  }
  if (jobBusy.value) {
    app.toast('warning', '已有安装任务在跑', '等它结束再运行下一个')
    return
  }
  closeManual()
  await startJob(tool, 'manual')
}

function scrollJobLog() {
  nextTick(() => {
    const el = jobLogEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

/** 把后端快照并进来：log 是增量，其余字段直接覆盖 */
function applyJobSnapshot(fresh: EnvJob) {
  if (fresh.log?.length) {
    jobLog.value.push(...fresh.log)
    if (jobLog.value.length > 900) jobLog.value.splice(0, jobLog.value.length - 900)
    scrollJobLog()
  }
  jobSince.value = fresh.total ?? jobSince.value
  const { log: _ignored, ...rest } = fresh
  job.value = rest as EnvJob
  if (rest.status !== 'running' && rest.status !== 'pending') canceling.value = false
}

function stopPolling() {
  if (jobTimer) window.clearTimeout(jobTimer)
  jobTimer = undefined
}

function schedulePoll(delay = 1200) {
  stopPolling()
  jobTimer = window.setTimeout(() => void pollJob(), delay)
}

async function pollJob() {
  const current = job.value
  if (!current) return
  try {
    const res = await api.get<{ ok: boolean; job: EnvJob }>(
      `/api/env/install/${current.id}?since=${jobSince.value}`,
    )
    if (!job.value || job.value.id !== current.id) return
    if (!res?.ok || !res.job) {
      stopPolling()
      return
    }
    applyJobSnapshot(res.job)
    if (jobBusy.value) schedulePoll(1200)
    else void onJobDone()
  } catch {
    // 后端重启 / 网络抖一下：继续追，别把任务面板扔了
    if (job.value?.id === current.id) schedulePoll(3000)
  }
}

/** auto=卡片一键安装（已二次确认）；manual=手动安装弹窗里的「一键运行」 */
async function startJob(tool: EnvItem, via: 'auto' | 'manual') {
  try {
    const res = await api.post<{ ok: boolean; job: EnvJob }>('/api/env/install', {
      tool_id: tool.id,
      add_path: installAddPath.value,
      via,
    })
    jobLog.value = []
    jobSince.value = 0
    job.value = null
    showLog.value = false
    applyJobSnapshot(res.job)
    nextTick(() => jobPanelEl.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
    schedulePoll(900)
  } catch (e) {
    app.report(e)
  }
}

async function startInstall() {
  const tool = confirmTool.value
  if (!tool) return
  closeConfirm()
  await startJob(tool, 'auto')
}

async function cancelInstall() {
  const current = job.value
  if (!current) return
  canceling.value = true
  try {
    const res = await api.post<{ ok: boolean; job: EnvJob }>(
      `/api/env/install/${current.id}/cancel`,
    )
    applyJobSnapshot(res.job)
    schedulePoll(700)
  } catch (e) {
    canceling.value = false
    app.report(e)
  }
}

async function onJobDone() {
  const done = job.value
  if (!done) return
  if (done.status === 'succeeded') {
    app.toast(
      'success',
      `${done.tool_name} 安装完成`,
      done.result?.path_dirs?.length ? 'PATH 已更新，新开的终端直接可用' : undefined,
    )
  } else if (done.status === 'failed') {
    app.toast('error', `${done.tool_name} 安装失败`, done.result?.hint || '看安装日志定位，或改用手动安装')
  }
  await loadEnv()
}

function dismissJob() {
  stopPolling()
  job.value = null
  jobLog.value = []
  jobSince.value = 0
  canceling.value = false
}

/** 重开面板 / 刷新页面时，把还在跑的任务接回来继续轮询 */
async function restoreJob() {
  try {
    const res = await api.get<{ ok: boolean; running: EnvJob | null }>('/api/env/installs')
    const target = res.running || null
    if (!target) return
    if (job.value && job.value.id === target.id && jobBusy.value) return
    jobLog.value = []
    jobSince.value = 0
    applyJobSnapshot(target)
    schedulePoll(900)
  } catch {
    /* 没有任务就算了 */
  }
}

// ---------------- 默认打开方式 ----------------
interface DefaultApp {
  ext: string
  prog_id: string
  source: string
  app: string
  exe: string
  dir: string
  kind: string
  editor_id: string
  code_ext: boolean
  applied?: string
  editor_name?: string
}

const ASSOC_EXTS = ['.py', '.java', '.js', '.ts', '.c', '.cs']
const defaults = ref<{ items: DefaultApp[]; summary: { scanned: number; editors: number } } | null>(null)
const defaultsLoading = ref(false)

const defaultApps = computed(() => {
  const items = defaults.value?.items || []
  return ASSOC_EXTS.map((ext) => items.find((i) => i.ext === ext)).filter(Boolean) as DefaultApp[]
})

/** 识别 + 自动写进「设置 → 编辑器」的快捷键库（幂等，只补不覆盖） */
async function scanDefaults() {
  defaultsLoading.value = true
  try {
    const res = await api.post<any>('/api/env/default-apps/apply', {})
    if (!res?.ok) return
    defaults.value = { items: res.items || [], summary: res.summary || { scanned: 0, editors: 0 } }
    const names = [
      ...(res.added || []).map((a: any) => a.name),
      ...(res.updated || []).map((u: any) => u.name),
    ]
    if (names.length) {
      const uniq = Array.from(new Set(names)) as string[]
      app.toast('success', '默认打开方式已写入编辑器库', uniq.slice(0, 3).join('、'))
    }
  } catch (e) {
    app.report(e)
  } finally {
    defaultsLoading.value = false
  }
}

function openEnvTab() {
  tab.value = 'env'
  loadEnv()
  scanDefaults()
  restoreJob()
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    app.toast('success', '命令已复制')
  } catch {
    app.toast('warning', '复制失败，请手动选择')
  }
}

const envGroups = computed(() => {
  const out: Record<string, EnvItem[]> = {}
  for (const item of envItems.value) {
    ;(out[item.kind] ||= []).push(item)
  }
  return out
})

// ---------------- 名称 ----------------
const brand = ref({ name: 'CodeMentor' })

async function loadBrand() {
  try {
    const res = await api.get<any>('/api/branding')
    brand.value.name = res.name || 'CodeMentor'
  } catch {
    /* ignore */
  }
}

const brandSaving = ref(false)

async function saveBrand() {
  brandSaving.value = true
  try {
    const res = await api.put<any>('/api/branding', { name: brand.value.name })
    const { useBrandingStore } = await import('../stores/branding')
    const store = useBrandingStore()
    store.name = res.name
    store.apply()
    app.toast('success', '名称已保存')
  } catch (e) {
    app.report(e)
  } finally {
    brandSaving.value = false
  }
}

async function uploadBrand(slot: 'logo' | 'favicon', ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > 256 * 1024) {
    app.toast('warning', '图片超过 256KB，请压缩后再传')
    return
  }
  const form = new FormData()
  form.append('file', file)
  try {
    const res = await api.post<any>(`/api/branding/${slot}`, form)
    const { useBrandingStore } = await import('../stores/branding')
    const store = useBrandingStore()
    store.logoUrl = res.logo_url || ''
    store.faviconUrl = res.favicon_url || ''
    store.apply()
    app.toast('success', slot === 'logo' ? 'Logo 已更新' : '页面图标已更新')
  } catch (e) {
    app.report(e)
  } finally {
    input.value = ''
  }
}

// ---------------- 编辑器快捷键库 ----------------
interface EditorKey { action: string; keys: string }
interface EditorMouse { action: string; gesture: string }
interface EditorItem { id: string; name: string; match: string[]; keys: EditorKey[]; mouse: EditorMouse[] }
const editorsList = ref<EditorItem[]>([])
const editorSaving = ref(false)
const activeEditor = ref(0)

async function loadEditors() {
  try {
    const res = await api.get<{ items: EditorItem[] }>('/api/screen/editors')
    editorsList.value = res.items || []
  } catch (e) {
    app.report(e)
  }
}

async function saveEditors() {
  editorSaving.value = true
  try {
    const res = await api.put<{ items: EditorItem[] }>('/api/screen/editors', {
      items: editorsList.value,
    })
    editorsList.value = res.items || []
    app.toast('success', '编辑器快捷键已保存')
  } catch (e) {
    app.report(e)
  } finally {
    editorSaving.value = false
  }
}

async function resetEditors() {
  try {
    const res = await api.post<{ items: EditorItem[] }>('/api/screen/editors/reset')
    editorsList.value = res.items || []
    app.toast('success', '已恢复预置')
  } catch (e) {
    app.report(e)
  }
}

function addKey(idx: number) {
  editorsList.value[idx].keys.push({ action: '', keys: '' })
}
function addMouse(idx: number) {
  if (!editorsList.value[idx].mouse) editorsList.value[idx].mouse = []
  editorsList.value[idx].mouse.push({ action: '', gesture: '' })
}
function removeMouse(idx: number, m: number) {
  editorsList.value[idx].mouse.splice(m, 1)
}
function removeKey(idx: number, k: number) {
  editorsList.value[idx].keys.splice(k, 1)
}
function addEditor() {
  editorsList.value.push({ id: `custom${Date.now() % 1000}`, name: '新编辑器', match: [], keys: [], mouse: [] })
  activeEditor.value = editorsList.value.length - 1
}
function removeEditor(idx: number) {
  editorsList.value.splice(idx, 1)
  activeEditor.value = 0
}

onMounted(() => {
  loadBrand()
  if (tab.value === 'editors') loadEditors()
})

// 关掉设置面板就别再轮询了（任务本身在后端继续跑，重开面板会自动接回来）
onBeforeUnmount(() => stopPolling())

function close() {
  ui.closeSettings()
}
</script>

<template>
  <div class="overlay">
    <div class="dialog">
      <header class="head">
        <div class="head-titles">
          <h2>设置</h2>
          <p>API Key 会加密保存在本地，重启后端后即开即用</p>
        </div>
        <div class="head-tabs">
          <button :class="{ on: tab === 'providers' }" @click="tab = 'providers'">模型接入</button>
          <button :class="{ on: tab === 'appearance' }" @click="tab = 'appearance'">外观</button>
          <button :class="{ on: tab === 'runtime' }" @click="tab = 'runtime'">运行参数</button>
          <button :class="{ on: tab === 'editors' }" @click="tab = 'editors'; loadEditors()">编辑器</button>
          <button :class="{ on: tab === 'env' }" @click="openEnvTab()">环境</button>
          <button :class="{ on: tab === 'about' }" @click="tab = 'about'">关于</button>
        </div>
        <button class="icon-btn" @click="close">✕</button>
      </header>

      <!-- 模型接入 -->
      <div v-if="tab === 'providers'" class="body two-col">
        <div class="provider-list">
          <button
            v-for="p in app.providers"
            :key="p.provider"
            class="p-item"
            :class="{ on: selected === p.provider }"
            @click="selected = p.provider"
          >
            <span class="p-dot" :class="{ ok: p.has_key || !p.needs_key, active: p.is_active }" />
            <span class="p-name ellipsis">{{ p.label }}</span>
            <span v-if="p.is_active" class="p-badge">使用中</span>
            <span v-else-if="p.needs_key && !p.has_key" class="p-badge muted">未配置</span>
          </button>
        </div>

        <div class="p-form">
          <div class="form-head">
            <div>
              <h3>{{ info?.label }}</h3>
              <a v-if="info?.doc && info?.needs_key" :href="info.doc" target="_blank" class="tiny">获取 API Key →</a>
              <span v-else-if="info?.doc" class="tiny muted">{{ info.doc }}</span>
            </div>
            <div class="head-tags">
              <span v-if="dirty" class="tag tag-warn">未保存</span>
              <span v-if="isActive" class="tag tag-ok">当前使用中</span>
              <span v-else-if="config?.has_key" class="tag tag-mute">已配置</span>
            </div>
          </div>

          <div class="field">
            <label>API Key <span v-if="config?.api_key_mask" class="mono tiny muted">已保存 {{ config.api_key_mask }}</span></label>
            <div class="row">
              <input
                v-model="form.api_key"
                class="input"
                type="password"
                autocomplete="off"
                :placeholder="config?.has_key ? '留空表示不修改已保存的 Key' : (info?.needs_key ? 'sk-...' : '本地模型可留空')"
              />
              <button v-if="config?.has_key" class="btn btn-sm btn-danger" @click="clearKey">清除</button>
            </div>
          </div>

          <div class="field">
            <label>接口地址 Base URL</label>
            <input v-model="form.base_url" class="input mono" />
          </div>

          <div class="grid-2">
            <div class="field">
              <label>对话模型</label>
              <input
                v-model="form.model"
                class="input mono"
                list="model-options"
                placeholder="可直接填写任意模型名"
                @input="onModelInput"
              />
              <datalist id="model-options">
                <option v-for="m in modelOptions" :key="m.id" :value="m.id">{{ m.label }}</option>
              </datalist>
            </div>
            <div class="field">
              <label>视觉模型（多模态 / 屏幕识别）</label>
              <input v-model="form.vision_model" class="input mono" list="vision-options" />
              <datalist id="vision-options">
                <option v-for="m in modelOptions.filter((x) => x.vision)" :key="m.id" :value="m.id">
                  {{ m.label }}
                </option>
              </datalist>
            </div>
          </div>

          <div class="model-source">
            <span class="tiny muted ellipsis">
              {{
                app.modelsLoading === selected
                  ? '正在向服务端获取模型列表…'
                  : modelsMeta?.message || '候选来自内置推荐'
              }}
            </span>
            <button class="btn btn-sm" :disabled="app.modelsLoading === selected" @click="refreshModels">
              {{ app.modelsLoading === selected ? '刷新中…' : '刷新模型列表' }}
            </button>
          </div>
          <p class="field-tip">
            列表来自该供应商的 <code>/models</code> 接口；厂商新发布的模型即使没出现在列表里，也可以直接手动填写模型名。
          </p>

          <div v-if="selected === 'ollama'" class="ollama-box">
            <button class="btn btn-sm" :disabled="scanning" @click="scanOllama">
              {{ scanning ? '扫描中…' : '扫描本地 Ollama 模型' }}
            </button>
            <div v-if="ollamaModels.length" class="ollama-list">
              <button
                v-for="m in ollamaModels"
                :key="m"
                class="chip"
                :class="{ on: form.model === m }"
                @click="form.model = m"
              >
                {{ m }}
              </button>
            </div>
            <p v-else class="tiny muted">先执行 <code>ollama pull qwen2.5:7b</code>，再点扫描</p>
          </div>

          <div v-if="testResult" class="test-result" :class="{ ok: testResult.ok }">
            {{ testResult.ok ? '✓' : '✕' }} {{ testResult.message }}
          </div>

          <div class="form-actions">
            <button v-if="!isActive" class="btn btn-primary" :disabled="saving" @click="saveAndActivate">
              <span v-if="saving" class="spinner" />
              {{ saving ? '处理中…' : '保存并启用' }}
            </button>
            <button v-else class="btn btn-primary" :disabled="saving" @click="save">
              {{ saving ? '保存中…' : '保存配置' }}
            </button>
            <button class="btn" :disabled="testing" @click="test">
              <span v-if="testing" class="spinner" />
              {{ testing ? '测试中…' : '测试连接' }}
            </button>
            <button v-if="!isActive" class="btn" :disabled="saving" @click="save">仅保存</button>
          </div>
          <p v-if="dirty" class="unsaved-tip">
            ⚠️ 有未保存的修改：点「保存并启用」会连同输入框里的 Key 一起加密写入本地
          </p>
        </div>
      </div>

      <!-- 运行参数 -->
      <div v-else-if="tab === 'appearance'" class="body appearance">
        <div class="style-bar">
          <p class="group-title tight">风格</p>
          <label class="tiny muted">主题色</label>
          <select v-model="accent" class="input sel" @change="applyAccent">
            <option value="indigo">靛蓝（默认）</option>
            <option value="emerald">翡翠绿</option>
            <option value="violet">紫罗兰</option>
            <option value="amber">琥珀橙</option>
            <option value="rose">玫瑰红</option>
            <option value="slate">石墨灰</option>
          </select>
          <label class="tiny muted">代码高亮</label>
          <select v-model="codeTheme" class="input sel" @change="applyCodeTheme">
            <option value="auto">跟随主题</option>
            <option value="github">GitHub</option>
            <option value="one-dark">One Dark</option>
            <option value="monokai">Monokai</option>
          </select>
          <label class="tiny muted">字体</label>
          <select v-model="fontFamily" class="input sel" @change="applyFont">
            <option value="system">跟随系统</option>
            <option value="Microsoft YaHei">微软雅黑</option>
            <option value="SimSun">宋体</option>
            <option value="KaiTi">楷体</option>
            <option value="Segoe UI">Segoe UI</option>
            <option value="Georgia">Georgia</option>
            <option value="Consolas">Consolas（等宽）</option>
          </select>
        </div>

        <div class="style-bar">
          <p class="group-title tight">动效</p>
          <label class="check-row inline">
            <input v-model="animOn" type="checkbox" @change="toggleAnim" />
            <span class="tiny">页面淡入、开场白渐显、消息逐条浮现、弹窗过渡</span>
          </label>
        </div>

        <div class="brand-bar">
          <p class="group-title tight">名称</p>
          <input v-model="brand.name" class="input brand-name" placeholder="智能体名称" @change="saveBrand" />
          <label class="btn tiny">
            上传 Logo
            <input type="file" accept="image/*" style="display: none" @change="uploadBrand('logo', $event)" />
          </label>
          <label class="btn tiny">
            上传图标
            <input type="file" accept="image/png,image/x-icon,image/svg+xml" style="display: none" @change="uploadBrand('favicon', $event)" />
          </label>
          <span class="grow" />
          <button class="btn tiny btn-primary" :disabled="brandSaving" @click="saveBrand">
            {{ brandSaving ? '保存中…' : '保存' }}
          </button>
          <span class="tiny muted">PNG/SVG/ICO ≤ 256KB · 上传即保存；名称改完点「保存」</span>
        </div>

        <div class="theme-bar">
          <p class="group-title tight">主题</p>
          <div class="theme-switch">
            <button :class="{ on: ui.theme === 'light' }" @click="ui.setTheme('light')">☀️ 浅色</button>
            <button :class="{ on: ui.theme === 'dark' }" @click="ui.setTheme('dark')">🌙 深色</button>
            <button :class="{ on: ui.theme === 'auto' }" @click="ui.setTheme('auto')">🖥️ 跟随系统</button>
          </div>
          <span class="field-tip inline">记在浏览器本地；右上角图标可一键切换</span>
        </div>

        <p class="group-title">背景画面 <span class="tiny muted">图片 / 视频循环</span></p>
        <div class="bg-stage">
        <div class="bg-left">
        <div class="bg-preview" :class="previewSize">
          <img
            v-if="ui.background.kind === 'image' && ui.background.url"
            :key="ui.background.url"
            :src="ui.background.url"
            alt=""
            :style="previewStyle"
          />
          <video
            v-else-if="ui.background.kind === 'video' && ui.background.url"
            :key="ui.background.url"
            :src="ui.background.url"
            autoplay
            loop
            muted
            playsinline
            :style="previewStyle"
          />
          <div v-else class="bg-preview-empty">未启用背景</div>
          <div class="bg-preview-scrim" :style="{ background: previewScrim }" />

          <!-- 界面线框：只画结构，不画真实图标文字，用色块/圆点占位 -->
          <div class="mock">
            <aside class="mock-col mock-left">
              <div class="mock-row">
                <span class="mock-dot logo" />
                <span class="mock-bar w46 strong" />
              </div>
              <div class="mock-pill" />
              <div class="mock-row"><span class="mock-dot" /><span class="mock-bar w70" /></div>
              <div class="mock-row"><span class="mock-dot" /><span class="mock-bar w62" /></div>
              <div class="mock-row"><span class="mock-dot" /><span class="mock-bar w55" /></div>
              <div class="mock-row mock-foot">
                <span class="mock-dot sm" />
                <span class="mock-bar w40" />
              </div>
            </aside>

            <main class="mock-main">
              <div class="mock-bar w52 strong tall" />
              <div class="mock-bar w66" />
              <div class="mock-cards">
                <div v-for="i in 4" :key="i" class="mock-card">
                  <span class="mock-dot sm" />
                  <span class="mock-bar w60" />
                  <span class="mock-bar w80 faint" />
                </div>
              </div>
              <div class="mock-composer">
                <span class="mock-bar w40 faint" />
                <span class="mock-send" />
              </div>
            </main>

            <aside class="mock-col mock-right">
              <div class="mock-stats">
                <div v-for="i in 4" :key="i" class="mock-stat">
                  <span class="mock-bar w60 strong" />
                  <span class="mock-bar w40 faint" />
                </div>
              </div>
              <div class="mock-block" />
              <div class="mock-block" />
              <div class="mock-block" />
            </aside>
          </div>

          <button class="bg-preview-zoom" @click="previewSize = previewSize === 'thumb' ? 'large' : 'thumb'">
            {{ previewSize === 'thumb' ? '🔍 放大' : '🔍 缩小' }}
          </button>
        </div>

        <div class="bg-lib-head">
          <span class="tiny muted">素材库（点一下就用）</span>
          <span class="grow" />
          <button class="btn tiny" :disabled="bgUploading" @click="bgInput?.click()">
            {{ bgUploading ? '上传中…' : '＋ 上传' }}
          </button>
        </div>
        <div v-if="library.length" class="bg-lib">
          <div
            v-for="item in library"
            :key="item.name"
            class="bg-lib-item"
            :class="{ on: ui.background.url === item.url }"
            :title="item.name"
            @click="applyLibraryItem(item)"
          >
            <img v-if="item.kind === 'image'" :src="item.url" alt="" />
            <video v-else :src="item.url + '#t=0.1'" muted playsinline preload="metadata" />
            <span class="bg-lib-tag">{{ item.kind === 'video' ? '视频' : '图片' }}</span>
            <button class="bg-lib-del" title="删除这个素材" @click="deleteLibraryItem(item, $event)">×</button>
          </div>
        </div>
        <p v-else class="field-tip">还没有素材，点右上「＋ 上传」或直接填 URL。</p>
        <input
          class="input url-input"
          :value="ui.background.url"
          placeholder="图片 / 视频 URL，例如 https://.../loop.mp4"
          @change="onBgUrl"
        />
        </div>

        <div class="bg-controls">
        <div class="bg-row">
          <button
            class="bg-pick"
            :class="{ on: ui.background.kind === 'none' }"
            @click="ui.clearBackground()"
          >
            无
          </button>
          <button
            class="bg-pick"
            :class="{ on: ui.background.kind === 'image' }"
            @click="pickBgType('image')"
          >
            🖼️ 图片
          </button>
          <button
            class="bg-pick"
            :class="{ on: ui.background.kind === 'video' }"
            @click="pickBgType('video')"
          >
            🎬 视频
          </button>
          <input
            ref="bgInput"
            type="file"
            accept="image/*,video/*"
            style="display: none"
            @change="onBgFile"
          />
        </div>


        <div v-if="ui.background.url" class="bg-tune">
          <label class="slider">
            <span>模糊 {{ ui.background.blur }}px</span>
            <input type="range" min="0" max="40" :value="ui.background.blur" @input="onBgBlur" />
          </label>
          <label class="slider">
            <span>遮罩 {{ Math.round(ui.background.dim * 100) }}%</span>
            <input type="range" min="0" max="80" :value="Math.round(ui.background.dim * 100)" @input="onBgDim" />
          </label>
          <label class="slider">
            <span>画面不透明度 {{ Math.round(ui.background.mediaOpacity * 100) }}%</span>
            <input type="range" min="10" max="100" :value="Math.round(ui.background.mediaOpacity * 100)" @input="onMediaOpacity" />
          </label>
          <label class="slider">
            <span>左栏不透明度 {{ Math.round(ui.background.leftAlpha * 100) }}%</span>
            <input type="range" min="0" max="95" :value="Math.round(ui.background.leftAlpha * 100)" @input="onLeftAlpha" />
          </label>
          <label class="slider">
            <span>右栏不透明度 {{ Math.round(ui.background.rightAlpha * 100) }}%</span>
            <input type="range" min="0" max="95" :value="Math.round(ui.background.rightAlpha * 100)" @input="onRightAlpha" />
          </label>
        </div>
        <p class="field-tip">
          视频自动静音循环；素材保存在后端 <code>data/backgrounds/</code>，本地只记 URL。
          左边预览里画的是页面线框，调滑杆可以边看边改。
        </p>
        </div>
        </div>
      </div>

      <!-- 运行参数 -->

      <!-- 编辑器快捷键库 -->
      <div v-else-if="tab === 'editors'" class="body editors-pane">
        <div class="ed-head">
          <p class="group-title tight">编辑器快捷键库</p>
          <span class="grow" />
          <button class="btn tiny" @click="addEditor">+ 新增编辑器</button>
          <button class="btn tiny" @click="resetEditors">恢复预置</button>
          <button class="btn tiny btn-primary" :disabled="editorSaving" @click="saveEditors">
            {{ editorSaving ? '保存中…' : '保存' }}
          </button>
        </div>

        <div class="ed-tabs">
          <button
            v-for="(e, i) in editorsList"
            :key="e.id"
            class="ed-tab"
            :class="{ on: activeEditor === i }"
            @click="activeEditor = i"
          >
            {{ e.name }}
          </button>
        </div>

        <div v-if="editorsList[activeEditor]" class="ed-detail">
          <div class="ed-row">
            <label class="ed-label">名称</label>
            <input v-model="editorsList[activeEditor].name" class="input" />
            <button class="icon-btn del" title="删除这个编辑器" @click="removeEditor(activeEditor)">×</button>
          </div>
          <div class="ed-row">
            <label class="ed-label">识别关键词</label>
            <input
              :value="(editorsList[activeEditor].match || []).join(', ')"
              class="input"
              placeholder="idea, pycharm"
              @change="(ev: any) => (editorsList[activeEditor].match = ev.target.value.split(',').map((x: string) => x.trim()).filter(Boolean))"
            />
          </div>

          <div class="ed-keys">
            <div class="ed-keys-head">
              <span>功能</span><span>快捷键</span><span />
            </div>
            <div v-for="(k, ki) in editorsList[activeEditor].keys" :key="ki" class="ed-key-row">
              <input v-model="k.action" class="input" placeholder="跳转到行" />
              <input v-model="k.keys" class="input mono" placeholder="ctrl+g" />
              <button class="icon-btn del" @click="removeKey(activeEditor, ki)">×</button>
            </div>
            <button class="btn tiny" style="margin-top: 6px" @click="addKey(activeEditor)">+ 添加一条</button>
          </div>

          <div class="ed-keys">
            <div class="ed-keys-head">
              <span>鼠标操作（编辑区）</span><span>手势标识</span><span />
            </div>
            <div v-for="(m, mi) in editorsList[activeEditor].mouse || []" :key="mi" class="ed-key-row">
              <input v-model="m.action" class="input" placeholder="三击选中整行" />
              <input v-model="m.gesture" class="input mono" placeholder="triple_click_line" />
              <button class="icon-btn del" @click="removeMouse(activeEditor, mi)">×</button>
            </div>
            <button class="btn tiny" style="margin-top: 6px" @click="addMouse(activeEditor)">+ 添加鼠标操作</button>
          </div>
          <p class="field-tip">
            屏幕智能体会按前台窗口标题匹配「识别关键词」，命中后把这套快捷键注入提示词，
            它就不用猜某个功能该按什么键了。
          </p>
        </div>
      </div>


      <!-- 环境管家：检测 / 一键安装 / 默认打开方式 -->
      <div v-else-if="tab === 'env'" class="body env-pane">
        <div class="env-head">
          <p class="group-title tight">开发环境检测</p>
          <span class="tiny muted" v-if="envSummary.total">
            已装 {{ envSummary.installed }} / {{ envSummary.total }}，缺失 {{ envSummary.missing }}
          </span>
          <span class="grow" />
          <button class="btn tiny btn-primary" :disabled="envLoading" @click="loadEnv">
            <span v-if="envLoading" class="spinner" />
            {{ envLoading ? '检测中…' : '开始检测' }}
          </button>
        </div>

        <p v-if="!envWinget && envItems.length" class="env-warn">
          没检测到 winget（应用安装程序），一键安装不可用；下面每张卡片的手动安装命令照旧能复制。
        </p>

        <!-- 安装任务：后台跑，按阶段给进度，详细日志按需展开 -->
        <div v-if="job" ref="jobPanelEl" class="install-job" :class="job.status">
          <div class="install-job-head">
            <span v-if="jobBusy" class="spinner" />
            <span class="install-job-title">{{ job.tool_name }} · {{ JOB_STATUS[job.status] }}</span>
            <span class="tiny muted mono">{{ job.elapsed_s }}s</span>
            <span class="grow" />
            <span class="stage-pct mono">{{ jobProgress.percent }}%</span>
            <button v-if="jobBusy" class="btn tiny" :disabled="canceling" @click="cancelInstall">
              {{ canceling ? '正在取消…' : '取消' }}
            </button>
            <button v-if="!jobBusy" class="btn tiny" @click="dismissJob">收起</button>
          </div>

          <!-- 阶段性进度条：每段是一个阶段，权重决定长度 -->
          <div class="stage-bar" :class="job.status">
            <div
              v-for="seg in jobProgress.segments"
              :key="seg.key"
              class="stage-seg"
              :class="seg.state"
              :title="seg.label"
            >
              <span class="stage-fill" :style="{ width: seg.fill * 100 + '%' }" />
              <span class="stage-label">{{ seg.label }}</span>
            </div>
          </div>

          <!-- 当前进度：一行小字 -->
          <p class="stage-caption ellipsis" :title="jobCaption">{{ jobCaption }}</p>

          <div v-if="!jobBusy" class="install-result">
            <span v-if="job.result.path_dirs && job.result.path_dirs.length" class="tiny muted">
              PATH 已加：{{ job.result.path_dirs.join('；') }}
            </span>
            <span v-else-if="job.add_path === false" class="tiny muted">按设置未改 PATH</span>
            <span v-if="job.status === 'failed'" class="bad">退出码 {{ job.exit_code }}</span>
            <span v-if="job.result.hint" class="tiny muted">{{ job.result.hint }}</span>
          </div>

          <button class="log-toggle" @click="showLog = !showLog">
            {{ showLog ? '收起详细日志' : '详细日志' }}
          </button>
          <pre v-if="showLog" ref="jobLogEl" class="install-log">{{ jobLog.length ? jobLog.join('\n') : '等待安装程序输出…' }}</pre>
        </div>

        <!-- 安装路径：可折叠，收起时只显示当前值 -->
        <div class="path-box">
          <button class="fold-head" :class="{ on: pathsOpen }" @click="pathsOpen = !pathsOpen">
            <span class="fold-caret" :class="{ open: pathsOpen }">▸</span>
            <span class="group-title tight">安装路径</span>
            <span class="tiny muted ellipsis">
              环境装到 <code class="mono">{{ runtime.env_install_root }}</code>，安装包落到
              <code class="mono">{{ runtime.env_download_dir }}</code>
            </span>
            <span class="grow" />
            <span class="tiny muted">{{ pathsOpen ? '收起' : '修改' }}</span>
          </button>
          <template v-if="pathsOpen">
            <div class="path-row">
              <label>安装包下载目录</label>
              <input v-model="runtime.env_download_dir" class="input mono" placeholder="D:/Downloads/setup" />
            </div>
            <div class="path-row">
              <label>环境安装根目录</label>
              <input v-model="runtime.env_install_root" class="input mono" placeholder="D:/DevEnv" />
            </div>
            <div class="path-row">
              <label>编辑器安装根目录</label>
              <input v-model="runtime.editor_install_root" class="input mono" placeholder="D:/DevEnv/editors" />
            </div>
            <p class="field-tip">
              每个工具装在根目录下的独立子文件夹（如 <code class="mono">D:/DevEnv/python/3.12</code>），
              互不干扰；安装包统一落在下载目录，装完可自行清理。
              支持自定义目录的安装包会用 <code class="mono">--location</code> 装到这里，其余装到默认位置后自动加 PATH。
            </p>
            <div class="path-actions">
              <button class="btn tiny btn-primary" :disabled="saving" @click="saveRuntime">保存路径</button>
            </div>
          </template>
        </div>

        <!-- 默认打开方式：读注册表文件关联 -->
        <div class="path-box">
          <div class="env-head">
            <p class="group-title tight">默认打开方式</p>
            <span class="tiny muted" v-if="defaults?.summary?.editors">
              识别到 {{ defaults.summary.editors }} 个编辑器
            </span>
            <span class="grow" />
            <button class="btn tiny" :disabled="defaultsLoading" @click="scanDefaults">
              <span v-if="defaultsLoading" class="spinner" />
              {{ defaultsLoading ? '识别中…' : '重新识别' }}
            </button>
          </div>
          <div v-if="defaultApps.length" class="assoc-grid">
            <div
              v-for="d in defaultApps"
              :key="d.ext"
              class="assoc-row"
              :title="d.exe || '注册表里没有查到关联程序'"
            >
              <code class="mono assoc-ext">{{ d.ext }}</code>
              <span class="assoc-app ellipsis">{{ d.app || '未关联' }}</span>
              <span class="assoc-badge" :class="d.editor_id ? 'on' : 'off'">
                {{
                  d.editor_id
                    ? d.applied === 'added'
                      ? '新加入编辑器库'
                      : d.applied === 'updated'
                        ? '补了关键词'
                        : '已在编辑器库'
                    : d.kind === 'browser'
                      ? '浏览器'
                      : '未识别为编辑器'
                }}
              </span>
            </div>
          </div>
          <p v-else class="field-tip">点「重新识别」读一下注册表里的 .py / .java / .js 关联。</p>
          <p class="field-tip">
            读 <code class="mono">HKCU\…\FileExts\.py\UserChoice</code> 拿到 ProgId，
            再读 <code class="mono">HKCR\…\shell\open\command</code> 拿到真正的 exe；
            识别到的编辑器（PyCharm / IDEA / VS Code …）会自动补进「设置 → 编辑器」的识别关键词，
            屏幕演示时就能按它自己的快捷键操作，而不是瞎猜。
          </p>
        </div>

        <p v-if="!envItems.length && !envLoading" class="field-tip">
          点「开始检测」扫描本机：Python、Node、JDK、Go、Rust、.NET、PHP、Ruby、Maven、Gradle、
          Git、MySQL、PostgreSQL、Redis、SQLite、Docker、npm/pnpm/Yarn、CMake、GCC。
        </p>

        <div v-for="(list, kind) in envGroups" :key="kind" class="env-group">
          <p class="env-kind">{{ kind }}</p>
          <div class="env-cards">
            <div v-for="it in list" :key="it.id" class="env-card" :class="{ ok: it.installed }">
              <div class="env-card-head">
                <span class="env-name">{{ it.name }}</span>
                <span class="env-badge" :class="it.installed ? 'on' : job && job.tool_id === it.id && jobBusy ? 'busy' : 'off'">
                  {{ it.installed ? '已安装' : job && job.tool_id === it.id && jobBusy ? '安装中' : '未安装' }}
                </span>
              </div>
              <p class="env-ver mono" :title="it.path">{{ it.installed ? it.version : it.desc }}</p>
              <div v-if="!it.installed" class="env-actions">
                <button
                  v-if="it.auto_install"
                  class="btn tiny btn-primary"
                  :disabled="jobBusy"
                  @click="askInstall(it)"
                >
                  {{ job && job.tool_id === it.id && jobBusy ? '安装中…' : '一键安装' }}
                </button>
                <button class="btn tiny" @click="openManual(it)">手动安装</button>
                <span v-if="!it.auto_install" class="tiny muted">无一键包</span>
              </div>

              </div>
          </div>
        </div>
      </div>

      <div v-else-if="tab === 'runtime'" class="body runtime">
        <p class="group-title">速度与预算</p>
        <div class="field">
          <label>工具轮回上限 <span class="tiny muted">（act⇄tools 最多几轮；1 最快，2 可先检索再跑代码）</span></label>
          <input v-model.number="runtime.agent_tool_rounds" class="input" type="number" min="1" max="12" />
        </div>
        <div class="field">
          <label>单轮时间预算（秒）<span class="tiny muted">（超时直接用已有证据作答）</span></label>
          <input v-model.number="runtime.agent_budget_s" class="input" type="number" min="5" max="600" step="5" />
        </div>
        <label class="check-row">
          <input v-model="runtime.agent_fast_lane" type="checkbox" />
          <span>快速通道：寒暄、极短的追问跳过规划与工具决策（省 2 次模型往返）</span>
        </label>
        <label class="check-row">
          <input v-model="runtime.llm_disable_thinking" type="checkbox" />
          <span>关闭思维链（通义 Qwen3 系列生效，思考型模型单跳可能 20s+）</span>
        </label>

        <p class="group-title">上下文与记忆</p>
        <div class="field">
          <label>Agent 最大工具迭代次数 <span class="tiny muted">（硬上限）</span></label>
          <input v-model.number="runtime.agent_max_iterations" class="input" type="number" min="1" max="12" />
        </div>
        <div class="field">
          <label>短期上下文窗口（条消息）</label>
          <input v-model.number="runtime.short_term_window" class="input" type="number" min="2" max="60" />
        </div>

        <p class="group-title">屏幕演示</p>
        <div class="field">
          <label>决策间隔（毫秒）<span class="tiny muted">（多久问一次模型；演示控制台里也能临时调）</span></label>
          <input v-model.number="runtime.screen_interval_ms" class="input" type="number" min="800" max="30000" step="200" />
        </div>
        <div class="field">
          <label>屏幕演示最大步数</label>
          <input v-model.number="runtime.screen_max_steps" class="input" type="number" min="1" max="200" />
        </div>
        <label class="check-row">
          <input v-model="runtime.screen_dry_run" type="checkbox" />
          <span>默认演练模式（只识别不操作鼠标）</span>
        </label>
        <div class="field">
          <label>场景模式 <span class="tiny muted">（决定屏幕演示用哪套策略）</span></label>
          <select v-model="runtime.screen_mode" class="input">
            <option value="demo">通用演示 · 看截图操作</option>
            <option value="editor">改代码 · 用行号跳转+整行替换</option>
            <option value="precise">精确操作 · 优先控件树</option>
            <option value="assist">协作 · 改文件前说明清楚</option>
          </select>
        </div>
        <div class="field">
          <label>画面采样间隔（毫秒）<span class="tiny muted">（抓帧节奏，便宜；默认 200ms，用来判断界面是否已稳定）</span></label>
          <input v-model.number="runtime.screen_capture_ms" class="input" type="number" min="100" max="5000" step="50" />
        </div>
        <label class="check-row">
          <input v-model="runtime.screen_skip_unchanged" type="checkbox" />
          <span>画面完全没变时跳过这次模型调用（省钱省时间；连续 8 次（约 4 秒）无变化会强制问一次）</span>
        </label>
        <div class="field">
          <label>截图最大宽度 <span class="tiny muted">（2560 的屏幕别低于 1568，否则字会糊；越高越慢）</span></label>
          <input v-model.number="runtime.screen_image_max_width" class="input" type="number" min="800" max="2560" step="64" />
        </div>
        <div class="field">
          <label>截图 JPEG 质量 <span class="tiny muted">（低于 75 文字边缘会振铃，模型容易认错字）</span></label>
          <input v-model.number="runtime.screen_image_quality" class="input" type="number" min="50" max="95" step="5" />
        </div>
        <label class="check-row">
          <input v-model="runtime.screen_retro" type="checkbox" />
          <span>演示结束后自动复盘：让模型把本次经验总结成提示知识，下次演示自动生效</span>
        </label>
        <label class="check-row">
          <input v-model="runtime.screen_share_chat_model" type="checkbox" />
          <span>屏幕演示直接复用对话模型（要求该模型支持图片；识别不准时可以试试）</span>
        </label>
        <div class="field" v-if="!runtime.screen_share_chat_model">
          <label>屏幕演示专用模型 <span class="tiny muted">（格式 provider:model，留空=自动挑多模态模型）</span></label>
          <input v-model="runtime.screen_model_override" class="input" placeholder="qwen:qwen3-vl-plus" />
        </div>
        <label class="check-row">
          <input v-model="runtime.screen_panic_enabled" type="checkbox" />
          <span>启用全局「强制停止」快捷键（任何窗口下都能用，改完重启后端生效）</span>
        </label>
        <div class="field" v-if="runtime.screen_panic_enabled">
          <label>强制停止快捷键 <span class="tiny muted">（默认 ctrl+alt+shift+f12，三修饰键几乎不冲突）</span></label>
          <input v-model="runtime.screen_panic_hotkey" class="input" placeholder="ctrl+alt+shift+f12" />
        </div>

        <p class="group-title">工具与权限</p>
        <label class="check-row">
          <input v-model="runtime.agent_screen_tool" type="checkbox" />
          <span>允许「看一眼屏幕」（look_at_screen，截图交视觉模型，与屏幕智能体共享所见）</span>
        </label>
        <label class="check-row">
          <input v-model="runtime.agent_fs_tool" type="checkbox" />
          <span>允许读取本机文件（<b>只读</b>：列目录 / 搜索 / 读文本 / 打开；<b>不能写入、删除或改名</b>，要改文件只能走屏幕演示的键鼠操作）</span>
        </label>
        <label class="check-row">
          <input v-model="runtime.fs_allow_all_drives" type="checkbox" />
          <span>允许读取所有磁盘（含移动硬盘；系统目录和别人的用户目录仍然拒绝）</span>
        </label>
        <div class="field">
          <label>额外允许访问的根目录 <span class="tiny muted">（多个用 ; 分隔）</span></label>
          <input v-model="runtime.fs_roots" class="input" placeholder="E:\学习资料\人工智能\project" />
        </div>
        <div class="field">
          <label>单次搜索时间预算（秒）<span class="tiny muted">（越大越能翻到深处的文件，2~25）</span></label>
          <input v-model.number="runtime.fs_search_budget_s" class="input" type="number" min="2" max="25" step="1" />
        </div>

        <button class="btn btn-primary" style="margin-top: 18px" @click="saveRuntime">
          {{ runtimeSaved ? '✓ 已保存' : '保存运行参数' }}
        </button>
        <div class="env-card">
          <div class="env-row"><span>数据库</span><code>{{ app.health?.database?.url || '—' }}</code></div>
          <div class="env-row"><span>向量库</span><code>Qdrant {{ app.health?.vector?.mode }} · {{ app.health?.vector?.embedder }} · {{ app.health?.vector?.dim }}d</code></div>
          <div class="env-row"><span>向量点</span><code>{{ app.health?.vector?.knowledge_points }} 知识 / {{ app.health?.vector?.memory_points }} 记忆</code></div>
          <div class="env-row"><span>运行时长</span><code>{{ app.health?.uptime_s }}s</code></div>
        </div>
      </div>

      <!-- 关于 -->
      <div v-else class="body about">
        <h3>CodeMentor · 编程学习助手</h3>
        <p>一个把「规划 → 工具执行 → 讲解 → 手把手演示」串起来的编程学习智能体。</p>
        <ul>
          <li>LangGraph 状态图编排：plan → act ⇄ tools → answer</li>
          <li>11 个内置工具：知识库检索、代码沙箱、记忆写入/召回、演示提案、看一眼屏幕、本机文件（只读：列目录 / 搜索 / 读文本 / 打开 / 定位）</li>
          <li>RAG：Qdrant 向量库（embedded 模式）+ 离线哈希向量 + 关键词重排</li>
          <li>短期记忆（滚动摘要）+ 长期记忆（MySQL 持久化 + 向量召回）</li>
          <li>多模态：图片上传 / 屏幕截图喂给视觉模型</li>
          <li>屏幕演示：截图 → 视觉决策 → pyautogui 执行，支持暂停续跑</li>
        </ul>
        <p class="tiny muted">后端 FastAPI + MySQL + Qdrant ｜ 前端 Vue3 + Vite ｜ 模型：DeepSeek / 通义千问 / OpenAI 兼容 / Ollama / 内置演示</p>
      </div>
    </div>

    <!-- 一键安装的二次确认：独立弹窗，盖在设置面板之上 -->
    <div v-if="confirmTool" class="confirm-mask" @click.self="closeConfirm">
      <div class="confirm-dialog" role="dialog" aria-modal="true">
        <div class="confirm-head">
          <span class="confirm-icon">⚠</span>
          <div class="confirm-titles">
            <p class="confirm-title">确认安装 {{ confirmTool.name }}？</p>
            <p class="confirm-sub">
              {{ confirmTool.install_kind === 'zip' ? '下载官方压缩包并解压' : '调用 winget 安装' }}，
              可能弹出 UAC 授权窗口
            </p>
          </div>
        </div>

        <p class="confirm-cmd mono" :title="confirmCmd">{{ confirmCmd }}</p>

        <label class="check-row tight">
          <input v-model="installAddPath" type="checkbox" />
          <span>装完自动加入 PATH（推荐，新终端直接能用）</span>
        </label>
        <p class="confirm-dir">
          <span class="tiny muted">安装位置</span>
          <code class="mono tiny">{{ confirmDir }}</code>
        </p>

        <p class="field-tip">
          装完会自动跑一次版本命令验证；安装过程可以随时取消。关掉面板不影响后台继续安装，下次打开会自动接回来。
        </p>

        <div class="confirm-actions">
          <button class="btn tiny" @click="closeConfirm">取消</button>
          <button class="btn tiny btn-primary" @click="startInstall">确认安装</button>
        </div>
      </div>
    </div>

    <!-- 手动安装弹窗：最上方官网入口 + 命令（复制 / 运行）+ 步骤 -->
    <div v-if="manualTool" class="confirm-mask" @click.self="closeManual">
      <div class="confirm-dialog manual-dialog" role="dialog" aria-modal="true">
        <div class="confirm-head">
          <span class="confirm-icon manual">🛠</span>
          <div class="confirm-titles">
            <p class="confirm-title">手动安装 {{ manualTool.name }}</p>
            <p class="confirm-sub">
              推荐 {{ manualTool.recommend.version || '最新稳定版' }} ·
              {{ manualTool.install_kind === 'zip' ? '官方压缩包' : manualTool.install_kind === 'winget' ? 'winget / 官网安装器' : '官网安装包' }}
            </p>
          </div>
          <button class="icon-btn" title="关闭" @click="closeManual">✕</button>
        </div>

        <!-- 最上方：官网访问链接 -->
        <a
          v-if="manualTool.recommend.url"
          class="official-link"
          :href="manualTool.recommend.url"
          target="_blank"
          rel="noopener"
        >
          <span class="official-icon">🌐</span>
          <span class="official-body">
            <span class="official-label">官网下载页</span>
            <span class="official-url mono ellipsis">{{ manualTool.recommend.url }}</span>
          </span>
          <span class="official-go">打开 ↗</span>
        </a>
        <p v-else class="field-tip">这个工具没有登记官网地址，请按下面的命令手动安装。</p>

        <p class="group-title tight">安装命令</p>
        <div class="manual-cmd">
          <code class="mono">{{ manualCmd || '见官网下载页' }}</code>
        </div>
        <div class="manual-actions">
          <button class="btn tiny" :disabled="!manualCmd" @click="copyText(manualCmd)">一键复制</button>
          <button
            class="btn tiny btn-primary"
            :disabled="!manualTool.auto_install || jobBusy"
            @click="runManual"
          >
            {{ jobBusy ? '已有任务在跑' : '一键运行' }}
          </button>
          <span v-if="!manualTool.auto_install" class="tiny muted">
            这个工具没有可自动运行的命令，请复制后手动执行
          </span>
        </div>

        <label class="check-row tight" v-if="manualTool.auto_install">
          <input v-model="installAddPath" type="checkbox" />
          <span>运行后自动加入 PATH（推荐，新终端直接能用）</span>
        </label>

        <p class="group-title tight">安装步骤</p>
        <ol class="env-steps">
          <li v-if="manualTool.install_kind !== 'zip'">打开管理员终端（Win+X → 终端(管理员)）</li>
          <li>粘贴上面的命令并回车，等待下载安装完成</li>
          <li v-if="manualTool.install_kind === 'zip'">
            把解压出来的 <code class="mono">bin</code> 目录加入 PATH（「一键运行」会自动做）
          </li>
          <li>关闭并重新打开终端，让 PATH 生效</li>
          <li>回到「环境」面板点「开始检测」确认变成「已安装」</li>
        </ol>

        <p v-if="manualTool.note" class="env-note">💡 {{ manualTool.note }}</p>

        <div class="confirm-actions">
          <button class="btn tiny" @click="closeManual">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 28px;
  background: var(--overlay-bg);
  backdrop-filter: blur(6px);
}
.dialog {
  width: min(880px, 94vw);
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  border-radius: 18px;
  background: var(--dialog-bg);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.head-titles {
  flex: 1;
}
.head-titles h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}
.head-titles p {
  margin: 3px 0 0;
  font-size: 11.5px;
  color: var(--text-3);
}
.head-tabs {
  display: flex;
  gap: 3px;
  padding: 3px;
  border-radius: 10px;
  background: var(--inset-bg);
  border: 1px solid var(--border);
}
.head-tabs button {
  padding: 6px 12px;
  border-radius: 7px;
  font-size: 12px;
  color: var(--text-3);
}
.head-tabs button.on {
  background: rgba(99, 102, 241, 0.22);
  color: var(--accent-ink);
}

.body {
  padding: 18px;
  overflow-y: auto;
}
.two-col {
  display: grid;
  grid-template-columns: 234px 1fr;
  gap: 18px;
  min-height: 420px;
}
.provider-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-right: 1px solid var(--border);
  padding-right: 14px;
}
.p-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 9px;
  font-size: 12.5px;
  color: var(--text-2);
  text-align: left;
  transition: all 0.16s;
}
.p-item:hover {
  background: var(--elev-2);
}
.p-item.on {
  background: rgba(99, 102, 241, 0.16);
  color: var(--text-1);
}
.p-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(148, 163, 184, 0.45);
  flex-shrink: 0;
}
.p-dot.ok {
  background: var(--success);
}
.p-dot.active {
  box-shadow: 0 0 8px var(--success);
}
.p-name {
  flex: 1;
}
.p-badge {
  font-size: 9.5px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(52, 211, 153, 0.16);
  color: var(--success-ink);
}
.p-badge.muted {
  background: rgba(148, 163, 184, 0.14);
  color: var(--text-3);
}

.p-form {
  min-width: 0;
}
.form-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
}
.form-head h3 {
  margin: 0 0 3px;
  font-size: 14px;
}
.field {
  margin-bottom: 12px;
}
.field label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: var(--text-3);
  margin-bottom: 5px;
}
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.ollama-box {
  padding: 11px;
  border-radius: 10px;
  background: rgba(34, 211, 238, 0.05);
  border: 1px solid rgba(34, 211, 238, 0.18);
  margin-bottom: 12px;
}
.ollama-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}
.chip {
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-family: var(--mono);
  background: var(--elev-2);
  border: 1px solid var(--border);
  color: var(--text-2);
}
.chip.on {
  background: rgba(34, 211, 238, 0.18);
  border-color: rgba(34, 211, 238, 0.4);
  color: var(--cyan-ink);
}
.ollama-box .tiny {
  margin: 8px 0 0;
}
.ollama-box code {
  font-family: var(--mono);
  font-size: 10.5px;
  background: var(--inset-bg);
  padding: 1px 5px;
  border-radius: 4px;
}

.test-result {
  padding: 9px 11px;
  border-radius: 9px;
  font-size: 11.5px;
  margin-bottom: 12px;
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.24);
  color: var(--danger-ink);
}
.test-result.ok {
  background: rgba(52, 211, 153, 0.08);
  border-color: rgba(52, 211, 153, 0.24);
  color: var(--success-ink);
}

.form-actions {
  display: flex;
  gap: 8px;
  padding-top: 6px;
}
.head-tags {
  display: flex;
  align-items: center;
  gap: 6px;
}
.unsaved-tip {
  margin: 10px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--warn-ink);
}

.runtime {
  /* 两列瀑布：原来限宽 520px 导致右侧大片留白 */
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 20px;
  row-gap: 2px;
  align-items: start;
  max-width: none;
}
.runtime .group-title,
.runtime .check-row,
.runtime .field-tip,
.runtime > p {
  grid-column: 1 / -1;
}
.runtime .field {
  margin-bottom: 10px;
}
.theme-switch {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  border-radius: 10px;
  background: var(--inset-bg);
  border: 1px solid var(--border);
}
.theme-switch button {
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--text-2);
  transition: all 0.16s ease;
}
.theme-switch button:hover {
  color: var(--text-1);
}
.theme-switch button.on {
  background: var(--grad-accent);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.28);
}
.field-tip {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-3);
}
.field-tip code {
  font-family: var(--mono);
  font-size: 10.5px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--elev-2);
}
.model-source {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 10px 0 0;
  padding: 8px 11px;
  border-radius: 9px;
  background: var(--elev-1);
  border: 1px solid var(--border);
}
.model-source .tiny {
  flex: 1;
  min-width: 0;
  line-height: 1.5;
}
.check-row {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 12.5px;
  color: var(--text-2);
  margin: 14px 0;
  cursor: pointer;
}
.check-row input {
  accent-color: var(--accent);
}
.env-card {
  margin-top: 22px;
  padding: 12px 14px;
  border-radius: 11px;
  background: var(--elev-1);
  border: 1px solid var(--border);
}
.env-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 0;
  font-size: 11.5px;
  color: var(--text-3);
}
.env-row code {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
  text-align: right;
  word-break: break-all;
}

.about h3 {
  margin: 0 0 8px;
  font-size: 15px;
}
.about p {
  font-size: 12.5px;
  line-height: 1.8;
  color: var(--text-2);
}
.about ul {
  padding-left: 20px;
  font-size: 12.5px;
  line-height: 2;
  color: var(--text-2);
}
.about li::marker {
  color: var(--accent-2);
}

@media (max-width: 720px) {
  .two-col {
    grid-template-columns: 1fr;
  }
  .provider-list {
    border-right: none;
    border-bottom: 1px solid var(--border);
    padding: 0 0 10px;
  }
  .grid-2 {
    grid-template-columns: 1fr;
  }
}

/* 背景选择器 */
.bg-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.bg-pick {
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-2);
  background: var(--inset-bg);
  border: 1px solid var(--border);
  transition: all 0.15s ease;
}
.bg-pick:hover {
  color: var(--text-1);
  border-color: var(--border-strong);
}
.bg-pick.on {
  color: #fff;
  background: var(--grad-accent);
  border-color: transparent;
}
.bg-tune {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.bg-tune .slider {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--text-3);
  min-width: 150px;
}
.bg-tune input[type='range'] {
  width: 100%;
  accent-color: var(--accent);
}

/* ================= 外观页 ================= */
.group-title {
  margin: 20px 0 10px;
  padding-bottom: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3);
  border-bottom: 1px solid var(--border);
}
.group-title:first-child {
  margin-top: 0;
}
.group-title .tiny {
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
}

.bg-preview {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--inset-bg);
  height: 132px;
  transition: height 0.18s ease;
}
.bg-preview.large {
  height: 260px;
}
.bg-preview img,
.bg-preview video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.bg-preview-scrim {
  position: absolute;
  inset: 0;
}
.bg-preview-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 11.5px;
  color: var(--text-3);
}
.bg-preview-zoom {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 2;
  padding: 3px 9px;
  border-radius: 6px;
  font-size: 10.5px;
  color: var(--text-1);
  background: rgba(10, 16, 30, 0.62);
  border: 1px solid var(--border-strong);
  backdrop-filter: blur(6px);
}
.bg-preview-zoom:hover {
  border-color: var(--accent);
}

.bg-lib {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
  gap: 8px;
  margin: 4px 0 10px;
}
.bg-lib-item {
  position: relative;
  height: 48px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border);
  cursor: pointer;
  background: var(--inset-bg);
}
.bg-lib-item.on {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.28);
}
.bg-lib-item img,
.bg-lib-item video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.bg-lib-tag {
  position: absolute;
  left: 4px;
  bottom: 3px;
  font-size: 9px;
  padding: 0 4px;
  border-radius: 3px;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
}
.bg-lib-del {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 15px;
  height: 15px;
  line-height: 13px;
  border-radius: 50%;
  font-size: 11px;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  opacity: 0;
  transition: opacity 0.15s;
}
.bg-lib-item:hover .bg-lib-del {
  opacity: 1;
}
.bg-lib-del:hover {
  background: var(--danger);
}

/* ---------- 预览里的界面线框 ---------- */
.mock {
  position: absolute;
  inset: 0;
  display: flex;
  z-index: 1;
  pointer-events: none;
  --m-fill: rgba(255, 255, 255, 0.18);
  --m-fill-strong: rgba(255, 255, 255, 0.34);
  --m-fill-faint: rgba(255, 255, 255, 0.09);
}
html[data-theme='light'] .mock {
  --m-fill: rgba(15, 23, 42, 0.16);
  --m-fill-strong: rgba(15, 23, 42, 0.3);
  --m-fill-faint: rgba(15, 23, 42, 0.08);
}

.mock-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 7px;
  height: 100%;
  box-sizing: border-box;
}
.mock-left {
  width: 21%;
  background: rgba(10, 16, 30, var(--panel-alpha-left, 0.45));
  border-right: 1px solid var(--border);
}
.mock-right {
  width: 24%;
  background: rgba(10, 16, 30, var(--panel-alpha-right, 0.62));
  border-left: 1px solid var(--border);
}
html[data-theme='light'] .mock-left {
  background: rgba(255, 255, 255, var(--panel-alpha-left, 0.52));
}
html[data-theme='light'] .mock-right {
  background: rgba(255, 255, 255, var(--panel-alpha-right, 0.7));
}

.mock-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px 10px;
  box-sizing: border-box;
  position: relative;
}

.mock-row {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 9px;
}
.mock-row.mock-foot {
  margin-top: auto;
}
.mock-dot {
  width: 9px;
  height: 9px;
  min-width: 9px;
  border-radius: 50%;
  background: var(--m-fill);
}
.mock-dot.sm {
  width: 6px;
  height: 6px;
  min-width: 6px;
}
.mock-dot.logo {
  background: var(--grad-accent);
  box-shadow: 0 0 6px rgba(99, 102, 241, 0.5);
}
.mock-bar {
  height: 5px;
  border-radius: 3px;
  background: var(--m-fill);
}
.mock-bar.faint {
  background: var(--m-fill-faint);
}
.mock-bar.strong {
  background: var(--m-fill-strong);
}
.mock-bar.tall {
  height: 9px;
  border-radius: 4px;
}
.mock-bar.w30 { width: 30%; }
.mock-bar.w40 { width: 40%; }
.mock-bar.w46 { width: 46%; }
.mock-bar.w52 { width: 52%; }
.mock-bar.w55 { width: 55%; }
.mock-bar.w60 { width: 60%; }
.mock-bar.w62 { width: 62%; }
.mock-bar.w66 { width: 66%; }
.mock-bar.w70 { width: 70%; }
.mock-bar.w80 { width: 80%; }

.mock-pill {
  height: 12px;
  border-radius: 6px;
  margin: 2px 0 3px;
  background: var(--grad-accent);
  opacity: 0.85;
}

.mock-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  width: 78%;
  margin-top: 6px;
}
.mock-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 5px 6px;
  border-radius: 5px;
  background: var(--surface);
  border: 1px solid var(--border);
}

.mock-composer {
  position: absolute;
  left: 8%;
  right: 8%;
  bottom: 6px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 7px;
  border-radius: 7px;
  background: var(--composer-bg);
  border: 1px solid var(--border);
}
.mock-send {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--grad-accent);
}

.mock-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
  padding: 5px 4px;
  border-radius: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  margin-bottom: 2px;
}
.mock-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}
.mock-block {
  height: 16px;
  border-radius: 5px;
  background: var(--elev-1);
  border: 1px solid var(--border);
}
.mock-block:last-child {
  height: 26px;
}


/* ---------- 外观页：预览 + 控件两列 ---------- */
.bg-stage {
  display: grid;
  grid-template-columns: minmax(280px, 42%) 1fr;
  gap: 16px;
  align-items: start;
}
.bg-stage .bg-preview {
  position: relative;
  width: 100%;
  /* 固定 16:9：和真实窗口一致，视频/图片用 cover 裁切时不会被压成竖条 */
  height: auto;
  aspect-ratio: 16 / 9;
  max-height: 340px;
  align-self: start;
}
.bg-stage .bg-preview.large {
  grid-column: 1 / -1;
  aspect-ratio: 16 / 9;
  max-height: 420px;
}
.bg-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.bg-controls .bg-tune {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 14px;
}
.bg-controls .bg-tune .slider {
  min-width: 0;
}
@media (max-width: 900px) {
  .bg-stage {
    grid-template-columns: 1fr;
  }
  .bg-stage .bg-preview {
    aspect-ratio: 16 / 9;
  }
}


/* 五个滑杆排两列时，最后一个占满一行，避免只剩半行显得空 */
.bg-controls .bg-tune .slider:last-child {
  grid-column: 1 / -1;
}
/* 预览较窄时，统计格改成两列读起来更清楚 */
.bg-stage .mock-stats {
  grid-template-columns: repeat(2, 1fr);
}


/* 主题：一行排布，右侧填说明，消除大片留白 */
.theme-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.group-title.tight {
  margin: 0;
}
.field-tip.inline {
  margin: 0 0 0 auto;
  text-align: right;
}
/* 背景：左列 = 预览 + 素材库 + URL，右列 = 模式 + 滑块 */
.bg-left {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.bg-lib-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}
.bg-left .bg-lib {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(74px, 1fr));
  gap: 6px;
  max-height: 132px;
  overflow-y: auto;
}
.bg-left .bg-lib-item {
  height: 54px;
}
.url-input {
  font-size: 11.5px;
}


/* 右列铺满整列高度，底部说明吸底，消除下半留白 */
.bg-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 100%;
}
.bg-controls .field-tip:last-child {
  margin-top: auto;
  padding-top: 6px;
}


.editors-pane { display: flex; flex-direction: column; gap: 10px; }
.ed-head { display: flex; align-items: center; gap: 8px; }
.ed-tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.ed-tab {
  padding: 5px 12px; border-radius: 8px; font-size: 12px;
  background: var(--inset-bg); border: 1px solid var(--border); color: var(--text-2);
}
.ed-tab.on { background: var(--grad-accent); color: #fff; border-color: transparent; }
.ed-detail { display: flex; flex-direction: column; gap: 8px; }
.ed-row { display: flex; align-items: center; gap: 8px; }
.ed-label { width: 76px; font-size: 12px; color: var(--text-3); flex: none; }
.ed-keys { border: 1px solid var(--border); border-radius: 10px; padding: 10px; }
.ed-keys-head, .ed-key-row {
  display: grid; grid-template-columns: 1fr 140px 28px; gap: 8px; align-items: center;
}
.ed-keys-head { font-size: 11px; color: var(--text-3); margin-bottom: 6px; }
.ed-key-row { margin-bottom: 6px; }


.brand-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.brand-name { width: 180px; }


.style-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.sel { width: auto; min-width: 110px; padding: 4px 8px; font-size: 12px; }


/* 两列网格里：标签统一两行高，避免一行说明把整行顶歪 */
.runtime .field label {
  min-height: 32px;
  align-items: flex-start;
  line-height: 1.5;
}
.runtime .field label .tiny {
  display: inline;
  line-height: 1.5;
}
/* 勾选项并排成两列，不再各自独占一行 */
.runtime .check-row {
  grid-column: auto;
  align-items: flex-start;
  margin: 2px 0 10px;
  line-height: 1.6;
}
.runtime .check-row.wide {
  grid-column: 1 / -1;
}


.check-row.inline { display: inline-flex; align-items: center; gap: 8px; margin: 0; }


.env-pane { display: flex; flex-direction: column; gap: 12px; }
.env-head { display: flex; align-items: center; gap: 10px; }
.env-group { display: flex; flex-direction: column; gap: 8px; }
.env-kind { margin: 0; font-size: 11.5px; color: var(--text-3); letter-spacing: 0.04em; }
.env-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.env-card {
  padding: 9px 11px; border-radius: 10px;
  background: var(--inset-bg); border: 1px solid var(--border);
}
.env-card.ok { border-color: rgba(16, 185, 129, 0.4); }
.env-card-head { display: flex; align-items: center; gap: 8px; }
.env-name { font-size: 12.5px; font-weight: 600; }
.env-badge { margin-left: auto; font-size: 10px; padding: 1px 7px; border-radius: 999px; }
.env-badge.on { background: rgba(16, 185, 129, 0.16); color: #10b981; }
.env-badge.off { background: rgba(244, 63, 94, 0.14); color: #f43f5e; }
.env-ver { margin: 6px 0 0; font-size: 11px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.env-actions { display: flex; align-items: center; gap: 6px; margin-top: 7px; }


.env-steps { margin: 0; padding-left: 16px; font-size: 11.5px; line-height: 1.75; color: var(--text-2); }
.env-steps code { font-size: 11px; color: var(--accent); }
.env-note { margin: 6px 0 0; font-size: 11px; line-height: 1.65; color: var(--text-3); }
.env-note a { color: var(--accent); }


.path-box {
  display: flex; flex-direction: column; gap: 8px;
  padding: 12px; border-radius: 12px;
  background: var(--inset-bg); border: 1px solid var(--border);
}
.path-row { display: flex; align-items: center; gap: 10px; }
.path-row label { width: 130px; flex: none; font-size: 11.5px; color: var(--text-3); }
.path-row .input { flex: 1; min-width: 0; font-size: 11.5px; }
.path-actions { display: flex; justify-content: flex-end; }

/* 可折叠的分组标题行（安装路径） */
.fold-head {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 0; border: 0; background: none; text-align: left; cursor: pointer;
}
.fold-head .tiny { color: var(--text-3); }
.fold-head:hover .fold-caret, .fold-head:hover .tiny:last-child { color: var(--accent-ink); }
.fold-caret {
  flex: none; font-size: 11px; line-height: 1; color: var(--text-2);
  transition: transform 0.18s ease, color 0.16s ease;
}
.fold-caret.open { transform: rotate(90deg); color: var(--accent-ink); }

/* ---------- 一键安装：二次确认 + 阶段进度 ---------- */
.env-warn {
  margin: 0; padding: 7px 10px; border-radius: 9px; font-size: 11.5px; line-height: 1.6;
  color: #f59e0b; background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3);
}
.env-badge.busy { background: rgba(99, 102, 241, 0.18); color: var(--accent-ink); }

.confirm-mask {
  position: fixed; inset: 0; z-index: 90;
  display: grid; place-items: center;
  padding: 24px; background: rgba(3, 7, 18, 0.62);
  backdrop-filter: blur(3px);
  animation: confirmIn 0.14s ease-out;
}
.confirm-dialog {
  width: min(520px, 92vw);
  display: flex; flex-direction: column; gap: 10px;
  padding: 18px; border-radius: 16px;
  background: var(--dialog-bg); border: 1px solid var(--border-strong);
  box-shadow: var(--shadow-lg);
}
.confirm-head { display: flex; gap: 10px; align-items: flex-start; }
.confirm-icon {
  flex: none; width: 26px; height: 26px; border-radius: 8px;
  display: grid; place-items: center; font-size: 14px;
  background: rgba(245, 158, 11, 0.16); color: #f59e0b;
}
.confirm-titles { flex: 1; min-width: 0; }
.confirm-title { margin: 0; font-size: 14px; font-weight: 650; }
.confirm-sub { margin: 3px 0 0; font-size: 11.5px; line-height: 1.55; color: var(--text-3); }
.confirm-cmd {
  margin: 0; padding: 8px 10px; border-radius: 8px; font-size: 11px;
  background: var(--inset-bg); border: 1px solid var(--border);
  color: var(--text-2); word-break: break-all;
}
.confirm-dialog .check-row.tight { margin: 0; gap: 8px; font-size: 12px; align-items: center; }
.confirm-dialog .check-row code { color: var(--accent); }
.confirm-dir { margin: 0; display: flex; align-items: center; gap: 8px; }
.confirm-dir code { color: var(--accent); word-break: break-all; }
.confirm-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 2px; }

/* 手动安装弹窗 */
.manual-dialog { width: min(600px, 94vw); max-height: 88vh; overflow-y: auto; }
.confirm-icon.manual { background: rgba(99, 102, 241, 0.16); color: var(--accent-ink); }
.confirm-head .icon-btn { flex: none; }
.official-link {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 11px; border-radius: 10px; text-decoration: none;
  background: rgba(99, 102, 241, 0.1); border: 1px solid rgba(99, 102, 241, 0.34);
  transition: background 0.16s ease, border-color 0.16s ease;
}
.official-link:hover { background: rgba(99, 102, 241, 0.18); border-color: rgba(99, 102, 241, 0.55); }
.official-icon { flex: none; font-size: 15px; }
.official-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.official-label { font-size: 12px; font-weight: 600; color: var(--text-1); }
.official-url { font-size: 10.5px; color: var(--text-3); }
.official-go { flex: none; font-size: 11.5px; font-weight: 600; color: var(--accent-ink); }

.manual-cmd {
  padding: 9px 11px; border-radius: 9px;
  background: var(--inset-bg); border: 1px solid var(--border);
}
.manual-cmd code {
  display: block; font-size: 11px; line-height: 1.65; color: var(--text-2);
  white-space: pre-wrap; word-break: break-all;
  max-height: 132px; overflow-y: auto;
}
.manual-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.manual-dialog .group-title.tight { margin: 2px 0 0; }
.manual-dialog .env-steps { margin: 0; }
@keyframes confirmIn {
  from { opacity: 0; transform: translateY(6px) scale(0.99); }
  to { opacity: 1; transform: none; }
}

.install-job {
  display: flex; flex-direction: column; gap: 7px;
  padding: 11px 12px; border-radius: 11px;
  background: rgba(99, 102, 241, 0.07); border: 1px solid rgba(99, 102, 241, 0.38);
}
.install-job.succeeded { border-color: rgba(16, 185, 129, 0.42); background: rgba(16, 185, 129, 0.06); }
.install-job.failed { border-color: rgba(244, 63, 94, 0.42); background: rgba(244, 63, 94, 0.06); }
.install-job.canceled { border-color: var(--border); background: var(--inset-bg); }
.install-job-head { display: flex; align-items: center; gap: 8px; }
.install-job-title { font-size: 12.5px; font-weight: 600; }
.stage-pct { font-size: 12px; font-weight: 650; color: var(--accent-ink); }
.install-job.succeeded .stage-pct { color: #10b981; }
.install-job.failed .stage-pct { color: #f43f5e; }
.install-job.canceled .stage-pct { color: var(--text-3); }

/* 阶段性进度条：一段一个阶段 */
.stage-bar { display: flex; gap: 5px; }
.stage-seg {
  position: relative; flex: 1; height: 20px; border-radius: 6px;
  overflow: hidden; background: var(--inset-bg); border: 1px solid var(--border);
}
.stage-fill {
  position: absolute; inset: 0 auto 0 0; width: 0;
  background: linear-gradient(90deg, #6366f1, #06b6d4);
  opacity: 0.75; transition: width 0.5s ease;
}
.stage-label {
  position: relative; z-index: 1; display: grid; place-items: center;
  height: 100%; font-size: 10.5px; color: var(--text-3); letter-spacing: 0.02em;
}
.stage-seg.done .stage-label, .stage-seg.now .stage-label { color: var(--text-1); }
.stage-seg.now { box-shadow: inset 0 0 0 1px rgba(99, 102, 241, 0.55); }
.stage-seg.now .stage-fill { animation: stagePulse 1.5s ease-in-out infinite alternate; }
.stage-seg.fail .stage-fill { background: linear-gradient(90deg, #f43f5e, #fb923c); opacity: 0.9; }
.stage-seg.fail .stage-label { color: #fecdd3; }
.stage-seg.stop .stage-fill { background: var(--text-3); opacity: 0.4; }
.stage-bar.succeeded .stage-fill { background: linear-gradient(90deg, #10b981, #34d399); }
.stage-seg.idle .stage-fill { width: 0 !important; }
@keyframes stagePulse {
  from { opacity: 0.45; }
  to { opacity: 0.9; }
}

/* 当前进度：一行小字 */
.stage-caption {
  margin: 0; font-size: 11px; line-height: 1.5; color: var(--text-3);
  font-family: var(--mono);
}
.log-toggle {
  align-self: flex-start; padding: 0; border: 0; background: none; cursor: pointer;
  font-size: 11px; color: var(--text-3); text-decoration: underline dotted;
  text-underline-offset: 3px;
}
.log-toggle:hover { color: var(--accent-ink); }
.install-log {
  margin: 0; max-height: 210px; overflow-y: auto; padding: 8px 10px; border-radius: 8px;
  background: var(--inset-bg); border: 1px solid var(--border);
  font-family: var(--mono); font-size: 11px; line-height: 1.6;
  color: var(--text-2); white-space: pre-wrap; word-break: break-all;
}
.install-result { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; font-size: 11.5px; }
.install-result .bad { color: #f43f5e; font-weight: 600; }

/* ---------- 默认打开方式 ---------- */
.assoc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 6px; }
.assoc-row {
  display: flex; align-items: center; gap: 8px; padding: 5px 9px;
  border-radius: 8px; background: var(--elev-1, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border);
}
.assoc-ext { flex: none; min-width: 42px; font-size: 10.5px; color: var(--accent); }
.assoc-app { flex: 1; min-width: 0; font-size: 11.5px; color: var(--text-1); }
.assoc-badge { flex: none; font-size: 10px; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
.assoc-badge.on { background: rgba(16, 185, 129, 0.16); color: #10b981; }
.assoc-badge.off { background: rgba(148, 163, 184, 0.16); color: var(--text-3); }

</style>
