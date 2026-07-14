const config = window.INITIAL_CONFIG;
const selected = new Map((config.govee.devices || []).map(device => [device.device, device]));
let discovered = [...selected.values()];
let savedSignature = null;
const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const notice = (message, error = false) => { const node = $('#notice'); node.textContent = message; node.className = `notice${error ? ' error' : ''}`; setTimeout(() => node.classList.add('hidden'), 5000); };

function renderDevices() {
  const box = $('#devices');
  box.innerHTML = discovered.length ? '' : 'No compatible color lights discovered yet.';
  discovered.forEach(device => {
    const row = document.createElement('label');
    row.className = 'device';
    row.innerHTML = `<input type="checkbox" ${selected.has(device.device) ? 'checked' : ''}><span><strong>${escapeHtml(device.deviceName || device.sku)}</strong><br><small>${escapeHtml(device.sku)} · ${escapeHtml(device.device)}</small></span>`;
    row.querySelector('input').onchange = event => event.target.checked ? selected.set(device.device, device) : selected.delete(device.device);
    box.append(row);
  });
}

function body() {
  return {
    govee: {api_key: $('#goveeKey').value || undefined, devices: [...selected.values()], brightness: +$('#brightness').value},
    home_assistant: {url: $('#haUrl').value, token: $('#haToken').value || undefined},
  };
}
const signature = () => JSON.stringify(body());
const updateSave = () => savedSignature !== null && $('#savebar').classList.toggle('hidden', signature() === savedSignature);

$('#brightness').oninput = event => { $('#brightnessLabel').textContent = `${event.target.value}%`; };
$('#discover').onclick = async () => {
  try {
    const response = await fetch('/api/govee/discover', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({api_key:$('#goveeKey').value})});
    const payload = await response.json();
    if (!payload.ok) throw Error(payload.error);
    discovered = payload.devices;
    discovered.forEach(device => { if (selected.has(device.device)) selected.set(device.device, device); });
    renderDevices();
    localStorage.setItem('skyportal-scenes-refresh', String(Date.now()));
    const sceneNote = payload.scenes_refreshed === payload.devices.length
      ? ' Scene lists refreshed.'
      : ` Refreshed scenes for ${payload.scenes_refreshed || 0} light${payload.scenes_refreshed === 1 ? '' : 's'}.`;
    notice(`Found ${payload.devices.length} compatible light${payload.devices.length === 1 ? '' : 's'}.${sceneNote}`);
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
savedSignature = signature();
setInterval(updateSave, 250);
