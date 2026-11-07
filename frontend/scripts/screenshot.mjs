/**
 * 自动截图脚本：用本机 Chrome 无头模式跑一遍真实 UI，产出文档用截图。
 * 用法：node scripts/screenshot.mjs
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
  const path = join(OUT, name)
  await page.screenshot({ path })
  console.log('📸', name)
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-gpu',
      '--hide-scrollbars',
      '--force-device-scale-factor=1',
      '--window-size=1680,1050',
    ],
    defaultViewport: { width: 1680, height: 1050 },
  })
  const page = await browser.newPage()
  const errors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text())
  })
  page.on('pageerror', (e) => errors.push(String(e)))

  // 深色主题固定（应用默认跟随系统，这里显式锁定以保证截图稳定）
  await page.evaluateOnNewDocument(() => localStorage.setItem('cm-theme', 'dark'))

  await page.goto(BASE, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.welcome', { timeout: 20000 })
  await sleep(600)
  await shot(page, '01-welcome.png')

  // ---------- 第 1 轮：让智能体跑一遍完整流程 ----------
  await page.click('.editor')
  await page.type('.editor', 'Python 装饰器的本质是什么？给我一个能直接跑的示例', { delay: 5 })
  await sleep(200)
  await shot(page, '02-input.png')
  await page.click('.send-btn')

  // 等规划出现
  await page.waitForSelector('.plan-card', { timeout: 20000 }).catch(() => {})
  await sleep(500)
  await shot(page, '03-agent-plan.png')

  // 等回答结束（demo 卡片出现）
  await page.waitForSelector('.demo-card', { timeout: 60000 }).catch(() => {})
  await sleep(900)
  await page.evaluate(() => {
    const el = document.querySelector('.messages')
    if (el) el.scrollTop = 380
  })
  await sleep(300)
  await shot(page, '04-answer-demo.png')

  await page.evaluate(() => {
    const el = document.querySelector('.messages')
    if (el) el.scrollTop = el.scrollHeight
  })
  await sleep(400)
  await shot(page, '05-answer-bottom.png')

  // ---------- 右侧面板：轨迹 ----------
  await page.evaluate(() => {
    const el = document.querySelector('.messages')
    if (el) el.scrollTop = 0
  })
  await sleep(400)
  await shot(page, '06-trace-panel.png')

  // ---------- 记忆面板 ----------
  await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.agent-panel .tab')]
    const target = tabs.find((t) => t.textContent.includes('记忆'))
    target && target.click()
  })
  await sleep(900)
  await shot(page, '07-memory-panel.png')

  // ---------- 知识库面板 ----------
  await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.agent-panel .tab')]
    const target = tabs.find((t) => t.textContent.includes('知识库'))
    target && target.click()
  })
  await sleep(900)
  await shot(page, '08-knowledge-panel.png')

  // ---------- 设置弹窗 ----------
  await page.evaluate(() => {
    const btn = document.querySelector('.sidebar .brand .icon-btn')
    btn && btn.click()
  })
  await page.waitForSelector('.dialog', { timeout: 8000 })
  await sleep(700)
  await shot(page, '09-settings.png')
  await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.head-tabs button')]
    const target = tabs.find((t) => t.textContent.includes('运行参数'))
    target && target.click()
  })
  await sleep(500)
  await shot(page, '10-settings-runtime.png')
  await page.keyboard.press('Escape')
  await page.evaluate(() => {
    const btn = document.querySelector('.dialog .head .icon-btn')
    btn && btn.click()
  })
  await sleep(500)

  // ---------- 屏幕演示控制台 ----------
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.demo-btn')].pop()
    btn && btn.click()
  })
  await page.waitForSelector('.console', { timeout: 8000 })
  await sleep(700)
  await shot(page, '11-screen-console.png')
  await page.keyboard.press('Escape')
  await sleep(400)

  // ---------- 第二轮对话（多轮 + 记忆写入） ----------
  await page.click('.editor')
  await page.type('.editor', '我是学 Vue3 的前端，更喜欢用组合式 API，记住这一点', { delay: 4 })
  await page.click('.send-btn')
  await page.waitForSelector('.demo-card', { timeout: 60000 }).catch(() => {})
  await sleep(1200)
  await shot(page, '12-second-turn.png')

  // ---------- 会话侧边栏 ----------
  await sleep(500)
  await shot(page, '13-sidebar.png')

  console.log(errors.length ? `⚠️ 控制台错误 ${errors.length} 条:` : '✅ 无控制台错误')
  errors.slice(0, 10).forEach((e) => console.log('   ', e.slice(0, 200)))
  await browser.close()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
