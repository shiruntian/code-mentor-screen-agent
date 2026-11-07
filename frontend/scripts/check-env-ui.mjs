/** UI 冒烟：打开 设置 → 环境，确认渲染正常、无控制台报错（只截图到临时目录，不产出文档图）。 */
import puppeteer from 'puppeteer-core'
import { join } from 'node:path'

const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000'
const OUT = process.env.TEMP || '.'

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
await page.waitForSelector('.welcome', { timeout: 20000 })
await page.evaluate(() => document.querySelector('.sidebar .brand .icon-btn')?.click())
await page.waitForSelector('.dialog', { timeout: 8000 })
await page.evaluate(() => {
  const t = [...document.querySelectorAll('.head-tabs button')].find((b) => b.textContent.includes('环境'))
  t?.click()
})
await page.waitForSelector('.env-card', { timeout: 20000 })
await page.waitForSelector('.assoc-row', { timeout: 20000 })
await new Promise((r) => setTimeout(r, 1500))
const info = await page.evaluate(() => ({
  cards: document.querySelectorAll('.env-card').length,
  installBtns: [...document.querySelectorAll('.env-actions .btn-primary')].length,
  assoc: document.querySelectorAll('.assoc-row').length,
  summary: document.querySelector('.env-head .tiny')?.textContent?.trim() || '',
}))
console.log('DOM:', JSON.stringify(info))
await page.screenshot({ path: join(OUT, 'env-check.png') })
console.log(errors.length ? `控制台错误 ${errors.length} 条: ${errors.slice(0, 5).join(' | ')}` : '✅ 无控制台错误')
await browser.close()