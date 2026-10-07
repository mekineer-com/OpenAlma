function irisParentActions(data) {
  var links = ' <a class="btn" href="/iris">Setup</a>';
  if (data.install_enabled === false) return links + ' <button class="btn" disabled>Stock Install</button>';
  if (!data.install_setup && data.action_kind !== 'install') links += ' <form class="inline" method="post" action="/iris/install"><button class="btn" type="submit"' + (irisInstallDisabled(data) ? ' disabled' : '') + '>Stock Install</button></form>';
  if (data.install_running || data.state === 'stopping') {
    return '<span class="spinner" role="status" aria-label="Working"></span>' +
      (data.force_stoppable ? ' <button class="btn" onclick="svcAction(\'iris-server\',\'force-stop\',this)">Force Stop</button>' : '') + links;
  }
  if (data.action_kind === 'stop' || data.force_stoppable) {
    return '<button class="btn" onclick="svcAction(\'iris-server\',\'' +
      (data.force_stoppable ? 'force-stop' : 'stop') + '\',this)">' +
      esc(data.force_stoppable ? 'Force Stop' : data.action_label || 'Cancel') + '</button>' + links;
  }
  if (data.action_kind === 'install') {
    return '<form class="inline" method="post" action="/install/iris-server"><button class="btn" type="submit">' +
      esc(data.action_label || 'Install') + '</button></form>' + links;
  }
  return links;
}

function renderIrisInstallations(data) {
  if (!Array.isArray(data.installations)) return;
  var parent = document.querySelector('tr[data-service="iris-server"]');
  var rows = new Map(Array.from(parent.parentNode.querySelectorAll('tr[data-iris-installation]'), function(row) {
    return [row.dataset.irisInstallation, row];
  }));
  var previous = parent;
  data.installations.forEach(function(installation) {
    var id = installation.device_session_id;
    var row = rows.get(id);
    if (!row) {
      row = document.createElement('tr');
      row.dataset.irisInstallation = id;
      row.innerHTML = '<td><span class="iris-name-view"><span class="iris-name"></span> ' +
        '<button class="btn" type="button">Rename</button></span>' +
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
          save.disabled = false;
        }
      };
      previous.after(row);
    }
    rows.delete(id);
    // Keep existing rows in place so reordered reports cannot interrupt Rename.
    previous = row;
    var appName = installation.host_package === 'com.mentra.mentra.openalma' ? 'OpenAlma Mentra' : 'Mentra';
    var tooltip = appName + (installation.host_version ? ' v' + installation.host_version : ' (version unknown)') +
      ', Iris ' + (installation.installed_version ? 'v' + installation.installed_version : 'not installed');
    var name = row.querySelector('.iris-name');
    name.textContent = installation.display_name;
    name.title = tooltip;
    var input = row.querySelector('input');
    input.title = tooltip;
    if (row.querySelector('form').hidden) input.value = installation.display_name;
    var status = row.querySelector('.iris-status');
    status.className = 'iris-status ' + (installation.state || 'unknown');
    status.textContent = installation.status_label || 'Status unavailable';
    row.querySelector('.iris-detail').textContent = installation.detail || '';
    row.querySelector('.iris-soul').textContent = 'Soul: ' + (installation.soul_id || 'Not chosen');
    var actions = ' <a class="btn" href="/iris">Setup</a> <button class="btn" type="button" data-forget>Forget</button>';
    if (installation.startable && installation.action_kind === 'start') {
      actions = '<form class="inline" method="post" action="/iris/install">' +
        '<input type="hidden" name="device_session_id" value="' + esc(id) + '">' +
        '<input type="hidden" name="host_package" value="' + esc(installation.host_package) + '">' +
        '<button class="btn" type="submit"' + (irisInstallDisabled(data) ? ' disabled' : '') + '>' + esc(installation.action_label || 'Install') + '</button></form>' + actions;
    }
    var cell = row.querySelector('.iris-actions');
    if (cell.irisActionsHtml !== actions && !row.dataset.forgetting) {
      cell.innerHTML = actions;
      cell.irisActionsHtml = actions;
      cell.querySelector('[data-forget]').onclick = async function() {
        if (!confirm('Forget this installation from the launcher? Chats, memories and phone storage are not deleted.')) return;
        row.dataset.forgetting = 'true';
        this.disabled = true;
        try {
          await irisMetadataAction(id, 'forget');
          row.remove();
          pollStatus('iris-server');
        } catch (error) {
          alert(error.message);
        } finally {
          delete row.dataset.forgetting;
          this.disabled = false;
        }
      };
    }
  });
  rows.forEach(function(row) { row.remove(); });
}

function irisInstallDisabled(data) {
  return data.running || data.starting || data.stuck || data.orphaned || (data.setup && !data.setup.ready);
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
