/**
 * 浅色主题截图：验证白天主题下的排版与对比度。
 * 用法：node scripts/screenshot-light.mjs
 */
import puppeteer from 'puppeteer-core'
import { mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = join(__dirname, '..', '..', 'docs', 'screenshots')
mkdirSync(OUT, { recursive: true })

const CHROME =
  process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function shot(page, name) {
  await page.screenshot({ path: join(OUT, name) })
  console.log('📸', name)
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1'],
    defaultViewport: { width: 1680, height: 1050 },
  })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))

  // 在页面脚本执行前写入主题偏好
  await page.evaluateOnNewDocument(() => localStorage.setItem('cm-theme', 'light'))
  await page.goto(BASE, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.welcome', { timeout: 20000 })
  await sleep(600)
  const theme = await page.evaluate(() => document.documentElement.dataset.theme)
  console.log('当前主题:', theme)
  await shot(page, 'light-01-welcome.png')

  await page.click('.editor')
  await page.type('.editor', 'Python 装饰器的本质是什么？给我一个能直接跑的示例', { delay: 5 })
  await page.click('.send-btn')
  await page.waitForSelector('.plan-card', { timeout: 20000 }).catch(() => {})
  await sleep(400)
  await shot(page, 'light-02-plan.png')

  await page.waitForSelector('.demo-card', { timeout: 60000 }).catch(() => {})
  await sleep(900)
  await page.evaluate(() => {
    const el = document.querySelector('.messages')
    if (el) el.scrollTop = el.scrollHeight
  })
  await sleep(400)
  await shot(page, 'light-03-answer.png')

  // 设置弹窗（浅色）
  await page.evaluate(() => {
    const btn = document.querySelector('.sidebar .brand .icon-btn')
    btn && btn.click()
  })
  await page.waitForSelector('.dialog', { timeout: 8000 })
  await sleep(500)
  await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.head-tabs button')]
    const target = tabs.find((t) => t.textContent.includes('运行参数'))
    target && target.click()
  })
  await sleep(500)
  await shot(page, 'light-04-settings.png')
  await page.evaluate(() => {
    const btn = document.querySelector('.dialog .head .icon-btn')
    btn && btn.click()
  })
  await sleep(400)

  // 知识库面板（浅色）
  await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.agent-panel .tab')]
    const target = tabs.find((t) => t.textContent.includes('知识库'))
    target && target.click()
  })
  await sleep(900)
  await shot(page, 'light-05-knowledge.png')

  // 切回深色，确认可逆
  await page.evaluate(() => {
    const btn = document.querySelector('.theme-btn')
    btn && btn.click()
  })
  await sleep(500)
  const after = await page.evaluate(() => document.documentElement.dataset.theme)
  console.log('点击切换后的主题:', after, after === 'dark' ? '✅ 可逆' : '❌ 未切回')
  await shot(page, 'light-06-back-to-dark.png')

  console.log(errors.length ? `⚠️ 页面错误 ${errors.length} 条` : '✅ 无页面错误')
  errors.slice(0, 5).forEach((e) => console.log('   ', e.slice(0, 160)))
  await browser.close()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})