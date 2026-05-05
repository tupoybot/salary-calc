const STORAGE_KEY = "salary-calc:v1";

const root = document.querySelector(".app-shell");
const currentYear = Number(root.dataset.currentYear);
const form = document.querySelector("#salary-form");
const controls = {
  grossSalary: document.querySelector("#grossSalary"),
  advanceDay: document.querySelector("#advanceDay"),
  salaryDay: document.querySelector("#salaryDay"),
  year: document.querySelector("#year"),
  sickExperienceRate: document.querySelector("#sickExperienceRate"),
  sickIncomeTwoYears: document.querySelector("#sickIncomeTwoYears"),
};
const resultBody = document.querySelector("#resultBody");
const vacationRows = document.querySelector("#vacationRows");
const sickRows = document.querySelector("#sickRows");
const bonusRows = document.querySelector("#bonusRows");
const statusEl = document.querySelector("#status");
const warningsEl = document.querySelector("#warnings");
const assumptionsEl = document.querySelector("#assumptions");

const moneyFormat = new Intl.NumberFormat("ru-RU", {
  maximumFractionDigits: 0,
});

let debounceTimer = null;
let state = loadState();

function defaultState() {
  return {
    grossSalary: "250000",
    advanceDay: 25,
    salaryDay: 10,
    year: currentYear,
    sickExperienceRate: "1",
    sickIncomeTwoYears: "",
    vacations: [],
    sickLeaves: [],
    bonuses: [],
  };
}

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return { ...defaultState(), ...saved };
  } catch {
    return defaultState();
  }
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function syncInputs() {
  controls.grossSalary.value = state.grossSalary;
  controls.advanceDay.value = state.advanceDay;
  controls.salaryDay.value = state.salaryDay;
  controls.year.value = state.year;
  controls.sickExperienceRate.value = state.sickExperienceRate;
  controls.sickIncomeTwoYears.value = state.sickIncomeTwoYears || "";
}

function renderDynamicRows() {
  vacationRows.innerHTML = "";
  state.vacations.forEach((vacation, index) => {
    const row = document.createElement("div");
    row.className = "dynamic-row vacation-row";
    row.innerHTML = `
      <label>
        <span>С</span>
        <input type="date" data-kind="vacation" data-index="${index}" data-field="start" value="${escapeHtml(toIsoDate(vacation.start))}">
      </label>
      <label>
        <span>По</span>
        <input type="date" data-kind="vacation" data-index="${index}" data-field="end" value="${escapeHtml(toIsoDate(vacation.end))}">
      </label>
      <button class="icon-button" type="button" data-remove-vacation="${index}" title="Удалить отпуск" aria-label="Удалить отпуск">×</button>
    `;
    vacationRows.appendChild(row);
  });

  bonusRows.innerHTML = "";
  state.bonuses.forEach((bonus, index) => {
    const row = document.createElement("div");
    row.className = "dynamic-row bonus-row";
    row.innerHTML = `
      <label>
        <span>Дата</span>
        <input type="date" data-kind="bonus" data-index="${index}" data-field="date" value="${escapeHtml(toIsoDate(bonus.date))}">
      </label>
      <label>
        <span>Сумма, ₽</span>
        <input inputmode="decimal" autocomplete="off" data-kind="bonus" data-index="${index}" data-field="amount" value="${escapeHtml(bonus.amount || "")}">
      </label>
      <button class="icon-button" type="button" data-remove-bonus="${index}" title="Удалить премию" aria-label="Удалить премию">×</button>
    `;
    bonusRows.appendChild(row);
  });

  if (!state.vacations.length) {
    vacationRows.appendChild(emptyRow("Отпусков нет"));
  }

  sickRows.innerHTML = "";
  state.sickLeaves.forEach((sickLeave, index) => {
    const row = document.createElement("div");
    row.className = "dynamic-row sick-row";
    row.innerHTML = `
      <label>
        <span>С</span>
        <input type="date" data-kind="sickLeave" data-index="${index}" data-field="start" value="${escapeHtml(toIsoDate(sickLeave.start))}">
      </label>
      <label>
        <span>По</span>
        <input type="date" data-kind="sickLeave" data-index="${index}" data-field="end" value="${escapeHtml(toIsoDate(sickLeave.end))}">
      </label>
      <button class="icon-button" type="button" data-remove-sick-leave="${index}" title="Удалить больничный" aria-label="Удалить больничный">×</button>
    `;
    sickRows.appendChild(row);
  });

  if (!state.sickLeaves.length) {
    sickRows.appendChild(emptyRow("Больничных нет"));
  }

  if (!state.bonuses.length) {
    bonusRows.appendChild(emptyRow("Премий нет"));
  }
}

function emptyRow(text) {
  const row = document.createElement("div");
  row.className = "empty-row";
  row.textContent = text;
  return row;
}

function collectForm() {
  state.grossSalary = controls.grossSalary.value.trim();
  state.advanceDay = Number(controls.advanceDay.value);
  state.salaryDay = Number(controls.salaryDay.value);
  state.year = Number(controls.year.value);
  state.sickExperienceRate = controls.sickExperienceRate.value;
  state.sickIncomeTwoYears = controls.sickIncomeTwoYears.value.trim();
}

function scheduleCalculation() {
  window.clearTimeout(debounceTimer);
  debounceTimer = window.setTimeout(calculate, 350);
}

async function calculate() {
  collectForm();
  saveState();
  statusEl.textContent = "Считаю…";
  warningsEl.hidden = true;
  warningsEl.innerHTML = "";

  try {
    const response = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Ошибка расчёта");
    }
    renderResult(payload);
    statusEl.textContent = "Готово";
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

function buildPayload() {
  return {
    ...state,
    vacations: state.vacations
      .map((vacation) => ({
        start: toIsoDate(vacation.start),
        end: toIsoDate(vacation.end),
      }))
      .filter((vacation) => vacation.start && vacation.end),
    sickLeaves: state.sickLeaves
      .map((sickLeave) => ({
        start: toIsoDate(sickLeave.start),
        end: toIsoDate(sickLeave.end),
      }))
      .filter((sickLeave) => sickLeave.start && sickLeave.end),
    bonuses: state.bonuses
      .map((bonus) => ({
        ...bonus,
        date: toIsoDate(bonus.date),
      }))
      .filter((bonus) => bonus.date && isPositiveAmount(bonus.amount)),
  };
}

function isPositiveAmount(value) {
  const number = Number(String(value).replaceAll(" ", "").replace(",", "."));
  return Number.isFinite(number) && number > 0;
}

function renderResult(result) {
  document.querySelector("#totalGross").textContent = money(result.totals.gross);
  document.querySelector("#totalTax").textContent = money(result.totals.tax);
  document.querySelector("#totalNet").textContent = money(result.totals.net);
  document.querySelector("#averageNet").textContent = money(result.totals.average_net);

  resultBody.innerHTML = "";
  result.rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <th scope="row">
        <span class="month-name">${row.month_name}</span>
        <span class="work-days">${workDays(row)}</span>
      </th>
      <td>${paymentCell(row.salary)}</td>
      <td>${paymentCell(row.advance)}</td>
      <td>${paymentCell(row.vacation)}</td>
      <td>${paymentCell(row.sick)}</td>
      <td>${paymentCell(row.bonus)}</td>
      <td>${taxCell(row)}</td>
      <td class="money-cell strong">${money(row.net_total)}</td>
      <td class="money-cell">${money(row.cumulative_gross)}</td>
    `;
    resultBody.appendChild(tr);
  });

  assumptionsEl.innerHTML = "";
  result.assumptions.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    assumptionsEl.appendChild(li);
  });

  if (result.warnings.length) {
    warningsEl.hidden = false;
    warningsEl.innerHTML = result.warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("");
  }
}

function taxCell(row) {
  if (!row.gross_total || row.tax_total <= 0) {
    return `<span class="muted">0 ₽</span>`;
  }
  return `
    <div class="payment-cell">
      <strong>${money(row.tax_total)}</strong>
      <span>ставка ${escapeHtml(row.tax_rate_label || "0%")}</span>
      <small>эфф. ${percent(row.effective_tax_rate)}</small>
    </div>
  `;
}

function paymentCell(summary) {
  if (!summary || summary.gross <= 0) {
    return `<span class="muted">0 ₽</span>`;
  }
  const dates = summary.dates.map(formatDate).join(", ");
  const labels = summary.items.map((item) => item.label).join("; ");
  return `
    <div class="payment-cell" title="${escapeHtml(labels)}">
      <strong>${money(summary.net)}</strong>
      <span>${dates}</span>
      <small>${money(summary.gross)} до НДФЛ</small>
    </div>
  `;
}

function workDays(row) {
  if (!row.work) return "";
  const vacation = row.work.vacation_work_days
    ? `, отпуск ${row.work.vacation_work_days}`
    : "";
  const sick = row.work.sick_work_days
    ? `, больн. ${row.work.sick_work_days}`
    : "";
  return `${row.work.worked_days}/${row.work.total_work_days} раб.${vacation}${sick}`;
}

function formatDate(value) {
  const iso = toIsoDate(value);
  if (!iso) return value || "";
  const [year, month, day] = iso.split("-");
  return `${day}.${month}.${year}`;
}

function toIsoDate(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";

  const isoMatch = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (isoMatch) {
    const [, year, month, day] = isoMatch;
    return isValidDateParts(year, month, day) ? `${year}-${month}-${day}` : "";
  }

  const ruMatch = raw.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/);
  if (!ruMatch) return "";

  const [, dayRaw, monthRaw, year] = ruMatch;
  const day = dayRaw.padStart(2, "0");
  const month = monthRaw.padStart(2, "0");
  return isValidDateParts(year, month, day) ? `${year}-${month}-${day}` : "";
}

function isValidDateParts(year, month, day) {
  const date = new Date(Number(year), Number(month) - 1, Number(day));
  return (
    date.getFullYear() === Number(year) &&
    date.getMonth() === Number(month) - 1 &&
    date.getDate() === Number(day)
  );
}

function money(value) {
  return `${moneyFormat.format(Math.round(Number(value || 0)))} ₽`;
}

function percent(value) {
  return `${(Number(value || 0) * 100).toFixed(1).replace(".", ",")}%`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

form.addEventListener("input", () => {
  collectForm();
  saveState();
  scheduleCalculation();
});

form.addEventListener("change", () => {
  collectForm();
  saveState();
  scheduleCalculation();
});

document.querySelector("#calculateButton").addEventListener("click", calculate);

document.querySelector("#clearButton").addEventListener("click", () => {
  localStorage.removeItem(STORAGE_KEY);
  state = defaultState();
  syncInputs();
  renderDynamicRows();
  calculate();
});

document.querySelector("#addVacation").addEventListener("click", () => {
  state.vacations.push({ start: `${state.year}-07-01`, end: `${state.year}-07-14` });
  renderDynamicRows();
  saveState();
  scheduleCalculation();
});

document.querySelector("#addSickLeave").addEventListener("click", () => {
  state.sickLeaves.push({ start: `${state.year}-02-02`, end: `${state.year}-02-06` });
  renderDynamicRows();
  saveState();
  scheduleCalculation();
});

document.querySelector("#addBonus").addEventListener("click", () => {
  state.bonuses.push({ date: `${state.year}-12-25`, amount: "0" });
  renderDynamicRows();
  saveState();
});

document.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  const kind = target.dataset.kind;
  const index = Number(target.dataset.index);
  const field = target.dataset.field;
  if (kind === "vacation" && state.vacations[index]) {
    state.vacations[index][field] = target.value;
    saveState();
    scheduleCalculation();
  }
  if (kind === "sickLeave" && state.sickLeaves[index]) {
    state.sickLeaves[index][field] = target.value;
    saveState();
    scheduleCalculation();
  }
  if (kind === "bonus" && state.bonuses[index]) {
    state.bonuses[index][field] = target.value;
    saveState();
    scheduleCalculation();
  }
});

document.addEventListener("click", (event) => {
  const target = event.target.closest("button");
  if (!target) return;
  if (target.dataset.removeVacation !== undefined) {
    state.vacations.splice(Number(target.dataset.removeVacation), 1);
    renderDynamicRows();
    saveState();
    scheduleCalculation();
  }
  if (target.dataset.removeSickLeave !== undefined) {
    state.sickLeaves.splice(Number(target.dataset.removeSickLeave), 1);
    renderDynamicRows();
    saveState();
    scheduleCalculation();
  }
  if (target.dataset.removeBonus !== undefined) {
    state.bonuses.splice(Number(target.dataset.removeBonus), 1);
    renderDynamicRows();
    saveState();
    scheduleCalculation();
  }
});

syncInputs();
renderDynamicRows();
calculate();
