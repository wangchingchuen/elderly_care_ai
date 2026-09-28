import messages from '../../caretrace/locales/en.json';

export type Language = 'zh-TW' | 'en';
let language: Language = 'zh-TW';
try { if (localStorage.getItem('caretrace.language') === 'en') language = 'en'; } catch { /* Storage may be disabled. */ }
export const getLanguage = () => language;
export function changeLanguage(value: Language) {
  language = value;
  document.documentElement.lang = value;
  document.title = value === 'en' ? 'CareTrace · Care backed by evidence' : 'CareTrace · 有跡可循的照護';
  try { localStorage.setItem('caretrace.language', value); } catch { /* The current session still works. */ }
}
const catalog: Record<string, string> = messages;
/** Translate system messages only. Never pass resident names, notes or other user content here. */
export function t(key: string, ...values: unknown[]): string {
  const template = language === 'en' ? catalog[key] ?? key : key;
  return template.replace(/\{(\d+)\}/g, (_, index) => String(values[Number(index)] ?? ''));
}
export function systemMessage(value: string): string {
  if (language !== 'en') return value;
  if (catalog[value]) return catalog[value];
  // Persisted worker messages can include a numeric progress value or an exception type.
  return Object.entries(catalog).sort((a,b) => b[0].length-a[0].length)
    .reduce((text, [source, translated]) => source.length > 6 ? text.split(source).join(translated) : text, value)
    .replace(/分析骨架與行為 · ([\d.]+) \/ ([\d.]+) 秒/g, 'Analyzing pose and behavior · $1 / $2 seconds')
    .replace(/語言模型不可用或輸出未通過驗證（([^）]+)），改用關鍵字備援/g, 'Language model unavailable or output invalid ($1); using keyword fallback');
}
changeLanguage(language);
