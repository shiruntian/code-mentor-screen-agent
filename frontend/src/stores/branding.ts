import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useBrandingStore = defineStore('branding', {
  state: () => ({
    name: 'CodeMentor',
    logoUrl: '',
    faviconUrl: '',
  }),
  actions: {
    async load() {
      try {
        const res = await api.get<any>('/api/branding')
        this.name = res.name || 'CodeMentor'
        this.logoUrl = res.logo_url || ''
        this.faviconUrl = res.favicon_url || ''
        this.apply()
      } catch {
        /* 后端没起来就用默认 */
      }
    },
    apply() {
      document.title = this.name
      let link = document.querySelector("link[rel='icon']") as HTMLLinkElement | null
      if (!link) {
        link = document.createElement('link')
        link.rel = 'icon'
        document.head.appendChild(link)
      }
      if (this.faviconUrl) link.href = this.faviconUrl
    },
  },
})
