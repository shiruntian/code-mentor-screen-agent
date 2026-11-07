/** 初始包实拍：把解压后的包跑起来，截一张默认状态（logo / 名称 / 空对话）的首页。 */
import puppeteer from 'puppeteer-core'
import { join } from 'node:path'

const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8010'
const OUT = process.env.OUT_DIR || '.'

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
await new Promise((r) => setTimeout(r, 1200))

const state = await page.evaluate(() => ({
  name: document.querySelector('.brand .name')?.textContent?.trim(),
  hasLogo: !!document.querySelector('.brand .logo img'),
  logoLoaded: (() => {
    const img = document.querySelector('.brand .logo img')
    return img ? img.complete && img.naturalWidth > 0 : false
  })(),
  brandSub: document.querySelector('.brand .sub')?.textContent?.trim(),
  welcome: document.querySelector('.welcome h1')?.textContent?.replace(/\s+/g, ' ').trim(),
  conversations: document.querySelectorAll('.conv-item').length,
}))
console.log('页面状态:', JSON.stringify(state, null, 0))
await page.screenshot({ path: join(OUT, '50-initial-package.png') })
console.log(errors.length ? `控制台错误 ${errors.length} 条` : '✅ 无控制台错误')
await browser.close()