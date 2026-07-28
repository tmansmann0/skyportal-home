const config = window.INITIAL_CONFIG;
const selected = new Map((config.govee.devices || []).map(device => [device.device, device]));
let discovered = [...selected.values()];
const selectedLifx = new Map((config.lifx?.devices || []).map(device => [device.serial, device]));
let discoveredLifx = [...selectedLifx.values()];
let savedSignature = null;
const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const notice = (message, error = false) => { const node = $('#notice'); node.textContent = message; node.className = `notice${error ? ' error' : ''}`; setTimeout(() => node.classList.add('hidden'), 5000); };

function renderDevices() {
  const box = $('#devices');
  box.innerHTML = discovered.length ? '' : 'No compatible Govee devices discovered yet.';
  discovered.forEach(device => {
    const row = document.createElement('label');
    row.className = 'device';
    row.innerHTML = `<input type="checkbox" ${selected.has(device.device) ? 'checked' : ''}><span><strong>${escapeHtml(device.deviceName || device.sku)}</strong><br><small>${escapeHtml(device.sku)} · ${escapeHtml(device.device)}</small></span>`;
    row.querySelector('input').onchange = event => event.target.checked ? selected.set(device.device, device) : selected.delete(device.device);
    box.append(row);
  });
}

function renderLifxDevices() {
  const box = $('#lifxDevices');
  box.innerHTML = discoveredLifx.length ? '' : 'No LIFX bulbs discovered yet.';
  discoveredLifx.forEach(device => {
    const row = document.createElement('label');
    row.className = 'device';
    row.innerHTML = `<input type="checkbox" ${selectedLifx.has(device.serial) ? 'checked' : ''}><span><strong>${escapeHtml(device.label)}</strong><br><small>LIFX LAN · ${escapeHtml(device.serial.toUpperCase())} · ${escapeHtml(device.ip)}</small></span>`;
    row.querySelector('input').onchange = event => event.target.checked ? selectedLifx.set(device.serial, device) : selectedLifx.delete(device.serial);
    box.append(row);
  });
}

function body() {
  return {
    govee: {api_key: $('#goveeKey').value || undefined, devices: [...selected.values()], brightness: +$('#brightness').value},
    lifx: {devices: [...selectedLifx.values()], brightness: +$('#lifxBrightness').value},
    home_assistant: {url: $('#haUrl').value, token: $('#haToken').value || undefined},
    behavior: {portal_confidence_seconds: +$('#portalConfidence').value},
  };
}
const signature = () => JSON.stringify(body());
const updateSave = () => savedSignature !== null && $('#savebar').classList.toggle('hidden', signature() === savedSignature);
const secondsLabel = value => {
  const seconds = Number(value);
  return `${seconds.toFixed(2).replace(/\.?0+$/, '')} second${seconds === 1 ? '' : 's'}`;
};

$('#brightness').oninput = event => { $('#brightnessLabel').textContent = `${event.target.value}%`; };
$('#lifxBrightness').oninput = event => { $('#lifxBrightnessLabel').textContent = `${event.target.value}%`; };
$('#portalConfidence').oninput = event => { $('#portalConfidenceLabel').textContent = secondsLabel(event.target.value); };
$('#discover').onclick = async () => {
  try {
    const response = await fetch('/api/govee/discover', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({api_key:$('#goveeKey').value})});
    const payload = await response.json();
    if (!payload.ok) throw Error(payload.error);
    const renamed = payload.devices.filter(device => selected.has(device.device)
      && selected.get(device.device).deviceName !== device.deviceName).length;
    discovered = payload.devices;
    discovered.forEach(device => { if (selected.has(device.device)) selected.set(device.device, device); });
    renderDevices();
    localStorage.setItem('skyportal-scenes-refresh', String(Date.now()));
    const sceneNote = !payload.scene_devices ? '' : payload.scenes_refreshed === payload.scene_devices
      ? ' Scene lists refreshed.'
      : ` Refreshed scenes for ${payload.scenes_refreshed || 0} light${payload.scenes_refreshed === 1 ? '' : 's'}.`;
    const nameNote = renamed ? ` Refreshed ${renamed} selected device name${renamed === 1 ? '' : 's'}; save to keep ${renamed === 1 ? 'it' : 'them'}.` : '';
    notice(`Found ${payload.devices.length} compatible device${payload.devices.length === 1 ? '' : 's'}.${sceneNote}${nameNote}`);
  } catch (error) { notice(error.message, true); }
};
$('#discoverLifx').onclick = async () => {
  try {
    const response = await fetch('/api/lifx/discover', {method:'POST'});
    const payload = await response.json();
    if (!payload.ok) throw Error(payload.error);
    discoveredLifx = payload.devices;
    discoveredLifx.forEach(device => { if (selectedLifx.has(device.serial)) selectedLifx.set(device.serial, device); });
    renderLifxDevices();
    notice(`Found ${payload.devices.length} LIFX bulb${payload.devices.length === 1 ? '' : 's'} on the local network.`);
  } catch (error) { notice(error.message, true); }
};
$('#save').onclick = async () => {
  try {
    const response = await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body())});
    const payload = await response.json();
    if (!payload.ok) throw Error(payload.error || 'Save failed');
    savedSignature = signature();
    updateSave();
    notice('Settings saved.');
  } catch (error) { notice(error.message, true); }
};
setInterval(async () => { const state = await (await fetch('/api/status')).json(); const portal = $('#portalStatus'); portal.className = `status ${state.portal}`; portal.querySelector('span').textContent = state.portal; }, 1500);
renderDevices();
renderLifxDevices();
savedSignature = signature();
setInterval(updateSave, 250);
