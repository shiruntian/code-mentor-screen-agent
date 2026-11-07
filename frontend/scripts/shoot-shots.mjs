/**
 * 截图：会话列表里的「截图占用」与清理确认框（51~53）。
 *
 * 注意：只打开确认框，不点「确认」——点了会真的删掉截图。
 */
import puppeteer from 'puppeteer-core'
import { join } from 'node:path'

const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000'
const OUT = process.env.OUT_DIR || '.'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--window-size=1680,1050'],
  defaultViewport: { width: 1680, height: 1050 },
})
const page = await browser.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
page.on('pageerror', (e) => errors.push(String(e)))
await page.evaluateOnNewDocument(() => localStorage.setItem('cm-theme', 'dark'))
await page.goto(BASE, { waitUntil: 'networkidle2' })
await page.waitForSelector('.conv', { timeout: 25000 })
await sleep(900)

// 统计侧边栏显示的信息
const info = await page.evaluate(() => {
  const total = document.querySelector('.shots-total')?.textContent?.trim() || ''
  const orphan = !!document.querySelector('.orphan-clean')
  const convs = [...document.querySelectorAll('.conv')].map((c) => ({
    title: c.querySelector('.conv-title')?.textContent?.trim(),
    badge: c.querySelector('.shot-badge')?.textContent?.trim() || '',
    meta: c.querySelector('.conv-meta')?.textContent?.replace(/\s+/g, ' ').trim(),
  }))
  return { total, orphan, convs }
})
console.log('总占用徽标:', info.total, '| 有未关联清理按钮:', info.orphan)
console.log('带体积的会话:')
info.convs.filter((c) => c.badge).forEach((c) => console.log(`  ${c.badge.padEnd(10)} ${c.title}`))

// 51：侧边栏全貌（带体积徽标）
await page.screenshot({ path: join(OUT, '51-conv-screenshot-size.png'), clip: { x: 0, y: 0, width: 300, height: 620 } })

// 52：悬停出清理按钮（选一个有截图且有按钮的会话）
const target = await page.evaluateHandle(() => {
  const rows = [...document.querySelectorAll('.conv')]
  return rows.find((r) => r.querySelector('.mini.shots')) || rows[0]
})
await target.asElement().hover()
await sleep(400)
const box = await target.asElement().boundingBox()
await page.screenshot({
  path: join(OUT, '52-conv-shot-hover.png'),
  clip: { x: 0, y: Math.max(0, box.y - 70), width: 300, height: 190 },
})

// 53：清理确认框
await page.evaluate(() => document.querySelector('.conv .mini.shots')?.click())
await page.waitForSelector('.confirm-dialog', { timeout: 8000 })
await sleep(500)
const confirm = await page.evaluate(() => ({
  title: document.querySelector('.confirm-title')?.textContent?.trim(),
  lines: [...document.querySelectorAll('.confirm-lines li')].map((l) => l.textContent.trim()),
  ok: document.querySelector('.confirm-actions .btn-primary')?.textContent?.trim(),
}))
console.log('确认框:', confirm)
await page.screenshot({ path: join(OUT, '53-shot-cleanup-confirm.png') })

// 关掉弹窗（不确认！）
await page.evaluate(() => {
  const btns = [...document.querySelectorAll('.confirm-actions .btn')]
  btns[0]?.click()
})
await sleep(300)
const stillOpen = await page.evaluate(() => !!document.querySelector('.confirm-dialog'))
console.log(stillOpen ? '⚠ 弹窗没关掉' : '✓ 已取消，没有删除任何截图')

console.log(errors.length ? `控制台错误 ${errors.length} 条: ${errors.slice(0, 3).join(' | ')}` : '✅ 无控制台错误')
await browser.close()