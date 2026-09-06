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

async function submitSoulForm(form) {
  try {
    const response = await fetch(form.action, {method: "POST", body: new FormData(form)});
    if (!response.ok) {
      const error = await response.json();
      const message = typeof error.detail === "string" ? error.detail : error.detail?.message || "Soul selection failed";
      if (response.status === 409 && error.detail?.reason === "existing_exact" && confirm(message)) {
        form.querySelector('[name="use_existing"]').value = "true";
        return submitSoulForm(form);
      }
      alert(message);
      return;
    }
    location.href = response.url;
  } catch (error) {
    alert("Could not submit: " + error.message);
  }
}
