from datetime import date, timedelta

from app.calculator import (
    BonusInput,
    PayrollInput,
    SickLeaveInput,
    VacationInput,
    YearCalendar,
    calculate_payroll,
)


class WeekdayProvider:
    def __init__(self):
        self.cache = {}

    def get_year(self, year):
        if year not in self.cache:
            start = date(year, 1, 1)
            days = 366 if _is_leap(year) else 365
            codes = {}
            for offset in range(days):
                day = start + timedelta(days=offset)
                codes[day] = "0" if day.weekday() < 5 else "1"
            self.cache[year] = YearCalendar(
                year=year,
                codes=codes,
                source="test weekday calendar",
            )
        return self.cache[year]


def test_january_does_not_include_previous_december_salary():
    result = calculate_payroll(
        PayrollInput(
            gross_salary=100_000,
            advance_day=25,
            salary_day=10,
            year=2026,
        ),
        WeekdayProvider(),
    )

    january = result["rows"][0]
    assert january["salary"]["gross"] == 0


def test_current_december_salary_is_included_when_paid_in_december():
    result = calculate_payroll(
        PayrollInput(
            gross_salary=100_000,
            advance_day=25,
            salary_day=10,
            year=2026,
        ),
        JanuaryHolidaysProvider(),
    )

    december = result["rows"][11]
    assert december["salary"]["gross"] > 0
    december_salary = [
        item for item in december["salary"]["items"]
        if item["source_month"] == 12
    ]
    assert december_salary
    assert december_salary[0]["date"].startswith("2026-12-")


def test_progressive_tax_crosses_first_threshold():
    result = calculate_payroll(
        PayrollInput(
            gross_salary=300_000,
            advance_day=25,
            salary_day=10,
            year=2026,
        ),
        WeekdayProvider(),
    )

    assert result["totals"]["gross"] > 2_400_000
    assert result["totals"]["tax"] > 2_400_000 * 0.13
    assert any("15%" in row["tax_rate_label"] for row in result["rows"])


def test_vacation_reduces_worked_days_and_adds_vacation_payment():
    result = calculate_payroll(
        PayrollInput(
            gross_salary=120_000,
            advance_day=25,
            salary_day=10,
            year=2026,
            vacations=[VacationInput(start=date(2026, 7, 1), end=date(2026, 7, 14))],
        ),
        WeekdayProvider(),
    )

    july = result["rows"][6]
    assert july["work"]["vacation_work_days"] > 0
    assert any(row["vacation"]["gross"] > 0 for row in result["rows"])


def test_sick_leave_reduces_worked_days_and_adds_sick_payment():
    result = calculate_payroll(
        PayrollInput(
            gross_salary=120_000,
            advance_day=25,
            salary_day=10,
            year=2026,
            sick_leaves=[SickLeaveInput(start=date(2026, 7, 1), end=date(2026, 7, 5))],
            sick_experience_rate=0.8,
            sick_income_two_years=2_400_000,
        ),
        WeekdayProvider(),
    )

    july = result["rows"][6]
    assert july["work"]["sick_work_days"] == 3
    assert any(row["sick"]["gross"] > 0 for row in result["rows"])


def test_bonus_increases_tax_base():
    base = calculate_payroll(
        PayrollInput(
            gross_salary=150_000,
            advance_day=25,
            salary_day=10,
            year=2026,
        ),
        WeekdayProvider(),
    )
    with_bonus = calculate_payroll(
        PayrollInput(
            gross_salary=150_000,
            advance_day=25,
            salary_day=10,
            year=2026,
            bonuses=[BonusInput(date=date(2026, 6, 20), amount=500_000)],
        ),
        WeekdayProvider(),
    )

    assert with_bonus["totals"]["gross"] == base["totals"]["gross"] + 500_000
    assert with_bonus["totals"]["tax"] > base["totals"]["tax"]


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


class JanuaryHolidaysProvider(WeekdayProvider):
    def get_year(self, year):
        calendar = super().get_year(year)
        if year == 2027:
            for day in range(1, 11):
                calendar.codes[date(2027, 1, day)] = "1"
        return calendar
