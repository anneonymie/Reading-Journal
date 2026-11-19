// Page behavior: dates, confirmations, repeating rows and the image controls.
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

  // Ask before destructive actions: a whole form, or one button in a form.
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });
  document.querySelectorAll("button[data-confirm]").forEach((button) => {
    button.addEventListener("click", (e) => {
      if (!window.confirm(button.dataset.confirm)) e.preventDefault();
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

  // ---------- tags

  // Forms marked data-swap post in the background; the server sends back the box named by
  // data-swap (e.g. #tags), which replaces the old one. Nothing else on the page reloads.
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("form[data-swap]");
    if (!form || e.defaultPrevented) return;
    e.preventDefault();
    const body = new FormData(form);
    // Adding a tag: empty the box straight away, so typing the next tag can start while this one saves.
    const typing = form.matches(".tag-add") ? form.querySelector("[data-tag-input]") : null;
    if (typing) typing.value = "";
    let response;
    try {
      response = await fetch(form.action, { method: "POST", body, headers: { "X-Partial": "1" } });
    } catch (_) {
      response = null;
    }
    if (!response || !response.ok) {   // put things back and let the page show what went wrong
      if (typing) typing.value = body.get("name");
      HTMLFormElement.prototype.submit.call(form);
      return;
    }
    document.querySelector(form.dataset.swap).outerHTML = await response.text();
    if (typing) {   // carry over anything typed meanwhile, and stay ready for the next tag
      const fresh = document.querySelector(`${form.dataset.swap} [data-tag-input]`);
      fresh.value = typing.value;
      fresh.focus();
      if (fresh.value) fresh.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });

  // Tag pop-ups: one open at a time; a click elsewhere or Escape closes it.
  document.addEventListener("toggle", (e) => {
    if (e.target.matches?.("[data-tag-popup]") && e.target.open) {
      document.querySelectorAll("[data-tag-popup][open]").forEach((d) => { if (d !== e.target) d.open = false; });
      // Near the right edge of the screen, slide the pop-up left so it stays visible.
      const pop = e.target.querySelector(".tag-pop");
      pop.style.left = "0px";
      const overflow = pop.getBoundingClientRect().right - (document.documentElement.clientWidth - 8);
      if (overflow > 0) pop.style.left = `${-overflow}px`;
    }
  }, true);
  document.addEventListener("click", (e) => {
    document.querySelectorAll("[data-tag-popup][open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    document.querySelectorAll("[data-tag-popup][open]").forEach((d) => { d.open = false; d.querySelector("summary").focus(); });
  });

  // Typing a tag: suggestions from the clever search appear under the box. Up/Down move through them,
  // Enter picks the highlighted one (or, with none highlighted, adds what was typed), Escape closes them.
  const suggestBox = (input) => {
    let list = input.parentElement.querySelector(".tag-suggest");
    if (!list) {
      list = document.createElement("ul");
      list.className = "tag-suggest";
      list.id = `${input.id}-suggestions`;
      list.setAttribute("role", "listbox");
      list.hidden = true;
      input.after(list);
      input.setAttribute("role", "combobox");
      input.setAttribute("aria-controls", list.id);
      input.setAttribute("aria-expanded", "false");
    }
    return list;
  };
  const closeSuggestions = (input) => {
    const list = suggestBox(input);
    list.hidden = true;
    list.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
  };
  const pick = (input, li) => {
    closeSuggestions(input);
    if (li.dataset.onWork) { input.value = ""; return; }   // nothing to add
    input.value = li.dataset.name;
    input.form.requestSubmit();
  };
  let pending = 0;
  document.addEventListener("input", async (e) => {
    const input = e.target;
    if (!input.matches?.("[data-tag-input]")) return;
    const q = input.value.trim();
    const ticket = ++pending;
    if (!q) { closeSuggestions(input); return; }
    await new Promise((r) => setTimeout(r, 120));   // wait for a pause in typing
    if (ticket !== pending) return;
    const params = new URLSearchParams({ q });
    if (input.dataset.work) params.set("work", input.dataset.work);
    let found = [];
    try {
      found = await (await fetch(`/tags/suggest?${params}`)).json();
    } catch (_) { /* no suggestions this time */ }
    if (ticket !== pending) return;
    const list = suggestBox(input);
    list.innerHTML = "";
    const exact = found.some((s) => s.on_work || s.name.toLowerCase() === q.toLowerCase()
      || (s.alias || "").toLowerCase() === q.toLowerCase());   // the typed text is already a tag: nothing to create
    found.forEach((s, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.id = `${list.id}-${i}`;
      li.dataset.name = s.name;
      const dot = document.createElement("span");
      dot.className = "swatch";
      dot.style.setProperty("--cat", s.color);
      const name = document.createElement("span");
      name.textContent = s.name;
      const why = document.createElement("span");
      why.className = "why";
      why.textContent = s.on_work ? "already on this work" : s.alias ? `also called ${s.alias}`
        : s.similar_to ? `often with ${s.similar_to}` : s.category;
      if (s.on_work) li.dataset.onWork = "1";
      li.append(dot, name, why);
      list.appendChild(li);
    });
    if (!exact) {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.id = `${list.id}-new`;
      li.className = "create";
      li.dataset.name = q;
      li.textContent = `Create “${q}” (Uncategorized)`;
      list.appendChild(li);
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  });
  document.addEventListener("keydown", (e) => {
    const input = e.target;
    if (!input.matches?.("[data-tag-input]")) return;
    const list = suggestBox(input);
    const items = Array.from(list.children);
    const current = items.findIndex((li) => li.getAttribute("aria-selected") === "true");
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && items.length && !list.hidden) {
      e.preventDefault();
      const next = e.key === "ArrowDown" ? Math.min(current + 1, items.length - 1) : Math.max(current - 1, 0);
      items.forEach((li, i) => li.setAttribute("aria-selected", String(i === next)));
      input.setAttribute("aria-activedescendant", items[next].id);
    } else if (e.key === "Enter" && current >= 0 && !list.hidden) {
      e.preventDefault();
      pick(input, items[current]);
    } else if (e.key === "Escape" && !list.hidden) {
      e.stopPropagation();
      closeSuggestions(input);
    }
  });
  document.addEventListener("mousedown", (e) => {
    const li = e.target.closest(".tag-suggest li");
    if (li) {
      e.preventDefault();   // keep focus in the box
      pick(li.closest(".tag-input-wrap").querySelector("[data-tag-input]"), li);
    }
  });
  document.addEventListener("focusout", (e) => {
    if (e.target.matches?.("[data-tag-input]")) closeSuggestions(e.target);
  });

  // Tags page: drag categories into order; the new order saves straight away.
  const categoryList = document.querySelector("[data-category-list]");
  if (categoryList && window.Sortable) {
    Sortable.create(categoryList, {
      animation: 150,
      draggable: ".category[data-id]",
      handle: ".category-head h2",
      delay: 150, delayOnTouchOnly: true,
      onEnd: () => {
        const body = new FormData();
        categoryList.querySelectorAll(".category[data-id]").forEach((s) => body.append("order", s.dataset.id));
        fetch("/categories/order", { method: "POST", body, headers: { "X-Partial": "1" } });
      },
    });
  }
})();
