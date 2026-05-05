from __future__ import annotations

from datetime import date, datetime

from flask import Flask, jsonify, render_template, request

from app.calendar_client import IsDayOffCalendarProvider
from app.calculator import (
    BonusInput,
    CalculationError,
    PayrollInput,
    SickLeaveInput,
    VacationInput,
    calculate_payroll,
)


app = Flask(__name__)
calendar_provider = IsDayOffCalendarProvider()


@app.get("/")
def index():
    return render_template("index.html", current_year=date.today().year)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/calculate")
def calculate():
    try:
        payload = request.get_json(force=True)
        payroll_input = _parse_payload(payload)
        result = calculate_payroll(payroll_input, calendar_provider)
        return jsonify(result)
    except CalculationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - last line of defense for the API
        app.logger.exception("Unexpected calculation error")
        return jsonify({"error": f"Не удалось выполнить расчёт: {exc}"}), 500


def _parse_payload(payload: dict) -> PayrollInput:
    gross_salary = _as_float(payload.get("grossSalary"), "зарплата до вычета")
    advance_day = _as_int(payload.get("advanceDay"), "число аванса")
    salary_day = _as_int(payload.get("salaryDay"), "число зарплаты")
    year = _as_int(payload.get("year", date.today().year), "год")

    vacations: list[VacationInput] = []
    for raw in payload.get("vacations", []):
        start = _parse_date(raw.get("start"), "дата начала отпуска")
        end = _parse_date(raw.get("end"), "дата окончания отпуска")
        vacations.append(VacationInput(start=start, end=end))

    sick_leaves: list[SickLeaveInput] = []
    for raw in payload.get("sickLeaves", []):
        start = _parse_date(raw.get("start"), "дата начала больничного")
        end = _parse_date(raw.get("end"), "дата окончания больничного")
        sick_leaves.append(SickLeaveInput(start=start, end=end))

    bonuses: list[BonusInput] = []
    for raw in payload.get("bonuses", []):
        bonus_date = _parse_date(raw.get("date"), "дата премии")
        amount = _as_float(raw.get("amount"), "сумма премии")
        bonuses.append(BonusInput(date=bonus_date, amount=amount))

    sick_experience_rate = _as_float(
        payload.get("sickExperienceRate", 1.0),
        "стаж для больничного",
    )
    sick_income_two_years = _optional_float(
        payload.get("sickIncomeTwoYears"),
        "доход за 2 года для больничных",
    )

    return PayrollInput(
        gross_salary=gross_salary,
        advance_day=advance_day,
        salary_day=salary_day,
        year=year,
        vacations=vacations,
        sick_leaves=sick_leaves,
        bonuses=bonuses,
        sick_experience_rate=sick_experience_rate,
        sick_income_two_years=sick_income_two_years,
    )


def _as_float(value, field_name: str) -> float:
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise CalculationError(f"Некорректное значение поля: {field_name}.") from exc


def _optional_float(value, field_name: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return _as_float(value, field_name)


def _as_int(value, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CalculationError(f"Некорректное значение поля: {field_name}.") from exc


def _parse_date(value, field_name: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise CalculationError(f"Некорректное значение поля: {field_name}.") from exc


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
