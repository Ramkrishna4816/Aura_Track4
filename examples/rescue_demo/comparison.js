(() => {
  'use strict';
  const boot = JSON.parse(document.getElementById('demo-config').textContent);
  const catalog = boot.clips;
  let config;
  const byId = id => document.getElementById(id);
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  let original = byId('original');
  const play = byId('play');
  const pause = byId('pause');
  const reset = byId('reset');
  const status = byId('playback-status');
  const driftStatus = byId('drift-status');
  const timeline = byId('timeline-tracks');
  const sourceStatus = byId('source-status');
  const localFile = location.protocol === 'file:';
  const toolTipDefault = 'Focus or hover an interval to see its exact bounds.';
  const rootKeys = ['team_id', 'video_id', 'duration_sec', 'label', 'actions', 'highlights'];
  const models = [['stock', 'Stock'], ['refined', 'Factorized-refined']]
    .map(([id, name]) => {
      const panel = document.querySelector(`[data-model="${id}"]`);
      return {id, name, panel, video: panel.querySelector('video'), revision: 0};
    });
  let refs = [];
  let clipRequests;
  let playback;
  let playbackModels = [];
  let playbackError;
  let chartDuration = 0;
  let sourceError;

  const seconds = value => `${value.toFixed(2)} s`;
  const interval = ([start, end]) => `${start.toFixed(2)}–${end.toFixed(2)} s`;
  const browserDuration = () => Number.isFinite(original.duration) && original.duration > 0 ? original.duration : 0;
  const hasSource = () => !sourceError && original.readyState >= 1 && browserDuration() > 0;
  const usableScore = score => Number.isFinite(score) && score >= 0 && score <= 1;
  const labelText = value => typeof value === 'string' && value.trim().length > 0;

  function acceptPrediction(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== rootKeys.length
        || !rootKeys.every(key => Object.hasOwn(value, key)) || value.video_id !== config.videoId
        || !labelText(value.team_id) || !Number.isFinite(value.duration_sec) || value.duration_sec <= 0
        || !labelText(value.label?.name) || !usableScore(value.label?.score)
        || !Array.isArray(value.actions) || !Array.isArray(value.highlights)) {
      throw new Error(`Expected a six-key ${config.videoId} prediction with a valid label and duration.`);
    }
    return value;
  }

  function displayRows(items, kind, limit) {
    const rows = [];
    let invalid = 0;
    let adjusted = 0;
    for (const item of items) {
      const raw = item?.segment;
      if (!Array.isArray(raw) || raw.length !== 2 || !raw.every(Number.isFinite) || raw[0] >= raw[1]
          || (kind === 'action' && (!labelText(item.verb) || !labelText(item.noun) || !usableScore(item.score)))) {
        invalid += 1;
        continue;
      }
      const segment = [Math.max(0, raw[0]), Math.min(limit, raw[1])];
      if (segment[0] >= segment[1]) {
        invalid += 1;
        continue;
      }
      const clamped = segment[0] !== raw[0] || segment[1] !== raw[1];
      if (clamped) adjusted += 1;
      const label = kind === 'highlight' ? 'Highlight' : `${item.verb} ${item.noun}`;
      rows.push({raw, segment, label, verb: item.verb, noun: item.noun,
        score: kind === 'action' ? item.score : undefined, clamped});
    }
    return {rows: rows.sort((a, b) => a.segment[0] - b.segment[0]), invalid, adjusted};
  }

  function spanLabel(row) {
    return row.clamped ? `${interval(row.raw)} saved · ${interval(row.segment)} shown` : interval(row.raw);
  }

  function showModel(model) {
    model.panel.dataset.state = model.state;
    const message = model.panel.querySelector('.data-message');
    const output = model.panel.querySelector('.model-output');
    output.hidden = !model.prediction;
    message.hidden = false;
    if (!model.prediction) {
      message.textContent = model.message || 'Loading saved prediction…';
      model.actions = [];
      model.highlights = [];
      return;
    }
    const prediction = model.prediction;
    const duration = browserDuration();
    const limit = duration ? Math.min(duration, prediction.duration_sec) : prediction.duration_sec;
    const actions = displayRows(prediction.actions, 'action', limit);
    const highlights = displayRows(prediction.highlights, 'highlight', limit);
    model.actions = actions.rows;
    model.highlights = highlights.rows;
    const invalid = actions.invalid + highlights.invalid;
    const adjusted = actions.adjusted + highlights.adjusted;
    const messages = [];
    if (invalid) messages.push(`${invalid} invalid ${invalid === 1 ? 'entry was' : 'entries were'} omitted from the tracks.`);
    if (adjusted) messages.push(`${adjusted} ${adjusted === 1 ? 'interval was' : 'intervals were'} clipped to the source bounds.`);
    message.textContent = messages.join(' ');
    message.hidden = !messages.length;
    model.panel.querySelector('.activity').replaceChildren(
      element('strong', prediction.label.name),
      element('p', `Activity score ${prediction.label.score.toFixed(4)} · Pipeline ${seconds(prediction.duration_sec)}`, 'meta'),
    );
    model.video.hidden = !highlights.rows.length;
    model.panel.querySelector('.clock').textContent = highlights.rows.length
      ? `Selected ${interval(highlights.rows[0].segment)}` : 'No playable highlights in this output.';
    const lists = [['Actions', actions.rows], ['Highlights', highlights.rows]].map(([title, rows]) => {
      const section = element('div');
      const list = element('ul');
      for (const row of rows) {
        const entry = element('li');
        entry.append(`${row.label} `, element('span', spanLabel(row), 'interval'));
        if (row.score !== undefined) entry.append(` · Score ${row.score.toFixed(4)}`);
        list.append(entry);
      }
      if (!rows.length) list.append(element('li', 'None to display'));
      section.append(element('h4', title), list);
      return section;
    });
    model.panel.querySelector('.prediction-details').replaceChildren(...lists);
    model.panel.querySelector('pre').textContent = JSON.stringify(prediction, null, 2);
    model.panel.querySelector('.output-identity').hidden = prediction.team_id !== 'Internal-QA-20261121';
  }

  function updatePlayhead() {
    const fraction = chartDuration ? Math.min(1, Math.max(0, original.currentTime / chartDuration)) : 0;
    timeline.style.setProperty('--playhead', `${100 * fraction}%`);
  }

  function selectOriginal(time) {
    if (!hasSource()) return;
    try {
      original.currentTime = Math.min(browserDuration(), Math.max(0, time));
      updatePlayhead();
    } catch {
      sourceStatus.textContent = 'The original video could not seek to that time.';
    }
  }

  function track(name, kind, rows, modelId) {
    const node = element('div', undefined, 'track');
    if (modelId) node.dataset.model = modelId;
    const rail = element('div', undefined, 'rail');
    for (const row of rows) {
      const [start, end] = row.segment;
      const button = element('button', undefined, `segment ${kind}`);
      button.type = 'button';
      button.dataset.seek = String(start);
      button.disabled = !hasSource();
      button.style.setProperty('--start', `${100 * start / chartDuration}%`);
      button.style.setProperty('--width', `${100 * (end - start) / chartDuration}%`);
      const description = `${name} · ${row.label} · ${spanLabel(row)}`;
      button.title = description;
      button.setAttribute('aria-label', `Seek original · ${description}`);
      const detail = byId('timeline-focus');
      button.addEventListener('focus', () => { detail.textContent = description; });
      button.addEventListener('pointerenter', () => { detail.textContent = description; });
      button.addEventListener('blur', () => { detail.textContent = toolTipDefault; });
      button.addEventListener('pointerleave', () => {
        if (document.activeElement !== button) detail.textContent = toolTipDefault;
      });
      button.addEventListener('click', () => selectOriginal(start));
      rail.append(button);
    }
    if (!rows.length) rail.append(element('div', 'No intervals', 'track-empty'));
    const playhead = element('i', undefined, 'playhead');
    playhead.setAttribute('aria-hidden', 'true');
    rail.append(playhead);
    node.append(element('div', name, 'track-label'), rail);
    return node;
  }

  function intersection(a, b) {
    return Math.max(0, Math.min(a[1], b[1]) - Math.max(a[0], b[0]));
  }

  function temporalIoU(a, b) {
    return intersection(a, b) / (Math.max(a[1], b[1]) - Math.min(a[0], b[0]));
  }

  function unionSpans(rows) {
    const merged = [];
    for (const {segment: [start, end]} of rows) {
      const previous = merged.at(-1);
      if (previous && start <= previous[1]) previous[1] = Math.max(previous[1], end);
      else merged.push([start, end]);
    }
    return merged;
  }

  function renderTracks() {
    const duration = browserDuration();
    const pipeline = models.filter(model => model.prediction).map(model => model.prediction.duration_sec);
    chartDuration = duration || Math.max(config.duration || 0, ...pipeline, ...refs.map(ref => ref.segment[1]));
    const publicRows = displayRows(refs, 'reference', chartDuration).rows;
    const plot = [track('Public reference', 'reference', publicRows)];
    for (const kind of ['action', 'highlight']) {
      for (const model of models) {
        const rows = kind === 'action' ? model.actions : model.highlights;
        plot.push(track(`${model.name} ${kind}s`, kind, rows, model.id));
      }
    }
    const axis = element('div', undefined, 'track axis-row');
    const ticks = element('div', undefined, 'axis meta');
    if (chartDuration) {
      ticks.append(element('span', '0 s'), element('span', seconds(chartDuration / 2)), element('span', seconds(chartDuration)));
    }
    axis.append(element('div', 'Source time', 'track-label'), ticks);
    timeline.replaceChildren(...plot, axis);
    const pipelineText = [...new Set(pipeline)].map(seconds).join(' / ');
    byId('clock-summary').textContent = `Browser media ${duration ? seconds(duration) : 'unavailable'} · Pipeline ${pipelineText || 'unavailable'}`;
    byId('timeline-focus').textContent = toolTipDefault;
    updatePlayhead();
    const [stock, refined] = models.map(model => unionSpans(model.highlights));
    const shared = stock.reduce((sum, left) => sum + refined.reduce((part, right) => part + intersection(left, right), 0), 0);
    const total = spans => spans.reduce((sum, [start, end]) => sum + end - start, 0);
    byId('highlight-summary').textContent = models.every(model => model.prediction)
      ? `Highlight coverage · Stock ${seconds(total(stock))} · Refined ${seconds(total(refined))} · Shared ${seconds(shared)}` : '';
  }

  function renderEvaluation() {
    const summary = byId('reference-summary');
    const comparison = byId('evaluation-summary');
    summary.replaceChildren();
    comparison.replaceChildren();
    if (!refs.length) {
      summary.textContent = 'No public evaluation reference was configured for this clip.';
      return;
    }
    const shown = catalog ? refs.filter(ref => config.videoId === 'P06_02' && ref.label === 'open dishwasher') : refs;
    for (const ref of shown) {
      const row = element('p');
      row.append(element('strong', ref.label), ` · ${interval(ref.segment)}`);
      summary.append(row);
    }
    summary.append(element('p', `${catalog ? `${refs.length} annotated actions · ` : ''}${config.referenceSource}. Evaluation only.`, 'meta'));
    const bestScores = [];
    for (const model of models) {
      const unused = new Set(refs);
      let best = 0;
      const actions = model.actions.filter(row => !row.clamped);
      for (const action of actions.sort((a, b) => b.score - a.score || a.raw[0] - b.raw[0])) {
        const references = refs.filter(ref => ref.verb === action.verb && ref.noun === action.noun);
        const iou = Math.max(0, ...references.map(ref => temporalIoU(action.raw, ref.segment)));
        best = Math.max(best, iou);
        const match = references.filter(ref => unused.has(ref))
          .sort((a, b) => temporalIoU(action.raw, b.segment) - temporalIoU(action.raw, a.segment))[0];
        const accepted = match && temporalIoU(action.raw, match.segment) >= config.matchThreshold;
        if (accepted) unused.delete(match);
        const row = element('div', undefined, 'evaluation-row');
        row.append(element('strong', `${model.name} · ${action.label} · ${interval(action.raw)}`),
          element('p', `tIoU ${iou.toFixed(3)} · ${accepted ? 'Matched reference' : 'False positive'}`,
            accepted ? 'verdict' : 'false-positive'));
        comparison.append(row);
      }
      bestScores.push(best);
    }
    if (!comparison.childElementCount) return;
    const better = models.every(model => model.prediction) && bestScores[1] > bestScores[0]
      && bestScores[1] >= config.matchThreshold;
    comparison.append(element('p', `${better ? 'The first refined detection is a better-localized match. ' : ''}`
      + `Local comparison uses one match per reference at tIoU ≥ ${config.matchThreshold.toFixed(2)}.`, 'meta'));
  }

  const percent = (number, digits = 1) => Number.isFinite(number) ? `${(100 * number).toFixed(digits)}%` : '—';

  function metricsTable(columns, rows) {
    const table = element('table');
    const header = table.createTHead().insertRow();
    for (const label of columns) {
      const heading = element('th', label);
      heading.scope = 'col';
      header.append(heading);
    }
    const body = table.createTBody();
    for (const [first, ...rest] of rows) {
      const row = body.insertRow();
      const heading = element('th', first);
      heading.scope = 'row';
      row.append(heading, ...rest.map(value => element('td', String(value))));
    }
    return table;
  }

  function clipCounts(metric) {
    return [metric.predicted_actions, metric.true_positives, metric.false_positives, metric.false_negatives,
      percent(metric.precision), percent(metric.recall), percent(metric.mean_map, 3), metric.false_positives_per_minute.toFixed(2)];
  }

  const countColumns = ['Predictions', 'Matches', 'False positives', 'Missed refs', 'Precision', 'Recall', 'Mean mAP', 'FP/min'];
  const scoredTiming = 'Detection counts, precision and recall use tIoU 0.30. Mean mAP averages tIoU 0.10–0.50. A dash indicates an undefined precision when an arm emitted no detections.';

  function renderClipMetrics() {
    const panel = byId('per-video-metrics');
    const evidence = byId('clip-evidence');
    if (!catalog) return;
    panel.hidden = false;
    const details = panel.querySelector('.reference-details');
    details.hidden = !refs.length;
    details.querySelector('ul').replaceChildren(...refs.map(ref => element('li', `${ref.label} · ${interval(ref.segment)}`)));
    panel.querySelector('h2').textContent = `${config.videoId} · local metrics`;
    const table = panel.querySelector('.table-scroll');
    table.replaceChildren();
    evidence.replaceChildren();
    evidence.hidden = true;
    if (!config.metrics || !refs.length) {
      table.append(element('p', 'Public references or saved metrics are unavailable for this clip.', 'meta'));
      return;
    }
    const stats = models.map(model => config.metrics[model.id]);
    table.append(element('p', scoredTiming, 'meta'));
    table.append(metricsTable(['Arm', ...countColumns, 'Highlight coverage', 'Highlights', 'Runtime'], models.map((model, i) => {
      const metric = stats[i];
      const capture = metric.highlights.distinct_pair_capture;
      return [model.name, ...clipCounts(metric), `${capture.captured_pairs}/${capture.ground_truth_pairs}`,
        seconds(metric.highlights.seconds), seconds(metric.runtime_seconds)];
    })));
    const stock = stats[0].highlights;
    const pairs = stock.distinct_pair_capture.captured_pair_names.map(pair => pair.join(' '));
    if (config.videoId === 'P09_04') {
      evidence.hidden = false;
      evidence.append(element('h3', 'Kitchen interactions and coverage'),
        element('p', `The saved runs selected ${stock.segments} highlights per arm, covering ${seconds(stock.seconds)} across ${seconds(stock.first_to_last_seconds)} of source time. Footage shows a cupboard reach, a move toward the sink, and package handling.`),
        element('p', `The stock action is a local false positive. Refined emitted no actions, leaving all ${stats[1].ground_truth_actions} annotated actions unmatched. Highlight overlap captured ${pairs.join(', ')}. Those are public references, separate from predicted action labels.`, 'meta'));
    }
    if (config.videoId === 'P14_03') {
      const number = value => value.toFixed(3);
      evidence.hidden = false;
      evidence.append(element('h3', 'Camera-motion challenge'),
        element('p', 'The selected footage shows a rapid head turn and a blurred crossing near the counter. The motion signal measures thumbnail change and can respond to camera movement.'),
        element('p', `Selected vs full clip · Motion ${number(stock.mean_motion_selected)} vs ${number(stock.mean_motion_full)} · Activity relevance ${number(stock.mean_activity_relevance_selected)} vs ${number(stock.mean_activity_relevance_full)}. Both arms covered 0 of ${stock.distinct_pair_capture.ground_truth_pairs} annotated pairs.`, 'meta'));
    }
  }

  function showOverview() {
    if (!catalog) return;
    const panel = byId('evaluation-overview');
    panel.hidden = false;
    byId('dashboard-architecture').hidden = false;
    const refined = boot.overview.refined;
    byId('overview-results').append(element('p', `Refined matched ${refined.true_positives}/${refined.ground_truth_actions} reference actions at tIoU 0.30 and emitted no actions on ${refined.zero_action_videos}/${catalog.length} videos.`),
      element('p', scoredTiming, 'meta'),
      metricsTable(['Arm', ...countColumns, 'Videos with no detections', 'Highlight coverage'], models.map(model => {
        const metric = boot.overview[model.id];
        return [model.name, ...clipCounts(metric), `${metric.zero_action_videos}/${catalog.length}`,
          `${metric.pairs_covered}/${metric.pairs_total} (${percent(metric.coverage)})`];
      })));
    byId('overview-results').classList.add('table-scroll');
    panel.querySelector('.report-detail .table-scroll').append(metricsTable(['Video and arm', ...countColumns],
      catalog.flatMap(clip => models.map(model => [`${clip.videoId} · ${model.name}`, ...clipCounts(clip.metrics[model.id])]))));
  }

  const stateText = {
    idle: 'Selections at the start.', seeking: 'Seeking selected excerpts…', playing: 'Playing selected excerpts.',
    paused: 'Selected excerpts paused.', finished: 'Selected excerpts finished.', error: 'Selected excerpts could not play.',
  };

  function setPlaybackState(state, message = stateText[state]) {
    if (status.dataset.state !== state || status.textContent !== message) {
      status.dataset.state = state;
      status.textContent = message;
    }
    play.disabled = !playback || state === 'seeking' || state === 'playing';
    pause.disabled = !playback || !['seeking', 'playing'].includes(state);
    reset.disabled = !playback;
  }

  function updatePlayback({state, clips, drift, scheduler, maxBoundaryOverrun}) {
    setPlaybackState(state, state === 'error' && playbackError ? playbackError : stateText[state]);
    clips.forEach((clip, index) => {
      const model = playbackModels[index];
      const selected = model.highlights[clip.segmentIndex]?.segment;
      const bounds = selected ? ` · Selected ${interval(selected)}` : '';
      const message = `${seconds(clip.sourceTime)} source${bounds} · ${seconds(clip.elapsed)} of ${seconds(clip.total)} selected`;
      const clock = model.panel.querySelector('.clock');
      if (clock.textContent !== message) clock.textContent = message;
    });
    driftStatus.dataset.samples = String(drift.samples);
    driftStatus.dataset.maxSeconds = String(drift.max ?? 0);
    driftStatus.dataset.scheduler = scheduler || '';
    status.dataset.scheduler = scheduler || '';
    driftStatus.dataset.maxBoundaryOverrun = maxBoundaryOverrun ?? '';
    driftStatus.dataset.warning = String((drift.max ?? 0) > 0.05);
    const message = drift.samples
      ? `Excerpt-relative drift · ${drift.current === null ? 'Peak' : `Current ${Math.round(1000 * drift.current)} ms · Peak`}`
        + ` ${Math.round(1000 * drift.max)} ms · ${drift.samples} samples${drift.max > 0.05 ? ' · Drift exceeded 50 ms' : ''}`
      : 'Drift is measured while both excerpts play.';
    if (driftStatus.textContent !== message) driftStatus.textContent = message;
  }

  function connectPlayback() {
    playback?.dispose();
    playback = undefined;
    playbackError = undefined;
    driftStatus.textContent = 'Drift is measured while both excerpts play.';
    driftStatus.dataset.samples = '0';
    driftStatus.dataset.maxSeconds = '0';
    driftStatus.dataset.scheduler = '';
    status.dataset.scheduler = '';
    driftStatus.dataset.maxBoundaryOverrun = '';
    driftStatus.dataset.warning = 'false';
    playbackModels = models.filter(model => model.highlights.length);
    const waiting = models.some(model => model.state === 'loading');
    if (!hasSource() || waiting || !playbackModels.length) {
      setPlaybackState(sourceError ? 'error' : 'idle', sourceError || (waiting || !hasSource()
        ? 'Waiting for selected original footage…' : 'No playable highlight intervals.'));
      return;
    }
    playback = createSelectionPlayback({
      original,
      excerpts: playbackModels.map(model => ({name: model.name, video: model.video,
        segments: model.highlights.map(row => row.segment)})),
      onUpdate: updatePlayback,
      onError: message => {
        playbackError = message;
        setPlaybackState('error', message);
      },
    });
    setPlaybackState('idle', 'Selections ready. Play selections starts both excerpts.');
    void playback.reset();
  }

  function refresh() {
    models.forEach(showModel);
    renderTracks();
    renderEvaluation();
    renderClipMetrics();
    const ready = models.filter(model => model.state === 'ready').length;
    byId('demo-status').textContent = models.some(model => model.state === 'loading') ? 'Loading saved predictions…'
      : localFile && ready < 2 ? `${ready} of 2 predictions loaded. Select the saved JSON in each model panel or use the local demo server.`
      : `${ready} of 2 saved predictions loaded.`;
    connectPlayback();
  }

  async function load(model, read) {
    const revision = ++model.revision;
    model.state = 'loading';
    model.prediction = undefined;
    model.message = undefined;
    refresh();
    try {
      const raw = await read();
      if (revision !== model.revision) return;
      let decoded;
      try { decoded = JSON.parse(raw); } catch { throw new Error('The saved prediction is not valid JSON.'); }
      const prediction = acceptPrediction(decoded);
      model.prediction = prediction;
      model.state = 'ready';
    } catch (error) {
      if (revision !== model.revision) return;
      model.state = 'error';
      model.message = `Could not load ${model.name} prediction. ${error.message}`;
    }
    refresh();
  }

  play.addEventListener('click', () => { playbackError = undefined; void playback?.play(); });
  pause.addEventListener('click', () => playback?.pause());
  reset.addEventListener('click', () => { playbackError = undefined; void playback?.reset(); });

  function replaceMedia(video) {
    video.pause();
    video.removeAttribute('src');
    video.load();
    const fresh = video.cloneNode(false);
    video.replaceWith(fresh);
    return fresh;
  }

  async function getSavedPrediction(url, signal) {
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal.addEventListener('abort', cancel, {once: true});
    const timeout = setTimeout(cancel, 8000);
    try {
      const response = await fetch(url, {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error(`The JSON request returned HTTP ${response.status}.`);
      return await response.text();
    } catch (error) {
      if (controller.signal.aborted && !signal.aborted) throw new Error('The JSON request timed out.');
      throw error;
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener('abort', cancel);
    }
  }

  function switchClip(clip) {
    clipRequests?.abort();
    playback?.dispose();
    playback = undefined;
    clipRequests = new AbortController();
    const {signal} = clipRequests;
    config = {...clip, referenceSource: boot.referenceSource, matchThreshold: boot.matchThreshold};
    refs = config.references.map(item => ({...item, label: `${item.verb} ${item.noun}`}));
    sourceError = undefined;
    delete sourceStatus.dataset.state;
    sourceStatus.textContent = 'Loading original video metadata…';
    document.querySelector('main').dataset.videoId = config.videoId;
    if (catalog) {
      byId('clip-summary').textContent = `${config.videoId} · ${seconds(config.duration)} annotated duration`;
      byId('per-video-metrics').querySelector('details').open = false;
    }
    original = replaceMedia(original);
    original.setAttribute('aria-label', `Full original ${config.videoId} video`);
    original.addEventListener('timeupdate', updatePlayhead, {signal});
    original.addEventListener('seeked', updatePlayhead, {signal});
    original.addEventListener('loadedmetadata', () => {
      sourceStatus.textContent = `Browser media ${seconds(browserDuration())} · ${original.videoWidth} × ${original.videoHeight}`;
      refresh();
    }, {signal});
    original.addEventListener('error', () => {
      sourceError = `The original MP4 for ${config.videoId} could not be loaded. Check the source path and browser video support.`;
      sourceStatus.textContent = sourceError;
      sourceStatus.dataset.state = 'error';
      refresh();
    }, {signal});
    original.src = config.videoUrl;
    for (const model of models) {
      model.revision += 1;
      model.prediction = undefined;
      model.state = localFile ? 'waiting' : 'loading';
      model.message = localFile ? 'Select the saved JSON file to load this comparison.' : undefined;
      model.url = config[`${model.id}Url`];
      model.video = replaceMedia(model.video);
      model.video.src = config.videoUrl;
      model.panel.querySelector('.json-link a').href = model.url;
      model.panel.querySelector('.json-link').hidden = localFile;
      model.panel.querySelector('details').open = false;
      // Clear previous clip material even while the new panel is loading or reports an error.
      for (const selector of ['.activity', '.prediction-details', '.clock', 'pre']) {
        model.panel.querySelector(selector).replaceChildren();
      }
      const label = model.panel.querySelector('.local-input');
      label.hidden = !localFile;
      const input = label.querySelector('input');
      input.value = '';
      if (localFile) {
        input.addEventListener('change', event => {
          const file = event.target.files[0];
          if (file) void load(model, () => file.text());
        }, {signal});
      }
    }
    refresh();
    if (!localFile) {
      for (const model of models) void load(model, () => getSavedPrediction(model.url, signal));
    }
  }

  if (catalog) {
    const selection = byId('video-select');
    for (const clip of catalog) {
      const option = element('option', clip.videoId);
      option.value = clip.videoId;
      selection.append(option);
    }
    byId('dashboard-controls').hidden = false;
    selection.addEventListener('change', () => {
      const selected = catalog.find(clip => clip.videoId === selection.value);
      if (selected && selected.videoId !== config.videoId) switchClip(selected);
    });
    showOverview();
    switchClip(catalog[0]);
  } else {
    switchClip(boot);
  }
})();
