from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "dashboard/static/web2/index.html"
JS = ROOT / "dashboard/static/web2/news_center_v12.js"
CSS = ROOT / "dashboard/static/web2/news_center_v12.css"


def test_news_center_assets_are_connected():
    html = INDEX.read_text(encoding="utf-8")
    assert "news_center_v12.js?" in html
    assert "news_center_v12.css?" in html
    assert 'data-page="news"' in html
    assert html.index("news_center_v12.css") < html.index("news_center_v12.js")


def test_news_center_uses_real_api_and_source_fields():
    source = JS.read_text(encoding="utf-8")
    assert "/api/social-news" in source
    assert "image_url" in source
    assert "source_url" in source
    assert "credibility" in source
    assert "related_assets" in source
    assert "Открыть источник" in source
    assert "Открыть на графике" in source


def test_news_center_has_no_demo_news_payload():
    source = JS.read_text(encoding="utf-8").lower()
    forbidden = ["math.random", "demo headline", "пример новости", "тестовая новость"]
    for marker in forbidden:
        assert marker not in source


def test_news_center_has_filters_and_mobile_styles():
    source = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "verifiedNewsOnly" in source
    assert "importantNewsOnly" in source
    assert "newsSearch" in source
    assert "newsFilter" in source
    assert "@media(max-width:760px)" in css


def test_recent_view_orders_publication_time_and_preserves_unknown_dates_in_archive():
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the actual News renderer behavior")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const now = Date.parse('2026-09-19T17:00:00Z');
Date.now = () => now;
const listeners = {}, elements = {}, box = {innerHTML: ''};
const element = id => elements[id] ||= {value: '', addEventListener: (event, fn) => { listeners[id + event] = fn; }};
const document = {getElementById: id => id === 'content' ? box : element(id),
  querySelector: () => ({dataset: {page: 'news'}}), addEventListener: () => {}};
let start;
const item = (title, published_at, extra = {}) => ({title, published_at, credibility_percent: 90,
  timestamp_quality: 'source_timestamp', source_name: 'Source', ...extra});
const items = [item('OLD-SEP4', '2026-09-04T12:00:00Z', {urgency: 'high'}),
  item('RECENT-EARLIER', '2026-09-19T09:00:00Z'), item('RECENT-LATEST', '2026-09-19T16:00:00Z'),
  item('OLD-SEP12', '2026-09-12T12:00:00Z'), item('MISSING', null, {checked_at: new Date(now).toISOString()}),
  item('FETCH-FALLBACK', new Date(now).toISOString(), {timestamp_quality: 'fetch_fallback_future_skew'}),
  item('FUTURE', '2026-09-20T12:00:00Z')];
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {document, Date, console, setTimeout,
  localStorage: {getItem: () => '{}'}, window: {addEventListener: (_, fn) => {start = fn;}},
  fetch: async () => ({ok: true, json: async () => ({news: {items}, last_refresh_at: now / 1000,
    rss_diagnostics: {failed_or_empty_sources: 20}})})});
(async () => {
  start(); await new Promise(resolve => setImmediate(resolve));
  assert(box.innerHTML.includes('RECENT-LATEST'));
  assert(box.innerHTML.indexOf('RECENT-LATEST') < box.innerHTML.indexOf('RECENT-EARLIER'));
  for (const title of ['OLD-SEP4','OLD-SEP12','MISSING','FETCH-FALLBACK','FUTURE']) assert(!box.innerHTML.includes(title));
  assert(box.innerHTML.includes('Ошибки / пустые источники: 20'));
  listeners.newsPeriodchange({target: {value: 'archive'}});
  for (const title of ['OLD-SEP4','OLD-SEP12','MISSING','FETCH-FALLBACK','FUTURE']) assert(box.innerHTML.includes(title));
  assert(!box.innerHTML.includes('RECENT-LATEST'));
  assert(box.innerHTML.includes('Время публикации не подтверждено'));
  assert(box.innerHTML.includes('АРХИВ'));
  items.splice(1, 2); // Successful collection with only old/unknown items isn't fresh.
  await listeners.newsReloadclick();
  listeners.newsPeriodchange({target: {value: 'recent'}});
  assert(box.innerHTML.includes('НЕТ СВЕЖИХ'));
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    subprocess.run([node, "-e", script, str(JS)], check=True, capture_output=True, text=True)
