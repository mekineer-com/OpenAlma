function createSoulSelector(input, select, useExisting) {
  let souls = new Set();

  select.addEventListener("change", function() {
    if (!select.value) return;
    input.value = select.value;
    useExisting.value = "true";
  });
  input.addEventListener("input", function() {
    select.value = "";
    useExisting.value = "false";
  });

  return {
    setSouls: function(names) {
      souls = new Set(names);
      select.replaceChildren(new Option("Select existing soul", ""), ...names.map(function(name) {
        return new Option(name, name);
      }));
      select.value = "";
      useExisting.value = "false";
    },
    prepareSubmit: function() {
      const name = input.value.trim();
      if (useExisting.value === "true" && select.value === name) return true;
      useExisting.value = "false";
      if (!souls.has(name)) return true;
      if (!confirm("Soul exists. Use existing database?")) return false;
      useExisting.value = "true";
      return true;
    },
  };
}

async function submitSoulForm(form, onSuccess) {
  try {
    const response = await fetch(form.action, {method: "POST", body: new FormData(form)});
    if (!response.ok) {
      const error = await response.json();
      const message = typeof error.detail === "string" ? error.detail : error.detail?.message || "Soul selection failed";
      if (response.status === 409 && error.detail?.reason === "existing_exact" && confirm(message)) {
        form.querySelector('[name="use_existing"]').value = "true";
        return submitSoulForm(form, onSuccess);
      }
      alert(message);
      return;
    }
    if (onSuccess) onSuccess();
    else location.href = response.url;
  } catch (error) {
    alert("Could not submit: " + error.message);
  }
}

function bindSoulCombobox(soulForm, names, onSaved, onChanged) {
      const soulInput = soulForm.querySelector("[name=soul_id]");
      const soulMenu = soulForm.querySelector(".soul-options");
      const soulReady = soulForm.querySelector(".soul-ready");
      const soulNew = soulForm.querySelector(".soul-new");
      const soulUseExisting = soulForm.querySelector("[name=use_existing]");
      const humanName = soulForm.querySelector("[name=user_name]");
      const humanNameLabel = soulForm.querySelector(".soul-human-name");
      const knownSouls = new Set(names);
      let pendingNewSoul = "";

      function updateHumanName() {
        const creating = Boolean(soulInput.value.trim()) && !knownSouls.has(soulInput.value.trim());
        humanName.disabled = !creating;
        humanNameLabel.hidden = !creating;
      }

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
          humanName.value = "";
          updateHumanName();
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
          humanName.value = "";
          updateHumanName();
          closeSoulMenu();
          if (onSaved && !wasReady) onSaved(name);
        });
      }
      knownSouls.forEach(addSoulOption);
      updateHumanName();
      soulInput.addEventListener("focus", openSoulMenu);
      soulInput.addEventListener("click", openSoulMenu);
      soulInput.addEventListener("blur", closeSoulMenu);
      soulInput.addEventListener("input", function() {
        pendingNewSoul = "";
        soulUseExisting.value = "false";
        soulReady.hidden = true;
        soulNew.hidden = true;
        humanName.value = "";
        updateHumanName();
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
        humanName.value = humanName.value.trim();
        if (!humanName.value.trim()) {
          humanName.reportValidity();
          return;
        }
        if (pendingNewSoul !== name) {
          pendingNewSoul = name;
          soulNew.hidden = false;
          return;
        }
        saveSoul(name);
      });
    }
