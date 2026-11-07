/**
 * 环境管家截图：独立二次确认弹窗 + 阶段性进度条 + 可折叠安装路径 + 默认打开方式。
 * 用法：node scripts/shoot-env.mjs   （后端需在 8000 运行；会真的装一次 PHP，跑完请 winget uninstall）
 */
import puppeteer from 'puppeteer-core'
import { mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = join(__dirname, '..', '..', 'docs', 'screenshots')
mkdirSync(OUT, { recursive: true })

const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function shot(page, name) {
  await page.screenshot({ path: join(OUT, name) })
  console.log('📸', name)
}

/** 在工具卡片上点「一键安装」/「手动安装」 */
async function clickCard(page, keyword, label) {
  await page.evaluate(
    ({ keyword, label }) => {
      const card = [...document.querySelectorAll('.env-card')].find((c) => c.textContent.includes(keyword))
      card?.scrollIntoView({ block: 'center' })
      const btn = [...(card?.querySelectorAll('.env-actions .btn') || [])].find((b) => b.textContent.includes(label))
      btn?.click()
    },
    { keyword, label },
  )
}

async function waitProgress(page, minPercent, timeout = 120000) {
  await page
    .waitForFunction(
      (min) => {
        const el = document.querySelector('.stage-pct')
        return el && Number.parseInt(el.textContent || '0', 10) >= min
      },
      { timeout, polling: 800 },
      minPercent,
    )
    .catch(() => console.log(`   （没等到 ${minPercent}%，照样截图）`))
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
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.evaluateOnNewDocument(() => localStorage.setItem('cm-theme', 'dark'))

  await page.goto(BASE, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.welcome', { timeout: 20000 })

  await page.evaluate(() => document.querySelector('.sidebar .brand .icon-btn')?.click())
  await page.waitForSelector('.dialog', { timeout: 8000 })
  await page.evaluate(() => {
    const tab = [...document.querySelectorAll('.head-tabs button')].find((b) => b.textContent.includes('环境'))
    tab?.click()
  })
  await page.waitForSelector('.env-card', { timeout: 20000 })
  await page.waitForSelector('.assoc-row', { timeout: 20000 })
  await sleep(1200)

  // ① 顶部：折叠的安装路径 + 默认打开方式
  await page.evaluate(() => (document.querySelector('.env-pane').scrollTop = 0))
  await sleep(300)
  await shot(page, '42-env-overview.png')

  // ② 展开安装路径，验证可折叠
  await page.evaluate(() => document.querySelector('.fold-head')?.click())
  await sleep(400)
  await shot(page, '43-env-paths-open.png')
  await page.evaluate(() => document.querySelector('.fold-head')?.click())
  await sleep(250)

  // ③ 工具卡片
  await page.evaluate(() => {
    const card = [...document.querySelectorAll('.env-card')].find((c) => c.textContent.includes('Go'))
    card?.scrollIntoView({ block: 'center' })
  })
  await sleep(300)
  await shot(page, '44-env-cards.png')

  // ④ 手动安装弹窗：官网入口 + 命令（一键复制 / 一键运行）
  await clickCard(page, 'Go', '手动安装')
  await page.waitForSelector('.manual-dialog', { timeout: 6000 })
  await sleep(400)
  await shot(page, '45-env-manual.png')
  await page.evaluate(() => document.querySelector('.manual-dialog .confirm-actions .btn')?.click())
  await sleep(300)

  // ⑤ 一键安装的独立二次确认弹窗（zip 类：Gradle）
  await clickCard(page, 'Gradle', '一键安装')
  await page.waitForSelector('.confirm-mask', { timeout: 6000 })
  await sleep(400)
  await shot(page, '46-env-confirm.png')

  // ⑥ 确认后看阶段性进度条（下载阶段会真的动）
  await page.evaluate(() => document.querySelector('.confirm-actions .btn-primary')?.click())
  await page.waitForSelector('.install-job', { timeout: 8000 })
  console.log('⏳ 等进度条走到 35%…')
  await waitProgress(page, 35, 240000)
  await sleep(600)
  await shot(page, '47-env-progress.png')

  // ⑦ 取消并收起，换一个能装完的（PHP，portable，无 UAC）
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.install-job-head .btn')].find((b) => b.textContent.includes('取消'))
    btn?.click()
  })
  await page.waitForFunction(() => !document.querySelector('.install-job-head .spinner'), { timeout: 90000 }).catch(() => {})
  await sleep(1200)
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.install-job-head .btn')].find((b) => b.textContent.includes('收起'))
    btn?.click()
  })
  await sleep(300)

  await clickCard(page, 'PHP', '一键安装')
  await page.waitForSelector('.confirm-mask', { timeout: 6000 })
  await page.evaluate(() => document.querySelector('.confirm-actions .btn-primary')?.click())
  await page.waitForSelector('.install-job', { timeout: 8000 })
  console.log('⏳ 等 PHP 装完…')
  await page
    .waitForFunction(
      () => {
        const job = document.querySelector('.install-job')
        return job && (job.classList.contains('succeeded') || job.classList.contains('failed'))
      },
      { timeout: 300000, polling: 1500 },
    )
    .catch(() => console.log('   （超时，仍截图）'))
  await sleep(900)
  await shot(page, '48-env-install-done.png')

  // ⑦ 编辑器库：默认打开方式已写进识别关键词
  await page.evaluate(() => {
    const tab = [...document.querySelectorAll('.head-tabs button')].find((b) => b.textContent.includes('编辑器'))
    tab?.click()
  })
  await page.waitForSelector('.ed-detail', { timeout: 8000 })
  await sleep(800)
  await shot(page, '49-editors-synced.png')

  console.log(errors.length ? `⚠️ 控制台错误 ${errors.length} 条` : '✅ 无控制台错误')
  errors.slice(0, 8).forEach((e) => console.log('   ', e.slice(0, 200)))
  await browser.close()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})