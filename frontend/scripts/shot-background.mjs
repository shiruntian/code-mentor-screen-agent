/**
 * 自定义背景效果截图：验证图片/视频背景 + 半透明磨砂面板。
 * 用法：node scripts/shot-background.mjs [图片URL]
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
const BG_URL = process.argv[2] || '/static/backgrounds/demo-bg.jpg'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

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

  await page.evaluateOnNewDocument((url) => {
    localStorage.setItem('cm-theme', 'dark')
    localStorage.setItem(
      'cm-bg',
      JSON.stringify({ kind: 'image', url, blur: 14, dim: 0.5, leftAlpha: 0.3, rightAlpha: 0.68 }),
    )
  }, BG_URL)

  await page.goto(BASE, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.welcome', { timeout: 20000 })
  await sleep(900)

  const applied = await page.evaluate(() => ({
    dataBg: document.documentElement.dataset.bg,
    hasLayer: !!document.querySelector('.bg-layer'),
    hasMedia: !!document.querySelector('.bg-media'),
    surface: getComputedStyle(document.documentElement).getPropertyValue('--surface').trim(),
  }))
  console.log('背景状态:', JSON.stringify(applied))

  await page.screenshot({ path: join(OUT, '25-bg-welcome.png') })
  console.log('📸 25-bg-welcome.png')

  // 打开设置看背景选择器
  await page.evaluate(() => {
    const btn = document.querySelector('.sidebar .brand .icon-btn')
    btn && btn.click()
  })
  await page.waitForSelector('.dialog', { timeout: 8000 })
  await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.head-tabs button')]
    const t = tabs.find((x) => x.textContent.includes('外观'))
    t && t.click()
  })
  await sleep(900)
  await page.screenshot({ path: join(OUT, '26-bg-settings.png') })
  console.log('📸 26-bg-settings.png')

  await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('.head-tabs button')]
    const t = tabs.find((x) => x.textContent.includes('运行参数'))
    t && t.click()
  })
  await sleep(600)
  await page.screenshot({ path: join(OUT, '27-settings-runtime.png') })
  console.log('📸 27-settings-runtime.png')

  console.log(errors.length ? `⚠️ 控制台错误 ${errors.length} 条` : '✅ 无控制台错误')
  errors.slice(0, 5).forEach((e) => console.log('   ', e.slice(0, 160)))
  await browser.close()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})