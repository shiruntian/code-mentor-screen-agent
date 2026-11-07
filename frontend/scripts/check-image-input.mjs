/**
 * 验证「粘贴上传 / 拖拽上传 / 点击放大预览」三件事，并截 54~56 图。
 *
 * 用 DataTransfer + ClipboardEvent/DragEvent 合成事件，走的是真实的前端代码路径
 * （会真的把图片 POST 到 /api/files/upload，所以需要后端在跑）。
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
page.on('requestfailed', (r) => errors.push(`REQ FAIL ${r.url()}`))
await page.evaluateOnNewDocument(() => localStorage.setItem('cm-theme', 'dark'))
await page.goto(BASE, { waitUntil: 'networkidle2' })
await page.waitForSelector('.composer', { timeout: 25000 })
await sleep(600)

// 造一张假截图（画个带文字的图，方便看放大效果）
await page.evaluate(() => {
  window.__makeShot = async (label, hue) => {
    const c = document.createElement('canvas')
    c.width = 900
    c.height = 560
    const g = c.getContext('2d')
    g.fillStyle = `hsl(${hue} 45% 18%)`
    g.fillRect(0, 0, c.width, c.height)
    g.fillStyle = '#e2e8f0'
    g.font = 'bold 54px Consolas, monospace'
    g.fillText(label, 48, 110)
    g.font = '26px Consolas, monospace'
    g.fillStyle = '#7dd3fc'
    ;['Traceback (most recent call last):', '  File "main.py", line 12, in <module>', '    print(1 / 0)', 'ZeroDivisionError: division by zero'].forEach(
      (line, i) => g.fillText(line, 48, 190 + i * 46),
    )
    g.strokeStyle = 'rgba(255,255,255,0.25)'
    g.strokeRect(24, 24, c.width - 48, c.height - 48)
    const blob = await new Promise((r) => c.toBlob(r, 'image/png'))
    return new File([blob], `${label}.png`, { type: 'image/png' })
  }
})

// ---------------------------------------------------------------- 粘贴
const pasted = await page.evaluate(async () => {
  const el = document.querySelector('.editor')
  el.focus()
  const file = await window.__makeShot('paste-shot', 210)
  const dt = new DataTransfer()
  dt.items.add(file)
  el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
  return true
})
await page.waitForSelector('.preview', { timeout: 15000 })
await sleep(500)
const count1 = await page.evaluate(() => document.querySelectorAll('.preview').length)
console.log(`粘贴上传：${pasted ? '触发成功' : '失败'}，缩略图 ${count1} 张`, count1 === 1 ? '✓' : '✗')

await page.screenshot({
  path: join(OUT, '54-paste-upload.png'),
  clip: { x: 340, y: 780, width: 1000, height: 250 },
})

// ---------------------------------------------------------------- 点击放大
await page.evaluate(() => document.querySelector('.preview').click())
await page.waitForSelector('.lightbox', { timeout: 8000 })
await sleep(600)
const lb = await page.evaluate(() => ({
  open: !!document.querySelector('.lightbox'),
  name: document.querySelector('.lb-name')?.textContent?.trim(),
  scale: document.querySelector('.lb-scale')?.textContent?.trim(),
  imgW: document.querySelector('.lb-img')?.naturalWidth,
  tip: document.querySelector('.lb-tip')?.textContent?.trim(),
}))
console.log('放大预览:', JSON.stringify(lb))
await page.screenshot({ path: join(OUT, '55-image-lightbox.png') })

// 滚轮放大 + Esc 关闭
await page.evaluate(() => {
  const stage = document.querySelector('.lb-stage')
  stage.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true }))
})
await sleep(300)
const zoomed = await page.evaluate(() => document.querySelector('.lb-scale')?.textContent?.trim())
console.log('滚轮放大后:', zoomed)
await page.screenshot({ path: join(OUT, '56-lightbox-zoom.png') })

await page.keyboard.press('Escape')
await sleep(300)
const closed = await page.evaluate(() => !document.querySelector('.lightbox'))
console.log('Esc 关闭:', closed ? '✓' : '✗')

// ---------------------------------------------------------------- 拖拽
await page.evaluate(async () => {
  const composer = document.querySelector('.composer')
  const file = await window.__makeShot('drag-shot', 150)
  const dt = new DataTransfer()
  dt.items.add(file)
  composer.dispatchEvent(new DragEvent('dragenter', { dataTransfer: dt, bubbles: true, cancelable: true }))
  composer.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, cancelable: true }))
})
await sleep(400)
const hint = await page.evaluate(() => document.querySelector('.drop-hint')?.textContent?.replace(/\s+/g, ' ').trim())
console.log('拖入提示:', hint || '（没出现）')
await page.screenshot({
  path: join(OUT, '57-drag-upload-hint.png'),
  clip: { x: 340, y: 780, width: 1000, height: 250 },
})

await page.evaluate(async () => {
  const composer = document.querySelector('.composer')
  const file = await window.__makeShot('drag-shot', 150)
  const dt = new DataTransfer()
  dt.items.add(file)
  composer.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }))
})
await sleep(900)
const after = await page.evaluate(() => ({
  previews: document.querySelectorAll('.preview').length,
  hintGone: !document.querySelector('.drop-hint'),
}))
console.log(`拖拽上传后：缩略图 ${after.previews} 张，提示层已消失 ${after.hintGone}`)

// 清理：把两张缩略图都删掉，别留在输入框里
await page.evaluate(() => {
  document.querySelectorAll('.preview .remove').forEach((b) => b.click())
})
await sleep(300)
const cleared = await page.evaluate(() => document.querySelectorAll('.preview').length)
console.log('清理缩略图:', cleared === 0 ? '✓' : `✗ 还剩 ${cleared}`)

console.log(errors.length ? `控制台错误 ${errors.length} 条: ${errors.slice(0, 3).join(' | ')}` : '✅ 无控制台错误')
await browser.close()