// src/where_my_job/panel/filter.js
// 固定脚本：只读取受控 data-* 属性；页签只切换 section.hidden，筛选与分页只改 tr.hidden、按钮的 textContent/hidden/aria-*；
// 页码按钮是模板里预置的固定若干个，脚本从不新建元素，也不接触 innerHTML/eval。
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
  var emptyBody = table.querySelector("tbody[data-empty]");
  var selects = Array.prototype.slice.call(document.querySelectorAll("select[data-filter]"));
  var search = document.querySelector("input[data-search]");
  var countEl = document.querySelector("[data-visible-count]");
  var pageBtns = Array.prototype.slice.call(document.querySelectorAll("button[data-page-btn]"));
  var steps = Array.prototype.slice.call(document.querySelectorAll("button[data-page-step]"));
  var sizeSel = document.querySelector("select[data-page-size]");
  var matched = rows.slice();
  var size = sizeSel ? (parseInt(sizeSel.value, 10) || 0) : 0;   // 0 表示不分页
  var page = 1;

  function paint() {
    var pages = size > 0 ? Math.max(1, Math.ceil(matched.length / size)) : 1;
    if (page > pages) page = pages;
    if (page < 1) page = 1;
    var start = size > 0 ? (page - 1) * size : 0;
    var end = size > 0 ? start + size : matched.length;
    rows.forEach(function (tr) { tr.hidden = true; });
    for (var i = start; i < end && i < matched.length; i++) matched[i].hidden = false;
    if (emptyBody) emptyBody.hidden = matched.length !== 0;
    var width = pageBtns.length;
    var first = Math.max(1, Math.min(page - Math.floor(width / 2), pages - width + 1));
    pageBtns.forEach(function (b, i) {
      var n = first + i;
      if (n > pages) { b.hidden = true; b.removeAttribute("data-page"); b.removeAttribute("aria-current"); return; }
      b.hidden = false;
      b.textContent = String(n);
      b.setAttribute("data-page", String(n));
      if (n === page) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    steps.forEach(function (b) {
      var d = parseInt(b.getAttribute("data-page-step"), 10);
      b.disabled = (d < 0 && page <= 1) || (d > 0 && page >= pages);
    });
  }

  function apply() {
    var q = search ? search.value.trim().toLowerCase() : "";
    matched = rows.filter(function (tr) {
      for (var i = 0; i < selects.length; i++) {
        var want = selects[i].value;
        if (want !== "" && tr.getAttribute("data-col-" + selects[i].getAttribute("data-filter")) !== want) return false;
      }
      if (q && (tr.getAttribute("data-search") || "").toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
    if (countEl) countEl.textContent = String(matched.length);
    page = 1;
    paint();
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
    apply();
  }

  selects.forEach(function (s) { s.addEventListener("change", apply); });
  if (search) search.addEventListener("input", apply);
  if (sizeSel) sizeSel.addEventListener("change", function () { size = parseInt(sizeSel.value, 10) || 0; page = 1; paint(); });
  pageBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      var n = parseInt(b.getAttribute("data-page"), 10);
      if (n) { page = n; paint(); }
    });
  });
  steps.forEach(function (b) {
    b.addEventListener("click", function () { page += parseInt(b.getAttribute("data-page-step"), 10); paint(); });
  });
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
