"use strict";
const $ = (s) => document.querySelector(s);
let cats = [],
  current = null,
  settings = {},
  taxProposal = null;
let suggestions = { items: [], stores: [] };
const yen = (n) =>
  new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" }).format(
    n,
  );
function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function message(text, error = false) {
  $("#message").textContent = text;
  $("#message").className = error ? "error" : "success";
  const local = $("#review-message");
  local.textContent = text;
  local.className = error ? "error" : "success";
  if (error) {
    const target =
      !$("#receipts").hidden && !$("#review").hidden ? local : $("#message");
    target.scrollIntoView({ block: "center" });
  }
}
async function api(path, method = "GET", data) {
  const options = { method };
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(data);
  }
  const r = await fetch("/api" + path, options);
  const d = await r.json();
  if (!r.ok) {
    const error = Error(typeof d.detail === "string" ? d.detail : "入力内容を確認してください");
    error.fieldErrors = d.field_errors || [];
    throw error;
  }
  return d;
}
let actionPending = false, pendingFocus = null;
const busyLabels = {
  save: "保存中…",
  confirm: "照合・確定中…",
  reopen: "再編集の準備中…",
  "tax-calculate": "税込額を計算中…",
  "tax-apply": "税込計算を適用中…",
  allocate: "商品の金額を計算中…",
  "apply-allocation": "商品の金額を反映中…",
  "local-ocr": "無料OCRで読み取り中…",
  ocr: "有料OCRで読み取り中…",
  manual: "下書きを作成中…",
  drive: "Drive取り込み中…",
  "save-settings": "設定を保存中…",
};
function action(fn) {
  return async (event) => {
    if (actionPending) return;
    actionPending = true;
    const button =
      event?.currentTarget?.tagName === "BUTTON" ? event.currentTarget : null;
    const label = button?.textContent;
    // Lock native controls together: edits during a request must not be lost when
    // the saved receipt is reloaded. Individual confirmed/OCR locks stay intact.
    $("#interaction").disabled = true;
    if (button) {
      button.textContent = busyLabels[button.id] || "処理中…";
      button.setAttribute("aria-busy", "true");
    }
    let firstInvalid = null;
    clearFieldErrors();
    try {
      await fn();
    } catch (e) {
      message(e.message, true);
      firstInvalid = showFieldErrors(e.fieldErrors, button?.closest(".category-editor"));
    } finally {
      $("#interaction").disabled = false;
      actionPending = false;
      if (button) {
        button.textContent = label;
        button.removeAttribute("aria-busy");
      }
      if (firstInvalid) focusError(firstInvalid);
      else if (pendingFocus?.isConnected) pendingFocus.focus();
      pendingFocus = null;
    }
  };
}
function page(id) {
  for (const s of document.querySelectorAll("main>section"))
    s.hidden = s.id !== id;
  for (const b of document.querySelectorAll("nav button"))
    b.classList.toggle("active", b.dataset.page === id);
}
for (const b of document.querySelectorAll("[data-page]"))
  b.onclick = action(async () => {
    page(b.dataset.page);
    if (b.dataset.page === "dashboard") await dashboard();
    if (b.dataset.page === "receipts") await list();
    if (b.dataset.page === "settings") await loadSettings();
  });
async function dashboard() {
  const month = $("#month").value;
  if (!month) return;
  const d = await api("/dashboard?month=" + month);
  $("#monthly-total").textContent = yen(d.total);
  $("#csv").href = "/api/export.csv?month=" + month;
  $("#category-totals").replaceChildren(
    ...d.categories.map((c) => {
      const n = node("div", undefined, "card");
      n.append(node("span", c.name), node("strong", yen(c.total)));
      return n;
    }),
  );
  drawCategoryChart(d);
  const table = $("#daily");
  table.replaceChildren();
  const h = node("tr");
  for (const text of ["日付", ...d.categories.map((c) => c.name), "合計"])
    h.append(node("th", text));
  table.append(h);
  for (const day of d.days) {
    const row = node("tr");
    for (const v of [
      day.date.slice(5),
      ...d.categories.map((c) => yen(day.categories[c.id])),
      yen(day.total),
    ])
      row.append(node("td", v));
    table.append(row);
  }
  draw(d);
}
function drawCategoryChart(d) {
  const canvas = $("#category-chart");
  const ctx = canvas.getContext("2d");
  const legend = $("#category-chart-legend");
  const colors = [
    "#126c60",
    "#bc6d29",
    "#7961a8",
    "#bb4d63",
    "#3374a8",
    "#637a34",
  ];
  const categories = d.categories.filter((category) => category.total > 0);
  const total = categories.reduce((sum, category) => sum + category.total, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  legend.replaceChildren();
  categories.forEach((category) => {
    const item = node("li", undefined, "category-chart-legend-item");
    const swatch = node("span", undefined, "category-chart-swatch");
    swatch.style.backgroundColor = colors[d.categories.indexOf(category) % colors.length];
    swatch.setAttribute("aria-hidden", "true");
    item.append(swatch, node("span", `${category.name} · ${yen(category.total)}`));
    legend.append(item);
  });
  if (total === 0) {
    ctx.fillStyle = "#64736a";
    ctx.font = "16px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("この月の支出はありません", canvas.width / 2, canvas.height / 2);
    legend.append(node("li", "支出なし", "category-chart-legend-item"));
    canvas.setAttribute("aria-label", "今月の分類別支出の円グラフ。この月の支出はありません");
    return;
  }

  let start = -Math.PI / 2;
  categories.forEach((category) => {
    const end = start + (category.total / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(canvas.width / 2, canvas.height / 2);
    ctx.arc(canvas.width / 2, canvas.height / 2, 138, start, end);
    ctx.closePath();
    ctx.fillStyle = colors[d.categories.indexOf(category) % colors.length];
    ctx.fill();
    start = end;
  });
  canvas.setAttribute(
    "aria-label",
    `今月の分類別支出の円グラフ。${categories.map((category) => `${category.name} ${yen(category.total)}`).join("、")}`,
  );
}
function trendScale(values) {
  return { min: Math.min(0, ...values), max: Math.max(1, ...values) };
}
function draw(d) {
  const canvas = $("#trend"),
    ctx = canvas.getContext("2d");
  canvas.height =
    280 + Math.max(0, Math.ceil(d.categories.length / 6) - 1) * 18;
  ctx.clearRect(0, 0, 1000, canvas.height);
  const colors = [
    "#126c60",
    "#bc6d29",
    "#7961a8",
    "#bb4d63",
    "#3374a8",
    "#637a34",
  ];
  const scale = trendScale(
      d.days.flatMap((day) => Object.values(day.categories)),
    ),
    y = (value) => 230 - ((value - scale.min) / (scale.max - scale.min)) * 195;
  ctx.font = "12px sans-serif";
  ctx.fillStyle = "#53665f";
  ctx.fillText(yen(scale.max), 6, 25);
  ctx.fillText(yen(scale.min), 6, 235);
  ctx.strokeStyle = "#d6e0da";
  ctx.beginPath();
  ctx.moveTo(65, y(0));
  ctx.lineTo(985, y(0));
  ctx.stroke();
  d.categories.forEach((c, i) => {
    ctx.strokeStyle = colors[i % colors.length];
    ctx.lineWidth = 2;
    ctx.beginPath();
    d.days.forEach((day, j) => {
      const x = 65 + (j * 920) / (d.days.length - 1);
      j
        ? ctx.lineTo(x, y(day.categories[c.id]))
        : ctx.moveTo(x, y(day.categories[c.id]));
    });
    ctx.stroke();
    ctx.fillStyle = colors[i % colors.length];
    ctx.fillText(
      c.name.slice(0, 14),
      65 + (i % 6) * 150,
      255 + Math.floor(i / 6) * 18,
    );
  });
}
async function list() {
  const receipts = await api("/receipts");
  $("#receipt-list").replaceChildren();
  if (!receipts.length)
    $("#receipt-list").append(
      node(
        "p",
        "まだレシートはありません。画像または手入力で追加してください。",
      ),
    );
  for (const r of receipts) {
    const b = node(
      "button",
      `${r.status === "confirmed" ? "確定" : "下書き"} · ${r.date || "日付未入力"} · ${r.store || "店名未入力"} · ${r.total === null ? "金額未入力" : yen(r.total)}`,
      "receipt-card",
    );
    b.onclick = action(() => open(r.id));
    $("#receipt-list").append(b);
  }
}
async function open(id) {
  [cats, suggestions] = await Promise.all([api("/categories"), api("/input-suggestions")]);
  $("#store-suggestions").replaceChildren(...suggestions.stores.map(name => new Option(name, name)));
  $("#item-suggestions").replaceChildren(...suggestions.items.map(item => new Option(item.name, item.name)));
  $("#bulk-category").replaceChildren(new Option("分類を選択", ""), ...cats.map(c => new Option(c.name, c.id)));
  current = await api("/receipts/" + id);
  $("#review-message").textContent = "";
  $("#review").hidden = false;
  $("#ok-discount-mode").value = current.ok_discount_mode || "off";
  $("#tax-preview").hidden = true;
  $("#tax-apply").hidden = true;
  taxProposal = null;
  $("#tax-summary").textContent = current.calculation
    ? `前回適用の計算（入力・設定を変えたら再計算）: 割引 ${yen(current.calculation.discount_total)} / 税 ${yen(current.calculation.tax_total)} / 合計 ${yen(current.calculation.total)}`
    : "";
  $("#ok-hint").textContent =
    /^(オーケー|OK(?:ストア|ストアー|[\s　]|$)|ＯＫ)/i.test(current.store)
      ? "OK店舗の可能性があります。割引を適用する会計か確認して選択してください。"
      : "";
  $("#receipt-status").textContent =
    current.status === "confirmed" ? "確定済み" : "下書き";
  $("#receipt-image").hidden = !current.image;
  $("#ocr-controls").hidden = !current.image;
  $("#no-image").hidden = !!current.image;
  $(".review-grid").classList.toggle("manual-review", !current.image);
  if (current.image) $("#receipt-image").src = "/api/receipts/" + id + "/image";
  $("#receipt-date").value = current.date;
  $("#store").value = current.store;
  $("#total").value = current.total ?? "";
  $("#reviewed").checked = current.reviewed;
  $("#allocation-preview").hidden = true;
  $("#apply-allocation").hidden = true;
  $("#tax-rates").value = (current.tax_rates || []).join(",");
  $("#tax-exclusive").checked = !!current.tax_exclusive;
  $("#allocation-approved").checked = !!current.allocation_approved;
  for (const [id, key] of [
    ["subtotal", "subtotal"],
    ["pre-discount-total", "pre_discount_total"],
    ["discount-total", "discount_total"],
    ["tax-total", "tax_total"],
    ["quantity-total", "quantity_total"],
  ])
    $("#" + id).value = current[key] ?? "";
  $("#allocation-panel").hidden = !current.tax_exclusive;
  $("#warnings").textContent = current.warnings.join(" / ");
  $("#raw").textContent = current.raw || "OCR未実行";
  let rawText = "無料OCR未実行";
  try {
    rawText = JSON.parse(current.raw)?.text || rawText;
  } catch {}
  $("#raw-text").textContent = rawText;
  $("#items").replaceChildren();
  for (const item of current.items) addItem(item);
  const locked = current.status === "confirmed";
  for (const input of $("#review").querySelectorAll("input,select"))
    input.disabled = locked;
  for (const id of [
    "save",
    "confirm",
    "add-item",
    "apply-category",
    "use-item-total",
    "ocr",
    "local-ocr",
    "allocate",
    "tax-calculate",
  ])
    $("#" + id).hidden = locked;
  $("#reopen").hidden = !locked;
  settings = await api("/settings");
  $("#local-ocr").disabled = !current.image || !settings.local_ocr?.available;
  $("#ocr").disabled = !current.image || !settings.ocr_ready;
  $("#local-ocr-hint").textContent =
    settings.local_ocr?.message ||
    "無料OCRの更新を反映するためサーバーを再起動してください。";
  for (const b of $("#items").querySelectorAll("button")) b.disabled = locked;
  syncDiscountField();
  balance();
  $("#review").scrollIntoView({ behavior: "smooth", block: "start" });
}
function addItem(item = {}) {
  const row = node("div", undefined, "item");
  const name = node("input");
  name.placeholder = "商品名";
  name.setAttribute("aria-label", "商品名");
  name.value = item.name || "";
  name.maxLength = 500;
  name.setAttribute("list", "item-suggestions");
  const category = node("select");
  category.setAttribute("aria-label", "分類");
  category.append(new Option("分類を選択", ""));
  for (const c of cats) category.append(new Option(c.name, c.id));
  category.value = item.category_id || "";
  const amount = node("input");
  amount.type = "number";
  amount.step = "1";
  amount.placeholder = "税込円";
  amount.setAttribute("aria-label", "税込円");
  amount.value = item.amount ?? "";
  const del = node("button", "削除");
  del.setAttribute("aria-label", "この明細を削除");
  del.onclick = () => {
    row.remove();
    invalidate();
  };
  const pre = node("input");
  pre.type = "number";
  pre.min = "0";
  pre.step = "1";
  pre.placeholder = "税抜明細額（数量込み）";
  pre.setAttribute("aria-label", "税抜明細額");
  pre.value = item.pre_tax ?? "";
  const qty = node("input");
  qty.type = "number";
  qty.min = "1";
  qty.step = "1";
  qty.setAttribute("aria-label", "数量");
  qty.value = item.quantity === undefined ? 1 : (item.quantity ?? "");
  row._allocation = {
    allocated_discount: item.allocated_discount ?? null,
    allocated_tax: item.allocated_tax ?? null,
    amount_source: item.amount_source || "manual",
  };
  const rate = node("select");
  rate.setAttribute("aria-label", "明細税率");
  rate.append(
    new Option("分類に従う", ""),
    new Option("8%", "8"),
    new Option("10%", "10"),
  );
  rate.value = item.tax_rate ?? "";
  const eligible = node("select");
  eligible.setAttribute("aria-label", "明細OK割引");
  eligible.append(
    new Option("分類に従う", ""),
    new Option("対象", "true"),
    new Option("対象外", "false"),
  );
  eligible.value =
    item.ok_discount_eligible == null ? "" : String(item.ok_discount_eligible);
  for (const control of [amount, pre, qty]) control.inputMode = "numeric";
  const details = node("details", undefined, "item-details");
  details.append(node("summary", "税抜の金額・個数など"));
  details.open = $("#tax-exclusive").checked || item.pre_tax != null ||
    item.tax_rate != null || item.ok_discount_eligible != null ||
    (item.quantity != null && item.quantity !== 1);
  const extra = node("div", undefined, "item-extra");
  details.append(extra);
  // Amounts are line totals including quantity, never unit prices to multiply again.
  for (const [field, control, text] of [
    ["name", name, "商品名"],
    ["category", category, "分類"],
    ["amount", amount, "金額（税込・円）"],
    ["preTax", pre, "税抜の金額（円・買った個数分）"],
    ["quantity", qty, "数量"],
    ["taxRate", rate, "明細税率"],
    ["okEligible", eligible, "OK割引の対象"],
  ]) {
    control.dataset.field = field;
    const label = node("label", text);
    label.append(control);
    (["name", "category", "amount"].includes(field) ? row : extra).append(label);
  }
  row.append(del, details);
  const manualNote = node("small", "金額を手修正しました。レシートと比べて確認してください。", "manual-amount-detail");
  manualNote.hidden = item.amount_source !== "manual" || item.allocated_tax == null;
  row.append(manualNote);
  rate.onchange = invalidate;
  eligible.onchange = invalidate;
  if (item.amount_source === "calculated")
    row.append(
      node(
        "small",
        `前回の計算値: 税抜 ${yen(item.pre_tax)} − 割引 ${yen(item.allocated_discount)} + 税 ${yen(item.allocated_tax)} = ${yen(item.amount)}`,
        "allocation-detail",
      ),
    );
  for (const input of [name, category, amount, pre, qty])
    input.oninput = invalidate;
  amount.oninput = () => {
    row._allocation.amount_source = "manual";
    manualNote.hidden = row._allocation.allocated_tax == null;
    invalidate({ manualAmount: true });
  };
  let suggestedCategory = null;
  category.onchange = () => { suggestedCategory = null; };
  name.oninput = () => {
    // Reuse only confirmed exact matches, and preserve any explicit selection.
    if (suggestedCategory !== null && category.value === suggestedCategory) category.value = "";
    suggestedCategory = null;
    const match = suggestions.items.find(item => item.name === name.value);
    if (!category.value && match && cats.some(c => c.id === match.category_id)) {
      suggestedCategory = String(match.category_id);
      category.value = suggestedCategory;
    }
    invalidate();
  };
  amount.onkeydown = event => {
    if (event.key !== "Enter" || event.isComposing || actionPending || current.status === "confirmed") return;
    event.preventDefault();
    if (!name.value.trim() || !category.value || amount.value === "" || !amount.validity.valid) return;
    const next = row.nextElementSibling;
    if (next) next.querySelector('[data-field="name"]').focus();
    else appendItem();
  };
  $("#items").append(row);
}
function invalidate({ manualAmount = false } = {}) {
  // Keep printed amounts and the previous calculation for audit/validation.
  // Edits invalidate approval and previews, never silently recalculate money.
  if (current?.calculation || $(".allocation-detail")) {
    $("#tax-summary").textContent =
      manualAmount
        ? "税込額を手修正しました。商品と合計をレシートと比べて確認してください。計算に使う金額も変更した場合は再計算が必要です。"
        : "入力が変わりました。税込欄は前回の値です。再計算して案を適用し、印字合計と照合してください。";
    for (const detail of document.querySelectorAll(".allocation-detail"))
      detail.hidden = true;
  }
  if (!$("#review-message").classList.contains("error")) {
    $("#review-message").textContent =
      "未保存の変更があります。途中でも下書きを保存できます。";
    $("#review-message").className = "muted";
  }
  taxProposal = null;
  $("#tax-preview").hidden = true;
  $("#tax-apply").hidden = true;
  $("#allocation-preview").hidden = true;
  $("#apply-allocation").hidden = true;
  $("#reviewed").checked = false;
  $("#allocation-approved").checked = false;
  balance();
}
function syncDiscountField() {
  $("#printed-discount").hidden =
    $("#ok-discount-mode").value !== "printed" && !$("#manual-allocation").open;
}
$("#manual-allocation").ontoggle = syncDiscountField;
$("#ok-discount-mode").onchange = () => {
  syncDiscountField();
  invalidate();
};
$("#tax-calculate").onclick = action(async () => {
  invalidate();
  await api("/receipts/" + current.id, "PUT", body());
  taxProposal = await api("/receipts/" + current.id + "/tax-preview", "POST");
  const c = taxProposal.calculation,
    preview = $("#tax-preview");
  preview.replaceChildren(
    node(
      "p",
      `計算案（未適用）: 割引 ${yen(c.discount_total)} / 税 ${yen(c.tax_total)} / 税込 ${yen(c.total)}`,
    ),
  );
  for (const i of taxProposal.items)
    preview.append(
      node(
        "p",
        `${i.name}: ${yen(i.pre_tax)} − ${yen(i.allocated_discount)} + ${yen(i.allocated_tax)} = ${yen(i.amount)}`,
      ),
    );
  preview.append(
    node(
      "p",
      taxProposal.total === null
        ? "印字の合計を入力してください。"
        : `印字合計との差額 ${yen(taxProposal.total - c.total)}。不一致なら税率・対象・印字割引を確認してください。`,
    ),
  );
  preview.hidden = false;
  $("#tax-apply").hidden = false;
  message(
    "入力は下書き保存済みです。金額を確認して「この金額を商品に反映する」を押してください。",
  );
});
$("#tax-apply").onclick = action(async () => {
  if (!taxProposal) throw Error("先に計算案を表示してください");
  await api("/receipts/" + current.id + "/tax-apply", "POST", {
    signature: taxProposal.calculation.signature,
  });
  await open(current.id);
  message(
    "商品の金額を反映しました。レシートの合計と比べて確認してください。",
  );
});
$("#tax-exclusive").onchange = () => {
  $("#allocation-panel").hidden = !$("#tax-exclusive").checked;
  if ($("#tax-exclusive").checked)
    for (const details of document.querySelectorAll(".item-details")) details.open = true;
  invalidate();
};
for (const id of [
  "tax-rates",
  "subtotal",
  "pre-discount-total",
  "discount-total",
  "tax-total",
  "quantity-total",
])
  $("#" + id).oninput = invalidate;
$("#allocate").onclick = action(async () => {
  invalidate();
  await api("/receipts/" + current.id, "PUT", body());
  const proposal = await api(
    "/receipts/" + current.id + "/allocation-preview",
    "POST",
  );
  const preview = $("#allocation-preview");
  preview.replaceChildren(
    node("p", "商品の税込金額（まだ反映していません）：税抜 − 割引 + 税金 = 税込"),
  );
  for (const item of proposal.items)
    preview.append(
      node(
        "p",
        `${item.name}: ${yen(item.pre_tax)} − ${yen(item.allocated_discount)} + ${yen(item.allocated_tax)} = ${yen(item.amount)}`,
      ),
    );
  preview.hidden = false;
  $("#apply-allocation").hidden = false;
  message(
    "入力は下書き保存済みです。金額を確認して「この金額を商品に反映する」を押してください。",
  );
});
$("#apply-allocation").onclick = action(async () => {
  await api("/receipts/" + current.id + "/allocate", "POST");
  await open(current.id);
  message(
    "商品の金額を反映しました。割引・税金は計算で求めています。レシートと比べて確認してください。",
  );
});
function body() {
  const number = (id) =>
    $("#" + id).value === "" ? null : Number($("#" + id).value);
  return {
    date: $("#receipt-date").value,
    store: $("#store").value,
    total: number("total"),
    tax_exclusive: $("#tax-exclusive").checked,
    tax_rates:
      $("#tax-rates").value === ""
        ? []
        : $("#tax-rates").value.split(",").map(Number),
    subtotal: number("subtotal"),
    allocation_method: current.allocation_method ?? null,
    calculation: current.calculation ?? null,
    ok_discount_mode: $("#ok-discount-mode").value,
    pre_discount_total: number("pre-discount-total"),
    discount_total: number("discount-total"),
    tax_total: number("tax-total"),
    quantity_total: number("quantity-total"),
    allocation_approved: $("#allocation-approved").checked,
    items: [...$("#items").children].map((row) => {
      const value = (field) =>
        row.querySelector(`[data-field="${field}"]`).value;
      // Unknown is null, not zero: missing money must block confirmation.
      const number = (field) =>
        value(field) === "" ? null : Number(value(field));
      return {
        ...row._allocation,
        name: value("name"),
        category_id: number("category"),
        amount: number("amount"),
        pre_tax: number("preTax"),
        quantity: number("quantity"),
        tax_rate: number("taxRate"),
        ok_discount_eligible:
          value("okEligible") === "" ? null : value("okEligible") === "true",
      };
    }),
    reviewed: $("#reviewed").checked,
  };
}
function balance() {
  const b = body(),
    sum = b.items.reduce((s, i) => s + (i.amount || 0), 0);
  $("#balance").textContent =
    `明細合計 ${yen(sum)} / 差額 ${b.total === null ? "合計未入力" : yen(b.total - sum)}`;
  $("#allocation-approval").hidden = !b.tax_exclusive &&
    !b.items.some(item => item.amount_source === "calculated");
  const missing = b.items.filter(item => item.amount === null).length;
  if (missing) $("#balance").textContent += ` / 金額未入力 ${missing}件`;
  $("#balance").className = !missing && b.total === sum ? "success" : "warning";
  const corrections = b.items.filter(item => item.amount_source === "calculated" &&
    item.amount !== null && item.pre_tax !== null && item.allocated_discount !== null &&
    item.allocated_tax !== null && item.amount !== item.pre_tax - item.allocated_discount + item.allocated_tax);
  $("#adopt-manual-amounts").hidden = current?.status === "confirmed" || corrections.length === 0;
  $("#adopt-manual-amounts").textContent = `保存済みの手修正額を採用（${corrections.length}件）`;
  $("#use-item-total").disabled = current?.status === "confirmed" || !b.items.length ||
    missing > 0 || b.items.some(item => !Number.isInteger(item.amount)) || sum < 0 || sum > 100000000;
}
$("#adopt-manual-amounts").onclick = () => {
  for (const row of $("#items").children) {
    const input = row.querySelector('[data-field="amount"]');
    const preTax = row.querySelector('[data-field="preTax"]');
    const a = row._allocation;
    if (a.amount_source === "calculated" && input.value !== "" && preTax.value !== "" &&
        a.allocated_discount !== null && a.allocated_tax !== null &&
        Number(input.value) !== Number(preTax.value) - a.allocated_discount + a.allocated_tax) {
      a.amount_source = "manual";
      row.querySelector(".manual-amount-detail").hidden = false;
    }
  }
  invalidate({ manualAmount: true });
};
for (const id of ["receipt-date", "store", "total"])
  $("#" + id).oninput = invalidate;
function appendItem() {
  addItem();
  invalidate();
  $("#items").lastElementChild.querySelector('[data-field="name"]').focus();
}
$("#add-item").onclick = appendItem;
$("#apply-category").onclick = () => {
  const category = $("#bulk-category").value;
  if (!category) return;
  for (const select of document.querySelectorAll('#items [data-field="category"]'))
    if (!select.value) select.value = category;
  invalidate();
};
$("#use-item-total").onclick = () => {
  const items = body().items;
  if (!items.length || items.some(item => item.amount === null || !Number.isInteger(item.amount))) return;
  const sum = items.reduce((total, item) => total + item.amount, 0);
  if (sum < 0 || sum > 100000000) return;
  $("#total").value = sum;
  invalidate();
};
$("#manual").onclick = action(async () => {
  const r = await api("/receipts", "POST");
  await list();
  await open(r.id);
  const today = new Date();
  $("#receipt-date").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  appendItem();
  pendingFocus = $("#store");
});
$("#upload").onchange = action(async () => {
  const f = $("#upload").files[0];
  if (!f) return;
  const data = new FormData();
  data.append("file", f);
  const r = await api("/upload", "POST", data);
  await list();
  await open(r.id);
  message("画像を下書きに保存しました（同じ画像は重複しません）。");
  $("#upload").value = "";
});
$("#save").onclick = action(async () => {
  await api("/receipts/" + current.id, "PUT", body());
  await list();
  message("下書きを保存しました。");
});
$("#confirm").onclick = action(async () => {
  await api("/receipts/" + current.id, "PUT", body());
  await api("/receipts/" + current.id + "/confirm", "POST");
  await open(current.id);
  await list();
  message("確定しました。集計に反映されます。");
});
$("#reopen").onclick = action(async () => {
  await api("/receipts/" + current.id + "/reopen", "POST");
  await open(current.id);
  await list();
  message("下書きに戻しました。再確定まで集計から除外します。");
});
$("#local-ocr").onclick = action(async () => {
  if (
    !window.confirm(
      "このMac内だけで無料OCRを実行します。入力中の下書きを置き換えます。続けますか？",
    )
  )
    return;
  const id = current.id;
  $("#local-ocr").disabled = true;
  $("#ocr").disabled = true;
  message(
    "無料OCRで読み取り中…初回準備は最大120秒、読取は最大60秒。外部送信なし。",
  );
  try {
    await api("/receipts/" + id + "/ocr/local", "POST");
    await open(id);
    await list();
    message(
      "無料OCRの下書きを作成しました。原文と画像を確認し、空欄・分類・数量を修正してください。",
    );
  } catch (e) {
    await open(id);
    throw e;
  } finally {
    $("#local-ocr").disabled = !current.image || !settings.local_ocr?.available;
    $("#ocr").disabled = !current.image || !settings.ocr_ready;
  }
});
$("#ocr").onclick = action(async () => {
  if (
    !window.confirm(
      "画像をOpenAIへ送信し、従量料金が発生します。入力中の明細を置き換えます。続けますか？",
    )
  )
    return;
  message("読み取り中…（自動再試行なし）");
  await api("/receipts/" + current.id + "/ocr", "POST");
  await open(current.id);
  message("読み取り結果を必ず確認・修正してください。");
});
$("#drive").onclick = action(async () => {
  message("Drive取り込み中…");
  const r = await api("/drive/import", "POST");
  await list();
  message(
    `新規 ${r.imported} 件 / 重複・対象外 ${r.skipped} 件 / エラー ${r.errors.length} 件` +
      (r.errors.length ? "。失敗分は再実行できます。" : ""),
  );
});
function categoryEditor(c = {}) {
  const row = node("div", undefined, "category-editor");
  const name = node("input");
  name.value = c.name || "";
  name.placeholder = "分類名";
  name.setAttribute("aria-label", "分類名");
  name.dataset.errorField = "name";
  const desc = node("textarea");
  desc.value = c.description || "";
  desc.placeholder = "この分類に含める商品の説明";
  desc.setAttribute("aria-label", "分類の説明");
  desc.dataset.errorField = "description";
  const save = node("button", "分類を保存");
  save.onclick = action(async () => {
    await api("/categories" + (c.id ? "/" + c.id : ""), c.id ? "PUT" : "POST", {
      name: name.value,
      description: desc.value,
      tax_rate: rate.value === "" ? null : Number(rate.value),
      ok_discount_eligible: eligible.checked,
    });
    await loadSettings();
    message("分類を保存しました。");
  });
  const rate = node("select");
  rate.setAttribute("aria-label", "カテゴリ税率");
  rate.dataset.errorField = "tax_rate";
  rate.append(
    new Option("税率未設定", ""),
    new Option("8%（食品）", "8"),
    new Option("10%", "10"),
  );
  rate.value = c.tax_rate ?? "";
  const eligible = node("input");
  eligible.type = "checkbox";
  eligible.checked = !!c.ok_discount_eligible;
  eligible.setAttribute("aria-label", "カテゴリOK割引対象");
  eligible.dataset.errorField = "ok_discount_eligible";
  const label = node("label", "OK食品割引の対象");
  label.prepend(eligible);
  row.append(name, desc, rate, label, save);
  $("#categories").append(row);
}
async function loadSettings() {
  cats = await api("/categories");
  settings = await api("/settings");
  $("#categories").replaceChildren();
  cats.forEach(categoryEditor);
  $("#drive-folder").value = settings.drive_folder;
  $("#consent").checked = settings.ocr_consent;
  $("#google-status").textContent = settings.google_authorized
    ? "認証ファイルあり（接続は取り込み時に検証）"
    : "未認証：READMEのGoogle OAuth手順を実行してください。";
  $("#local-ocr-status").textContent =
    (settings.local_ocr?.available
      ? "利用環境あり（日本語対応は実行時に確認） · "
      : "利用できません · ") +
    (settings.local_ocr?.message || "サーバーを再起動してください。");
  $("#ocr-status").textContent =
    `${settings.ocr_ready ? "設定済み（接続・API残高は未確認）" : "無効 / 設定不足"} · モデル: ${settings.model || "未設定"} · APIキー: ${settings.key_present ? "設定あり" : "未設定"}`;
  $("#setup-instructions").replaceChildren(
    ...settings.instructions.map((s) => node("p", s, "muted")),
  );
}
$("#new-category").onclick = () => categoryEditor();
$("#save-settings").onclick = action(async () => {
  await api("/settings", "PUT", {
    drive_folder: $("#drive-folder").value.trim(),
    ocr_consent: $("#consent").checked,
  });
  await loadSettings();
  message("設定を保存しました。");
});
$("#month").onchange = action(dashboard);
const now = new Date();
$("#month").value =
  `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
action(async () => {
  cats = await api("/categories");
  page("dashboard");
  await dashboard();
})();
