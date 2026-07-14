const config = window.INITIAL_CONFIG;
const selected = new Map((config.govee.devices || []).map(device => [device.device, device]));
let elementOutputs = structuredClone(config.element_outputs || {});
let elementActions = structuredClone(config.element_actions || {});
let elementCombos = structuredClone(config.element_combos || {});
let figurePalettes = structuredClone(config.figure_palettes || {});
let powerupPalettes = structuredClone(config.powerup_palettes || {});
let defaultPalette = structuredClone(config.default_palette || {});
let activeElement = null;
let activeComboKey = null;
let activeNamed = null;
let currentState = {figures: [], recent_figures: config.recent_figures || [], recent_powerups: config.recent_powerups || [], history: config.history || []};
const sceneCache = new Map();
let sceneRefreshInFlight = false;
let savedSignature = null;

const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const notice = (message, error = false) => {
  const node = $('#notice');
  node.textContent = message;
  node.className = `notice${error ? ' error' : ''}`;
  setTimeout(() => node.classList.add('hidden'), 5000);
};

function capability(device, instance) {
  return (device.capabilities || []).find(item => item.instance === instance);
}

function namedCollection(kind) {
  return kind === 'figure' ? figurePalettes : powerupPalettes;
}

function namedCatalog(kind) {
  return kind === 'figure' ? window.FIGURES : window.POWERUPS;
}

function addNamedPalette(kind, id) {
  const catalog = namedCatalog(kind);
  const figure = catalog[id];
  if (!figure) return;
  const collection = namedCollection(kind);
  collection[id] ||= {color: elementColor(figure.element), outputs: {}, lights_enabled: true, ha_scene: ''};
  renderNamedPalettes(kind);
}

function renderNamedPalettes(kind) {
  const collection = namedCollection(kind);
  const catalog = namedCatalog(kind);
  const box = $(`#${kind === 'figure' ? 'figurePalettes' : 'powerupPalettes'}`);
  const query = $(`#${kind === 'figure' ? 'figureSearch' : 'powerupSearch'}`).value.toLowerCase();
  box.innerHTML = '';
  Object.entries(collection).filter(([id]) => (catalog[id]?.name || '').toLowerCase().includes(query)).forEach(([id, profile]) => {
    const figure = catalog[id] || {name: `#${id}`, element: 'unknown'};
    const card = document.createElement('article');
    card.className = 'named-palette';
    card.innerHTML = `<div><strong>${escapeHtml(figure.name)}</strong><small>${escapeHtml(figure.element || 'Power up')}</small></div><input class="named-color" type="color" value="${profile.color || elementColor(figure.element)}"><button type="button" class="secondary named-customize">Customize</button><button type="button" class="named-remove">Remove</button>`;
    card.querySelector('.named-color').oninput = event => { profile.color = event.target.value.toUpperCase(); };
    card.querySelector('.named-customize').onclick = () => openNamedCustomize(kind, id).catch(error => notice(error.message, true));
    card.querySelector('.named-remove').onclick = () => { delete collection[id]; renderNamedPalettes(kind); };
    box.append(card);
  });
  if (!box.children.length) box.innerHTML = '<div class="empty-state">No matching palettes yet.</div>';
}

function elementColor(element) {
  return document.querySelector(`.element-card[data-element="${element}"] .element-color`).value.toUpperCase();
}

function activeColor(deviceIndex = 0) {
  if (activeNamed) return namedCollection(activeNamed.kind)[activeNamed.id].color || elementColor(namedCatalog(activeNamed.kind)[activeNamed.id].element);
  if (activeElement === 'default') return defaultPalette.color || elementColor('default');
  if (!activeComboKey) return elementColor(activeElement);
  const combo = elementCombos[activeComboKey];
  const split = Math.ceil(selected.size / 2);
  const element = combo.elements[deviceIndex < split ? 0 : 1];
  return combo.colors[element] || elementColor(element);
}

function profileFor(device, deviceIndex) {
  let outputs;
  if (activeNamed) outputs = (namedCollection(activeNamed.kind)[activeNamed.id].outputs ||= {});
  else if (activeElement === 'default') outputs = (defaultPalette.outputs ||= {});
  else if (activeComboKey) outputs = (elementCombos[activeComboKey].outputs ||= {});
  else outputs = (elementOutputs[activeElement] ||= {});
  outputs[device.device] ||= {
    mode: 'color', color: activeColor(deviceIndex), brightness: config.govee.brightness,
  };
  return outputs[device.device];
}

function activeAction() {
  if (activeNamed) return namedCollection(activeNamed.kind)[activeNamed.id];
  if (activeElement === 'default') return defaultPalette;
  if (activeComboKey) return elementCombos[activeComboKey];
  elementActions[activeElement] ||= {};
  return elementActions[activeElement];
}

function renderPaletteAutomation() {
  const action = activeAction();
  if (action.lights_enabled === undefined) action.lights_enabled = true;
  const box = $('#paletteAutomation');
  box.innerHTML = `<label class="check-label"><input id="paletteLights" type="checkbox" ${action.lights_enabled ? 'checked' : ''}> Change Govee lights</label><label>Home Assistant scene<input id="paletteHaScene" placeholder="scene.portal_action" value="${escapeHtml(action.ha_scene || '')}"></label><small>Disable Govee lights to trigger only the Home Assistant scene.</small>`;
  $('#paletteLights').onchange = event => { action.lights_enabled = event.target.checked; $('#customizeDevices').classList.toggle('disabled-profiles', !event.target.checked); };
  $('#paletteHaScene').oninput = event => { action.ha_scene = event.target.value.trim(); };
  $('#customizeDevices').classList.toggle('disabled-profiles', !action.lights_enabled);
}

function musicValue(device, profile) {
  const fields = capability(device, 'musicMode')?.parameters?.fields || [];
  const modeField = fields.find(field => field.fieldName === 'musicMode');
  return {
    musicMode: profile.musicMode ?? modeField?.options?.[0]?.value ?? 1,
    sensitivity: profile.sensitivity ?? 50,
    autoColor: profile.autoColor ?? 1,
    rgb: parseInt((profile.color || activeColor()).slice(1), 16),
  };
}

async function loadScenes(device, select, profile) {
  select.innerHTML = '<option>Loading scenes…</option>';
  try {
    if (!sceneCache.has(device.device)) {
      const response = await fetch('/api/govee/scenes', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device: device.device}),
      });
      const payload = await response.json();
      if (!payload.ok) throw Error(payload.error);
      sceneCache.set(device.device, payload.scenes);
    }
    const scenes = sceneCache.get(device.device);
    select.innerHTML = scenes.length ? '' : '<option>No scenes returned</option>';
    scenes.forEach((scene, index) => {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = scene.name;
      if (JSON.stringify(scene.capability) === JSON.stringify(profile.capability)) option.selected = true;
      select.append(option);
    });
    if (scenes.length && !profile.capability) profile.capability = scenes[+select.value || 0].capability;
    select.onchange = () => { profile.capability = scenes[+select.value].capability; };
  } catch (error) {
    select.innerHTML = `<option>${escapeHtml(error.message)}</option>`;
  }
}

async function refreshSceneCache(force = true) {
  if (sceneRefreshInFlight || !selected.size) return;
  sceneRefreshInFlight = true;
  try {
    for (const device of selected.values()) {
      const response = await fetch('/api/govee/scenes', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device: device.device, refresh: force}),
      });
      const payload = await response.json();
      if (payload.ok) sceneCache.set(device.device, payload.scenes);
    }
  } finally {
    sceneRefreshInFlight = false;
  }
}

function renderCustomizeDevices() {
  const box = $('#customizeDevices');
  box.innerHTML = '';
  if (!selected.size) {
    box.innerHTML = '<div class="empty-state">Select at least one Govee light first.</div>';
    return;
  }
  [...selected.values()].forEach((device, deviceIndex) => {
    const profile = profileFor(device, deviceIndex);
    const supportsScene = !!(capability(device, 'lightScene') || capability(device, 'diyScene'));
    const music = capability(device, 'musicMode');
    const card = document.createElement('article');
    card.className = 'light-profile';
    const modes = [`<option value="color">Individual color</option>`];
    if (supportsScene) modes.push('<option value="scene">Govee scene</option>');
    if (music) modes.push('<option value="music">Music mode</option>');
    card.innerHTML = `<div class="profile-head"><div><strong>${escapeHtml(device.deviceName || device.sku)}</strong><small>${escapeHtml(device.sku)}</small></div><select class="profile-mode">${modes.join('')}</select></div><div class="profile-controls"></div>`;
    const mode = card.querySelector('.profile-mode');
    mode.value = (profile.mode === 'scene' && !supportsScene) || (profile.mode === 'music' && !music) ? 'color' : profile.mode;
    profile.mode = mode.value;
    const controls = card.querySelector('.profile-controls');

    const renderControls = () => {
      controls.innerHTML = '';
      profile.mode = mode.value;
      if (profile.mode === 'color') {
        controls.innerHTML = `<label>Color<input class="profile-color" type="color" value="${profile.color || activeColor(deviceIndex)}"></label><label>Brightness <span>${profile.brightness || config.govee.brightness}%</span><input class="profile-brightness" type="range" min="1" max="100" value="${profile.brightness || config.govee.brightness}"></label>`;
        controls.querySelector('.profile-color').oninput = event => { profile.color = event.target.value.toUpperCase(); };
        const brightness = controls.querySelector('.profile-brightness');
        brightness.oninput = event => { profile.brightness = +event.target.value; event.target.previousElementSibling.textContent = `${event.target.value}%`; };
      } else if (profile.mode === 'scene') {
        controls.innerHTML = '<label>Scene<select class="profile-scene"></select></label>';
        loadScenes(device, controls.querySelector('.profile-scene'), profile);
      } else {
        const fields = music.parameters?.fields || [];
        const options = fields.find(field => field.fieldName === 'musicMode')?.options || [];
        controls.innerHTML = `<label>Music style<select class="music-style">${options.map(option => `<option value="${option.value}">${escapeHtml(option.name)}</option>`).join('')}</select></label><label>Sensitivity <span>${profile.sensitivity ?? 50}%</span><input class="music-sensitivity" type="range" min="0" max="100" value="${profile.sensitivity ?? 50}"></label><label>Base color<input class="music-color" type="color" value="${profile.color || activeColor(deviceIndex)}"></label><label class="check-label"><input class="music-auto" type="checkbox" ${profile.autoColor !== 0 ? 'checked' : ''}> Automatic colors</label>`;
        const style = controls.querySelector('.music-style');
        if (profile.musicMode != null) style.value = profile.musicMode;
        const updateMusic = () => {
          profile.musicMode = +style.value;
          profile.sensitivity = +controls.querySelector('.music-sensitivity').value;
          profile.color = controls.querySelector('.music-color').value.toUpperCase();
          profile.autoColor = controls.querySelector('.music-auto').checked ? 1 : 0;
          profile.capability = {type: music.type, instance: music.instance, value: musicValue(device, profile)};
        };
        controls.querySelectorAll('input,select').forEach(input => input.oninput = event => {
          if (event.target.classList.contains('music-sensitivity')) event.target.previousElementSibling.textContent = `${event.target.value}%`;
          updateMusic();
        });
        updateMusic();
      }
    };
    mode.onchange = renderControls;
    renderControls();
    box.append(card);
  });
}

async function openCustomize(element) {
  activeElement = element;
  activeComboKey = null;
  activeNamed = null;
  $('#customizeTitle').textContent = element === 'default' ? 'Customize No Skylander' : `Customize ${element[0].toUpperCase()}${element.slice(1)}`;
  await save(false);
  renderPaletteAutomation();
  renderCustomizeDevices();
  $('#customizeDialog').showModal();
}

async function openComboCustomize(key) {
  activeComboKey = key;
  activeElement = null;
  activeNamed = null;
  const combo = elementCombos[key];
  $('#customizeTitle').textContent = `Customize ${combo.elements.map(element => element[0].toUpperCase() + element.slice(1)).join(' + ')}`;
  await save(false);
  renderPaletteAutomation();
  renderCustomizeDevices();
  $('#customizeDialog').showModal();
}

async function openNamedCustomize(kind, id) {
  activeNamed = {kind, id};
  activeElement = null;
  activeComboKey = null;
  $('#customizeTitle').textContent = `Customize ${namedCatalog(kind)[id].name}`;
  await save(false);
  renderPaletteAutomation();
  renderCustomizeDevices();
  $('#customizeDialog').showModal();
}

function renderCombos() {
  const grid = $('#comboGrid');
  grid.innerHTML = '';
  const entries = Object.entries(elementCombos);
  if (!entries.length) {
    grid.innerHTML = '<div class="empty-state">No advanced combinations yet. Add two elements above.</div>';
    return;
  }
  entries.forEach(([key, combo]) => {
    combo.colors ||= {};
    const card = document.createElement('article');
    card.className = 'combo-card';
    const [first, second] = combo.elements;
    const firstColor = combo.colors[first] || elementColor(first);
    const secondColor = combo.colors[second] || elementColor(second);
    card.innerHTML = `<div class="combo-title"><div class="combo-dots"><i style="--dot:${firstColor}"></i><i style="--dot:${secondColor}"></i></div><strong>${escapeHtml(first[0].toUpperCase() + first.slice(1))} + ${escapeHtml(second[0].toUpperCase() + second.slice(1))}</strong></div><div class="combo-colors"><label>${escapeHtml(first)}<input type="color" data-element="${first}" value="${firstColor}"></label><label>${escapeHtml(second)}<input type="color" data-element="${second}" value="${secondColor}"></label></div><div class="combo-actions"><button type="button" class="secondary combo-customize">Customize lights</button><button type="button" class="secondary combo-test">Test</button><button type="button" class="combo-remove">Remove</button></div>`;
    card.querySelectorAll('.combo-colors input').forEach(input => input.oninput = event => {
      combo.colors[event.target.dataset.element] = event.target.value.toUpperCase();
      const dots = card.querySelectorAll('.combo-dots i');
      dots[event.target.dataset.element === first ? 0 : 1].style.setProperty('--dot', event.target.value);
    });
    card.querySelector('.combo-customize').onclick = () => openComboCustomize(key).catch(error => notice(error.message, true));
    card.querySelector('.combo-test').onclick = async () => {
      await save(false);
      const response = await fetch('/api/test-combo', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({elements: combo.elements})});
      const payload = await response.json();
      notice(payload.ok ? `Testing ${first} + ${second}.` : payload.error, !payload.ok);
    };
    card.querySelector('.combo-remove').onclick = () => { delete elementCombos[key]; renderCombos(); };
    grid.append(card);
  });
}

function renderRecommendations() {
  const figures = currentState.figures || [];
  const elements = [...new Set(figures.filter(figure => figure.kind !== 'power_up').map(figure => figure.element))].slice(0, 2).sort();
  const combo = $('#comboRecommendation');
  combo.classList.toggle('hidden', elements.length !== 2);
  if (elements.length === 2) {
    combo.innerHTML = `<span>On the portal now: <strong>${escapeHtml(elements[0])} + ${escapeHtml(elements[1])}</strong></span><button type="button">Create recommended combo</button>`;
    combo.querySelector('button').onclick = () => {
      const key = elements.join('+');
      elementCombos[key] ||= {elements, colors: {[elements[0]]: elementColor(elements[0]), [elements[1]]: elementColor(elements[1])}, outputs: {}};
      renderCombos();
    };
  }
  renderLibraryRecommendation('figure', figures.filter(figure => figure.kind !== 'power_up').map(figure => figure.id), currentState.recent_figures || []);
  renderLibraryRecommendation('powerup', figures.filter(figure => figure.kind === 'power_up').map(figure => figure.id), currentState.recent_powerups || []);
}

function renderLibraryRecommendation(kind, currentIds, recentIds) {
  const box = $(`#${kind === 'figure' ? 'figureRecommendation' : 'powerupRecommendation'}`);
  const catalog = namedCatalog(kind);
  const ids = [...new Set([...currentIds, ...recentIds])].filter(id => catalog[id]).slice(0, 8);
  box.classList.toggle('hidden', !ids.length);
  if (!ids.length) return;
  box.innerHTML = `<span><strong>${currentIds.length ? 'On portal now' : 'Recently used'}</strong></span><div class="recommendation-chips"></div>`;
  const chips = box.querySelector('.recommendation-chips');
  ids.forEach(id => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = catalog[id].name;
    button.onclick = () => addNamedPalette(kind, String(id));
    chips.append(button);
  });
}

function renderHistory() {
  const box = $('#history');
  const history = currentState.history || [];
  box.innerHTML = history.length ? '' : '<div class="empty-state">No activity recorded yet.</div>';
  history.slice(0, 30).forEach(entry => {
    const row = document.createElement('div');
    row.className = 'history-row';
    const when = new Date(entry.at * 1000).toLocaleString();
    row.innerHTML = `<span><strong>${escapeHtml(entry.label)}</strong><small>${escapeHtml(entry.detail || entry.event)}</small></span><time>${escapeHtml(when)}</time>`;
    box.append(row);
  });
}

function catalogIdFromSearch(kind) {
  const input = $(`#${kind === 'figure' ? 'figureSearch' : 'powerupSearch'}`);
  const query = input.value.trim().toLowerCase();
  const entries = Object.entries(namedCatalog(kind));
  const match = entries.find(([, item]) => item.name.toLowerCase() === query)
    || entries.find(([, item]) => item.name.toLowerCase().includes(query));
  return match?.[0];
}

document.querySelectorAll('.element-color').forEach(input => input.oninput = event => event.target.closest('.element-card').querySelector('.swatch').style.setProperty('--color', event.target.value));
document.querySelectorAll('.customize').forEach(button => button.onclick = () => openCustomize(button.closest('.element-card').dataset.element).catch(error => notice(error.message, true)));
document.querySelectorAll('.palette-tab').forEach(tab => tab.onclick = () => {
  document.querySelectorAll('.palette-tab,.palette-panel').forEach(node => node.classList.remove('active'));
  tab.classList.add('active');
  $(`#${tab.dataset.panel}`).classList.add('active');
});
$('#addCombo').onclick = () => {
  const elements = [$('#comboElementA').value, $('#comboElementB').value].sort();
  if (elements[0] === elements[1]) return notice('Choose two different elements.', true);
  const key = elements.join('+');
  elementCombos[key] ||= {elements, colors: {[elements[0]]: elementColor(elements[0]), [elements[1]]: elementColor(elements[1])}, outputs: {}};
  renderCombos();
};
$('#addFigurePalette').onclick = () => {
  const id = catalogIdFromSearch('figure');
  if (!id) return notice('Choose a character from the suggestions.', true);
  addNamedPalette('figure', id);
  $('#figureSearch').value = '';
  renderNamedPalettes('figure');
};
$('#addPowerupPalette').onclick = () => {
  const id = catalogIdFromSearch('powerup');
  if (!id) return notice('Choose a power up from the suggestions.', true);
  addNamedPalette('powerup', id);
  $('#powerupSearch').value = '';
  renderNamedPalettes('powerup');
};
$('#figureSearch').oninput = () => renderNamedPalettes('figure');
$('#powerupSearch').oninput = () => renderNamedPalettes('powerup');
document.querySelectorAll('.test').forEach(button => button.onclick = async () => {
  const element = button.closest('.element-card').dataset.element;
  await save(false);
  const response = await fetch(`/api/test/${element}`, {method: 'POST'});
  const payload = await response.json();
  notice(payload.ok ? `Testing ${element}.` : payload.error, !payload.ok);
});
$('#closeCustomize').onclick = () => $('#customizeDialog').close();
$('#doneCustomize').onclick = () => $('#customizeDialog').close();
$('#previewCustomize').onclick = async () => {
  const status = $('#previewStatus');
  const button = $('#previewCustomize');
  button.disabled = true;
  status.textContent = 'Applying…';
  try {
    await save(false);
    let response;
    if (activeNamed) {
      response = await fetch(`/api/test-figure/${activeNamed.kind}/${activeNamed.id}`, {method: 'POST'});
    } else if (activeComboKey) {
      response = await fetch('/api/test-combo', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({elements: elementCombos[activeComboKey].elements}),
      });
    } else {
      response = await fetch(`/api/test/${activeElement}`, {method: 'POST'});
    }
    const payload = await response.json();
    if (!payload.ok) throw Error(payload.error || 'Preview failed');
    status.textContent = 'Preview applied';
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
$('#customizeDialog').onclick = event => { if (event.target === $('#customizeDialog')) $('#customizeDialog').close(); };

function settingsBody() {
  const colors = {};
  document.querySelectorAll('.element-card').forEach(card => { colors[card.dataset.element] = card.querySelector('.element-color').value.toUpperCase(); });
  return {
    element_colors: colors, element_outputs: elementOutputs, element_actions: elementActions,
    element_combos: elementCombos, figure_palettes: figurePalettes,
    powerup_palettes: powerupPalettes, default_palette: defaultPalette,
  };
}

function settingsSignature() {
  return JSON.stringify(settingsBody());
}

function updateSaveVisibility() {
  if (savedSignature === null) return;
  $('#savebar').classList.toggle('hidden', settingsSignature() === savedSignature);
}

async function save(show = true) {
  const body = settingsBody();
  const response = await fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const payload = await response.json();
  if (!payload.ok) throw Error(payload.error || 'Save failed');
  savedSignature = settingsSignature();
  updateSaveVisibility();
  if (show) notice('Configuration saved.');
}

$('#save').onclick = () => save().catch(error => notice(error.message, true));
setInterval(async () => {
  const state = await (await fetch('/api/status')).json();
  currentState = state;
  const portal = $('#portalStatus');
  portal.className = `status ${state.portal}`;
  portal.querySelector('span').textContent = state.portal;
  $('#figureName').textContent = state.figure ? state.figure.name : 'Waiting for a Skylander…';
  $('#figureMeta').textContent = state.figure ? state.figure.element[0].toUpperCase() + state.figure.element.slice(1) : 'Place a figure to trigger your lights.';
  $('#orb').style.setProperty('--orb', state.figure ? state.figure.color : '#456078');
  renderRecommendations();
  renderHistory();
}, 1500);

renderCombos();
renderNamedPalettes('figure');
renderNamedPalettes('powerup');
renderRecommendations();
renderHistory();
savedSignature = settingsSignature();
updateSaveVisibility();
setInterval(updateSaveVisibility, 250);
const sceneSessionKey = 'skyportal-scenes-session-refreshed';
if (!sessionStorage.getItem(sceneSessionKey)) {
  sessionStorage.setItem(sceneSessionKey, String(Date.now()));
  refreshSceneCache(true);
}
window.addEventListener('storage', event => {
  if (event.key === 'skyportal-scenes-refresh') {
    sceneCache.clear();
    refreshSceneCache(false);
  }
});
