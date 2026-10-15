function irisParentActions() {
  return ' <button class="btn" type="button" popovertarget="mentra-apk-popup" onclick="mentraApkQr()" aria-label="OpenAlma Mentra APK download QR">QR</button> <a class="btn" href="/iris">Setup</a>';
}

async function mentraApkQr() {
  var url = 'https://github.com/mekineer-com/MentraOS/releases';
  var canvas = document.getElementById('mentra-apk-qr');
  var message = document.getElementById('mentra-apk-message');
  canvas.hidden = true;
  message.textContent = 'Loading QR...';
  try {
    var response = await fetch('/mentra/apk');
    if (response.ok) url = (await response.json()).url || url;
  } catch (_error) {}
  try {
    await QRCode.toCanvas(canvas, url, {width: 220, margin: 1});
    canvas.hidden = false;
    message.textContent = '';
  } catch (_error) {
    message.textContent = 'Could not draw QR. Use apk on github.';
  }
}

function renderIrisInstallations(data) {
  var parent = document.querySelector('tr[data-service="iris-server"]');
  var rows = new Map(Array.from(parent.parentNode.querySelectorAll('tr[data-iris-installation]'), function(row) {
    return [row.dataset.irisInstallation, row];
  }));
  if (!Array.isArray(data.installations)) {
    rows.forEach(function(row) {
      var status = row.querySelector('.iris-status');
      status.className = 'iris-status unavailable';
      status.textContent = 'Status unavailable';
      row.querySelector('.iris-detail').textContent = data.detail || 'Iris app status is unavailable.';
      row.querySelectorAll('.iris-name, button[type="submit"], [data-forget]').forEach(function(button) { button.disabled = true; });
      row.querySelector('.iris-actions').irisActionsHtml = null;
    });
    return;
  }
  var previous = parent;
  data.installations.forEach(function(installation) {
    var id = installation.device_session_id;
    var row = rows.get(id);
    if (!row) {
      row = document.createElement('tr');
      row.dataset.irisInstallation = id;
      row.innerHTML = '<td><span class="iris-name-view"><button class="iris-name" type="button"></button></span>' +
        '<form hidden><input name="display_name" aria-label="Display name" required> ' +
        '<button class="btn" type="submit">Save</button> <button class="btn" type="button">Cancel</button></form></td>' +
        '<td><span class="iris-status"></span><div class="svc-detail iris-detail"></div>' +
        '<div class="svc-detail iris-soul"></div></td><td class="iris-actions"></td><td></td>';
      var view = row.querySelector('.iris-name-view');
      var form = row.querySelector('form');
      var input = form.elements.display_name;
      view.querySelector('button').onclick = function() {
        view.hidden = true;
        form.hidden = false;
        input.focus();
        input.select();
      };
      form.querySelector('button[type="button"]').onclick = function() {
        form.hidden = true;
        view.hidden = false;
        input.value = row.querySelector('.iris-name').textContent;
        view.querySelector('button').focus();
      };
      form.onsubmit = async function(event) {
        event.preventDefault();
        var save = form.querySelector('button[type="submit"]');
        var displayName = input.value;
        save.disabled = true;
        try {
          await irisMetadataAction(id, 'rename', new URLSearchParams({display_name: displayName}));
          row.querySelector('.iris-name').textContent = displayName;
          form.hidden = true;
          view.hidden = false;
          view.querySelector('button').focus();
          pollStatus('iris-server');
        } catch (error) {
          alert(error.message);
        } finally {
          save.disabled = row.querySelector('.iris-name-view button').disabled;
        }
      };
      previous.after(row);
    }
    rows.delete(id);
    // Keep existing rows in place so reordered reports cannot interrupt Rename.
    previous = row;
    var known = installation.metadata_known !== false;
    if (!known || row.querySelector('.iris-name-view button').disabled) row.querySelector('button[type="submit"]').disabled = !known;
    row.querySelector('.iris-name-view button').disabled = !known;
    var appName = !known ? 'App details unavailable' : installation.host_package === 'com.mentra.mentra.openalma' ? 'OpenAlma Mentra' : 'Mentra';
    var tooltip = appName + (installation.host_version ? ' v' + installation.host_version : ' (version unknown)') +
      ', Iris ' + (installation.installed_version ? 'v' + installation.installed_version : known ? 'not installed' : '(version unknown)');
    var name = row.querySelector('.iris-name');
    name.textContent = installation.display_name;
    name.title = tooltip;
    name.setAttribute('aria-label', known ? 'Rename ' + installation.display_name : installation.display_name);
    var input = row.querySelector('input');
    input.title = tooltip;
    if (row.querySelector('form').hidden) input.value = installation.display_name;
    var status = row.querySelector('.iris-status');
    status.className = 'iris-status ' + (installation.state || 'unknown');
    status.textContent = installation.status_label || 'Status unavailable';
    row.querySelector('.iris-detail').textContent = installation.detail || '';
    row.querySelector('.iris-soul').textContent = 'Soul: ' + (installation.soul_id || 'Not chosen');
    var forgetBlocked = installation.active || installation.host_reporting ||
      (data.release_device_session_id === id && irisInstallerBusy(data));
    var actions = ' <a class="btn" href="/iris?device_session_id=' + encodeURIComponent(id) + '">Setup</a>' + (known ?
      ' <button class="btn" type="button" data-forget title="Close the app and wait 15 seconds before forgetting it. Opening it again restores its row."' +
      (forgetBlocked ? ' disabled' : '') + '>Forget</button>' : '');
    if (installation.startable && installation.action_kind === 'start' && installation.action_label !== 'Repair') {
      actions = '<form class="inline" method="post" action="/iris/install">' +
        '<input type="hidden" name="device_session_id" value="' + esc(id) + '">' +
        '<input type="hidden" name="host_package" value="' + esc(installation.host_package) + '">' +
        '<button class="btn" type="submit"' + (irisInstallDisabled(data) ? ' disabled' : '') + '>' + esc(installation.action_label || 'Install') + '</button></form>' + actions;
    }
    var cell = row.querySelector('.iris-actions');
    if (cell.irisActionsHtml !== actions && !row.dataset.forgetting) {
      cell.innerHTML = actions;
      cell.irisActionsHtml = actions;
      var forget = cell.querySelector('[data-forget]');
      if (forget) forget.onclick = async function() {
        if (!confirm('Forget this installation from the launcher? Chats, memories and phone storage are not deleted.')) return;
        row.dataset.forgetting = 'true';
        this.disabled = true;
        try {
          await irisMetadataAction(id, 'forget');
          row.remove();
        } catch (error) {
          alert(error.message);
        } finally {
          delete row.dataset.forgetting;
          cell.irisActionsHtml = null;
          pollStatus('iris-server');
        }
      };
    }
  });
  rows.forEach(function(row) { row.remove(); });
  var installed = String(data.installations.length > 0);
  if (parent.dataset && parent.dataset.installed !== installed) {
    parent.dataset.installed = installed;
    groupServiceRows();
  }
}

function irisInstallerBusy(data) {
  return Boolean(data.running || data.starting || data.stuck || data.orphaned);
}

function irisInstallDisabled(data, prepare = false) {
  return Boolean(irisInstallerBusy(data) || data.blocked ||
    data.install_running || data.state === 'stopping' || (data.ready === false && !(prepare && data.action_kind === 'install')) ||
    !Array.isArray(data.installations) || (data.setup && !data.setup.ready && !(prepare && data.setup.step === 'release')));
}

async function irisMetadataAction(id, action, body) {
  var response = await fetch('/iris/installations/' + encodeURIComponent(id) + '/' + action, {method: 'POST', body: body});
  if (!response.ok) {
    var result = await response.json();
    throw new Error(irisErrorMessage(result, 'Installation action failed'));
  }
}

function irisErrorMessage(payload, fallback) {
  var detail = payload.detail;
  if (Array.isArray(detail)) return detail.map(function(error) { return error.msg; }).filter(Boolean).join('; ') || fallback;
  return typeof detail === 'string' && detail ? detail : fallback;
}
