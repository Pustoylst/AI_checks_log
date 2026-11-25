// Execute the real page script and exercise its registered overview handlers.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8');

async function check(storageBlocked) {
  const elements = new Map();
  function element() {
    const text = { textContent: 'Кнопка' };
    return {
      value: '', textContent: '', innerHTML: '', hidden: true, disabled: false,
      dataset: {}, style: {}, events: {},
      querySelector: (selector) => selector === '.spinner' ? { hidden: true } : text,
      addEventListener(name, fn) { this.events[name] = fn; },
      scrollIntoView() {}, append() {}, appendChild() {},
    };
  }
  for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set('#' + match[1], element());
  elements.get('#share-focus').value = 'errors';
  elements.get('#share-overview-limit').value = '0';
  const requests = [];
  let fail = false;
  const context = {
    document: {
      querySelector: (selector) => elements.get(selector) || null,
      querySelectorAll: () => [], createElement: () => element(),
    },
    localStorage: {
      getItem() { if (storageBlocked) throw new Error('Storage denied'); return null; },
      setItem() { if (storageBlocked) throw new Error('Storage denied'); },
    },
    URLSearchParams, Date, console, setInterval, clearInterval,
    fetch: async (url, options) => {
      requests.push([url, options]);
      return {
        ok: !fail,
        json: async () => fail ? { detail: 'Папка недоступна' }
          : url.includes('/overview/analyze') ? { result: 'Анализ готов' }
          : { report: 'Сводка', stats: { files_scanned: 1 } },
      };
    },
  };
  vm.runInNewContext(source, context);
  const markdown = context.renderMarkdown(
    '# Анализ\n\n**Ошибка:** `BrokerNotAvailableException`\n\n' +
    '- Причина: *RabbitMQ недоступен*\n' +
    '- [Документация](https://example.test/help)\n\n' +
    '```text\n<unsafe>\n```\n\n' +
    '[опасная ссылка](javascript:alert(1))\n<img src=x onerror=alert(1)>',
  );
  assert.match(markdown, /<h1>Анализ<\/h1>/);
  assert.match(markdown, /<strong>Ошибка:<\/strong>/);
  assert.match(markdown, /<code>BrokerNotAvailableException<\/code>/);
  assert.match(markdown, /<ul>[\s\S]*<li>Причина: <em>RabbitMQ недоступен<\/em><\/li>/);
  assert.match(markdown, /href="https:\/\/example\.test\/help"/);
  assert.match(markdown, /&lt;unsafe&gt;/);
  assert.doesNotMatch(markdown, /href="javascript:/i);
  assert.match(markdown, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.equal(elements.get('#startup-message').hidden, true);
  elements.get('#repo-path').events.input();
  const preview = elements.get('#share-overview-preview-button');
  const analyze = elements.get('#share-overview-analyze-button');
  const all = elements.get('#share-overview-button');
  assert.equal(typeof preview.events.click, 'function');
  await preview.events.click();
  assert.equal(requests.length, 1);
  assert.equal(elements.get('#share-overview-panel').hidden, false);
  assert.equal(analyze.disabled, false);
  await analyze.events.click();
  assert.equal(requests.length, 2);
  assert.equal(elements.get('#share-overview-analysis').hidden, false);
  await all.events.click();
  assert.equal(requests.length, 4);
  assert.match(requests[3][0], /overview\/analyze/);
  fail = true;
  await preview.events.click();
  assert.equal(elements.get('#share-overview-message').textContent, 'Папка недоступна');
  assert.equal(preview.disabled, false);
  assert.equal(analyze.disabled, true);
}
(async () => {
  await check(false);
  await check(true);
  console.log('PASS overview buttons: preview, analysis, combined flow, error, blocked storage');
})().catch(error => { console.error(error); process.exitCode = 1; });
