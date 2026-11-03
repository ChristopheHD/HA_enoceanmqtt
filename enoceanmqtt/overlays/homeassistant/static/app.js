const form = document.querySelector('#device-form');
const deviceType = document.querySelector('#device-type');
const profileSelect = document.querySelector('#device-profile');
const profileLabel = document.querySelector('#profile-label');
const virtualCheckbox = document.querySelector('#device-virtual');
const senderField = document.querySelector('#sender-field');
const senderInput = document.querySelector('#device-sender');
const message = document.querySelector('#form-message');
const submitButton = document.querySelector('#submit-button');
const registry = document.querySelector('#registry-content');
const deviceCount = document.querySelector('#device-count');
const addDialog = document.querySelector('#add-device-dialog');
const openAddDialogButton = document.querySelector('#open-add-dialog');
const closeAddDialogButton = document.querySelector('#close-add-dialog');

let profileOptions = { eep: [], model: [] };

function showMessage(text, success = false) {
  message.textContent = text;
  message.classList.toggle('success', success);
}

function selectedOptions() {
  return deviceType.value === 'model' ? profileOptions.model : profileOptions.eep;
}

function renderProfiles() {
  profileLabel.textContent = deviceType.value === 'model' ? 'Model' : 'EEP profile';
  profileSelect.replaceChildren();
  const options = selectedOptions();
  if (!options.length) {
    profileSelect.add(new Option('No profiles available', ''));
    profileSelect.disabled = true;
    return;
  }
  profileSelect.disabled = false;
  profileSelect.add(new Option('Select a profile', ''));
  for (const profile of options) {
    profileSelect.add(new Option(profile.label, profile.value));
  }
}

function deviceElement(device) {
  const row = document.createElement('li');
  row.className = 'device-row';

  const primary = document.createElement('div');
  primary.className = 'device-main';
  const name = document.createElement('span');
  name.className = 'device-name';
  name.textContent = device.name;
  const type = document.createElement('span');
  type.className = 'device-type';
  type.textContent = device.type === 'model' ? 'Model' : 'EEP';
  primary.append(name, type);

  const details = document.createElement('div');
  details.className = 'device-details';
  const profile = document.createElement('code');
  profile.textContent = device.profile;
  const address = document.createElement('code');
  address.textContent = `Address · 0x${device.address}`;
  details.append(profile, address);
  if (device.sender) {
    const sender = document.createElement('code');
    sender.textContent = `Sender · 0x${device.sender}`;
    details.append(sender);
  }
  if (device.virtual) {
    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.textContent = 'Virtual';
    details.append(badge);
  }

  const remove = document.createElement('button');
  remove.className = 'delete-button';
  remove.type = 'button';
  remove.setAttribute('aria-label', `Delete ${device.name} from bridge`);
  const trashIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  trashIcon.setAttribute('viewBox', '0 0 24 24');
  trashIcon.setAttribute('width', '18');
  trashIcon.setAttribute('height', '18');
  trashIcon.setAttribute('fill', 'none');
  trashIcon.setAttribute('stroke', 'currentColor');
  trashIcon.setAttribute('stroke-width', '1.8');
  trashIcon.setAttribute('stroke-linecap', 'round');
  trashIcon.setAttribute('stroke-linejoin', 'round');
  trashIcon.setAttribute('aria-hidden', 'true');
  const trashShape = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  trashShape.setAttribute('d', 'M4 7h16M10 11v6m4-6v6M5 7l1 13h12l1-13M9 7V4h6v3m-8 0h10');
  trashIcon.append(trashShape);
  remove.append(trashIcon);
  remove.addEventListener('click', () => deleteDevice(device, remove));

  row.append(primary, details, remove);
  return row;
}

function renderDevices(devices) {
  deviceCount.textContent = String(devices.length);
  registry.replaceChildren();
  if (!devices.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    const icon = document.createElement('span');
    icon.className = 'empty-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '⌁';
    const heading = document.createElement('h3');
    heading.textContent = 'No devices yet';
    const copy = document.createElement('p');
    copy.textContent = 'Add your first mapped EnOcean device. It will appear here as soon as it is saved.';
    empty.append(icon, heading, copy);
    registry.append(empty);
    return;
  }
  const list = document.createElement('ul');
  list.className = 'device-list';
  for (const device of devices) {
    list.append(deviceElement(device));
  }
  registry.append(list);
}

async function loadDevices() {
  registry.innerHTML = '<div class="skeleton-list" aria-label="Loading devices"><span></span><span></span><span></span></div>';
  try {
    const response = await fetch('api/devices', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not load devices.');
    renderDevices(result.devices);
  } catch (error) {
    deviceCount.textContent = '!';
    registry.replaceChildren();
    const state = document.createElement('div');
    state.className = 'error-state';
    const heading = document.createElement('h3');
    heading.textContent = 'Could not load the device list';
    const details = document.createElement('p');
    details.textContent = error.message;
    const retry = document.createElement('button');
    retry.className = 'quiet-button';
    retry.type = 'button';
    retry.textContent = 'Try again';
    retry.addEventListener('click', loadDevices);
    state.append(heading, details, retry);
    registry.append(state);
  }
}

async function deleteDevice(device, button) {
  if (!window.confirm(`Delete "${device.name}"? Its Home Assistant discovery entities will also be removed.`)) {
    return;
  }
  button.disabled = true;
  showMessage('');
  try {
    const response = await fetch(`api/devices/${encodeURIComponent(device.id)}`, {
      method: 'DELETE'
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not delete the device.');
    await loadDevices();
  } catch (error) {
    button.disabled = false;
    window.alert(error.message);
  }
}

deviceType.addEventListener('change', renderProfiles);
openAddDialogButton.addEventListener('click', () => addDialog.showModal());
closeAddDialogButton.addEventListener('click', () => addDialog.close());
addDialog.addEventListener('click', (event) => {
  if (event.target === addDialog) addDialog.close();
});
virtualCheckbox.addEventListener('change', () => {
  senderField.hidden = !virtualCheckbox.checked;
  senderInput.required = virtualCheckbox.checked;
  if (!virtualCheckbox.checked) senderInput.value = '';
});
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showMessage('');
  submitButton.disabled = true;
  submitButton.querySelector('span').textContent = 'Adding device…';
  const payload = {
    name: document.querySelector('#device-name').value.trim(),
    type: deviceType.value,
    profile: profileSelect.value,
    address: document.querySelector('#device-address').value.trim(),
    virtual: virtualCheckbox.checked,
    sender: senderInput.value.trim()
  };
  try {
    const response = await fetch('api/devices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not add the device.');
    form.reset();
    senderField.hidden = true;
    senderInput.required = false;
    renderProfiles();
    await loadDevices();
    addDialog.close();
  } catch (error) {
    showMessage(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector('span').textContent = 'Add device';
  }
});

async function initialize() {
  try {
    const response = await fetch('api/options', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not load supported profiles.');
    profileOptions = { eep: result.eeps, model: result.models };
    renderProfiles();
  } catch (error) {
    showMessage(error.message);
    profileSelect.replaceChildren(new Option('Profiles unavailable', ''));
    profileSelect.disabled = true;
  }
  await loadDevices();
}

initialize();
