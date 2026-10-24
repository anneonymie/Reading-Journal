// Small enhancements. Every page also works without JavaScript.
(function () {
  "use strict";

  // Show stored UTC times in the reader's own time zone.
  const fmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  document.querySelectorAll("time[data-local]").forEach((el) => {
    const d = new Date(el.getAttribute("datetime"));
    if (!isNaN(d)) el.textContent = fmt.format(d);
  });

  // Date fields are stored as UTC text; give them a local date-time picker.
  const pad = (n) => String(n).padStart(2, "0");
  const toLocalValue = (d) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const toUtc = (d) => d.toISOString().replace(/\.\d{3}Z$/, "Z");
  document.querySelectorAll("input.js-utc").forEach((hidden) => {
    const picker = document.createElement("input");
    picker.type = "datetime-local";
    if (hidden.id) { picker.id = hidden.id; hidden.removeAttribute("id"); }
    if (hidden.value) {
      const d = new Date(hidden.value);
      if (!isNaN(d)) picker.value = toLocalValue(d);
    }
    picker.addEventListener("input", () => {
      if (!picker.value) { hidden.value = ""; return; }
      const d = new Date(picker.value);           // no offset = local time
      hidden.value = isNaN(d) ? "" : toUtc(d);
    });
    hidden.type = "hidden";
    hidden.after(picker);
  });

  // Ask before destructive actions.
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  // Ctrl/Cmd + Enter posts.
  document.querySelectorAll("textarea[data-ctrl-enter]").forEach((ta) => {
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        ta.form.requestSubmit();
      }
    });
  });

  // New works: picking a format pre-selects its usual unit, until the unit is chosen by hand.
  const formatSelect = document.querySelector("[data-format-select]");
  const unitSelect = document.querySelector("[data-unit-select]");
  if (formatSelect && unitSelect) {
    unitSelect.addEventListener("change", () => unitSelect.setAttribute("data-touched", ""));
    const apply = () => {
      if (unitSelect.hasAttribute("data-touched")) return;
      const opt = formatSelect.selectedOptions[0];
      if (opt && opt.dataset.defaultUnit) unitSelect.value = opt.dataset.defaultUnit;
    };
    formatSelect.addEventListener("change", apply);
    apply();
  }

  // Creators: a button that adds a blank row. Each row's tick boxes carry its row number.
  document.querySelectorAll("[data-creators]").forEach((set) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = "+ Add another creator";
    button.addEventListener("click", () => {
      const rows = set.querySelectorAll("[data-creator-row]");
      const row = rows[rows.length - 1].cloneNode(true);
      row.querySelectorAll("input").forEach((input) => {
        if (input.type === "checkbox") {
          input.checked = false;
          input.value = String(rows.length);
        } else {
          input.value = "";
          input.setAttribute("aria-label", `Creator ${rows.length + 1} name`);
        }
      });
      button.before(row);
      row.querySelector("input").focus();
    });
    set.appendChild(button);
  });

  // Images: paste, drop or pick; preview them and allow removal before posting.
  document.querySelectorAll("input[data-image-input]").forEach((input) => {
    const form = input.form;
    const previews = form.querySelector("[data-previews]");
    const textarea = form.querySelector("textarea[data-paste-images]");
    let files = [];
    let canSet = true;
    try { new DataTransfer(); } catch (_) { canSet = false; }

    const sync = () => {
      if (canSet) {
        const dt = new DataTransfer();
        files.forEach((f) => dt.items.add(f));
        input.files = dt.files;
      }
      previews.querySelectorAll("img").forEach((img) => URL.revokeObjectURL(img.src));
      previews.innerHTML = "";
      previews.hidden = files.length === 0;
      files.forEach((file, index) => {
        const box = document.createElement("div");
        box.className = "preview";
        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.alt = file.name || "Image";
        box.appendChild(img);
        if (canSet) {
          const remove = document.createElement("button");
          remove.type = "button";
          remove.textContent = "×";
          remove.setAttribute("aria-label", `Remove ${file.name || "image"}`);
          remove.addEventListener("click", () => { files.splice(index, 1); sync(); });
          box.appendChild(remove);
        }
        previews.appendChild(box);
      });
    };
    const add = (list) => {
      const images = Array.from(list).filter((f) => f.type.startsWith("image/"));
      if (!images.length) return false;
      files = canSet ? files.concat(images) : images;
      sync();
      return true;
    };

    input.addEventListener("change", () => {
      // The picker replaces input.files, so re-add what was already chosen.
      const picked = Array.from(input.files);
      if (canSet) { files = files.concat(picked); sync(); } else { files = picked; sync(); }
    });

    if (textarea && canSet) {
      textarea.addEventListener("paste", (e) => {
        const cd = e.clipboardData;
        if (!cd || !cd.files || !cd.files.length) return;
        const hasText = cd.types.includes("text/plain");
        if (add(cd.files) && !hasText) e.preventDefault();
      });
    }
    if (canSet) {
      form.addEventListener("dragover", (e) => { e.preventDefault(); });
      form.addEventListener("drop", (e) => {
        if (e.dataTransfer && add(e.dataTransfer.files)) e.preventDefault();
      });
    }
  });
})();
