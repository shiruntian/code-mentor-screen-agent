/** 外观：主题色 / 代码高亮 / 字体 / 动效 —— 统一入口，页面启动时回放。 */

export const ACCENTS: Record<string, [string, string, string]> = {
  // [主色, 渐变色, 命名]
  indigo: ['#6366f1', '#22d3ee', '靛蓝'],
  emerald: ['#10b981', '#34d399', '翡翠绿'],
  violet: ['#8b5cf6', '#e879f9', '紫罗兰'],
  amber: ['#f59e0b', '#fbbf24', '琥珀橙'],
  rose: ['#f43f5e', '#fb923c', '玫瑰红'],
  slate: ['#64748b', '#94a3b8', '石墨灰'],
}

export const FONTS: Record<string, string> = {
  system: "system-ui, -apple-system, 'Segoe UI', sans-serif",
  'Microsoft YaHei': "'Microsoft YaHei', 'PingFang SC', sans-serif",
  SimSun: "SimSun, 'Songti SC', serif",
  KaiTi: "KaiTi, 'Kaiti SC', serif",
  'Segoe UI': "'Segoe UI', system-ui, sans-serif",
  Georgia: "Georgia, 'Times New Roman', serif",
  Consolas: "Consolas, 'Cascadia Code', monospace",
}

const KEY = { accent: 'cm-accent', code: 'cm-code-theme', font: 'cm-font', anim: 'cm-anim' }

export interface Appearance {
  accent: string
  codeTheme: string
  font: string
  anim: boolean
}

export function readAppearance(): Appearance {
  return {
    accent: localStorage.getItem(KEY.accent) || 'indigo',
    codeTheme: localStorage.getItem(KEY.code) || 'auto',
    font: localStorage.getItem(KEY.font) || 'system',
    anim: localStorage.getItem(KEY.anim) !== 'off',
  }
}

export function applyAppearance(patch: Partial<Appearance> = {}): Appearance {
  const next = { ...readAppearance(), ...patch }
  const root = document.documentElement
  const [accent, second] = ACCENTS[next.accent] || ACCENTS.indigo
  root.style.setProperty('--accent', accent)
  root.style.setProperty('--accent-2', second)
  root.style.setProperty('--grad-accent', `linear-gradient(135deg, ${accent} 0%, ${second} 100%)`)
  root.dataset.code = next.codeTheme
  root.dataset.anim = next.anim ? 'on' : 'off'
  root.style.setProperty('--font-ui', FONTS[next.font] || FONTS.system)
  localStorage.setItem(KEY.accent, next.accent)
  localStorage.setItem(KEY.code, next.codeTheme)
  localStorage.setItem(KEY.font, next.font)
  localStorage.setItem(KEY.anim, next.anim ? 'on' : 'off')
  // 通知 App：外观变了，好把主题色/字体同步给后端（演示提问窗要用）
  try {
    window.dispatchEvent(new CustomEvent('cm-appearance', { detail: next }))
  } catch {
    /* 忽略 */
  }
  return next
}

export const FONT_OPTIONS = Object.keys(FONTS)
export const CODE_THEMES = ['auto', 'github', 'one-dark', 'monokai']
/** 主题色 → 十六进制（给后端演示提问窗用）。 */
export function accentHex(name: string): string {
  return (ACCENTS[name] || ACCENTS.indigo)[0]
}

/** 字体键 → 具体字族（给后端演示提问窗用，取第一个可用字族）。 */
export function fontFamily(name: string): string {
  const raw = FONTS[name] || FONTS.system
  const first = raw.split(',')[0].trim().replace(/^['"]|['"]$/g, '')
  return first === 'system-ui' ? '' : first
}
