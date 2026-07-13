const config = window.INITIAL_CONFIG;
const selected = new Map((config.govee.devices || []).map(device => [device.device, device]));
let discovered = [...selected.values()];
let overrides = {...(config.figure_overrides || {})};
let elementOutputs = structuredClone(config.element_outputs || {});
let elementCombos = structuredClone(config.element_combos || {});
let activeElement = null;
let activeComboKey = null;
const sceneCache = new Map();
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

function renderDevices() {
  const box = $('#devices');
  box.innerHTML = discovered.length ? '' : 'No compatible color lights discovered yet.';
  discovered.forEach(device => {
    const row = document.createElement('label');
    row.className = 'device';
    row.innerHTML = `<input type="checkbox" data-id="${escapeHtml(device.device)}" ${selected.has(device.device) ? 'checked' : ''}><span><strong>${escapeHtml(device.deviceName || device.sku)}</strong><br><small>${escapeHtml(device.sku)} · ${escapeHtml(device.device)}</small></span>`;
    row.querySelector('input').onchange = event => {
      if (event.target.checked) selected.set(device.device, device);
      else selected.delete(device.device);
    };
    box.append(row);
  });
}

function renderOverrides() {
  const box = $('#overrides');
  box.innerHTML = '';
  Object.entries(overrides).forEach(([id, output]) => {
    const figure = window.FIGURES[id];
    const row = document.createElement('div');
    row.className = 'override';
    row.innerHTML = `<span><strong>${escapeHtml(figure?.name || `#${id}`)}</strong><br><small>${escapeHtml(output.color || 'Element color')} ${output.ha_scene ? `· ${escapeHtml(output.ha_scene)}` : ''}</small></span><span style="width:24px;height:24px;border-radius:50%;background:${output.color || '#456078'}"></span><button class="secondary">Remove</button>`;
    row.querySelector('button').onclick = () => { delete overrides[id]; renderOverrides(); };
    box.append(row);
  });
}

function elementColor(element) {
  return document.querySelector(`.element-card[data-element="${element}"] .element-color`).value.toUpperCase();
}

function activeColor(deviceIndex = 0) {
  if (!activeComboKey) return elementColor(activeElement);
  const combo = elementCombos[activeComboKey];
  const split = Math.ceil(selected.size / 2);
  const element = combo.elements[deviceIndex < split ? 0 : 1];
  return combo.colors[element] || elementColor(element);
}

function profileFor(device, deviceIndex) {
  const outputs = activeComboKey
    ? (elementCombos[activeComboKey].outputs ||= {})
    : (elementOutputs[activeElement] ||= {});
  outputs[device.device] ||= {
    mode: 'color', color: activeColor(deviceIndex), brightness: +$('#brightness').value,
  };
  return outputs[device.device];
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
        controls.innerHTML = `<label>Color<input class="profile-color" type="color" value="${profile.color || activeColor(deviceIndex)}"></label><label>Brightness <span>${profile.brightness || $('#brightness').value}%</span><input class="profile-brightness" type="range" min="1" max="100" value="${profile.brightness || $('#brightness').value}"></label>`;
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
  $('#customizeTitle').textContent = `Customize ${element[0].toUpperCase()}${element.slice(1)}`;
  await save(false);
  renderCustomizeDevices();
  $('#customizeDialog').showModal();
}

async function openComboCustomize(key) {
  activeComboKey = key;
  activeElement = null;
  const combo = elementCombos[key];
  $('#customizeTitle').textContent = `Customize ${combo.elements.map(element => element[0].toUpperCase() + element.slice(1)).join(' + ')}`;
  await save(false);
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

$('#brightness').oninput = event => { $('#brightnessLabel').textContent = `${event.target.value}%`; };
document.querySelectorAll('.element-color').forEach(input => input.oninput = event => event.target.closest('.element-card').querySelector('.swatch').style.setProperty('--color', event.target.value));
$('#discover').onclick = async () => {
  try {
    const response = await fetch('/api/govee/discover', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({api_key: $('#goveeKey').value})});
    const payload = await response.json();
    if (!payload.ok) throw Error(payload.error);
    discovered = payload.devices;
    renderDevices();
    notice(`Found ${payload.devices.length} compatible light${payload.devices.length === 1 ? '' : 's'}.`);
  } catch (error) { notice(error.message, true); }
};
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
document.querySelectorAll('.test').forEach(button => button.onclick = async () => {
  const element = button.closest('.element-card').dataset.element;
  await save(false);
  const response = await fetch(`/api/test/${element}`, {method: 'POST'});
  const payload = await response.json();
  notice(payload.ok ? `Testing ${element}.` : payload.error, !payload.ok);
});
$('#closeCustomize').onclick = () => $('#customizeDialog').close();
$('#doneCustomize').onclick = () => $('#customizeDialog').close();
$('#customizeDialog').onclick = event => { if (event.target === $('#customizeDialog')) $('#customizeDialog').close(); };
$('#addOverride').onclick = () => { const id = $('#figureSelect').value; overrides[id] = {color: $('#overrideColor').value, ha_scene: $('#haScene').value.trim()}; renderOverrides(); };

function settingsBody() {
  const colors = {};
  document.querySelectorAll('.element-card').forEach(card => { colors[card.dataset.element] = card.querySelector('.element-color').value.toUpperCase(); });
  return {
    govee: {api_key: $('#goveeKey').value || undefined, devices: [...selected.values()], brightness: +$('#brightness').value},
    home_assistant: {url: $('#haUrl').value, token: $('#haToken').value || undefined},
    element_colors: colors, element_outputs: elementOutputs, element_combos: elementCombos, figure_overrides: overrides,
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
  const portal = $('#portalStatus');
  portal.className = `status ${state.portal}`;
  portal.querySelector('span').textContent = state.portal;
  $('#figureName').textContent = state.figure ? state.figure.name : 'Waiting for a Skylander…';
  $('#figureMeta').textContent = state.figure ? state.figure.element[0].toUpperCase() + state.figure.element.slice(1) : 'Place a figure to trigger your lights.';
  $('#orb').style.setProperty('--orb', state.figure ? state.figure.color : '#456078');
}, 1500);

renderDevices();
renderOverrides();
renderCombos();
savedSignature = settingsSignature();
updateSaveVisibility();
setInterval(updateSaveVisibility, 250);
