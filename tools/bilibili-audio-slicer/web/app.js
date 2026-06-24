const state = {
  jobId: null,
  audioUrl: null,
  duration: 0,
  peaks: null,
  dragging: false,
  dragMode: "range",
  selection: { start: 0, end: 0 },
  view: { zoom: 1, start: 0 },
  audioContext: null,
  playSelection: false,
};

const storageKeys = {
  videoUrl: "bilibili-audio-slicer.videoUrl",
  cookies: "bilibili-audio-slicer.cookies",
};

const el = {
  health: document.querySelector("#health"),
  videoUrl: document.querySelector("#videoUrl"),
  cookies: document.querySelector("#cookies"),
  downloadBtn: document.querySelector("#downloadBtn"),
  status: document.querySelector("#status"),
  audio: document.querySelector("#audio"),
  canvas: document.querySelector("#waveform"),
  startTime: document.querySelector("#startTime"),
  endTime: document.querySelector("#endTime"),
  durationLabel: document.querySelector("#durationLabel"),
  zoomLevel: document.querySelector("#zoomLevel"),
  zoomLabel: document.querySelector("#zoomLabel"),
  panPosition: document.querySelector("#panPosition"),
  playSelectionBtn: document.querySelector("#playSelectionBtn"),
  clipId: document.querySelector("#clipId"),
  updateCatalog: document.querySelector("#updateCatalog"),
  exportBtn: document.querySelector("#exportBtn"),
  exportResult: document.querySelector("#exportResult"),
};

function restoreSavedInputs() {
  el.videoUrl.value = localStorage.getItem(storageKeys.videoUrl) || "";
  el.cookies.value = localStorage.getItem(storageKeys.cookies) || "";
}

function saveInput(key, value) {
  localStorage.setItem(key, value);
}

function setStatus(message) {
  el.status.textContent = message;
}

function setExportResult(message) {
  el.exportResult.textContent = message;
}

function formatSeconds(seconds) {
  if (!Number.isFinite(seconds)) return "0.000";
  return seconds.toFixed(3);
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    const tools = [
      data.yt_dlp ? "yt-dlp OK" : "yt-dlp missing",
      data.ffmpeg ? "ffmpeg OK" : "ffmpeg missing",
    ];
    el.health.textContent = tools.join(" / ");
  } catch (error) {
    el.health.textContent = `Health check failed: ${error.message}`;
  }
}

async function loadAudioFromUrl() {
  const url = el.videoUrl.value.trim();
  if (!url) {
    setStatus("Paste a Bilibili URL first.");
    return;
  }

  el.downloadBtn.disabled = true;
  setStatus("Downloading and extracting audio...");
  setExportResult("");

  try {
    const data = await postJson("/api/download", {
      url,
      cookies: el.cookies.value.trim(),
    });
    state.jobId = data.job_id;
    state.audioUrl = `${data.audio_url}?t=${Date.now()}`;
    el.audio.src = state.audioUrl;
    setStatus(`Loaded: ${data.title}`);
    await buildWaveform(state.audioUrl);
  } catch (error) {
    setStatus(error.message);
  } finally {
    el.downloadBtn.disabled = false;
  }
}

async function buildWaveform(audioUrl) {
  setStatus("Decoding audio for waveform...");
  if (!state.audioContext) {
    state.audioContext = new AudioContext();
  }
  const response = await fetch(audioUrl);
  const arrayBuffer = await response.arrayBuffer();
  const audioBuffer = await state.audioContext.decodeAudioData(arrayBuffer);

  state.duration = audioBuffer.duration;
  state.selection.start = 0;
  state.selection.end = Math.min(3, state.duration);
  state.view.zoom = 1;
  state.view.start = 0;
  el.zoomLevel.value = "1";
  el.panPosition.value = "0";
  syncZoomControls();
  el.startTime.value = formatSeconds(state.selection.start);
  el.endTime.value = formatSeconds(state.selection.end);
  el.durationLabel.textContent = `${formatSeconds(state.duration)}s`;

  state.peaks = calculatePeaks(audioBuffer, 2400);
  drawWaveform();
  setStatus("Drag on the waveform to choose a slice.");
}

function calculatePeaks(audioBuffer, targetWidth) {
  const channelCount = audioBuffer.numberOfChannels;
  const length = audioBuffer.length;
  const samplesPerPeak = Math.max(1, Math.floor(length / targetWidth));
  const peaks = [];

  for (let i = 0; i < targetWidth; i += 1) {
    const start = i * samplesPerPeak;
    const end = Math.min(start + samplesPerPeak, length);
    let min = 1;
    let max = -1;

    for (let channel = 0; channel < channelCount; channel += 1) {
      const data = audioBuffer.getChannelData(channel);
      for (let index = start; index < end; index += 1) {
        const value = data[index] || 0;
        if (value < min) min = value;
        if (value > max) max = value;
      }
    }

    peaks.push({ min, max });
  }

  return peaks;
}

function resizeCanvasForDisplay() {
  const rect = el.canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));
  if (el.canvas.width !== width || el.canvas.height !== height) {
    el.canvas.width = width;
    el.canvas.height = height;
  }
  return { width, height };
}

function timeToX(time, width) {
  if (!state.duration) return 0;
  const { start, end } = visibleRange();
  return ((time - start) / (end - start)) * width;
}

function xToTime(x, width) {
  if (!state.duration) return 0;
  const { start, end } = visibleRange();
  return clamp(start + (x / width) * (end - start), start, end);
}

function visibleRange() {
  if (!state.duration) {
    return { start: 0, end: 0 };
  }
  const zoom = clamp(state.view.zoom, 1, 20);
  const windowDuration = state.duration / zoom;
  const maxStart = Math.max(0, state.duration - windowDuration);
  const start = clamp(state.view.start, 0, maxStart);
  return { start, end: start + windowDuration };
}

function updatePanFromSlider() {
  if (!state.duration) return;
  const zoom = Number(el.zoomLevel.value || 1);
  state.view.zoom = clamp(zoom, 1, 20);
  const windowDuration = state.duration / state.view.zoom;
  const maxStart = Math.max(0, state.duration - windowDuration);
  state.view.start = maxStart * Number(el.panPosition.value || 0);
  syncZoomControls();
  drawWaveform();
}

function syncZoomControls() {
  const { start, end } = visibleRange();
  const windowDuration = Math.max(0, end - start);
  const maxStart = Math.max(0, state.duration - windowDuration);
  el.zoomLevel.value = String(state.view.zoom);
  el.zoomLabel.textContent = `${state.view.zoom.toFixed(1)}x`;
  el.panPosition.disabled = state.view.zoom <= 1 || maxStart <= 0;
  el.panPosition.value = maxStart > 0 ? String(state.view.start / maxStart) : "0";
}

function zoomAround(factor, anchorTime) {
  if (!state.duration) return;
  const previous = visibleRange();
  const anchorRatio = previous.end > previous.start ? (anchorTime - previous.start) / (previous.end - previous.start) : 0.5;
  const nextZoom = clamp(state.view.zoom * factor, 1, 20);
  const nextWindow = state.duration / nextZoom;
  const maxStart = Math.max(0, state.duration - nextWindow);
  state.view.zoom = nextZoom;
  state.view.start = clamp(anchorTime - anchorRatio * nextWindow, 0, maxStart);
  syncZoomControls();
  drawWaveform();
}

function drawWaveform() {
  const { width, height } = resizeCanvasForDisplay();
  const ctx = el.canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = "#fbfcfd";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#d7dbe2";
  ctx.beginPath();
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();

  if (!state.peaks) {
    ctx.fillStyle = "#687385";
    ctx.fillText("Load audio to draw waveform.", 18, 30);
    return;
  }

  const startX = timeToX(state.selection.start, width);
  const endX = timeToX(state.selection.end, width);
  ctx.fillStyle = "rgba(22, 119, 255, 0.2)";
  ctx.fillRect(startX, 0, Math.max(1, endX - startX), height);

  ctx.strokeStyle = "#2f6f73";
  ctx.lineWidth = 1;
  ctx.beginPath();
  const center = height / 2;
  const scale = height * 0.42;
  for (let x = 0; x < width; x += 1) {
    const time = xToTime(x, width);
    const peakIndex = Math.floor((time / state.duration) * state.peaks.length);
    const peak = state.peaks[peakIndex] || { min: 0, max: 0 };
    ctx.moveTo(x + 0.5, center + peak.min * scale);
    ctx.lineTo(x + 0.5, center + peak.max * scale);
  }
  ctx.stroke();

  ctx.strokeStyle = "#1677ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(startX, 0);
  ctx.lineTo(startX, height);
  ctx.moveTo(endX, 0);
  ctx.lineTo(endX, height);
  ctx.stroke();

  if (el.audio.duration) {
    const playheadX = timeToX(el.audio.currentTime, width);
    ctx.strokeStyle = "#c2410c";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(playheadX, 0);
    ctx.lineTo(playheadX, height);
    ctx.stroke();
  }
}

function syncInputsFromSelection() {
  el.startTime.value = formatSeconds(state.selection.start);
  el.endTime.value = formatSeconds(state.selection.end);
}

function syncSelectionFromInputs() {
  const start = clamp(Number(el.startTime.value || 0), 0, state.duration || 0);
  const end = clamp(Number(el.endTime.value || 0), 0, state.duration || 0);
  state.selection.start = Math.min(start, end);
  state.selection.end = Math.max(start, end);
  ensureSelectionVisible();
  drawWaveform();
}

function ensureSelectionVisible() {
  if (!state.duration || state.view.zoom <= 1) return;
  const { start, end } = visibleRange();
  if (state.selection.start >= start && state.selection.end <= end) return;
  const windowDuration = end - start;
  const center = (state.selection.start + state.selection.end) / 2;
  const maxStart = Math.max(0, state.duration - windowDuration);
  state.view.start = clamp(center - windowDuration / 2, 0, maxStart);
  syncZoomControls();
}

function canvasEventX(event) {
  const rect = el.canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  return (event.clientX - rect.left) * ratio;
}

function beginDrag(event) {
  if (!state.duration) return;
  const { width } = resizeCanvasForDisplay();
  const x = canvasEventX(event);
  const startX = timeToX(state.selection.start, width);
  const endX = timeToX(state.selection.end, width);
  const edgeDistance = 12 * (window.devicePixelRatio || 1);

  if (Math.abs(x - startX) < edgeDistance) {
    state.dragMode = "start";
  } else if (Math.abs(x - endX) < edgeDistance) {
    state.dragMode = "end";
  } else {
    state.dragMode = "range";
    const time = xToTime(x, width);
    state.selection.start = time;
    state.selection.end = time;
  }

  state.dragging = true;
  updateDrag(event);
}

function updateDrag(event) {
  if (!state.dragging || !state.duration) return;
  const { width } = resizeCanvasForDisplay();
  const time = xToTime(canvasEventX(event), width);

  if (state.dragMode === "start") {
    state.selection.start = clamp(time, 0, state.selection.end);
  } else if (state.dragMode === "end") {
    state.selection.end = clamp(time, state.selection.start, state.duration);
  } else {
    state.selection.end = time;
    if (state.selection.end < state.selection.start) {
      [state.selection.start, state.selection.end] = [state.selection.end, state.selection.start];
    }
  }

  syncInputsFromSelection();
  drawWaveform();
}

function endDrag() {
  state.dragging = false;
}

function playSelection() {
  if (!state.duration || state.selection.end <= state.selection.start) return;
  state.playSelection = true;
  el.audio.currentTime = state.selection.start;
  el.audio.play();
  ensurePlayheadVisible();
}

function ensurePlayheadVisible() {
  if (!state.duration || state.view.zoom <= 1) return;
  const { start, end } = visibleRange();
  const time = el.audio.currentTime;
  if (time >= start && time <= end) return;
  const windowDuration = end - start;
  const maxStart = Math.max(0, state.duration - windowDuration);
  state.view.start = clamp(time - windowDuration / 2, 0, maxStart);
  syncZoomControls();
}

async function exportClip() {
  if (!state.jobId) {
    setExportResult("Load audio first.");
    return;
  }
  syncSelectionFromInputs();
  if (state.selection.end <= state.selection.start) {
    setExportResult("Select a non-empty range.");
    return;
  }
  const clipId = el.clipId.value.trim();
  if (!clipId) {
    setExportResult("ID is required.");
    return;
  }

  el.exportBtn.disabled = true;
  setExportResult("Exporting clip...");
  try {
    const data = await postJson("/api/clip", {
      job_id: state.jobId,
      start: state.selection.start,
      end: state.selection.end,
      clip_id: clipId,
      update_catalog: el.updateCatalog.checked,
    });
    setExportResult(`Saved ${data.path}; updated ${data.catalog}.`);
  } catch (error) {
    setExportResult(error.message);
  } finally {
    el.exportBtn.disabled = false;
  }
}

el.downloadBtn.addEventListener("click", loadAudioFromUrl);
el.videoUrl.addEventListener("input", () => saveInput(storageKeys.videoUrl, el.videoUrl.value));
el.cookies.addEventListener("input", () => saveInput(storageKeys.cookies, el.cookies.value));
el.playSelectionBtn.addEventListener("click", playSelection);
el.exportBtn.addEventListener("click", exportClip);
el.startTime.addEventListener("change", syncSelectionFromInputs);
el.endTime.addEventListener("change", syncSelectionFromInputs);
el.zoomLevel.addEventListener("input", updatePanFromSlider);
el.panPosition.addEventListener("input", updatePanFromSlider);
el.audio.addEventListener("timeupdate", () => {
  if (state.playSelection && el.audio.currentTime >= state.selection.end) {
    el.audio.pause();
    state.playSelection = false;
  }
  ensurePlayheadVisible();
  drawWaveform();
});
el.canvas.addEventListener("mousedown", beginDrag);
el.canvas.addEventListener("wheel", (event) => {
  if (!state.duration) return;
  event.preventDefault();
  const { width } = resizeCanvasForDisplay();
  const anchorTime = xToTime(canvasEventX(event), width);
  zoomAround(event.deltaY < 0 ? 1.2 : 1 / 1.2, anchorTime);
}, { passive: false });
window.addEventListener("mousemove", updateDrag);
window.addEventListener("mouseup", endDrag);
window.addEventListener("resize", drawWaveform);

restoreSavedInputs();
checkHealth();
drawWaveform();
