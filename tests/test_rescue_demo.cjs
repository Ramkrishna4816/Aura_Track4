/* Run from the workspace with Node.js 22+ and Microsoft Edge: node tests/test_rescue_demo.cjs */
'use strict';

const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const { mkdtemp, readFile, realpath, rm } = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');

const workspace = path.resolve(__dirname, '..');
const demoPath = '/evaluation/final_quality_pass/demo/P06_02.html';
const filePath = url => {
  const file = path.resolve(workspace, `.${decodeURIComponent(url)}`);
  assert(file.startsWith(workspace + path.sep), `Outside the workspace: ${url}`);
  return file;
};

function localUrl(relative) {
  const resolved = new URL(relative, `http://127.0.0.1${demoPath}`);
  assert.equal(resolved.origin, 'http://127.0.0.1', 'Demo uses a nonlocal asset');
  return resolved.pathname;
}

function sendVideo(request, response, file) {
  const size = fs.statSync(file).size;
  const range = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range || '');
  const start = range ? Number(range[1]) : 0;
  const end = range?.[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
  if (start > end) {
    response.writeHead(416, { 'Content-Range': `bytes */${size}` }).end();
    return;
  }
  const headers = {
    'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes', 'Content-Length': end - start + 1,
  };
  if (range) headers['Content-Range'] = `bytes ${start}-${end}/${size}`;
  response.writeHead(range ? 206 : 200, headers);
  if (request.method === 'HEAD') {
    response.end();
    return;
  }
  const stream = fs.createReadStream(file, { start, end });
  response.on('close', () => stream.destroy());
  stream.pipe(response);
}

async function startServer() {
  const html = await readFile(filePath(demoPath), 'utf8');
  const match = /<script\b(?=[^>]*\bid=["']demo-config["'])[^>]*>([\s\S]*?)<\/script>/i.exec(html);
  assert(match, 'Generate the current demo before running browser QA');
  const config = JSON.parse(match[1]);
  const stockPath = localUrl(config.stockUrl);
  const refinedPath = localUrl(config.refinedUrl);
  const mediaPath = localUrl(config.videoUrl);
  const stockBody = await readFile(filePath(stockPath));
  const refinedBody = await readFile(filePath(refinedPath));
  const stock = JSON.parse(stockBody);
  const refined = JSON.parse(refinedBody);
  let options = {};

  const server = http.createServer((request, response) => {
    response.setHeader('Cache-Control', 'no-store');
    const url = new URL(request.url, 'http://127.0.0.1').pathname;
    if (url === demoPath) {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(html);
    } else if (url === stockPath || url === refinedPath) {
      const fixture = url === stockPath ? options.stock : options.refined;
      const body = fixture === undefined ? (url === stockPath ? stockBody : refinedBody) : fixture;
      const reply = () => response.writeHead(body === null ? 404 : 200, {
        'Content-Type': 'application/json', 'Cache-Control': 'no-store',
      }).end(body);
      if (options.delayJson) setTimeout(reply, options.delayJson);
      else reply();
    } else if (url === mediaPath && !options.missingMedia) {
      sendVideo(request, response, filePath(mediaPath));
    } else if (url === '/favicon.ico') {
      response.writeHead(204).end();
    } else {
      response.writeHead(404).end();
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {
    address: `http://127.0.0.1:${server.address().port}${demoPath}`,
    fixtures: value => { options = value; }, stock, refined,
    close: () => { server.closeAllConnections(); server.close(); },
  };
}

async function waitUntil(check, description, timeout = 9000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const result = await check();
    if (result) return result;
    await delay(50);
  }
  throw Error(`Timed out waiting for ${description}`);
}

async function openPage(port) {
  const base = `http://127.0.0.1:${port}`;
  const target = await (await fetch(`${base}/json/new?about:blank`, { method: 'PUT' })).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  const pending = new Map();
  const errors = [];
  let nextId = 1;
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    const finish = pending.get(message.id);
    if (finish) {
      finish(message);
      return;
    }
    const { method, params } = message;
    if (method === 'Runtime.exceptionThrown') {
      const detail = params.exceptionDetails;
      errors.push(detail.exception?.description || detail.text);
    }
    if (method === 'Runtime.consoleAPICalled' && params.type === 'error') {
      errors.push(params.args.map(arg => arg.description ?? arg.value).join(' '));
    }
    if (method === 'Log.entryAdded' && params.entry.level === 'error' && params.entry.source !== 'network') {
      errors.push(params.entry.text);
    }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(Error(`CDP timed out in ${method}`));
    }, 12000);
    pending.set(id, message => {
      clearTimeout(timer);
      pending.delete(id);
      if (message.error) reject(Error(message.error.message));
      else resolve(message.result);
    });
    socket.send(JSON.stringify({ id, method, params }));
  });
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Log.enable');
  return {
    send, errors,
    async evaluate(expression) {
      const result = await send('Runtime.evaluate', {
        expression, awaitPromise: true, returnByValue: true, userGesture: true,
      });
      if (result.exceptionDetails) {
        const detail = result.exceptionDetails;
        throw Error(detail.exception?.description || detail.text);
      }
      return result.result.value;
    },
    async close() {
      socket.close();
      await fetch(`${base}/json/close/${target.id}`).catch(() => {});
    },
  };
}

async function closeBrowser(port) {
  // On Windows the launcher can exit after handing off to the isolated browser.
  // Close the browser itself over DevTools before removing its profile.
  const response = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(2000) });
  const version = await response.json();
  const socket = new WebSocket(version.webSocketDebuggerUrl);
  try {
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true });
      socket.addEventListener('error', reject, { once: true });
    });
    const disconnected = new Promise(resolve => socket.addEventListener('close', resolve, { once: true }));
    socket.send(JSON.stringify({ id: 1, method: 'Browser.close' }));
    await Promise.race([disconnected, delay(1500)]);
  } finally {
    socket.close();
  }
}

async function runScenario(port, server, name, test, options = {}) {
  server.fixtures(options.fixture || {});
  const page = await openPage(port);
  try {
    await page.send('Page.bringToFront');
    if (options.beforeLoad) {
      await page.send('Page.addScriptToEvaluateOnNewDocument', { source: options.beforeLoad });
    }
    const navigation = await page.send('Page.navigate', { url: server.address });
    assert(!navigation.errorText, navigation.errorText);
    await waitUntil(() => page.evaluate('Boolean(document.querySelector("#demo-status"))'), 'demo document');
    const result = await test(page);
    assert.deepEqual(page.errors, [], 'Browser console errors');
    console.log(`PASS ${name}${result ? ` (${result})` : ''}`);
  } finally {
    await page.close();
  }
}

const selectors = `
  const model = name => document.querySelector('article[data-model="' + name + '"]');
  const clips = () => [...document.querySelectorAll('.excerpt')];
  const ready = () => ['stock', 'refined'].every(name => model(name)?.dataset.state === 'ready');
  const videoReady = () => Boolean(document.querySelector('#original')?.readyState >= 1);
  const modelButtons = name => [...document.querySelectorAll('.segment[data-seek]')].filter(button =>
    button.closest('[data-model]')?.dataset.model === name);
  const playback = () => document.querySelector('#playback-status');
  const drift = () => document.querySelector('#drift-status');
  const click = id => document.getElementById(id).click();
`;

function probe(page, expression) {
  return page.evaluate(`(() => { ${selectors} return (${expression}); })()`);
}

async function waitForModels(page) {
  await waitUntil(() => probe(page, 'ready()'), 'both model outputs');
}

async function waitForMedia(page) {
  try {
    await waitUntil(() => probe(page, `videoReady() && clips().length === 2
      && clips().every(video => video.readyState >= 1 && !video.seeking)
      && !document.querySelector('#play').disabled`), 'three media elements and ready playback');
  } catch (error) {
    const state = await probe(page, `({
      state: playback().textContent, source: document.querySelector('#source-status').textContent,
      media: [...document.querySelectorAll('video')].map(video => ({
        error: video.error?.message, ready: video.readyState, seeking: video.seeking,
      })),
    })`);
    throw Error(`${error.message}: ${JSON.stringify(state)}`);
  }
}

function closeTo(actual, expected, tolerance, label) {
  assert(Math.abs(actual - expected) <= tolerance, `${label}: got ${actual}, expected ${expected} ± ${tolerance}`);
}

const countFrameCallbacks = `
  (() => {
    const prototype = HTMLVideoElement.prototype;
    const request = prototype.requestVideoFrameCallback;
    const cancel = prototype.cancelVideoFrameCallback;
    if (!request || !cancel) return;
    const callbacks = new WeakMap();
    const metric = { maximumPending: 0, registered: 0 };
    window.demoFrameCallbackMetric = metric;
    prototype.requestVideoFrameCallback = function (callback) {
      if (!callbacks.has(this)) callbacks.set(this, new Set());
      const pending = callbacks.get(this);
      const id = request.call(this, (...args) => { pending.delete(id); callback(...args); });
      pending.add(id);
      metric.maximumPending = Math.max(metric.maximumPending, pending.size);
      metric.registered += 1;
      return id;
    };
    prototype.cancelVideoFrameCallback = function (id) {
      callbacks.get(this)?.delete(id);
      return cancel.call(this, id);
    };
  })();
`;

async function checkPage(page, server) {
  const loading = await probe(page, `['stock','refined'].some(name => model(name).dataset.state === 'loading')`);
  assert(loading, 'The delayed JSON response should leave a visible loading state');
  await waitForModels(page);
  await waitForMedia(page);
  const rendered = await probe(page, `['stock','refined'].map(name => {
    const panel = model(name);
    const actions = modelButtons(name).map(button => ({
      start: Number(button.dataset.seek), label: button.getAttribute('aria-label'),
      title: button.getAttribute('title'), tag: button.tagName, tabIndex: button.tabIndex,
      position: (button.getBoundingClientRect().left - button.parentElement.getBoundingClientRect().left)
        / button.parentElement.getBoundingClientRect().width,
    }));
    return {
      data: JSON.parse(panel.querySelector('pre').textContent),
      activity: panel.querySelector('.activity').textContent, actions,
    };
  })`);
  assert.deepEqual(rendered.map(row => row.data), [server.stock, server.refined]);
  assert.deepEqual(rendered.map(row => row.actions.map(action => action.start).sort((a, b) => a-b)), [[2, 4], [1, 4, 5.76]]);
  assert(await probe(page, `['3.14', '4.65', 'false positive', 'opt-in'].every(phrase => document.body.textContent.toLowerCase().includes(phrase))`));
  for (const row of rendered) {
    const { label } = row.data;
    assert(row.activity.toLowerCase().includes(label.name));
    assert(row.activity.replaceAll(',', '.').includes(label.score.toFixed(4)));
    for (const action of row.actions) {
      assert.equal(action.tag, 'BUTTON');
      assert(action.label && action.title && action.tabIndex >= 0);
      closeTo(action.position, action.start / row.data.duration_sec, 0.02, 'timeline position');
    }
  }
  const mobile = await (async () => {
    const panels = () => probe(page, `['stock','refined'].map(name => {
      const rect = model(name).getBoundingClientRect();
      return [rect.top, rect.left, rect.right, rect.bottom];
    })`);
    const desktop = await panels();
    assert(desktop[1][1] >= desktop[0][2] - 1, 'Desktop comparisons should be side by side');
    await page.send('Emulation.setDeviceMetricsOverride', {
      width: 375, height: 812, deviceScaleFactor: 1, mobile: true,
    });
    await probe(page, `[...document.querySelectorAll('.model details')].forEach(details => { details.open = true; })`);
    const stacked = await panels();
    assert(stacked[1][0] >= stacked[0][3] - 1, 'Mobile comparisons should stack');
    assert(await probe(page, 'document.documentElement.scrollWidth <= innerWidth + 1'));
    return stacked;
  })();
  assert(mobile[0][2] <= 376 && mobile[1][2] <= 376);
  await page.send('Emulation.clearDeviceMetricsOverride');
  const focus = await probe(page, `(() => {
    const button = modelButtons('stock').find(button => Number(button.dataset.seek) === 4);
    button.focus();
    return { active: document.activeElement === button, tip: document.querySelector('#timeline-focus').textContent, title: button.title };
  })()`);
  assert(focus.active && ['4.00', '6.00'].every(time => focus.tip.includes(time)), JSON.stringify(focus));
  const enter = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
  await page.send('Input.dispatchKeyEvent', { type: 'keyDown', text: '\r', unmodifiedText: '\r', ...enter });
  await page.send('Input.dispatchKeyEvent', { type: 'keyUp', ...enter });
  await waitUntil(() => probe(page, `!document.querySelector('#original').seeking && Math.abs(document.querySelector('#original').currentTime - 4) < 0.03`), 'keyboard seek', 4000);
}

async function checkPlayback(page, { perturb = false } = {}) {
  await waitForModels(page);
  await waitForMedia(page);
  await probe(page, `click('play')`);
  await waitUntil(() => probe(page, 'clips().every(video => !video.paused && !video.seeking)'), 'excerpt start after seek');
  await waitUntil(() => probe(page, 'Number(drift()?.dataset.samples) > 1'), 'drift samples');
  const initial = await probe(page, `clips().map(video => video.currentTime)`);
  assert(initial[0] >= 2 && initial[0] < 4 && initial[1] >= 1 && initial[1] < 3);

  let induced;
  if (perturb) {
    await probe(page, `clips()[1].playbackRate = 0.5`);
    try {
      induced = await waitUntil(() => probe(page, `(() => {
        const max = Number(drift().dataset.maxSeconds);
        return drift().dataset.warning === 'true' && max >= 0.1 ? max : false;
      })()`), 'reported induced drift', 4000);
    } catch (error) {
      const meter = await probe(page, `({
        status: playback().textContent, meter: drift().textContent,
        clips: clips().map(video => ({time: video.currentTime, rate: video.playbackRate, paused: video.paused})),
      })`);
      throw Error(`${error.message}: ${JSON.stringify(meter)}`);
    } finally {
      await probe(page, `clips()[1].playbackRate = 1`);
    }
  }
  await probe(page, `click('pause')`);
  await waitUntil(() => probe(page, 'clips().every(video => video.paused)'), 'paused excerpts');
  const paused = await probe(page, 'clips().map(video => video.currentTime)');
  await delay(175);
  for (const [i, current] of (await probe(page, 'clips().map(video => video.currentTime)')).entries()) {
    closeTo(current, paused[i], 0.03, 'pause holds each source timestamp');
  }
  await probe(page, `click('play')`);
  await waitUntil(() => probe(page, `clips().every(video => !video.paused && !video.seeking)`), 'resume after pause');
  const resumed = await probe(page, 'clips().map(video => video.currentTime)');
  for (const [i, time] of resumed.entries()) {
    assert(time >= paused[i] - 0.03, 'Resume should retain each selected source timestamp');
  }
  // Rapid controls exercise pending seek/play cancellation. The final Reset wins.
  await page.evaluate(`(() => { ${selectors} click('play'); click('pause'); click('play'); click('reset'); })()`);
  await waitUntil(() => probe(page, `clips().every((video, i) => video.paused && !video.seeking && Math.abs(video.currentTime - [2,1][i]) < 0.03)`), 'reset after rapid controls');

  await probe(page, `click('play')`);
  await waitUntil(() => probe(page, 'clips().every(video => !video.paused)'), 'restarted excerpts');
  await probe(page, `document.querySelector('#original').play().then(() => true)`);
  await waitUntil(() => probe(page, `clips().every(video => video.paused) && !document.querySelector('#original').paused`), 'original playback pausing excerpts');

  await probe(page, `click('reset')`);
  await waitUntil(() => probe(page, `clips().every((video, i) => video.paused && !video.seeking && Math.abs(video.currentTime - [2,1][i]) < 0.03)`), 'reset after original playback');
  await probe(page, `click('play')`);
  await waitUntil(() => probe(page, `document.querySelector('#original').paused && clips().every((video, i) => video.paused && !video.seeking && Math.abs(video.currentTime - [6,5][i]) < 0.03)`), 'selected playback ending at both exact boundaries');
  const final = await probe(page, `({
    samples: Number(drift().dataset.samples), peak: Number(drift().dataset.maxSeconds),
    boundaryOverrun: Number(drift().dataset.maxBoundaryOverrun), scheduler: drift().dataset.scheduler,
    callbacks: window.demoFrameCallbackMetric,
  })`);
  assert(final.samples > 1 && Number.isFinite(final.peak) && final.peak >= 0);
  assert(Number.isFinite(final.boundaryOverrun) && final.boundaryOverrun >= 0);
  assert.equal(final.scheduler, perturb ? 'video-frame' : 'animation-frame');
  if (final.callbacks) {
    assert(final.callbacks.registered > 1);
    assert(final.callbacks.maximumPending <= 1, 'A video should never have two queued frame callbacks');
  }
  const millis = seconds => `${(seconds * 1000).toFixed(1)} ms`;
  return `${final.scheduler}, ${final.samples} samples, ${millis(final.peak)} peak drift, `
    + `${millis(final.boundaryOverrun)} max boundary overrun${induced ? `, ${millis(induced)} induced drift` : ''}`;
}

async function tests(port, server) {
  await runScenario(port, server, 'actual JSON, timeline geometry, mobile and keyboard seek', page => checkPage(page, server), {
    fixture: { delayJson: 750 },
  });
  for (const [name, value] of [['missing JSON', null], ['malformed JSON', '{invalid']]) {
    await runScenario(port, server, name, async page => {
      await waitUntil(() => probe(page, `model('stock')?.dataset.state === 'error' && model('refined')?.dataset.state === 'ready'`), 'isolated JSON error');
      assert(await probe(page, `model('stock').querySelector('.data-message')?.textContent.trim().length > 0`));
      assert.deepEqual(await probe(page, `modelButtons('stock').map(button => button.dataset.seek)`), []);
      await waitUntil(() => probe(page, 'videoReady()'), 'original footage despite invalid model data');
    }, { fixture: { stock: value } });
  }
  const unusual = structuredClone(server.stock);
  unusual.label = { name: 'cleaning', score: 0.5123 };
  unusual.actions = [[-1, 2], [7, 6], [15, 16]].map(segment => ({
    ...server.stock.actions[0], verb: 'take', noun: 'bowl', segment,
  }));
  unusual.highlights.push({ segment: [12, 30] });
  await runScenario(port, server, 'timestamp clamp, omission, and JSON-driven labels', async page => {
    await waitForModels(page);
    await waitUntil(() => probe(page, 'videoReady()'), 'original metadata');
    const view = await probe(page, `({
      json: JSON.parse(model('stock').querySelector('pre').textContent),
      activity: model('stock').querySelector('.activity').textContent,
      details: model('stock').querySelector('.prediction-details').textContent,
      starts: modelButtons('stock').map(button => Number(button.dataset.seek)).sort((a, b) => a-b),
      lastTitle: modelButtons('stock').find(button => Number(button.dataset.seek) === 12)?.title,
      notice: model('stock').querySelector('.data-message')?.textContent,
    })`);
    assert.deepEqual(view.json, unusual);
    assert(view.activity.toLowerCase().includes('cleaning') && view.activity.includes('0.5123'));
    assert(view.details.includes('take bowl'));
    assert.deepEqual(view.starts, [0, 2, 12]);
    assert(/13\.95|14\.00/.test(view.lastTitle));
    assert(view.notice?.trim());
  }, { fixture: { stock: JSON.stringify(unusual) } });
  await runScenario(port, server, 'source-video failure', async page => {
    await waitForModels(page);
    await waitUntil(() => probe(page, `Boolean(document.querySelector('#original').error)`), 'media error');
    assert(await probe(page, `/could not|unavailable|unable|cannot|failed|error/.test(document.querySelector('#source-status').textContent.toLowerCase())`));
    assert(await probe(page, `document.querySelector('#play').disabled`));
  }, { fixture: { missingMedia: true } });
  await runScenario(port, server, 'playback, drift detection, repeated controls, and boundaries', page => checkPlayback(page, { perturb: true }), {
    beforeLoad: countFrameCallbacks,
  });
  await runScenario(port, server, 'playback without video frame callbacks', page => checkPlayback(page), {
    beforeLoad: `Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', { value: undefined });`,
  });
}

async function withBrowser(run) {
  const edge = process.env.AURA_EDGE || path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe');
  assert(fs.existsSync(edge), 'Set AURA_EDGE to the installed Edge/Chromium executable');
  const testRoot = await realpath(__dirname);
  const profile = await mkdtemp(path.join(testRoot, '.aura-demo-qa-'));
  let browser;
  let port;
  try {
    browser = spawn(edge, [
      '--headless=new', '--disable-background-networking', '--disable-component-update', '--disable-sync',
      '--disable-gpu', '--mute-audio', '--no-first-run', '--no-default-browser-check',
      `--user-data-dir=${profile}`, '--remote-debugging-port=0', '--window-size=1280,900', 'about:blank',
    ], { stdio: 'ignore', windowsHide: true });
    let launchError;
    browser.on('error', error => { launchError = error; });
    port = await waitUntil(async () => {
      if (launchError) throw launchError;
      if (browser.exitCode) throw Error(`Edge exited at startup with code ${browser.exitCode}`);
      const data = await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8').catch(() => '');
      return Number.parseInt(data.split(/\r?\n/)[0], 10);
    }, 'Edge DevTools');
    await run(port);
  } finally {
    if (port) await closeBrowser(port).catch(() => {});
    if (browser?.pid && browser.exitCode === null) {
      const exited = new Promise(resolve => browser.once('exit', () => resolve(true)));
      browser.kill();
      await Promise.race([exited, delay(2000)]);
    }
    assert.equal(path.dirname(await realpath(profile)), testRoot, 'QA profile is outside tests/');
    await rm(profile, { recursive: true, force: true, maxRetries: 8, retryDelay: 200 });
  }
}

async function main() {
  const server = await startServer();
  try {
    await withBrowser(port => tests(port, server));
  } finally {
    server.close();
  }
}

module.exports = { waitUntil, runScenario, withBrowser };

if (require.main === module) {
  main().catch(error => { console.error(error); process.exitCode = 1; });
}
