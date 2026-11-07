export function relativeTime(input?: string | null): string {
  if (!input) return ''
  const date = new Date(input.endsWith('Z') ? input : `${input}Z`)
  const diff = (Date.now() - date.getTime()) / 1000
  if (Number.isNaN(diff)) return ''
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export function clockTime(input?: string | null): string {
  if (!input) return ''
  const date = new Date(input.endsWith('Z') ? input : `${input}Z`)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function fileSize(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function shortModel(name?: string | null): string {
  if (!name) return '未选择'
  return name.length > 22 ? `${name.slice(0, 20)}…` : name
}