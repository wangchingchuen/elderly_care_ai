const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const catalog = JSON.parse(fs.readFileSync(path.join(root, '../caretrace/locales/en.json'), 'utf8'));
const cjk = /[\u3400-\u9fff]/;
for (const [key, value] of Object.entries(catalog)) {
  assert(value.trim() && !cjk.test(value), 'Missing English translation: '+key);
  assert.deepEqual((key.match(/\{\d+\}/g) || []).sort(), (value.match(/\{\d+\}/g) || []).sort(), 'Placeholder mismatch: '+key);
}
const code = fs.readFileSync(path.join(root, 'src/main.tsx'), 'utf8');
const tree = ts.createSourceFile('main.tsx', code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function visit(node) {
  if (ts.isCallExpression(node) && ['t', 'setNotice', 'setError'].includes(node.expression.getText(tree))) {
    const key = node.arguments[0];
    if (key && ts.isStringLiteral(key) && cjk.test(key.text)) assert(key.text in catalog, 'Untranslated message: '+key.text);
  }
  if (ts.isJsxText(node)) assert(!cjk.test(node.text), 'Untranslated JSX: '+node.text);
  ts.forEachChild(node, visit);
}
visit(tree);
// Execute the actual translator, including persistence and disabled browser storage.
const compiled = ts.transpileModule(fs.readFileSync(path.join(root, 'src/i18n.ts'), 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS, esModuleInterop:true},
}).outputText;
for (const blocked of [false, true]) {
  const memory = new Map([['caretrace.language', 'en']]);
  const context = {exports:{}, document:{documentElement:{}, title:''},
    require: () => catalog,
    localStorage:{
      getItem(key) {if(blocked) throw Error('Disabled'); return memory.get(key);},
      setItem(key, value) {if(blocked) throw Error('Disabled'); memory.set(key,value);},
    }};
  vm.runInNewContext(compiled, context);
  const {t, changeLanguage, systemMessage, getLanguage} = context.exports;
  assert.equal(getLanguage(), blocked ? 'zh-TW' : 'en');
  changeLanguage('en');
  assert.equal(t('為 {0} 建立可回看的照護證據。', '住民 A'), 'Create replayable care evidence for 住民 A.');
  assert.equal(systemMessage('分析骨架與行為 · 1.0 / 15.0 秒'), 'Analyzing pose and behavior · 1.0 / 15.0 seconds');
  assert.equal(systemMessage('ValueError: 影片沒有可分析的影格'), 'ValueError: The video has no analyzable frames');
  assert(!cjk.test(systemMessage('語言模型不可用或輸出未通過驗證（RuntimeError），改用關鍵字備援')));
  changeLanguage('zh-TW');
  assert.equal(t('照護總覽'), '照護總覽');
  assert.equal(context.document.documentElement.lang, 'zh-TW');
  if (!blocked) assert.equal(memory.get('caretrace.language'), 'zh-TW');
}
console.log('Translation catalog, placeholders, UI coverage, persistence and fallback checks passed.');
