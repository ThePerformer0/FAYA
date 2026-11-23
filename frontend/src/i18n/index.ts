import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import fr from "./fr.json";

export const SUPPORTED_LANGUAGES = ["fr", "en"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

const STORAGE_KEY = "faya_lang";

function detectInitialLanguage(): SupportedLanguage {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "fr" || stored === "en") {
      return stored;
    }
  } catch {
    // Stockage local indisponible (mode privé strict)
  }

  const preferred = navigator.languages ?? [navigator.language];
  for (const locale of preferred) {
    const base = locale.toLowerCase().split("-")[0];
    if (base === "fr" || base === "en") {
      return base;
    }
  }
  return "fr";
}

const initialLanguage = detectInitialLanguage();

void i18n.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: initialLanguage,
  fallbackLng: "fr",
  interpolation: {
    escapeValue: false,
  },
});

function syncHtmlLang(lang: string): void {
  const normalized: SupportedLanguage = lang.startsWith("en") ? "en" : "fr";
  document.documentElement.lang = normalized;
}

syncHtmlLang(initialLanguage);

i18n.on("languageChanged", (lang) => {
  syncHtmlLang(lang);
  try {
    window.localStorage.setItem(STORAGE_KEY, lang.startsWith("en") ? "en" : "fr");
  } catch {
    // Ignorer si le stockage local est bloqué
  }
});

export function setAppLanguage(lang: SupportedLanguage): void {
  void i18n.changeLanguage(lang);
}

export function getActiveLanguage(): SupportedLanguage {
  return i18n.language.startsWith("en") ? "en" : "fr";
}

export default i18n;
