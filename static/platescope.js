'use strict';

const byId = (name) => document.getElementById(name);
const state = {
  modes: {}, mode: 'spots', panel: null, options: null, image: null, result: null,
  tool: null, anchor: null, hover: null, marker: null, plotCursor: null, serial: 0,
  seriesKey: null, suggestion: null,
};
const photoCanvas = byId('photo');
const photoContext = photoCanvas.getContext('2d');
const plotCanvas = byId('plot');
const plotContext = plotCanvas.getContext('2d');
const tools = [...document.querySelectorAll('[data-tool]')];
const inputNames = ['lanes', 'lane', 'reference', 'sample_band', 'reference_band', 'cutoff', 'min_height', 'tolerance'];

function notice(message, error = false) {
  const node = byId('status');
  node.textContent = message;
  node.classList.toggle('error', error);
  clearTimeout(notice.timer);
  notice.timer = setTimeout(() => { node.textContent = ''; }, 5500);
}

async function request(path, method = 'GET', data) {
  const response = await fetch('/tlc' + path, {
    method,
    headers: data && !(data instanceof FormData) ? {'Content-Type': 'application/json'} : {},
    body: data instanceof FormData ? data : data === undefined ? undefined : JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || '读板请求未完成。');
  return result;
}

function safe(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (error) {
      notice(error.message, true);
    }
  };
}

function piece(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function panelPath(path = '') {
  return '/panels/' + state.panel.id + path;
}

function sourceTag(panel) {
  return {synthetic: '合成练习', prepared: '照片准备结果', upload: '上传原片'}[panel.provenance.kind];
}

async function listPanels() {
  const records = await request('/panels');
  const list = byId('library');
  list.replaceChildren();
  if (!records.length) list.append(piece('p', 'quiet', '还没有照片'));
  for (const panel of records) {
    const select = piece('button', 'panel-chip');
    select.classList.toggle('chosen', panel.id === state.panel?.id);
    select.append(piece('strong', '', panel.title),
                  piece('small', '', `${sourceTag(panel)} · ${panel.width} × ${panel.height}`));
    select.addEventListener('click', safe(() => openPanel(panel.id)));
    list.append(select);
  }
  return records;
}

function listChecks() {
  const list = byId('saved');
  list.replaceChildren();
  const checks = state.panel?.checks || [];
  if (!checks.length) list.append(piece('p', 'quiet', '还没有保存的读板'));
  for (const check of checks) {
    const select = piece('button', 'saved-chip');
    select.classList.toggle('chosen', check.id === state.result?.id);
    select.append(piece('strong', '', check.heading),
                  piece('small', '', new Date(check.created).toLocaleString('zh-CN', {hour12: false})));
    select.addEventListener('click', safe(() => openCheck(check.id)));
    list.append(select);
  }
}

function inputValues() {
  const form = byId('settings');
  return {...state.options, channel: form.elements.channel.value,
          splits: state.options?.splits ?? [],
          ...Object.fromEntries(inputNames.map(name => [name, form.elements[name].valueAsNumber]))};
}

function drawInputs() {
  const form = byId('settings');
  for (const name of inputNames) form.elements[name].value = state.options[name];
  form.elements.channel.value = state.options.channel;
}

function renderModes() {
  const list = byId('modes');
  list.replaceChildren();
  for (const mode of state.modeOrder ?? []) {
    const label = state.modes[mode];
    const button = piece('button', state.mode === mode ? 'selected' : '', label);
    button.disabled = !state.panel;
    button.setAttribute('aria-pressed', String(state.mode === mode));
    button.addEventListener('click', safe(async () => {
      state.mode = mode;
      renderModes();
      await run();
    }));
    list.append(button);
  }
}

function enableDesk(enabled) {
  for (const button of tools) button.disabled = !enabled;
  for (const name of ['inputs', 'save', 'run', 'apply']) byId(name).disabled = !enabled;
}

async function openPanel(id) {
  const serial = ++state.serial;
  const panel = await request('/panels/' + id);
  const image = new Image();
  image.src = '/tlc/panels/' + id + '/image';
  await image.decode();
  if (serial !== state.serial) return;
  state.panel = panel;
  state.image = image;
  state.options = panel.settings;
  state.result = null;
  localStorage.setItem('platescope-panel', id);
  byId('title').textContent = panel.title;
  byId('source-info').textContent = `${sourceTag(panel)} · ${panel.filename} · ${panel.width} × ${panel.height} px`;
  const scale = Math.min(1, 1700 / Math.max(panel.width, panel.height));
  photoCanvas.width = Math.round(panel.width * scale);
  photoCanvas.height = Math.round(panel.height * scale);
  photoCanvas.hidden = false;
  byId('empty').hidden = true;
  enableDesk(true);
  selectTool(null);
  drawInputs();
  renderModes();
  drawPhoto();
  listChecks();
  await run();
  await listPanels();
}

function drawMark(mark, scaleX, scaleY) {
  const points = mark.points.map(([x, y]) => [x * scaleX, y * scaleY]);
  photoContext.strokeStyle = mark.color;
  photoContext.fillStyle = mark.color;
  photoContext.lineWidth = Math.max(1, photoCanvas.width / 700);
  const [[left, top], [right, bottom]] = points;
  if (mark.type === 'box') {
    photoContext.strokeRect(left, top, right - left, bottom - top);
  } else {
    photoContext.beginPath();
    photoContext.moveTo(left, top);
    points.slice(1).forEach(([x, y]) => photoContext.lineTo(x, y));
    if (mark.type === 'polygon') photoContext.closePath();
    photoContext.stroke();
  }
  if (mark.label) {
    photoContext.font = `${Math.max(13, photoCanvas.width / 55)}px system-ui`;
    photoContext.lineWidth = 2.6;
    photoContext.strokeStyle = '#f2f2ea';
    photoContext.strokeText(mark.label, left + 4, Math.max(12, top - 4));
    photoContext.fillText(mark.label, left + 4, Math.max(12, top - 4));
  }
}

function drawPhoto() {
  if (!state.image) return;
  const {width, height} = photoCanvas;
  photoContext.drawImage(state.image, 0, 0, width, height);
  const scaleX = width / state.panel.width;
  const scaleY = height / state.panel.height;
  if (byId('marks').checked) {
    for (const mark of state.result?.marks || []) drawMark(mark, scaleX, scaleY);
  }
  if (state.tool && state.hover) {
    const [bx, by] = state.hover;
    const [ax, ay] = state.anchor || state.hover;
    if (state.tool !== 'roi' || state.anchor) {
      const mark = state.tool === 'roi'
        ? {type: 'box', points: [[Math.min(ax, bx), Math.min(ay, by)], [Math.max(ax, bx), Math.max(ay, by)]]}
        : {type: 'line', points: [[state.options.roi[0], by], [state.options.roi[2], by]]};
      drawMark({...mark, color: '#ef7619'}, width, height);
    }
  }
  if (state.marker) {
    const [x, y] = [state.marker[0] * scaleX, state.marker[1] * scaleY];
    const radius = Math.max(5, width / 100);
    photoContext.strokeStyle = '#ecff96';
    photoContext.lineWidth = Math.max(2, width / 600);
    photoContext.beginPath();
    photoContext.arc(x, y, radius, 0, Math.PI * 2);
    photoContext.moveTo(x - radius * 1.5, y);
    photoContext.lineTo(x + radius * 1.5, y);
    photoContext.moveTo(x, y - radius * 1.5);
    photoContext.lineTo(x, y + radius * 1.5);
    photoContext.stroke();
  }
}

function showAt(at) {
  state.marker = at;
  if (at) byId('position').textContent = `原片 ${at[0]}, ${at[1]} px`;
  drawPhoto();
}

function activeSeries() {
  const graph = state.result?.plot;
  const list = graph?.series ?? [];
  if (!list.length) return null;
  return list.find(part => part.key === state.seriesKey) || list[0];
}

function drawLegend() {
  const legend = byId('plot-legend');
  const series = state.result?.plot?.series ?? [];
  legend.replaceChildren();
  legend.hidden = !series.length;
  if (!series.length) return;
  const chosen = activeSeries();
  for (const part of series) {
    const dot = piece('i');
    dot.style.background = part.color;
    const button = piece('button', part.key === chosen?.key ? 'chosen' : '');
    button.append(dot, document.createTextNode(part.label));
    button.setAttribute('aria-pressed', String(part.key === chosen?.key));
    button.addEventListener('click', () => {
      state.seriesKey = part.key;
      state.plotCursor = null;
      drawPlot();
    });
    legend.append(button);
  }
}

function drawPlot() {
  const graph = state.result?.plot;
  const series = activeSeries();
  const samples = series ? series.samples : graph?.samples ?? [];
  byId('plot-box').hidden = !samples.length;
  drawLegend();
  if (!samples.length) return;
  const {width, height} = plotCanvas;
  plotContext.clearRect(0, 0, width, height);
  byId('plot-title').textContent = graph.label;
  const chosen = state.plotCursor;
  byId('sample-read').textContent = chosen
    ? `${chosen.x} · ${chosen.y}` : series ? '点击曲线回到这一团计入的像素' : '点击曲线回到原片';
  const [left, right, top, bottom] = [47, width - 27, 13, height - 28];
  const minX = samples[0].x;
  const maxX = samples.at(-1).x;
  const minY = Math.min(...samples.map(s => s.y));
  const maxY = Math.max(...samples.map(s => s.y));
  const toX = (x) => left + (x - minX) * (right - left) / Math.max(maxX - minX, 1e-5);
  const toY = (y) => bottom - (y - minY) * (bottom - top) / Math.max(maxY - minY, 1e-5);
  plotContext.font = '12px system-ui';
  plotContext.fillStyle = '#52675e';
  for (let step = 0; step <= 4; step++) {
    const y = top + (bottom - top) * step / 4;
    plotContext.strokeStyle = '#e1eae5';
    plotContext.beginPath();
    plotContext.moveTo(left, y);
    plotContext.lineTo(right, y);
    plotContext.stroke();
    plotContext.fillText(String(+(maxY - (maxY - minY) * step / 4).toPrecision(3)), 1, y + 4);
    const value = minX + (maxX - minX) * step / 4;
    plotContext.fillText(String(+value.toPrecision(4)), toX(value), bottom + 21);
  }
  plotContext.beginPath();
  plotContext.strokeStyle = series ? series.color : '#166958';
  plotContext.lineWidth = 2;
  samples.forEach((sample, index) => {
    if (index) plotContext.lineTo(toX(sample.x), toY(sample.y));
    else plotContext.moveTo(toX(sample.x), toY(sample.y));
  });
  plotContext.stroke();
  plotContext.lineWidth = 1;
  if (chosen) {
    plotContext.fillStyle = series ? series.color : '#ac5619';
    plotContext.beginPath();
    plotContext.arc(toX(chosen.x), toY(chosen.y), 5, 0, Math.PI * 2);
    plotContext.fill();
  }
}

function renderSplit() {
  const list = state.result?.suggestions ?? [];
  const box = byId('split-box');
  const target = byId('split-list');
  target.replaceChildren();
  box.hidden = !list.length;
  state.suggestion = null;
  for (const suggestion of list) {
    const card = piece('div', 'split-card');
    card.append(piece('strong', '', `带 ${suggestion.band} 可拆成两团`),
                piece('p', '', suggestion.reason));
    const button = piece('button', 'primary', '采用拆分');
    button.addEventListener('click', () => adopt(suggestion));
    card.append(button);
    target.append(card);
  }
  if (list.length) state.suggestion = list[0];
}

async function adopt(suggestion) {
  const rest = (state.options.splits ?? []).filter(item => item.lane !== suggestion.lane);
  state.options = {...inputValues(), splits: [...rest, {lane: suggestion.lane, seeds: suggestion.seeds}]};
  state.marker = null;
  state.plotCursor = null;
  state.seriesKey = null;
  await run();
  notice('已采用拆分；可在「显色曲线」逐团查看，保存读板会一并保留');
}

function renderResult() {
  const result = state.result;
  if (!result) return;
  byId('result-title').textContent = result.heading;
  byId('result-state').textContent = result.id ? '已保存' : '预览';
  const metrics = byId('metrics');
  metrics.replaceChildren();
  for (const metric of result.metrics) {
    const card = piece('div', 'metric');
    card.append(piece('small', '', metric.label),
                piece('b', '', [metric.value, metric.units].filter(v => v !== '').join(' ')));
    metrics.append(card);
  }
  const rows = byId('rows');
  rows.replaceChildren();
  for (const row of result.rows) {
    const element = piece(row.at ? 'button' : 'div', 'reading');
    element.append(piece('span', '', row.label), piece('b', '', Array.isArray(row.value) ? row.value.join(', ') : row.value));
    if (row.detail) element.append(piece('small', '', row.detail));
    if (row.at) element.addEventListener('click', () => showAt(row.at));
    rows.append(element);
  }
  for (const [name, ext] of [['csv', 'report.csv'], ['png', 'overlay.png']]) {
    const download = byId(name);
    download.hidden = !result.id;
    if (result.id) download.href = '/tlc' + panelPath(`/checks/${result.id}/${ext}`);
    else download.removeAttribute('href');
  }
  renderSplit();
  state.seriesKey = (result.plot?.series ?? []).length ? state.seriesKey : null;
  drawPhoto();
  drawPlot();
  listChecks();
}

async function run() {
  if (!state.panel || !byId('settings').reportValidity()) return;
  const serial = ++state.serial;
  const chosen = inputValues();
  const result = await request(panelPath('/preview'), 'POST', {mode: state.mode, settings: chosen});
  if (serial !== state.serial) return;
  state.options = result.settings;
  state.result = result;
  state.marker = null;
  state.plotCursor = null;
  renderResult();
}

async function openCheck(id) {
  const serial = ++state.serial;
  const saved = await request(panelPath('/checks/' + id));
  if (serial !== state.serial) return;
  state.result = saved;
  state.mode = saved.mode;
  state.options = saved.settings;
  state.marker = null;
  state.plotCursor = null;
  drawInputs();
  renderModes();
  renderResult();
}

function selectTool(name) {
  state.tool = name;
  state.anchor = null;
  state.hover = null;
  photoCanvas.classList.toggle('active-tool', Boolean(name));
  for (const button of tools) button.classList.toggle('chosen', name === button.dataset.tool);
  byId('position').textContent = name === 'roi' ? '在照片上点板区的两个对角' : name ? '点击照片标出参考线' : '';
  drawPhoto();
}

function normalPoint(event) {
  const rect = photoCanvas.getBoundingClientRect();
  const scale = Math.min(rect.width / photoCanvas.width, rect.height / photoCanvas.height);
  const width = photoCanvas.width * scale, height = photoCanvas.height * scale;
  const left = rect.left + (rect.width - width) / 2, top = rect.top + (rect.height - height) / 2;
  const x = (event.clientX - left) / width, y = (event.clientY - top) / height;
  return x >= 0 && x <= 1 && y >= 0 && y <= 1 ? [x, y] : null;
}

photoCanvas.addEventListener('pointermove', (event) => {
  if (!state.panel) return;
  const point = normalPoint(event);
  if (!point) return;
  byId('position').textContent = `原片 ${Math.round(point[0] * (state.panel.width - 1))}, ${Math.round(point[1] * (state.panel.height - 1))} px`;
  if (state.tool) {
    state.hover = point;
    drawPhoto();
  }
});

photoCanvas.addEventListener('pointerleave', () => {
  state.hover = null;
  drawPhoto();
});

photoCanvas.addEventListener('click', safe(async (event) => {
  const point = normalPoint(event);
  if (!state.tool || !point || !byId('settings').reportValidity()) return;
  const chosen = inputValues();
  const [x, y] = point;
  if (state.tool === 'roi') {
    if (!state.anchor) {
      state.anchor = point;
      return;
    }
    const [ax, ay] = state.anchor;
    const [left, right] = [Math.min(ax, x), Math.max(ax, x)];
    const [top, bottom] = [Math.min(ay, y), Math.max(ay, y)];
    if (right - left < .06 || bottom - top < .08) throw Error('板区过小，请重选后一个角。');
    chosen.roi = [left, top, right, bottom];
    if (chosen.front < top || chosen.origin > bottom) {
      const margin = (bottom - top) * .08;
      chosen.front = top + margin;
      chosen.origin = bottom - margin;
    }
  } else {
    const next = {...chosen, [state.tool]: y};
    if (next.front < next.roi[1] || next.origin > next.roi[3] || next.origin - next.front < .04) {
      throw Error('在板区内点击，溶剂前沿应在起跑线上方。');
    }
    chosen[state.tool] = y;
  }
  state.options = chosen;
  selectTool(null);
  await run();
}));

plotCanvas.addEventListener('click', (event) => {
  const graph = state.result?.plot;
  const series = activeSeries();
  const samples = series ? series.samples : graph?.samples ?? [];
  if (!samples.length) return;
  const rect = plotCanvas.getBoundingClientRect();
  const left = 47, right = plotCanvas.width - 27;
  const x = (event.clientX - rect.left) * plotCanvas.width / rect.width;
  const t = Math.max(0, Math.min(1, (x - left) / (right - left)));
  state.plotCursor = samples[Math.round(t * (samples.length - 1))];
  showAt(state.plotCursor.at);
  drawPlot();
});

for (const button of tools) button.addEventListener('click', () => selectTool(button.dataset.tool));
byId('marks').addEventListener('change', drawPhoto);
byId('settings').addEventListener('submit', safe(async (event) => { event.preventDefault(); await run(); }));
byId('upload').addEventListener('click', () => { byId('file').value = ''; byId('file').click(); });
byId('file').addEventListener('change', safe(async () => {
  const selected = byId('file').files[0];
  if (!selected) return;
  const data = new FormData();
  data.append('file', selected);
  const panel = await request('/panels', 'POST', data);
  await openPanel(panel.id);
}));
byId('demo').addEventListener('click', safe(async () => {
  const panel = await request('/demo', 'POST');
  await openPanel(panel.id);
}));
byId('apply').addEventListener('click', safe(async () => {
  if (!byId('settings').reportValidity()) return;
  const id = state.panel.id;
  const panel = await request(panelPath('/settings'), 'PUT', {revision: state.panel.revision, settings: inputValues()});
  if (state.panel.id !== id) return;
  state.panel = panel;
  state.options = panel.settings;
  notice('板照标定已保留');
  await run();
}));
byId('save').addEventListener('click', safe(async () => {
  if (!byId('settings').reportValidity()) return;
  const id = state.panel.id;
  const saved = await request(panelPath('/checks'), 'POST', {
    revision: state.panel.revision, mode: state.mode, settings: inputValues(),
  });
  if (state.panel.id !== id) return;
  state.panel = saved.panel;
  state.options = saved.check.settings;
  state.result = saved.check;
  state.marker = null;
  state.plotCursor = null;
  renderResult();
  notice('读板已保存，可下载 CSV 或标记 PNG');
}));

safe(async () => {
  const config = await request('/config');
  state.modes = config.modes;
  state.modeOrder = config.mode_order;
  byId('channel').replaceChildren(...Object.entries(config.channels).map(([value, label]) => {
    const option = piece('option', '', label);
    option.value = value;
    return option;
  }));
  renderModes();
  listChecks();
  const records = await listPanels();
  const id = localStorage.getItem('platescope-panel');
  const chosen = records.find(p => p.id === id) || records[0];
  if (chosen) await openPanel(chosen.id);
})();
