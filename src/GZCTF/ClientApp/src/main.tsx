import { App } from '@App'
import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import resourcesToBackend from 'i18next-resources-to-backend'
import ReactDOM from 'react-dom/client'
import { initReactI18next } from 'react-i18next'
import { BrowserRouter } from 'react-router'
import manifest from 'virtual:i18n-manifest'
import { convertLanguage, LanguageProvider } from '@Utils/I18n'

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .use(
    // implement by custom vite plugin, see plugins/vite-i18n-virtual-manifest.ts
    resourcesToBackend(async (lang: string, _: string) => {
      const file = manifest[lang.toLowerCase()]
      if (!file) return {}
      const response = await fetch(`${import.meta.env.BASE_URL}static/${file}`)
      return response.json()
    })
  )
  .init({
    fallbackLng: convertLanguage,
    interpolation: {
      escapeValue: false,
    },
    detection: {
      convertDetectedLanguage: convertLanguage,
    },
  })

const app = ReactDOM.createRoot(document.getElementById('root')!)

app.render(
  <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || undefined}>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </BrowserRouter>
)
