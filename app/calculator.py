from __future__ import annotations

import calendar as pycalendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol


WORKING_CODES = {"0", "2", "4"}
HOLIDAY_CODES = {"8"}
AVERAGE_MONTH_DAYS = 29.3

CONTRIBUTION_BASE_LIMITS = {
    2022: 1_032_000.0,
    2023: 1_917_000.0,
    2024: 2_225_000.0,
    2025: 2_759_000.0,
    2026: 2_979_000.0,
}

MROT_BY_YEAR = {
    2023: 16_242.0,
    2024: 19_242.0,
    2025: 22_440.0,
    2026: 27_093.0,
}

MONTH_NAMES = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]

TAX_BRACKETS = [
    (0.0, 2_400_000.0, 0.13),
    (2_400_000.0, 5_000_000.0, 0.15),
    (5_000_000.0, 20_000_000.0, 0.18),
    (20_000_000.0, 50_000_000.0, 0.20),
    (50_000_000.0, float("inf"), 0.22),
]


class CalculationError(ValueError):
    pass


class CalendarProvider(Protocol):
    def get_year(self, year: int) -> "YearCalendar":
        ...


@dataclass(frozen=True)
class YearCalendar:
    year: int
    codes: dict[date, str]
    source: str
    fallback: bool = False

    def code(self, day: date) -> str:
        try:
            return self.codes[day]
        except KeyError as exc:
            raise CalculationError(f"Нет календарных данных для {day.isoformat()}") from exc

    def is_working(self, day: date) -> bool:
        return self.code(day) in WORKING_CODES

    def is_holiday(self, day: date) -> bool:
        return self.code(day) in HOLIDAY_CODES


@dataclass(frozen=True)
class VacationInput:
    start: date
    end: date


@dataclass(frozen=True)
class SickLeaveInput:
    start: date
    end: date


@dataclass(frozen=True)
class BonusInput:
    date: date
    amount: float


@dataclass(frozen=True)
class PayrollInput:
    gross_salary: float
    advance_day: int
    salary_day: int
    year: int
    vacations: list[VacationInput] = field(default_factory=list)
    sick_leaves: list[SickLeaveInput] = field(default_factory=list)
    bonuses: list[BonusInput] = field(default_factory=list)
    sick_experience_rate: float = 1.0
    sick_income_two_years: float | None = None


@dataclass
class MonthAccrual:
    year: int
    month: int
    total_work_days: int
    worked_first_half: int
    worked_second_half: int
    vacation_work_first_half: int
    vacation_work_second_half: int
    sick_work_first_half: int
    sick_work_second_half: int
    advance_gross: float
    salary_remainder_gross: float

    @property
    def worked_days(self) -> int:
        return self.worked_first_half + self.worked_second_half

    @property
    def vacation_work_days(self) -> int:
        return self.vacation_work_first_half + self.vacation_work_second_half

    @property
    def sick_work_days(self) -> int:
        return self.sick_work_first_half + self.sick_work_second_half


@dataclass
class PaymentEvent:
    date: date
    kind: str
    label: str
    gross: float
    tax: float = 0.0
    net: float = 0.0
    tax_rates: list[float] = field(default_factory=list)
    source_year: int | None = None
    source_month: int | None = None
    payload: dict = field(default_factory=dict)


class CalendarAccess:
    def __init__(self, provider: CalendarProvider) -> None:
        self.provider = provider
        self.used: dict[int, YearCalendar] = {}

    def get_year(self, year: int) -> YearCalendar:
        calendar = self.provider.get_year(year)
        self.used[year] = calendar
        return calendar

    def is_working(self, day: date) -> bool:
        return self.get_year(day.year).is_working(day)

    def is_holiday(self, day: date) -> bool:
        return self.get_year(day.year).is_holiday(day)


def calculate_payroll(data: PayrollInput, provider: CalendarProvider) -> dict:
    _validate_input(data)
    calendars = CalendarAccess(provider)
    events: list[PaymentEvent] = []
    outside_events: list[PaymentEvent] = []
    monthly_accruals: dict[tuple[int, int], MonthAccrual] = {}

    def get_accrual(year: int, month: int) -> MonthAccrual:
        key = (year, month)
        if key not in monthly_accruals:
            monthly_accruals[key] = _calculate_month_accrual(
                year=year,
                month=month,
                gross_salary=data.gross_salary,
                vacations=data.vacations,
                sick_leaves=data.sick_leaves,
                calendars=calendars,
            )
        return monthly_accruals[key]

    for source_month in range(1, 13):
        current_accrual = get_accrual(data.year, source_month)
        advance_date = _payment_date(data.year, source_month, data.advance_day, calendars)
        _append_event(
            events,
            outside_events,
            data.year,
            PaymentEvent(
                date=advance_date,
                kind="advance",
                label=f"Аванс за {MONTH_NAMES[source_month - 1].lower()}",
                gross=current_accrual.advance_gross,
                source_year=data.year,
                source_month=source_month,
                payload={
                    "source_month_name": MONTH_NAMES[source_month - 1],
                    "worked_days": current_accrual.worked_first_half,
                    "vacation_work_days": current_accrual.vacation_work_first_half,
                    "sick_work_days": current_accrual.sick_work_first_half,
                    "total_work_days": current_accrual.total_work_days,
                },
            ),
        )

        if source_month == 12:
            pay_year, pay_month = data.year + 1, 1
        else:
            pay_year, pay_month = data.year, source_month + 1

        salary_date = _payment_date(pay_year, pay_month, data.salary_day, calendars)
        _append_event(
            events,
            outside_events,
            data.year,
            PaymentEvent(
                date=salary_date,
                kind="salary",
                label=f"Зарплата за {MONTH_NAMES[source_month - 1].lower()} {data.year}",
                gross=current_accrual.salary_remainder_gross,
                source_year=data.year,
                source_month=source_month,
                payload={
                    "source_month_name": MONTH_NAMES[source_month - 1],
                    "worked_days": current_accrual.worked_second_half,
                    "vacation_work_days": current_accrual.vacation_work_second_half,
                    "sick_work_days": current_accrual.sick_work_second_half,
                },
            ),
        )

    for vacation in data.vacations:
        paid_days = _vacation_paid_days(vacation, calendars)
        if paid_days <= 0:
            continue

        pay_date = _adjust_to_previous_working_day(vacation.start - timedelta(days=3), calendars)
        avg_daily = _vacation_average_daily(vacation.start, data.gross_salary, data.bonuses)
        _append_event(
            events,
            outside_events,
            data.year,
            PaymentEvent(
                date=pay_date,
                kind="vacation",
                label=f"Отпускные {vacation.start.strftime('%d.%m')}-{vacation.end.strftime('%d.%m')}",
                gross=avg_daily * paid_days,
                payload={
                    "start": vacation.start.isoformat(),
                    "end": vacation.end.isoformat(),
                    "paid_days": paid_days,
                    "average_daily": avg_daily,
                },
            ),
        )

    for sick_leave in data.sick_leaves:
        paid_days = _sick_paid_days(sick_leave)
        if paid_days <= 0:
            continue

        pay_date = _add_working_days(sick_leave.end, 10, calendars)
        average_daily = _sick_average_daily(
            sick_leave.start,
            data.gross_salary,
            data.sick_income_two_years,
        )
        _append_event(
            events,
            outside_events,
            data.year,
            PaymentEvent(
                date=pay_date,
                kind="sick",
                label=f"Больничный {sick_leave.start.strftime('%d.%m')}-{sick_leave.end.strftime('%d.%m')}",
                gross=average_daily * data.sick_experience_rate * paid_days,
                payload={
                    "start": sick_leave.start.isoformat(),
                    "end": sick_leave.end.isoformat(),
                    "paid_days": paid_days,
                    "average_daily": average_daily,
                    "experience_rate": data.sick_experience_rate,
                    "employer_days": min(3, paid_days),
                    "sfr_days": max(0, paid_days - 3),
                },
            ),
        )

    for bonus in data.bonuses:
        pay_date = _adjust_to_previous_working_day(bonus.date, calendars)
        _append_event(
            events,
            outside_events,
            data.year,
            PaymentEvent(
                date=pay_date,
                kind="bonus",
                label="Премия",
                gross=bonus.amount,
                payload={"planned_date": bonus.date.isoformat()},
            ),
        )

    events.sort(key=lambda event: (event.date, _kind_order(event.kind), event.label))
    _apply_progressive_tax(events)

    rows = _build_month_rows(data.year, events, monthly_accruals)
    totals = _build_totals(rows)
    warnings = _build_warnings(data, outside_events, calendars.used)

    return {
        "year": data.year,
        "rows": rows,
        "totals": totals,
        "events": [_event_to_dict(event) for event in events],
        "warnings": warnings,
        "calendar_sources": {
            str(year): {
                "source": calendar.source,
                "fallback": calendar.fallback,
            }
            for year, calendar in sorted(calendars.used.items())
        },
        "tax_brackets": [
            {"from": lower, "to": None if upper == float("inf") else upper, "rate": rate}
            for lower, upper, rate in TAX_BRACKETS
        ],
        "assumptions": [
            "Аванс считается за рабочие дни с 1 по 15 число пропорционально окладу и рабочим дням месяца.",
            "Дата выплаты сдвигается на предыдущий рабочий день, если попадает на выходной или праздник.",
            "Декабрь прошлого года не включается в январь выбранного года.",
            "Отпускные рассчитаны упрощенно: средний дневной заработок = доход за 12 месяцев / 12 / 29,3.",
            "Больничные рассчитаны как собственная болезнь или травма: доход за 2 предыдущих года / 730 * коэффициент стажа * календарные дни больничного.",
        ],
    }


def _validate_input(data: PayrollInput) -> None:
    if data.gross_salary <= 0:
        raise CalculationError("Зарплата до вычета должна быть больше нуля.")
    if not 16 <= data.advance_day <= 31:
        raise CalculationError("Число аванса должно быть с 16 по 31.")
    if not 1 <= data.salary_day <= 15:
        raise CalculationError("Число зарплаты должно быть с 1 по 15.")
    if not 2000 <= data.year <= 2100:
        raise CalculationError("Год должен быть в диапазоне 2000-2100.")

    for vacation in data.vacations:
        if vacation.end < vacation.start:
            raise CalculationError("Дата окончания отпуска не может быть раньше даты начала.")

    if data.sick_experience_rate not in {0.6, 0.8, 1.0}:
        raise CalculationError("Некорректный коэффициент стажа для больничных.")
    if data.sick_income_two_years is not None and data.sick_income_two_years < 0:
        raise CalculationError("Доход за 2 года для больничных не может быть отрицательным.")

    for sick_leave in data.sick_leaves:
        if sick_leave.end < sick_leave.start:
            raise CalculationError("Дата окончания больничного не может быть раньше даты начала.")

    for bonus in data.bonuses:
        if bonus.amount <= 0:
            raise CalculationError("Сумма премии должна быть больше нуля.")


def _append_event(
    events: list[PaymentEvent],
    outside_events: list[PaymentEvent],
    target_year: int,
    event: PaymentEvent,
) -> None:
    if event.gross <= 0.004:
        return
    if event.date.year == target_year:
        events.append(event)
    else:
        outside_events.append(event)


def _calculate_month_accrual(
    year: int,
    month: int,
    gross_salary: float,
    vacations: list[VacationInput],
    sick_leaves: list[SickLeaveInput],
    calendars: CalendarAccess,
) -> MonthAccrual:
    first_day = date(year, month, 1)
    last_day = date(year, month, pycalendar.monthrange(year, month)[1])
    total_work_days = 0
    worked_first_half = 0
    worked_second_half = 0
    vacation_work_first_half = 0
    vacation_work_second_half = 0
    sick_work_first_half = 0
    sick_work_second_half = 0

    for day in _daterange(first_day, last_day):
        if not calendars.is_working(day):
            continue
        total_work_days += 1
        in_vacation = _is_in_vacation(day, vacations)
        in_sick_leave = _is_in_sick_leave(day, sick_leaves)
        if day.day <= 15:
            if in_sick_leave:
                sick_work_first_half += 1
            elif in_vacation:
                vacation_work_first_half += 1
            else:
                worked_first_half += 1
        else:
            if in_sick_leave:
                sick_work_second_half += 1
            elif in_vacation:
                vacation_work_second_half += 1
            else:
                worked_second_half += 1

    daily_salary = gross_salary / total_work_days if total_work_days else 0.0
    return MonthAccrual(
        year=year,
        month=month,
        total_work_days=total_work_days,
        worked_first_half=worked_first_half,
        worked_second_half=worked_second_half,
        vacation_work_first_half=vacation_work_first_half,
        vacation_work_second_half=vacation_work_second_half,
        sick_work_first_half=sick_work_first_half,
        sick_work_second_half=sick_work_second_half,
        advance_gross=daily_salary * worked_first_half,
        salary_remainder_gross=daily_salary * worked_second_half,
    )


def _payment_date(year: int, month: int, preferred_day: int, calendars: CalendarAccess) -> date:
    day = min(preferred_day, pycalendar.monthrange(year, month)[1])
    return _adjust_to_previous_working_day(date(year, month, day), calendars)


def _adjust_to_previous_working_day(day: date, calendars: CalendarAccess) -> date:
    current = day
    for _ in range(14):
        if calendars.is_working(current):
            return current
        current -= timedelta(days=1)
    raise CalculationError(f"Не удалось найти рабочий день перед {day.isoformat()}.")


def _add_working_days(day: date, count: int, calendars: CalendarAccess) -> date:
    current = day
    added = 0
    while added < count:
        current += timedelta(days=1)
        if calendars.is_working(current):
            added += 1
    return current


def _apply_progressive_tax(events: list[PaymentEvent]) -> None:
    cumulative_gross = 0.0
    index = 0
    while index < len(events):
        group_date = events[index].date
        group: list[PaymentEvent] = []
        while index < len(events) and events[index].date == group_date:
            group.append(events[index])
            index += 1

        group_gross = sum(event.gross for event in group)
        if group_gross <= 0:
            continue

        tax_before = _round_rubles(_compute_cumulative_tax(cumulative_gross))
        tax_after = _round_rubles(_compute_cumulative_tax(cumulative_gross + group_gross))
        group_tax = tax_after - tax_before
        group_tax_rates = _tax_rates_for_range(cumulative_gross, cumulative_gross + group_gross)

        allocated = 0.0
        for position, event in enumerate(group):
            if position == len(group) - 1:
                event.tax = _round_money(group_tax - allocated)
            else:
                event.tax = _round_money(group_tax * event.gross / group_gross)
                allocated += event.tax
            event.net = event.gross - event.tax
            event.tax_rates = group_tax_rates

        cumulative_gross += group_gross


def _compute_cumulative_tax(gross: float) -> float:
    tax = 0.0
    for lower, upper, rate in TAX_BRACKETS:
        if gross <= lower:
            break
        tax += (min(gross, upper) - lower) * rate
    return tax


def _tax_rates_for_range(start_gross: float, end_gross: float) -> list[float]:
    rates: list[float] = []
    for lower, upper, rate in TAX_BRACKETS:
        if end_gross > lower and start_gross < upper:
            rates.append(rate)
    return rates


def _build_month_rows(
    year: int,
    events: list[PaymentEvent],
    accruals: dict[tuple[int, int], MonthAccrual],
) -> list[dict]:
    events_by_month: dict[int, list[PaymentEvent]] = defaultdict(list)
    for event in events:
        events_by_month[event.date.month].append(event)

    rows: list[dict] = []
    cumulative = 0.0
    for month in range(1, 13):
        month_events = sorted(
            events_by_month.get(month, []),
            key=lambda event: (event.date, _kind_order(event.kind), event.label),
        )
        gross_total = sum(event.gross for event in month_events)
        tax_total = sum(event.tax for event in month_events)
        net_total = sum(event.net for event in month_events)
        cumulative += gross_total
        current_accrual = accruals.get((year, month))

        row = {
            "month": month,
            "month_name": MONTH_NAMES[month - 1],
            "events": [_event_to_dict(event) for event in month_events],
            "advance": _kind_summary(month_events, "advance"),
            "salary": _kind_summary(month_events, "salary"),
            "vacation": _kind_summary(month_events, "vacation"),
            "sick": _kind_summary(month_events, "sick"),
            "bonus": _kind_summary(month_events, "bonus"),
            "gross_total": _round_money(gross_total),
            "tax_total": _round_money(tax_total),
            "net_total": _round_money(net_total),
            "cumulative_gross": _round_money(cumulative),
            "tax_rate_label": _tax_rate_label(_event_tax_rates(month_events)),
            "effective_tax_rate": _effective_rate(tax_total, gross_total),
        }
        if current_accrual:
            row["work"] = {
                "total_work_days": current_accrual.total_work_days,
                "worked_days": current_accrual.worked_days,
                "vacation_work_days": current_accrual.vacation_work_days,
                "sick_work_days": current_accrual.sick_work_days,
                "worked_first_half": current_accrual.worked_first_half,
                "worked_second_half": current_accrual.worked_second_half,
            }
        rows.append(row)

    return rows


def _kind_summary(events: list[PaymentEvent], kind: str) -> dict:
    kind_events = [event for event in events if event.kind == kind]
    return {
        "gross": _round_money(sum(event.gross for event in kind_events)),
        "tax": _round_money(sum(event.tax for event in kind_events)),
        "net": _round_money(sum(event.net for event in kind_events)),
        "dates": sorted({event.date.isoformat() for event in kind_events}),
        "items": [_event_to_dict(event) for event in kind_events],
        "tax_rate_label": _tax_rate_label(_event_tax_rates(kind_events)),
        "effective_tax_rate": _effective_rate(
            sum(event.tax for event in kind_events),
            sum(event.gross for event in kind_events),
        ),
    }


def _build_totals(rows: list[dict]) -> dict:
    gross = sum(row["gross_total"] for row in rows)
    tax = sum(row["tax_total"] for row in rows)
    net = sum(row["net_total"] for row in rows)
    return {
        "gross": _round_money(gross),
        "tax": _round_money(tax),
        "net": _round_money(net),
        "average_net": _round_money(net / 12 if rows else 0.0),
    }


def _build_warnings(
    data: PayrollInput,
    outside_events: list[PaymentEvent],
    used_calendars: dict[int, YearCalendar],
) -> list[str]:
    warnings: list[str] = []
    if any(calendar.fallback for calendar in used_calendars.values()):
        warnings.append(
            "Не удалось получить часть данных isDayOff; для этих лет использован запасной календарь понедельник-пятница без праздников."
        )

    if _has_range_intersection(data.vacations, data.sick_leaves):
        warnings.append(
            "Есть пересечение отпуска и больничного; рабочие дни отсутствия не удваиваются, больничный имеет приоритет при уменьшении оклада."
        )

    for event in outside_events:
        warnings.append(
            f"{event.label} с датой выплаты {event.date.strftime('%d.%m.%Y')} не вошла в итоги {data.year} года."
        )

    return warnings


def _event_to_dict(event: PaymentEvent) -> dict:
    result = {
        "date": event.date.isoformat(),
        "kind": event.kind,
        "label": event.label,
        "gross": _round_money(event.gross),
        "tax": _round_money(event.tax),
        "net": _round_money(event.net),
        "tax_rate_label": _tax_rate_label(event.tax_rates),
        "effective_tax_rate": _effective_rate(event.tax, event.gross),
        "source_year": event.source_year,
        "source_month": event.source_month,
        "payload": event.payload,
    }
    return result


def _vacation_paid_days(vacation: VacationInput, calendars: CalendarAccess) -> int:
    return sum(
        1 for day in _daterange(vacation.start, vacation.end)
        if not calendars.is_holiday(day)
    )


def _sick_paid_days(sick_leave: SickLeaveInput) -> int:
    return sum(1 for _ in _daterange(sick_leave.start, sick_leave.end))


def _vacation_average_daily(
    vacation_start: date,
    gross_salary: float,
    bonuses: list[BonusInput],
) -> float:
    period_start = _add_months(date(vacation_start.year, vacation_start.month, 1), -12)
    period_end = date(vacation_start.year, vacation_start.month, 1) - timedelta(days=1)
    bonus_income = sum(
        bonus.amount
        for bonus in bonuses
        if period_start <= bonus.date <= period_end
    )
    return (gross_salary * 12 + bonus_income) / 12 / AVERAGE_MONTH_DAYS


def _sick_average_daily(
    sick_start: date,
    gross_salary: float,
    sick_income_two_years: float | None,
) -> float:
    income = sick_income_two_years
    if income is None:
        income = gross_salary * 24

    average = income / 730
    max_average = _sick_max_average_daily(sick_start.year)
    min_average = _sick_min_average_daily(sick_start.year)
    if max_average is not None:
        average = min(average, max_average)
    if min_average is not None:
        average = max(average, min_average)
    return average


def _sick_max_average_daily(year: int) -> float | None:
    previous_year = CONTRIBUTION_BASE_LIMITS.get(year - 1)
    two_years_ago = CONTRIBUTION_BASE_LIMITS.get(year - 2)
    if previous_year is None or two_years_ago is None:
        return None
    return (previous_year + two_years_ago) / 730


def _sick_min_average_daily(year: int) -> float | None:
    mrot = MROT_BY_YEAR.get(year)
    if mrot is None:
        return None
    return mrot * 24 / 730


def _add_months(day: date, months: int) -> date:
    month_index = day.year * 12 + (day.month - 1) + months
    year = month_index // 12
    month = month_index % 12 + 1
    max_day = pycalendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, max_day))


def _is_in_vacation(day: date, vacations: list[VacationInput]) -> bool:
    return any(vacation.start <= day <= vacation.end for vacation in vacations)


def _is_in_sick_leave(day: date, sick_leaves: list[SickLeaveInput]) -> bool:
    return any(sick_leave.start <= day <= sick_leave.end for sick_leave in sick_leaves)


def _has_range_intersection(
    vacations: list[VacationInput],
    sick_leaves: list[SickLeaveInput],
) -> bool:
    return any(
        vacation.start <= sick_leave.end and sick_leave.start <= vacation.end
        for vacation in vacations
        for sick_leave in sick_leaves
    )


def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _round_money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_rubles(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _tax_rate_label(rates: list[float]) -> str:
    unique_rates = sorted(set(rates))
    if not unique_rates:
        return "0%"
    return "/".join(f"{rate * 100:.0f}%" for rate in unique_rates)


def _event_tax_rates(events: list[PaymentEvent]) -> list[float]:
    rates: list[float] = []
    for event in events:
        rates.extend(event.tax_rates)
    return rates


def _effective_rate(tax: float, gross: float) -> float:
    if gross <= 0:
        return 0.0
    return float(Decimal(str(tax / gross)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _kind_order(kind: str) -> int:
    return {
        "salary": 0,
        "advance": 1,
        "vacation": 2,
        "sick": 3,
        "bonus": 4,
    }.get(kind, 10)
