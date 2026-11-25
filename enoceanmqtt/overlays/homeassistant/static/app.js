const form = document.querySelector('#device-form');
const deviceType = document.querySelector('#device-type');
const profileSelect = document.querySelector('#device-profile');
const profileLabel = document.querySelector('#profile-label');
const virtualCheckbox = document.querySelector('#device-virtual');
const senderField = document.querySelector('#sender-field');
const senderInput = document.querySelector('#device-sender');
const securityFields = document.querySelector('#security-fields');
const securedCheckbox = document.querySelector('#device-secured');
const secureOptions = document.querySelector('#secure-options');
const secureTeachinTelegrams = document.querySelector('#secure-teachin-telegrams');
const secureTeachinBidirectional = document.querySelector('#secure-teachin-bidirectional');
const message = document.querySelector('#form-message');
const submitButton = document.querySelector('#submit-button');
const registry = document.querySelector('#registry-content');
const deviceCount = document.querySelector('#device-count');
const addDialog = document.querySelector('#add-device-dialog');
const openAddDialogButton = document.querySelector('#open-add-dialog');
const closeAddDialogButton = document.querySelector('#close-add-dialog');
const dialogTitle = document.querySelector('#add-title');

let profileOptions = { eep: [], model: [] };
let editingDeviceId = null;

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
    securityFields.hidden = true;
    return;
  }
  profileSelect.disabled = false;
  profileSelect.add(new Option('Select a profile', ''));
  for (const profile of options) {
    profileSelect.add(new Option(profile.label, profile.value));
  }
  renderSecurityFields();
}

function selectedProfile() {
  return selectedOptions().find((profile) => profile.value === profileSelect.value);
}

function renderSecurityFields(security = null) {
  const mappedSecurity = selectedProfile()?.security;
  const settings = security || mappedSecurity;
  securityFields.hidden = !settings;
  if (!settings) return;
  securedCheckbox.checked = Boolean(settings.secured);
  secureOptions.hidden = !securedCheckbox.checked;
  secureTeachinTelegrams.value = String(settings.secure_teachin_telegrams || 2);
  secureTeachinBidirectional.checked = Boolean(settings.secure_teachin_bidirectional);
}

function prepareAddForm() {
  editingDeviceId = null;
  form.reset();
  showMessage('');
  dialogTitle.textContent = 'Add a device';
  submitButton.querySelector('span').textContent = 'Add device';
  senderField.hidden = true;
  senderInput.required = false;
  renderProfiles();
}

function editDevice(device) {
  editingDeviceId = device.id;
  form.reset();
  showMessage('');
  dialogTitle.textContent = 'Edit device';
  submitButton.querySelector('span').textContent = 'Save changes';
  document.querySelector('#device-name').value = device.name;
  document.querySelector('#device-address').value = device.address;
  deviceType.value = device.type;
  renderProfiles();
  profileSelect.value = device.profile;
  renderSecurityFields(device.security);
  virtualCheckbox.checked = device.virtual;
  senderField.hidden = !device.virtual;
  senderInput.required = device.virtual;
  senderInput.value = device.sender || '';
  addDialog.showModal();
}

function deviceElement(device) {
  const row = document.createElement('li');
  row.className = 'device-row';

  const edit = document.createElement('button');
  edit.className = 'device-edit';
  edit.type = 'button';
  edit.setAttribute('aria-label', `Edit ${device.name}`);
  edit.addEventListener('click', () => editDevice(device));

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

  edit.append(primary, details);
  row.append(edit, remove);
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
profileSelect.addEventListener('change', () => renderSecurityFields());
openAddDialogButton.addEventListener('click', () => {
  prepareAddForm();
  addDialog.showModal();
});
closeAddDialogButton.addEventListener('click', () => addDialog.close());
addDialog.addEventListener('click', (event) => {
  if (event.target === addDialog) addDialog.close();
});
virtualCheckbox.addEventListener('change', () => {
  senderField.hidden = !virtualCheckbox.checked;
  senderInput.required = virtualCheckbox.checked;
  if (!virtualCheckbox.checked) senderInput.value = '';
});
securedCheckbox.addEventListener('change', () => {
  secureOptions.hidden = !securedCheckbox.checked;
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
    secured: securedCheckbox.checked,
    sender: senderInput.value.trim()
  };
  if (!securityFields.hidden && securedCheckbox.checked) {
    payload.secure_teachin_telegrams = Number(secureTeachinTelegrams.value);
    payload.secure_teachin_bidirectional = secureTeachinBidirectional.checked;
  }
  try {
    const response = await fetch(
      editingDeviceId
        ? `api/devices/${encodeURIComponent(editingDeviceId)}`
        : 'api/devices',
      {
      method: editingDeviceId ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
      }
    );
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not add the device.');
    prepareAddForm();
    await loadDevices();
    addDialog.close();
  } catch (error) {
    showMessage(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector('span').textContent = editingDeviceId
      ? 'Save changes'
      : 'Add device';
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
