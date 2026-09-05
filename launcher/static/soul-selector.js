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
