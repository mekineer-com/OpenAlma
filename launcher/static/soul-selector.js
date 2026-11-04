async function submitSoulForm(form, onSuccess) {
  clearLauncherMessage();
  try {
    const body = new FormData(form);
    const response = await fetch(form.action, {method: "POST", body});
    if (!response.ok) {
      const error = response.status === 409 ? await response.clone().json().catch(() => null) : null;
      const message = await launcherErrorMessage(response, "Soul selection failed");
      const useExisting = form.querySelector('[name="use_existing"]');
      if (useExisting && error?.detail?.reason === "existing_exact" &&
          new FormData(form).get("soul_id") !== body.get("soul_id")) return;
      if (useExisting && error?.detail?.reason === "existing_exact" && confirm(message)) {
        useExisting.value = "true";
        return submitSoulForm(form, onSuccess);
      }
      showLauncherMessage(message);
      return;
    }
    if (onSuccess) onSuccess();
    else location.href = response.url;
  } catch (error) {
    showLauncherMessage("Could not submit: " + error.message);
  }
}

function bindSoulCombobox(soulForm, names, onSaved, onChanged) {
      const soulInput = soulForm.querySelector("[name=soul_id]");
      const soulMenu = soulForm.querySelector(".soul-options");
      const soulReady = soulForm.querySelector(".soul-ready");
      const soulNew = soulForm.querySelector(".soul-new");
      const soulUseExisting = soulForm.querySelector("[name=use_existing]");
      const knownSouls = new Set(names);
      let pendingNewSoul = "";

      function closeSoulMenu() {
        soulMenu.hidden = true;
        soulInput.setAttribute("aria-expanded", "false");
      }
      function openSoulMenu() {
        soulMenu.hidden = knownSouls.size === 0;
        soulInput.setAttribute("aria-expanded", String(!soulMenu.hidden));
      }
      function addSoulOption(name) {
        const option = document.createElement("button");
        option.type = "button";
        option.role = "option";
        option.textContent = name;
        option.addEventListener("mousedown", function(event) { event.preventDefault(); });
        option.addEventListener("click", function() {
          if (!soulReady.hidden && soulInput.value.trim() === name) {
            closeSoulMenu();
            return;
          }
          soulInput.value = name;
          soulUseExisting.value = "true";
          soulReady.hidden = true;
          soulNew.hidden = true;
          closeSoulMenu();
          if (onChanged) onChanged();
        });
        soulMenu.appendChild(option);
      }
      function saveSoul(name) {
        void submitSoulForm(soulForm, function() {
          if (soulInput.value.trim() !== name) return;
          const wasReady = !soulReady.hidden;
          if (!knownSouls.has(name)) {
            knownSouls.add(name);
            addSoulOption(name);
          }
          pendingNewSoul = "";
          soulNew.hidden = true;
          soulReady.hidden = false;
          closeSoulMenu();
          if (onSaved && !wasReady) onSaved(name);
        });
      }
      knownSouls.forEach(addSoulOption);
      soulInput.addEventListener("focus", openSoulMenu);
      soulInput.addEventListener("click", openSoulMenu);
      soulInput.addEventListener("blur", closeSoulMenu);
      soulInput.addEventListener("input", function() {
        pendingNewSoul = "";
        soulUseExisting.value = "false";
        soulReady.hidden = true;
        soulNew.hidden = true;
        openSoulMenu();
        if (onChanged) onChanged();
      });
      soulForm.addEventListener("submit", function(event) {
        event.preventDefault();
        const name = soulInput.value.trim();
        if (!name) return;
        if (knownSouls.has(name)) {
          soulUseExisting.value = "true";
          saveSoul(name);
          return;
        }
        soulUseExisting.value = "false";
        if (pendingNewSoul !== name) {
          pendingNewSoul = name;
          soulNew.hidden = false;
          return;
        }
        saveSoul(name);
      });
    }

function bindHermesSoulSettings(soulForm, names, onSaved) {
  const checkbox = document.getElementById('mental-health-addon');
  const input = soulForm.querySelector('[name=soul_id]');
  const ready = soulForm.querySelector('.soul-ready');
  let selectedSoul = names.includes(input.value.trim()) ? input.value.trim() : '';
  let generation = 0;
  let saving = null;
  let savedValue = false;

  function invalidate() {
    generation++;
    selectedSoul = '';
    checkbox.checked = false;
    checkbox.disabled = true;
  }

  async function request(name, changes) {
    const response = await fetch('/souls/' + encodeURIComponent(name) + '/settings', {
      method: changes ? 'PATCH' : 'GET', cache: 'no-store',
      ...(changes ? {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(changes)} : {}),
    });
    if (!response.ok) throw new Error(await launcherErrorMessage(response, 'Could not read or save Soul settings'));
    const data = await response.json();
    if (!data.settings || typeof data.settings !== 'object' || Array.isArray(data.settings) ||
        ('mental_health_addon' in data.settings && typeof data.settings.mental_health_addon !== 'boolean')) {
      throw new Error('Server returned invalid Soul settings');
    }
    return data.settings.mental_health_addon === true;
  }

  async function load(name) {
    const current = ++generation;
    selectedSoul = name;
    checkbox.disabled = true;
    checkbox.checked = false;
    if (!name) return;
    try {
      // A switch back to the saving Soul must read after its PATCH has settled.
      if (saving) await saving.catch(() => {});
      if (current !== generation) return;
      const value = await request(name);
      if (current !== generation || name !== selectedSoul) return;
      savedValue = checkbox.checked = value;
      checkbox.disabled = false;
    } catch (error) {
      if (current === generation) showLauncherMessage(error.message);
    }
  }

  bindSoulCombobox(soulForm, names, function(name) {
    void load(name);
    if (onSaved) onSaved(name);
  }, invalidate);

  checkbox.addEventListener('change', async function() {
    if (checkbox.disabled || !selectedSoul) return;
    const name = selectedSoul;
    const current = ++generation;
    checkbox.disabled = true;
    clearLauncherMessage();
    saving = request(name, {mental_health_addon: checkbox.checked});
    try {
      const value = await saving;
      if (current !== generation || name !== selectedSoul) return;
      savedValue = checkbox.checked = value;
      checkbox.disabled = false;
    } catch (error) {
      if (current !== generation || name !== selectedSoul) return;
      checkbox.checked = savedValue;
      showLauncherMessage(error.message);
    } finally {
      saving = null;
    }
  });

  function refresh() {
    if (!ready.hidden && selectedSoul) void load(selectedSoul);
  }
  window.addEventListener('focus', refresh);
  document.addEventListener('visibilitychange', function() {
    if (!document.hidden) refresh();
  });
  void load(selectedSoul);
}
