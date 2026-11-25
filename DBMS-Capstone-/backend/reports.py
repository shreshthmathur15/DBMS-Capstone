"""
Phase 3: Query & Report Development + Index Execution Plan Analyzer.
Provides the three mandatory analytical reports and demonstrable Before/After
query execution plan (`EXPLAIN QUERY PLAN`) improvements.
"""

from __future__ import annotations
import sqlite3
import time
from typing import Any, Dict, List, Optional


def get_monthly_attendance_summary(
    conn: sqlite3.Connection,
    pay_month: Optional[int] = None,
    pay_year: Optional[int] = None,
    emp_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Phase 3 — Report 1: Monthly Attendance Summary.
    Returns attendance summary per employee for the requested month/year.
    """
    query = "SELECT * FROM v_monthly_attendance_summary WHERE 1=1"
    params: List[Any] = []
    if pay_year is not None:
        query += " AND att_year = ?"
        params.append(int(pay_year))
    if pay_month is not None:
        query += " AND att_month = ?"
        params.append(int(pay_month))
    if emp_id is not None:
        query += " AND emp_id = ?"
        params.append(int(emp_id))
    query += " ORDER BY att_year DESC, att_month DESC, emp_id ASC"
    cur = conn.cursor()
    cur.execute(query, params)
    return [dict(r) for r in cur.fetchall()]


def get_salary_slips(
    conn: sqlite3.Connection,
    pay_month: Optional[int] = None,
    pay_year: Optional[int] = None,
    emp_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Phase 3 — Report 2: Itemized Employee Salary Slip.
    Returns itemized monthly salary slips joining Employee, Department, Salary_Structure, and Payroll.
    """
    query = "SELECT * FROM v_employee_salary_slip WHERE 1=1"
    params: List[Any] = []
    if pay_year is not None:
        query += " AND pay_year = ?"
        params.append(int(pay_year))
    if pay_month is not None:
        query += " AND pay_month = ?"
        params.append(int(pay_month))
    if emp_id is not None:
        query += " AND emp_id = ?"
        params.append(int(emp_id))
    query += " ORDER BY pay_year DESC, pay_month DESC, emp_id ASC"
    cur = conn.cursor()
    cur.execute(query, params)
    return [dict(r) for r in cur.fetchall()]


def get_late_marks_report(
    conn: sqlite3.Connection,
    pay_month: Optional[int] = None,
    pay_year: Optional[int] = None,
    emp_id: Optional[int] = None,
    only_late: bool = False,
) -> List[Dict[str, Any]]:
    """
    Phase 3 — Report 3: Late-Marks & Punctuality Report.
    Returns employee late-arrival statistics, total/max late minutes, and LOP penalty days.
    """
    query = "SELECT * FROM v_late_marks_report WHERE 1=1"
    params: List[Any] = []
    if pay_year is not None:
        query += " AND att_year = ?"
        params.append(int(pay_year))
    if pay_month is not None:
        query += " AND att_month = ?"
        params.append(int(pay_month))
    if emp_id is not None:
        query += " AND emp_id = ?"
        params.append(int(emp_id))
    if only_late:
        query += " AND late_days_count > 0"
    query += " ORDER BY late_days_count DESC, total_late_minutes DESC, emp_id ASC"
    cur = conn.cursor()
    cur.execute(query, params)
    return [dict(r) for r in cur.fetchall()]


def benchmark_index_execution_plan(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Demonstrates the Phase 3 Query Execution Plan improvement (BEFORE vs AFTER indexing)
    across the Late-Marks Report query and the Salary Slip Report query.
    """
    cur = conn.cursor()

    # Representative range & join query for Report 3 (Late-Marks Report in Oct 2026)
    late_report_sql = """
    SELECT
        e.emp_id,
        e.emp_code,
        e.first_name || ' ' || e.last_name AS employee_name,
        COUNT(a.attendance_id) AS late_days_count,
        SUM(a.late_minutes) AS total_late_minutes,
        MAX(a.check_in) AS latest_check_in
    FROM Attendance a
    JOIN Employee e ON a.emp_id = e.emp_id
    WHERE a.att_date BETWEEN '2026-10-01' AND '2026-10-31'
      AND a.is_late = 1
    GROUP BY e.emp_id, e.emp_code, e.first_name, e.last_name
    ORDER BY late_days_count DESC
    """

    # Representative query for Report 2 (Monthly Salary Slip Report by period)
    salary_slip_sql = """
    SELECT
        p.payroll_id, e.emp_code, e.first_name || ' ' || e.last_name AS employee_name,
        p.gross_salary, p.total_deductions, p.net_salary
    FROM Payroll p
    JOIN Employee e ON p.emp_id = e.emp_id
    WHERE p.pay_year = 2026 AND p.pay_month = 10
    ORDER BY p.emp_id ASC
    """

    # Step 1: Drop secondary report indexes to measure BEFORE state
    cur.execute("DROP INDEX IF EXISTS idx_attendance_emp_date_late;")
    cur.execute("DROP INDEX IF EXISTS idx_attendance_date_late_emp;")
    cur.execute("DROP INDEX IF EXISTS idx_payroll_period_emp;")
    cur.execute("DROP INDEX IF EXISTS idx_leave_emp_status_dates;")

    cur.execute(f"EXPLAIN QUERY PLAN {late_report_sql}")
    before_late_plan = [dict(r)["detail"] for r in cur.fetchall()]

    cur.execute(f"EXPLAIN QUERY PLAN {salary_slip_sql}")
    before_slip_plan = [dict(r)["detail"] for r in cur.fetchall()]

    # Measure 300 iterations BEFORE indexes
    t0 = time.perf_counter()
    for _ in range(300):
        cur.execute(late_report_sql).fetchall()
    before_late_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    # Step 2: Recreate Phase 3 Performance Indexes
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attendance_emp_date_late
            ON Attendance (emp_id, att_date, is_late, att_status, late_minutes, work_hours);
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attendance_date_late_emp
            ON Attendance (is_late, att_date, emp_id, late_minutes, check_in);
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_payroll_period_emp
            ON Payroll (pay_year, pay_month, emp_id);
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_leave_emp_status_dates
            ON Leave_Request (emp_id, status, start_date, end_date);
        """
    )
    conn.commit()

    cur.execute(f"EXPLAIN QUERY PLAN {late_report_sql}")
    after_late_plan = [dict(r)["detail"] for r in cur.fetchall()]

    cur.execute(f"EXPLAIN QUERY PLAN {salary_slip_sql}")
    after_slip_plan = [dict(r)["detail"] for r in cur.fetchall()]

    # Measure 300 iterations AFTER indexes
    t1 = time.perf_counter()
    for _ in range(300):
        cur.execute(late_report_sql).fetchall()
    after_late_ms = round((time.perf_counter() - t1) * 1000.0, 3)

    speedup_pct = (
        round(((before_late_ms - after_late_ms) / before_late_ms) * 100.0, 1)
        if before_late_ms > 0
        else 0.0
    )

    return {
        "late_marks_report": {
            "query": late_report_sql.strip(),
            "before_index_plan": before_late_plan,
            "after_index_plan": after_late_plan,
            "before_200_runs_ms": before_late_ms,
            "after_200_runs_ms": after_late_ms,
            "improvement_pct": speedup_pct,
            "index_used": "idx_attendance_date_late_emp (is_late, att_date, emp_id, late_minutes, check_in)",
        },
        "salary_slip_report": {
            "query": salary_slip_sql.strip(),
            "before_index_plan": before_slip_plan,
            "after_index_plan": after_slip_plan,
            "index_used": "idx_payroll_period_emp (pay_year, pay_month, emp_id)",
        },
    }
