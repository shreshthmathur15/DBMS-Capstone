"""
Phase 2: Procedural Implementation — Stored Functions & Stored Procedures.

Registers native SQL scalar functions on SQLite connections:
  - fn_calculate_income_tax(annual_gross) -> monthly TDS deduction
  - fn_calculate_gross_salary(basic_pay, hra_pct, da_pct, special_allowance) -> full monthly gross
  - fn_calculate_late_penalty_days(late_count) -> LOP penalty days (every 3 late marks = 0.5 day LOP)

And provides the database stored procedures:
  - sp_process_monthly_payroll(conn, emp_id, pay_month, pay_year)
  - sp_process_bulk_payroll(conn, pay_month, pay_year)
"""

from __future__ import annotations
import sqlite3
from typing import Dict, Any, List


def fn_calculate_income_tax(annual_gross: float) -> float:
    """
    Stored Function: fn_calculate_income_tax(p_annual_gross)
    Calculates monthly Income Tax (TDS) using progressive tax slabs:
      - Standard Deduction: Rs. 75,000
      - 0 to 4,00,000       : 0%
      - 4,00,001 to 8,00,000: 5%
      - 8,00,001 to 12,00,000: 10%
      - 12,00,001 to 16,00,000: 15%
      - Above 16,00,000     : 20%
      - Section 87A Rebate: 0 tax if taxable income <= Rs. 7,00,000
      - Plus 4% Health & Education Cess, divided by 12 for monthly TDS.
    """
    if annual_gross is None or annual_gross <= 0:
        return 0.0

    taxable = max(0.0, float(annual_gross) - 75000.0)
    if taxable <= 700000.0:
        return 0.0

    annual_tax = 0.0
    if taxable <= 400000.0:
        annual_tax = 0.0
    elif taxable <= 800000.0:
        annual_tax = (taxable - 400000.0) * 0.05
    elif taxable <= 1200000.0:
        annual_tax = 20000.0 + (taxable - 800000.0) * 0.10
    elif taxable <= 1600000.0:
        annual_tax = 60000.0 + (taxable - 1200000.0) * 0.15
    else:
        annual_tax = 120000.0 + (taxable - 1600000.0) * 0.20

    # Add 4% Health & Education Cess and divide by 12 months
    monthly_tds = (annual_tax * 1.04) / 12.0
    return round(monthly_tds, 2)


def fn_calculate_gross_salary(
    basic_pay: float,
    hra_percent: float,
    da_percent: float,
    special_allowance: float,
) -> float:
    """
    Stored Function: fn_calculate_gross_salary(basic_pay, hra_percent, da_percent, special_allowance)
    Computes standard monthly gross salary from 3NF Salary_Structure components.
    """
    basic = float(basic_pay or 0.0)
    hra = basic * (float(hra_percent or 0.0) / 100.0)
    da = basic * (float(da_percent or 0.0) / 100.0)
    special = float(special_allowance or 0.0)
    return round(basic + hra + da + special, 2)


def fn_calculate_late_penalty_days(late_count: int) -> float:
    """
    Stored Function: fn_calculate_late_penalty_days(late_count)
    Disciplinary rule: Every 3 late arrivals in a calendar month incur 0.5 day Loss of Pay (LOP).
    """
    if not late_count or int(late_count) < 3:
        return 0.0
    return round((int(late_count) // 3) * 0.5, 1)


def register_sql_functions(conn: sqlite3.Connection) -> None:
    """Registers the Phase 2 stored functions directly into the SQLite SQL engine."""
    conn.create_function("fn_calculate_income_tax", 1, fn_calculate_income_tax)
    conn.create_function("fn_calculate_gross_salary", 4, fn_calculate_gross_salary)
    conn.create_function("fn_calculate_late_penalty_days", 1, fn_calculate_late_penalty_days)


def sp_process_monthly_payroll(
    conn: sqlite3.Connection,
    emp_id: int,
    pay_month: int,
    pay_year: int,
    payment_status: str = "PROCESSED",
) -> Dict[str, Any]:
    """
    Stored Procedure: sp_process_monthly_payroll(p_emp_id, p_month, p_year)
    Executes the complete payroll calculation for one employee for a given (pay_month, pay_year)
    using the Phase 1 3NF tables:
      1. Reads Salary_Structure for the employee.
      2. Aggregates Attendance for (pay_month, pay_year): working_days, present_days, late_count.
      3. Distinguishes paid vs unpaid approved leaves via Leave_Request + Leave_Type.
      4. Computes late_penalty_days via SQL function fn_calculate_late_penalty_days(late_count).
      5. Computes total LOP days (unpaid absences + unpaid leaves + late_penalty_days).
      6. Prorates Basic, HRA, DA, Special Allowance and computes PF, Professional Tax,
         and monthly Income Tax (TDS) via SQL function fn_calculate_income_tax(annual_gross).
      7. Upserts the record into the Payroll table.
    """
    if not (1 <= int(pay_month) <= 12):
        raise ValueError("INVALID_PAY_PERIOD: pay_month must be between 1 and 12.")

    cur = conn.cursor()

    # 1. Fetch Employee & Salary_Structure using SQL function fn_calculate_gross_salary
    cur.execute(
        """
        SELECT
            e.emp_id,
            e.emp_code,
            e.first_name || ' ' || e.last_name AS employee_name,
            e.status,
            ss.basic_pay,
            ss.hra_percent,
            ss.da_percent,
            ss.special_allowance,
            ss.pf_percent,
            ss.professional_tax,
            fn_calculate_gross_salary(ss.basic_pay, ss.hra_percent, ss.da_percent, ss.special_allowance) AS full_gross
        FROM Employee e
        JOIN Salary_Structure ss ON e.emp_id = ss.emp_id
        WHERE e.emp_id = ?
        """,
        (emp_id,),
    )
    emp_row = cur.fetchone()
    if not emp_row:
        raise ValueError(f"EMPLOYEE_NOT_FOUND: No employee/salary structure found for emp_id={emp_id}.")

    basic_pay = float(emp_row["basic_pay"])
    hra_pct = float(emp_row["hra_percent"])
    da_pct = float(emp_row["da_percent"])
    special_allowance = float(emp_row["special_allowance"])
    pf_pct = float(emp_row["pf_percent"])
    prof_tax = float(emp_row["professional_tax"])
    full_gross = float(emp_row["full_gross"])

    period_prefix = f"{int(pay_year):04d}-{int(pay_month):02d}"

    # 2. Aggregate Attendance & Paid Leave metrics for the month
    cur.execute(
        """
        SELECT
            COUNT(a.attendance_id) AS working_days,
            COALESCE(SUM(
                CASE
                    WHEN a.att_status = 'PRESENT'  THEN 1.0
                    WHEN a.att_status = 'HALF_DAY' THEN 0.5
                    ELSE 0.0
                END
            ), 0.0) AS present_days,
            COALESCE(SUM(
                CASE
                    WHEN a.att_status = 'ON_LEAVE' AND EXISTS (
                        SELECT 1
                        FROM Leave_Request lr
                        JOIN Leave_Type lt ON lr.leave_type_id = lt.leave_type_id
                        WHERE lr.emp_id = a.emp_id
                          AND lr.status = 'APPROVED'
                          AND lt.is_paid = 1
                          AND date(a.att_date) BETWEEN date(lr.start_date) AND date(lr.end_date)
                    ) THEN 1.0
                    ELSE 0.0
                END
            ), 0.0) AS paid_leave_days,
            COALESCE(SUM(CASE WHEN a.is_late = 1 THEN 1 ELSE 0 END), 0) AS late_count
        FROM Attendance a
        WHERE a.emp_id = ?
          AND strftime('%Y-%m', a.att_date) = ?
        """,
        (emp_id, period_prefix),
    )
    att_row = cur.fetchone()
    working_days = int(att_row["working_days"] or 0)
    if working_days == 0:
        raise ValueError(
            f"NO_ATTENDANCE_DATA: Cannot process payroll for emp_id={emp_id} in {period_prefix} with 0 attendance rows."
        )

    present_days = round(float(att_row["present_days"]), 1)
    paid_leave_days = round(float(att_row["paid_leave_days"]), 1)
    late_count = int(att_row["late_count"])

    # 3. Call SQL Function fn_calculate_late_penalty_days
    cur.execute("SELECT fn_calculate_late_penalty_days(?) AS penalty", (late_count,))
    late_penalty_days = float(cur.fetchone()["penalty"])

    # 4. Calculate total Loss of Pay (LOP) days (unpaid absences + half-day unpaid portions + late penalty)
    unpaid_absence_days = max(0.0, round(working_days - (present_days + paid_leave_days), 1))
    total_lop_days = min(float(working_days), round(unpaid_absence_days + late_penalty_days, 1))

    # 5. Compute LOP deduction & prorated earnings
    lop_deduction = round((full_gross / working_days) * total_lop_days, 2)
    payable_ratio = max(0.0, (working_days - total_lop_days) / float(working_days))

    basic_earned = round(basic_pay * payable_ratio, 2)
    hra_earned = round((basic_pay * hra_pct / 100.0) * payable_ratio, 2)
    da_earned = round((basic_pay * da_pct / 100.0) * payable_ratio, 2)
    special_earned = round(special_allowance * payable_ratio, 2)
    gross_earned = round(basic_earned + hra_earned + da_earned + special_earned, 2)

    # 6. Statutory Deductions (PF on earned basic, Professional Tax, Income Tax via SQL function)
    pf_deduction = round(basic_earned * (pf_pct / 100.0), 2)
    cur.execute("SELECT fn_calculate_income_tax(?) AS monthly_tds", (gross_earned * 12.0,))
    income_tax_deduction = float(cur.fetchone()["monthly_tds"])

    # Total deductions reported on slip (PF + PT + TDS + LOP deduction from contracted gross)
    total_deductions = round(pf_deduction + prof_tax + income_tax_deduction + lop_deduction, 2)
    net_salary = max(0.0, round(gross_earned - (pf_deduction + prof_tax + income_tax_deduction), 2))

    # 7. Upsert into Payroll table
    cur.execute(
        """
        INSERT INTO Payroll (
            emp_id, pay_month, pay_year,
            working_days, present_days, paid_leave_days, lop_days,
            late_count, late_penalty_days,
            basic_earned, hra_earned, da_earned, special_allowance_earned, gross_salary,
            pf_deduction, professional_tax, income_tax_deduction, lop_deduction,
            total_deductions, net_salary, payment_status, processed_at
        ) VALUES (
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, CURRENT_TIMESTAMP
        )
        ON CONFLICT(emp_id, pay_month, pay_year) DO UPDATE SET
            working_days             = excluded.working_days,
            present_days             = excluded.present_days,
            paid_leave_days          = excluded.paid_leave_days,
            lop_days                 = excluded.lop_days,
            late_count               = excluded.late_count,
            late_penalty_days        = excluded.late_penalty_days,
            basic_earned             = excluded.basic_earned,
            hra_earned               = excluded.hra_earned,
            da_earned                = excluded.da_earned,
            special_allowance_earned = excluded.special_allowance_earned,
            gross_salary             = excluded.gross_salary,
            pf_deduction             = excluded.pf_deduction,
            professional_tax         = excluded.professional_tax,
            income_tax_deduction     = excluded.income_tax_deduction,
            lop_deduction            = excluded.lop_deduction,
            total_deductions         = excluded.total_deductions,
            net_salary               = excluded.net_salary,
            payment_status           = excluded.payment_status,
            processed_at             = CURRENT_TIMESTAMP
        """,
        (
            emp_id,
            int(pay_month),
            int(pay_year),
            working_days,
            present_days,
            paid_leave_days,
            total_lop_days,
            late_count,
            late_penalty_days,
            basic_earned,
            hra_earned,
            da_earned,
            special_earned,
            gross_earned,
            pf_deduction,
            prof_tax,
            income_tax_deduction,
            lop_deduction,
            total_deductions,
            net_salary,
            payment_status,
        ),
    )

    cur.execute(
        "SELECT * FROM Payroll WHERE emp_id = ? AND pay_month = ? AND pay_year = ?",
        (emp_id, int(pay_month), int(pay_year)),
    )
    return dict(cur.fetchone())


def sp_process_bulk_payroll(
    conn: sqlite3.Connection,
    pay_month: int,
    pay_year: int,
    payment_status: str = "PAID",
) -> List[Dict[str, Any]]:
    """
    Stored Procedure: sp_process_bulk_payroll(p_month, p_year)
    Processes monthly payroll for all ACTIVE employees for the specified month and year.
    """
    cur = conn.cursor()
    cur.execute("SELECT emp_id FROM Employee WHERE status = 'ACTIVE' ORDER BY emp_id")
    emp_ids = [row["emp_id"] for row in cur.fetchall()]
    results = []
    for emp_id in emp_ids:
        res = sp_process_monthly_payroll(conn, emp_id, pay_month, pay_year, payment_status=payment_status)
        results.append(res)
    return results
