// src/where_my_job/panel/filter.js
// 固定脚本：只读取受控 data-* 属性；页签只切换 section.hidden，筛选只改 tr.hidden 与计数 textContent；不接触 innerHTML/eval。
(function () {
  "use strict";
  var tabs = Array.prototype.slice.call(document.querySelectorAll("button[data-tab-target]"));
  var panels = Array.prototype.slice.call(document.querySelectorAll("section[data-tab]"));
  function show(name) {
    panels.forEach(function (p) { p.hidden = p.getAttribute("data-tab") !== name; });
    tabs.forEach(function (t) {
      t.setAttribute("aria-selected", t.getAttribute("data-tab-target") === name ? "true" : "false");
    });
  }
  tabs.forEach(function (t, i) {
    t.setAttribute("role", "tab");
    t.addEventListener("click", function () { show(t.getAttribute("data-tab-target")); });
    t.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      var j = (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
      tabs[j].focus();
      show(tabs[j].getAttribute("data-tab-target"));
    });
  });
  show("main");

  var table = document.getElementById("jobs");
  if (!table) return;
  var rows = Array.prototype.slice.call(table.tBodies[0].rows);
  var selects = Array.prototype.slice.call(document.querySelectorAll("select[data-filter]"));
  var search = document.querySelector("input[data-search]");
  var countEl = document.querySelector("[data-visible-count]");

  function apply() {
    var q = search ? search.value.trim().toLowerCase() : "";
    var visible = 0;
    rows.forEach(function (tr) {
      var ok = true;
      selects.forEach(function (sel) {
        var col = sel.getAttribute("data-filter");
        var want = sel.value;
        if (want !== "" && tr.getAttribute("data-col-" + col) !== want) ok = false;
      });
      if (ok && q) {
        var hay = (tr.getAttribute("data-search") || "").toLowerCase();
        if (hay.indexOf(q) === -1) ok = false;
      }
      tr.hidden = !ok;
      if (ok) visible++;
    });
    if (countEl) countEl.textContent = String(visible);
  }

  var heads = Array.prototype.slice.call(table.tHead.rows[0].cells);

  function sortBy(col, numeric, th) {
    var dir = table.getAttribute("data-sort-col") === col && table.getAttribute("data-sort-dir") === "desc" ? "asc" : "desc";
    table.setAttribute("data-sort-col", col); table.setAttribute("data-sort-dir", dir);
    heads.forEach(function (h) { h.removeAttribute("aria-sort"); });
    if (th) th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
    rows.sort(function (a, b) {
      var va = a.getAttribute("data-col-" + col) || "", vb = b.getAttribute("data-col-" + col) || "";
      var r;
      if (numeric) { var na = parseFloat(va), nb = parseFloat(vb); if (isNaN(na)) na = -Infinity; if (isNaN(nb)) nb = -Infinity; r = na - nb; }
      else { r = va < vb ? -1 : va > vb ? 1 : 0; }
      return dir === "desc" ? -r : r;
    });
    var body = table.tBodies[0];
    rows.forEach(function (tr) { body.appendChild(tr); });
  }

  selects.forEach(function (s) { s.addEventListener("change", apply); });
  if (search) search.addEventListener("input", apply);
  heads.forEach(function (th) {
    th.setAttribute("tabindex", "0");
    function activate() { sortBy(th.getAttribute("data-col"), th.getAttribute("data-numeric") === "1", th); }
    th.addEventListener("click", activate);
    th.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      activate();
    });
  });
  apply();
})();
