// Page behaviour: dates, confirmations, repeating rows and the image controls.
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

  // Repeating rows (creators, alternate titles): a button that adds a blank copy of the last row.
  // Each creator row's tick boxes carry its row number.
  document.querySelectorAll("[data-repeat]").forEach((set) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = set.dataset.repeat;
    button.addEventListener("click", () => {
      const rows = set.querySelectorAll("[data-repeat-row]");
      const row = rows[rows.length - 1].cloneNode(true);
      row.querySelectorAll("input").forEach((input) => {
        if (input.type === "checkbox") {
          input.checked = false;
          input.value = String(rows.length);
        } else {
          input.value = "";
          const label = input.getAttribute("aria-label");
          if (label) input.setAttribute("aria-label", label.replace(/\d+/, String(rows.length + 1)));
        }
      });
      button.before(row);
      row.querySelector("input").focus();
    });
    set.appendChild(button);
  });

  // Text shown as-is until Edit swaps in its form. Cancel restores the saved text and shows it again.
  document.querySelectorAll("[data-inline-edit]").forEach((box) => {
    const view = box.querySelector("[data-view]");
    const form = box.querySelector("[data-form]");
    const textarea = form.querySelector("textarea");
    box.querySelector("[data-edit]").addEventListener("click", () => {
      view.hidden = true;
      form.hidden = false;
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    });
    box.querySelector("[data-cancel]").addEventListener("click", () => {
      form.reset();
      form.hidden = true;
      view.hidden = false;
    });
  });

  // Images: pick, paste or drop them in; drag to reorder; × takes one off.
  // Every tile carries a hidden image_order field: a saved image's id, or "new:<n>" for the n-th
  // uploaded file. The file box is rebuilt from the new tiles in page order after every change.
  document.querySelectorAll("input[data-image-input]").forEach((input) => {
    const form = input.form;
    const grid = form.querySelector("[data-image-grid]");
    const textarea = form.querySelector("textarea[data-paste-images]");
    const fileOf = new Map();   // tile -> File, for images not saved yet

    const sync = () => {
      const tiles = Array.from(grid.children);
      const dt = new DataTransfer();
      tiles.forEach((tile) => {
        const file = fileOf.get(tile);
        if (file) {
          tile.querySelector("input").value = `new:${dt.items.length}`;
          dt.items.add(file);
        }
      });
      input.files = dt.files;
      grid.hidden = tiles.length === 0;
    };

    const add = (list) => {
      const images = Array.from(list).filter((f) => f.type.startsWith("image/"));
      images.forEach((file) => {
        const tile = document.createElement("div");
        tile.className = "image-tile";
        const order = document.createElement("input");
        order.type = "hidden";
        order.name = "image_order";
        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.alt = file.name || "Image";
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "tile-remove";
        remove.textContent = "×";
        remove.setAttribute("aria-label", `Remove ${file.name || "image"}`);
        tile.append(order, img, remove);
        grid.appendChild(tile);
        fileOf.set(tile, file);
      });
      sync();
      return images.length > 0;
    };

    // × takes the tile off the page. A saved image is only dropped from the entry when the form is saved.
    grid.addEventListener("click", (e) => {
      const button = e.target.closest(".tile-remove");
      if (!button) return;
      const tile = button.closest(".image-tile");
      if (fileOf.has(tile)) {
        URL.revokeObjectURL(tile.querySelector("img").src);
        fileOf.delete(tile);
      } else {
        const gone = document.createElement("input");
        gone.type = "hidden";
        gone.name = "remove_image";
        gone.value = button.dataset.remove;
        form.appendChild(gone);
      }
      tile.remove();
      sync();
    });

    // The picker replaces the file box's contents (or empties it on Cancel); add its files, then rebuild.
    input.addEventListener("change", () => add(input.files));

    if (textarea) {
      textarea.addEventListener("paste", (e) => {
        const cd = e.clipboardData;
        if (!cd || !cd.files || !cd.files.length) return;
        const hasText = cd.types.includes("text/plain");
        if (add(cd.files) && !hasText) e.preventDefault();
      });
    }
    form.addEventListener("dragover", (e) => { e.preventDefault(); });
    form.addEventListener("drop", (e) => {
      if (e.dataTransfer && e.dataTransfer.files.length && add(e.dataTransfer.files)) e.preventDefault();
    });

    if (window.Sortable) {
      Sortable.create(grid, {
        animation: 150,
        delay: 150, delayOnTouchOnly: true,   // on a phone, press and hold to drag; a quick swipe still scrolls
        filter: "button",
        preventOnFilter: false,
        onEnd: () => sync(),
      });
    }
    sync();
  });
})();
