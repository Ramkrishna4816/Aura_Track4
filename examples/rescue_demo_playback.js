function createSelectionPlayback({original, excerpts, onUpdate, onError}) {
  const mediaTimeoutMs = 8000;
  const fallbackTimeoutMs = 120;
  const clips = excerpts.map(({video, segments, name}, index) => {
    let total = 0;
    const intervals = segments.map(([start, end]) => {
      const interval = {start, end, elapsedBefore: total};
      total += end - start;
      return interval;
    });
    return {
      video, name: name || `Selection ${index + 1}`, intervals, total,
      index: 0, finished: intervals.length === 0, target: intervals[0]?.start ?? null,
    };
  });

  const drift = {current: null, max: null, samples: 0};
  let maxBoundaryOverrun = null;
  let state = "idle";
  let scheduler = null;
  let operation = null;
  let scheduled = null;
  let willPlay = false;
  let disposed = false;

  function elapsed(clip) {
    if (clip.finished) return clip.total;
    const {start, end, elapsedBefore} = clip.intervals[clip.index];
    const sourceTime = clip.target ?? clip.video.currentTime;
    return elapsedBefore + Math.min(end - start, Math.max(0, sourceTime - start));
  }

  function publish() {
    onUpdate({
      state, scheduler, maxBoundaryOverrun, drift: {...drift},
      clips: clips.map(clip => ({
        sourceTime: clip.video.currentTime, elapsed: elapsed(clip), total: clip.total,
        segmentIndex: clip.index, finished: clip.finished,
      })),
    });
  }

  function cancelTick() {
    if (!scheduled) return;
    scheduled.cancelFrame();
    clearTimeout(scheduled.watchdog);
    scheduled = null;
  }

  function stopOperation() {
    cancelTick();
    operation?.abort();
    operation = null;
    for (const {video} of clips) video.pause();
    drift.current = null;
  }

  function fail(message) {
    stopOperation();
    willPlay = false;
    state = "error";
    publish();
    onError(message);
  }

  function begin(task, playWhenReady) {
    stopOperation();
    operation = new AbortController();
    const {signal} = operation;
    willPlay = playWhenReady;
    state = "seeking";
    publish();
    return task(signal).catch(error => {
      if (!signal.aborted) fail(error.message || "Selected footage could not play.");
    });
  }

  function awaitEvent(clip, type, signal, trigger = () => {}) {
    const {video, name} = clip;
    return new Promise((resolve, reject) => {
      function settle(error) {
        clearTimeout(timeout);
        video.removeEventListener(type, onReady);
        video.removeEventListener("error", onMediaError);
        signal.removeEventListener("abort", onAbort);
        if (error) reject(error);
        else resolve();
      }
      const onReady = () => {
        if (type === "seeked" && video.seeking) return;
        if (type === "loadedmetadata" && video.readyState < 1) return;
        settle();
      };
      const onMediaError = () => settle(new Error(`${name} could not load the source video.`));
      const onAbort = () => settle(signal.reason);
      const timeout = setTimeout(
        () => settle(new Error(`${name} timed out while ${type === "seeked" ? "seeking" : "loading"}.`)),
        mediaTimeoutMs,
      );
      if (signal.aborted) return onAbort();
      if (video.error) return onMediaError();
      video.addEventListener(type, onReady);
      video.addEventListener("error", onMediaError, {once: true});
      signal.addEventListener("abort", onAbort, {once: true});
      try {
        trigger();
        if (type === "seeked" && !video.seeking) onReady();
      } catch (error) {
        settle(error);
      }
    });
  }

  async function prepare(clip, signal) {
    if (clip.intervals.length === 0) return;
    const {video} = clip;
    if (video.readyState < 1) await awaitEvent(clip, "loadedmetadata", signal);
    if (signal.aborted) return;
    if (clip.target !== null) {
      const target = Math.min(clip.target, video.duration);
      if (!Number.isFinite(target)) throw new Error(`${clip.name} has no usable media duration.`);
      if (video.currentTime !== target || video.seeking) {
        await awaitEvent(clip, "seeked", signal, () => { video.currentTime = target; });
      }
      if (!signal.aborted) clip.target = null;
    } else if (video.seeking) {
      await awaitEvent(clip, "seeked", signal);
    }
  }

  function startTogether(active, signal) {
    return new Promise((resolve, reject) => {
      function finish(error) {
        clearTimeout(timeout);
        signal.removeEventListener("abort", abort);
        if (error) reject(error);
        else resolve();
      }
      const abort = () => finish(signal.reason);
      const timeout = setTimeout(
        () => finish(new Error("The selected footage timed out before playback.")), mediaTimeoutMs,
      );
      if (signal.aborted) return abort();
      signal.addEventListener("abort", abort, {once: true});
      const requests = active.map(async ({video, name}) => {
        try {
          await video.play();
        } catch (error) {
          throw new Error(`${name} could not start playback. ${error.message}`);
        }
      });
      Promise.all(requests).then(() => finish(), finish);
    });
  }

  async function resume(signal) {
    await Promise.all(clips.map(clip => prepare(clip, signal)));
    if (signal.aborted) return;
    const active = clips.filter(clip => !clip.finished);
    if (!active.length) {
      state = "finished";
      willPlay = false;
      publish();
      return;
    }
    await startTogether(active, signal);
    if (signal.aborted) return;
    state = "playing";
    schedule(signal);
    publish();
  }

  function schedule(signal) {
    const frameVideo = clips.find(({video, finished}) => !finished
      && typeof video.requestVideoFrameCallback === "function"
      && typeof video.cancelVideoFrameCallback === "function")?.video;
    const tick = {};
    const run = () => {
      if (scheduled !== tick || signal.aborted) return;
      cancelTick();
      monitor(signal);
    };
    if (frameVideo) {
      scheduler = "video-frame";
      const id = frameVideo.requestVideoFrameCallback(run);
      tick.cancelFrame = () => frameVideo.cancelVideoFrameCallback(id);
    } else {
      scheduler = "animation-frame";
      const id = requestAnimationFrame(run);
      tick.cancelFrame = () => cancelAnimationFrame(id);
    }
    // A stalled source stops supplying frame callbacks. The watchdog still checks the other clip.
    tick.watchdog = setTimeout(run, fallbackTimeoutMs);
    scheduled = tick;
  }

  function monitor(signal) {
    const active = clips.filter(clip => !clip.finished);
    if (active.length > 1 && active.every(({video}) => !video.seeking)) {
      const times = active.map(elapsed);
      drift.current = Math.max(...times) - Math.min(...times);
      drift.max = Math.max(drift.current, drift.max ?? 0);
      drift.samples += 1;
    } else {
      drift.current = null;
    }
    let crossedBoundary = false;
    for (const clip of active) {
      const {end} = clip.intervals[clip.index];
      const boundary = Math.min(end, clip.video.duration);
      if (clip.video.currentTime < boundary && !clip.video.ended) continue;
      crossedBoundary = true;
      maxBoundaryOverrun = Math.max(maxBoundaryOverrun ?? 0, clip.video.currentTime - boundary);
      if (clip.index + 1 < clip.intervals.length) {
        clip.index += 1;
        clip.target = clip.intervals[clip.index].start;
      } else {
        clip.finished = true;
        clip.target = boundary;
      }
    }
    if (crossedBoundary) {
      // Stop as a group while clips change source segments. The other elapsed positions are retained.
      begin(resume, true);
      return;
    }
    schedule(signal);
    publish();
  }

  function rewind() {
    for (const clip of clips) {
      clip.index = 0;
      clip.finished = clip.intervals.length === 0;
      clip.target = clip.intervals[0]?.start ?? null;
    }
    Object.assign(drift, {current: null, max: null, samples: 0});
    maxBoundaryOverrun = null;
  }

  function play() {
    if (disposed || willPlay || clips.every(clip => !clip.intervals.length)) return;
    original.pause();
    if (clips.every(clip => clip.finished)) rewind();
    return begin(resume, true);
  }

  function pause() {
    if (disposed || !willPlay) return;
    stopOperation();
    willPlay = false;
    state = "paused";
    publish();
  }

  function reset() {
    if (disposed || clips.every(clip => !clip.intervals.length)) return;
    rewind();
    return begin(async signal => {
      await Promise.all(clips.map(clip => prepare(clip, signal)));
      if (signal.aborted) return;
      state = "idle";
      publish();
    }, false);
  }

  function onOriginalPlay() {
    if (!original.paused) pause();
  }

  original.addEventListener("play", onOriginalPlay);
  const errorHandlers = clips.map(({video, name}) => {
    const handler = () => fail(`${name} could not load the source video.`);
    video.addEventListener("error", handler);
    return handler;
  });

  function dispose() {
    disposed = true;
    stopOperation();
    original.removeEventListener("play", onOriginalPlay);
    clips.forEach(({video}, index) => video.removeEventListener("error", errorHandlers[index]));
  }

  return {play, pause, reset, dispose};
}
