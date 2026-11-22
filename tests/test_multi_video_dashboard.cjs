/* Run from the workspace with Node.js 22+, Python, and Edge: node tests/test_multi_video_dashboard.cjs */
'use strict';

const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { existsSync } = require('node:fs');
const { readFile, open } = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');
const { waitUntil, runScenario, withBrowser } = require('./test_rescue_demo.cjs');

const workspace = path.resolve(__dirname, '..');
const runPath = '/evaluation/final_quality_pass';
const videos = ['P06_02', 'P06_08', 'P09_01', 'P09_04', 'P14_02', 'P14_03'];
const models = { stock: 'stock', refined: 'factorized-refined' };
const originalPath = id => `/data/EPIC/development/EPIC-KITCHENS/${id.split('_')[0]}/videos/${id}.MP4`;
const jsonPath = (arm, id) => `${runPath}/${models[arm]}/${id}.json`;
const localPath = url => path.join(workspace, url.slice(1));
const mediaRoutes = new Map();
const mediaPath = id => mediaRoutes.get(id);

async function startDashboard() {
  const venv = path.join(workspace, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const python = process.env.AURA_DASHBOARD_PYTHON ||
    (existsSync(venv) ? venv : process.platform === 'win32' ? 'python' : 'python3');
  const child = spawn(python, ['-B', 'examples/make_multi_video_dashboard.py', '--serve', '--port', '0'], {
    cwd: workspace, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
  });
  const messages = { stdout: '', stderr: '', error: null };
  for (const stream of ['stdout', 'stderr']) {
    child[stream].setEncoding('utf8');
    child[stream].on('data', data => { messages[stream] += data; });
  }
  child.on('error', error => { messages.error = error; });
  const close = async () => {
    if (!child.pid || child.exitCode !== null) return;
    const exited = new Promise(resolve => child.once('exit', resolve));
    child.kill();
    await Promise.race([exited, delay(2000)]);
  };
  try {
    const address = await waitUntil(() => {
      if (messages.error) throw messages.error;
      if (child.exitCode !== null) throw Error(`Dashboard server stopped (${child.exitCode})\n${messages.stderr}`);
      return /^http:\/\/127\.0\.0\.1:\d+\/[^\r\n]+/m.exec(messages.stdout)?.[0];
    }, 'the Python dashboard server', 20000);
    return { address, fixtures() {}, close };
  } catch (error) {
    await close();
    throw error;
  }
}

async function inspectRoutes(address) {
  const response = await fetch(address);
  assert.equal(response.status, 200);
  const configText = /<script\b(?=[^>]*\bid=["']demo-config["'])[^>]*>([\s\S]*?)<\/script>/i.exec(await response.text());
  assert(configText, 'Dashboard must publish its model route metadata');
  const config = JSON.parse(configText[1]);
  assert.deepEqual(config.clips.map(clip => clip.videoId), videos);
  const fixtures = new Map();
  for (const clip of config.clips) {
    const id = clip.videoId;
    const expected = {};
    for (const [arm, configKey] of [['stock', 'stockUrl'], ['refined', 'refinedUrl']]) {
      const url = new URL(clip[configKey], address);
      assert.equal(url.href, new URL(jsonPath(arm, id), address).href);
      const payload = await readFile(localPath(jsonPath(arm, id)));
      const served = await fetch(url);
      assert.equal(served.status, 200);
      assert.deepEqual(Buffer.from(await served.arrayBuffer()), payload);
      expected[arm] = JSON.parse(payload);
      assert.equal(expected[arm].video_id, id);
    }
    const video = new URL(clip.videoUrl, address);
    assert.equal(video.origin, new URL(address).origin);
    assert([originalPath(id), `/development-media/${id}.MP4`].includes(video.pathname));
    mediaRoutes.set(id, video.pathname);
    const source = await open(localPath(originalPath(id)), 'r');
    try {
      const { size } = await source.stat();
      const start = Math.floor(size / 2);
      const end = start + 31;
      const range = await fetch(video, { headers: { Range: `bytes=${start}-${end}` } });
      assert.equal(range.status, 206);
      assert.equal(range.headers.get('Content-Range'), `bytes ${start}-${end}/${size}`);
      const { buffer, bytesRead } = await source.read(Buffer.alloc(32), 0, 32, start);
      assert.equal(bytesRead, 32);
      assert.deepEqual(Buffer.from(await range.arrayBuffer()), buffer);
    } finally {
      await source.close();
    }
    fixtures.set(id, { ...expected, metrics: clip.metrics });
  }
  assert.equal((await fetch(new URL('/TEAM_ID/weights/tokenizer.json', address))).status, 404);
  console.log('PASS actual production dashboard routes, 12 original JSON files, and six MP4 byte ranges');
  return fixtures;
}

async function startFaultProxy(address) {
  const dashboard = new URL(address);
  const routes = new Set([dashboard.pathname, ...videos.flatMap(id =>
    [mediaPath(id), ...Object.keys(models).map(arm => jsonPath(arm, id))])]);
  let fixtures = {};
  const server = http.createServer((request, response) => {
    const source = new URL(request.url, dashboard.origin);
    const name = source.pathname;
    if (!routes.has(name) || source.origin !== dashboard.origin || fixtures.missing?.includes(name)) {
      response.writeHead(404, { 'Cache-Control': 'no-store' }).end();
      return;
    }
    function forward() {
      if (response.destroyed) return;
      const upstream = http.request(fixtures.wrong?.[name] ? new URL(fixtures.wrong[name], dashboard) : source, {
        method: request.method, headers: request.headers.range ? { Range: request.headers.range } : {},
      }, incoming => {
        response.writeHead(incoming.statusCode, { ...incoming.headers, 'Cache-Control': 'no-store' });
        incoming.pipe(response);
      });
      upstream.on('error', () => { if (!response.destroyed) response.destroy(); });
      response.on('close', () => upstream.destroy());
      upstream.end();
    }
    if (fixtures.slow?.path === name) {
      fixtures.slow.requested = true;
      setTimeout(forward, fixtures.slow.ms);
    } else forward();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {
    address: `http://127.0.0.1:${server.address().port}${dashboard.pathname}`,
    fixtures: value => { fixtures = value; },
    close: () => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); },
  };
}

const selectors = `
  const selected = () => document.querySelector('#video-select');
  const panel = arm => document.querySelector('article[data-model="' + arm + '"]');
  const payload = arm => JSON.parse(panel(arm)?.querySelector('pre')?.textContent || 'null');
  const original = () => document.querySelector('#original');
  const excerpts = () => [...document.querySelectorAll('.excerpt')];
  const btn = id => document.getElementById(id);
`;

function probe(page, expression) {
  return page.evaluate(`(() => { ${selectors} return (${expression}); })()`);
}

async function select(page, id) {
  await probe(page, `(() => { selected().value = ${JSON.stringify(id)}; selected().dispatchEvent(new Event('change', { bubbles: true })); })()`);
}

async function waitForClip(page, id, { stock = 'ready', refined = 'ready', media = true } = {}) {
  const expectedId = JSON.stringify(id);
  const status = `document.querySelector('main').dataset.videoId === ${expectedId}
    && selected()?.value === ${expectedId}
    && panel('stock')?.dataset.state === ${JSON.stringify(stock)}
    && panel('refined')?.dataset.state === ${JSON.stringify(refined)}`;
  try {
    await waitUntil(() => probe(page, status + (media ? ` && original().readyState >= 1
      && new URL(original().currentSrc).pathname === ${JSON.stringify(mediaPath(id))}` : '')),
    `${id} dashboard state`, 14000);
  } catch (error) {
    const current = await probe(page, `({ id: document.querySelector('main').dataset.videoId,
      stock: panel('stock')?.dataset.state, refined: panel('refined')?.dataset.state,
      source: original()?.currentSrc, ready: original()?.readyState, status: btn('demo-status')?.textContent })`);
    throw Error(`${error.message}: ${JSON.stringify(current)}`);
  }
}

async function assertClip(page, id, expected) {
  await waitForClip(page, id);
  const actual = await probe(page, `['stock','refined'].map(arm => ({
    prediction: payload(arm), activity: panel(arm).querySelector('.activity').textContent,
    segments: [...document.querySelectorAll('.track[data-model="' + arm + '"] .segment[data-seek]')]
      .map(button => Number(button.dataset.seek)).sort((a,b) => a-b),
  }))`);
  for (const [index, arm] of Object.keys(models).entries()) {
    const prediction = expected[arm];
    assert.deepEqual(actual[index].prediction, prediction);
    assert(actual[index].activity.toLowerCase().includes(prediction.label.name));
    assert(actual[index].activity.includes(prediction.label.score.toFixed(4)));
    assert.deepEqual(actual[index].segments,
      [...prediction.actions, ...prediction.highlights].map(entry => entry.segment[0]).sort((a,b) => a-b));
  }
  const local = await probe(page, `({ heading: btn('per-video-metrics').querySelector('h2').textContent,
    counts: [...btn('per-video-metrics').querySelectorAll('tbody tr')].map(row =>
      [...row.children].slice(1, 5).map(cell => Number(cell.textContent))) })`);
  assert(local.heading.includes(id));
  assert.deepEqual(local.counts, Object.keys(models).map(arm => {
    const metric = expected.metrics[arm];
    return [metric.predicted_actions, metric.true_positives, metric.false_positives, metric.false_negatives];
  }));
}

async function earlyPlay(page) {
  await waitUntil(() => probe(page, `excerpts().length === 2 && excerpts().every(video => video.readyState >= 1 && !video.seeking)
    && !btn('play').disabled`), 'enabled excerpt playback', 15000);
  await probe(page, `btn('play').click()`);
  await waitUntil(() => probe(page, 'excerpts().every(video => !video.paused && !video.seeking)'), 'paired excerpt playback', 14000);
}

async function checkAllClips(page, expected) {
  assert.deepEqual(await probe(page, `[...selected().options].map(option => option.value)`), videos);
  const aggregates = (await probe(page, `btn('evaluation-overview').textContent`)).replace(/\s/g, '');
  for (const phrase of ['1.081%', '1.622%', '1/44']) assert(aggregates.includes(phrase), `Missing aggregate: ${phrase}`);
  assert.match(aggregates, /50(?:\.0+)?%/, 'Missing refined precision');
  for (const id of videos) {
    await select(page, id);
    await assertClip(page, id, expected.get(id));
    if (id === 'P06_02') {
      assert.match((await probe(page, `document.querySelector('main').textContent`)).toLowerCase(), /false positive/);
      const referenceTracks = await probe(page, `btn('timeline-tracks').textContent`);
      assert.match(referenceTracks.toLowerCase(), /reference/);
      assert(await probe(page, `Boolean(document.querySelector('.segment.reference[data-seek="3.14"]'))`));
    }
    if (id === 'P09_04') {
      const evidence = await probe(page, `btn('clip-evidence').textContent`);
      assert.match(evidence.toLowerCase(), /cupboard|jar|bag/);
      assert.equal(expected.get(id).stock.actions[0].verb, 'wash');
      assert.equal(expected.get(id).refined.actions.length, 0);
      assert.equal(expected.get(id).stock.highlights.length, 3);
    }
    if (id === 'P14_03') {
      const evidence = await probe(page, `btn('clip-evidence').textContent`);
      assert.match(evidence.toLowerCase(), /(?:camera|viewpoint).*motion|motion.*(?:camera|viewpoint)/s);
      assert.match(evidence, /0\.87[0-9]*/);
      assert.match(evidence, /0\.20[0-9]*|0\.21/);
    }
  }
}

async function checkComplexPlayback(page, expected) {
  await select(page, 'P09_04');
  await waitForClip(page, 'P09_04');
  await earlyPlay(page);
  const highlights = expected.get('P09_04').stock.highlights.map(row => row.segment);
  // Speed up progression while keeping both decoders and all boundaries active.
  await probe(page, `excerpts().forEach(video => { video.defaultPlaybackRate = 4; video.playbackRate = 4; })`);
  for (const [start, end] of highlights) {
    await waitUntil(() => probe(page, `excerpts().every(video => !video.paused && !video.seeking
      && video.currentTime >= ${start} - 0.03 && video.currentTime < ${end})`),
    `both P09_04 excerpts in ${start}–${end}`, 12000);
  }
  const end = highlights.at(-1)[1];
  await waitUntil(() => probe(page, `excerpts().every(video => video.paused && !video.seeking
    && Math.abs(video.currentTime - ${end}) < 0.03)`), 'P09_04 final boundary', 15000);
}

async function checkRace(page, expected, slow) {
  await waitForClip(page, 'P06_02');
  await earlyPlay(page);
  await probe(page, `window.auraOldMedia = [original(), ...excerpts()]`);
  await select(page, 'P06_08');
  await waitUntil(() => slow.requested, 'intermediate JSON request');
  await select(page, 'P14_03');
  await assertClip(page, 'P14_03', expected.get('P14_03'));
  await delay(slow.ms + 100);
  await assertClip(page, 'P14_03', expected.get('P14_03'));
  assert(await probe(page, `[...window.auraOldMedia, original(), ...excerpts()].every(video => video.paused)`));
  assert(await probe(page, `Number(btn('drift-status').dataset.samples) === 0`));
  assert(await probe(page, `excerpts().every(video => !video.currentSrc || new URL(video.currentSrc).pathname === ${JSON.stringify(mediaPath('P14_03'))})`));
}

async function checkFaults(page) {
  await select(page, 'P09_04');
  await waitForClip(page, 'P09_04', { stock: 'error' });
  assert(await probe(page, `payload('refined')?.video_id === 'P09_04' && panel('stock').querySelector('.model-output').hidden`));
  assert.match(await probe(page, `panel('stock').querySelector('.data-message').textContent`), /P09_04|wrong|invalid/i);
  await select(page, 'P14_02');
  await waitForClip(page, 'P14_02', { refined: 'error' });
  assert.match(await probe(page, `panel('refined').querySelector('.data-message').textContent`), /404|unavailable|could not/i);
  assert(await probe(page, `payload('stock')?.video_id === 'P14_02' && panel('refined').querySelector('.model-output').hidden`));
  await select(page, 'P14_03');
  await waitForClip(page, 'P14_03', { media: false });
  await waitUntil(() => probe(page, `original().error && btn('play').disabled`), 'failed original media');
  assert.match(await probe(page, `btn('source-status').textContent`), /could not|unavailable|failed/i);
  await select(page, 'P06_02');
  await waitForClip(page, 'P06_02');
  assert(await probe(page, `!original().error && payload('stock').video_id === 'P06_02'`));
}

async function checkMobile(page) {
  await page.send('Emulation.setDeviceMetricsOverride', { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
  await page.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  await select(page, 'P14_03');
  await waitForClip(page, 'P14_03');
  assert(await probe(page, `(() => {
    for (const arm of ['stock','refined']) panel(arm).querySelector('details').open = true;
    const stock = panel('stock').getBoundingClientRect();
    const refined = panel('refined').getBoundingClientRect();
    return document.documentElement.scrollWidth <= innerWidth + 1 && refined.top >= stock.bottom - 1;
  })()`), 'Mobile content must stack and stay in the viewport width');
  const target = await probe(page, `(() => {
    const button = document.querySelector('.track[data-model="stock"] .segment[data-seek="16"]');
    button.scrollIntoView({ block: 'center' });
    const rect = button.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  })()`);
  await page.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [target] });
  await page.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await waitUntil(() => probe(page, `!original().seeking && Math.abs(original().currentTime - 16) < 0.05`), 'touch timeline seek');
}

async function main() {
  const dashboard = await startDashboard();
  let proxy;
  try {
    const expected = await inspectRoutes(dashboard.address);
    proxy = await startFaultProxy(dashboard.address);
    await withBrowser(async port => {
      const slow = { path: jsonPath('refined', 'P06_08'), ms: 900, requested: false };
      await runScenario(port, dashboard, 'all six videos, per-clip and aggregate evidence', page => checkAllClips(page, expected));
      await runScenario(port, dashboard, 'P09_04 multi-interval playback and final boundaries', page => checkComplexPlayback(page, expected));
      await runScenario(port, proxy, 'switch during playback and discard late JSON', page => checkRace(page, expected, slow), {
        fixture: { slow },
      });
      await runScenario(port, proxy, 'missing, wrong-video, and media failures stay isolated', checkFaults, {
        fixture: {
          missing: [jsonPath('refined', 'P14_02'), mediaPath('P14_03')],
          wrong: { [jsonPath('stock', 'P09_04')]: jsonPath('stock', 'P06_02') },
        },
      });
      await runScenario(port, dashboard, '375 px stacking and touch timeline seek', checkMobile);
    });
  } finally {
    await proxy?.close();
    await dashboard.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
