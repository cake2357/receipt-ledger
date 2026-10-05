"use strict";
// Structured server locations only; never infer business meaning from prose.
let fieldErrors = [], fieldErrorSequence = 0;
const itemFieldNames = { category_id: "category", pre_tax: "preTax", tax_rate: "taxRate", ok_discount_eligible: "okEligible" };
function errorControl(loc, scope) {
  if (!Array.isArray(loc)) return null;
  if (scope) return scope.querySelector(`[data-error-field="${CSS.escape(String(loc[0]))}"]`);
  if (loc[0] === "items") {
    if (loc.length === 1) return document.querySelector("#add-item");
    const row = document.querySelectorAll("#items > .item")[loc[1]];
    return row?.querySelector(`[data-field="${CSS.escape(itemFieldNames[loc[2]] || String(loc[2]))}"]`);
  }
  const id = { date: "receipt-date", calculation: "tax-calculate", allocation_method: "allocate" }[loc[0]] || String(loc[0]).replaceAll("_", "-");
  return document.getElementById(id);
}
function focusError(control) {
  if (!control?.isConnected) return;
  for (let parent = control.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === "DETAILS") parent.open = true;
    if (["allocation-panel", "printed-discount"].includes(parent.id)) parent.hidden = false;
  }
  control.scrollIntoView({ block: "center" });
  control.focus({ preventScroll: true });
}
function removeFieldError(entry) {
  const {control, inline} = entry;
  control.removeAttribute("aria-invalid");
  const ids = (control.getAttribute("aria-describedby") || "").split(/\s+/).filter(id => id && id !== inline.id);
  if (ids.length) control.setAttribute("aria-describedby", ids.join(" "));
  else control.removeAttribute("aria-describedby");
  inline.remove();
}
function clearFieldErrors() {
  fieldErrors.forEach(removeFieldError);
  fieldErrors = [];
  document.querySelectorAll(".field-error-summary").forEach(el => el.remove());
}
function renderErrorSummary() {
  document.querySelectorAll(".field-error-summary").forEach(el => el.remove());
  if (!fieldErrors.length) return;
  const summary = document.createElement("div");
  summary.className = "field-error-summary";
  summary.setAttribute("role", "alert");
  const heading = document.createElement("p");
  heading.textContent = `修正・確認が必要な項目（${fieldErrors.length}件）。項目名を押すと移動します。`;
  summary.append(heading);
  const list = document.createElement("ul");
  for (const entry of fieldErrors) {
    const li = document.createElement("li"), link = document.createElement("a");
    link.href = "#" + entry.control.id;
    link.textContent = entry.label + "：" + entry.message;
    link.onclick = event => { event.preventDefault(); focusError(entry.control); };
    li.append(link); list.append(li);
  }
  summary.append(list);
  const scope = fieldErrors[0].scope;
  if (scope) scope.prepend(summary);
  else document.querySelector("#review-message").before(summary);
}
function showFieldErrors(errors, scope) {
  clearFieldErrors();
  for (const error of errors || []) {
    const control = errorControl(error.loc, scope);
    if (!control || fieldErrors.some(entry => entry.control === control)) continue;
    if (!control.id) control.id = "error-field-" + (++fieldErrorSequence);
    const inline = document.createElement("span");
    inline.id = "field-reason-" + (++fieldErrorSequence);
    inline.className = "field-error-reason";
    inline.textContent = error.message;
    control.setAttribute("aria-invalid", "true");
    control.setAttribute("aria-describedby", [control.getAttribute("aria-describedby"), inline.id].filter(Boolean).join(" "));
    control.after(inline);
    const label = (error.loc[0] === "items" && error.loc.length > 1 ? `明細${error.loc[1] + 1}・` : "") +
      (control.getAttribute("aria-label") || control.labels?.[0]?.childNodes[0]?.textContent?.trim() || control.textContent || "入力項目");
    fieldErrors.push({...error, control, inline, label, scope});
  }
  renderErrorSummary();
  return fieldErrors[0]?.control;
}
function editedFieldErrors(event) {
  const receiptEdit = event.target.closest("#review") && !["reviewed", "allocation-approved"].includes(event.target.id);
  const removed = fieldErrors.filter(entry => entry.control === event.target || !entry.control.isConnected || (receiptEdit && entry.derived));
  removed.forEach(removeFieldError);
  fieldErrors = fieldErrors.filter(entry => !removed.includes(entry));
  renderErrorSummary();
  if (removed.length && !fieldErrors.length) {
    const local = document.querySelector("#review-message");
    local.textContent = "入力を変更しました。保存・計算・確定をもう一度実行して確認してください。";
    local.className = "muted";
    document.querySelector("#message").textContent = "";
  }
}
document.addEventListener("input", editedFieldErrors);
document.addEventListener("change", editedFieldErrors);
