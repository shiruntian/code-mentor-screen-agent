import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/common'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang, ignoreIllegals: true }).value}</code></pre>`
      } catch {
        /* ignore */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})

// 代码块加语言标签 + 复制按钮占位（交互由组件事件委托处理）
const defaultFence = md.renderer.rules.fence!
md.renderer.rules.fence = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const lang = (token.info || '').trim().split(/\s+/)[0] || 'text'
  const highlighted = defaultFence(tokens, idx, options, env, self)
  const withBar = highlighted.replace(
    '<pre class="hljs">',
    `<div class="code-block"><div class="code-bar"><span>${lang}</span><button class="code-copy" data-code="${encodeURIComponent(
      token.content,
    )}">复制</button></div><pre class="hljs">`,
  )
  return withBar + '</div>'
}

export function renderMarkdown(text: string): string {
  if (!text) return ''
  const html = md.render(text)
  return DOMPurify.sanitize(html, { ADD_ATTR: ['data-code', 'target'] })
}