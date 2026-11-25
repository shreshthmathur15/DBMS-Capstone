"""
Phase 4: Security, Role-Based Access Control (RBAC) & ACID Transaction Layer.

Distinguishes:
  - HR_ADMIN : Full access to manage employees, revise salary structures, log attendance,
               approve/reject leaves, run monthly payroll, and view organization-wide reports.
  - EMPLOYEE : Strictly read-only access to their own attendance, leave, and salary/payroll
               records (plus ability to submit their own leave request). Any attempt to read
               another employee's records or mutate salary/payroll raises PermissionDeniedError.

All salary, payroll, attendance, and leave mutations execute inside explicit database
transactions using SAVEPOINT / COMMIT / ROLLBACK so partial failures never corrupt state.
"""

from __future__ import annotations
from dataclasses import dataclass
import datetime
import sqlite3
from typing import Any, Dict, List, Optional

from backend.procedures import sp_process_bulk_payroll, sp_process_monthly_payroll
from backend.reports import (
    get_late_marks_report,
    get_monthly_attendance_summary,
    get_salary_slips,
)


class PermissionDeniedError(PermissionError):
    """Raised when an actor's role violates RBAC access control policy."""


@dataclass(frozen=True)
class ActorContext:
    emp_id: int
    emp_code: str
    full_name: str
    role: str  # 'HR_ADMIN' or 'EMPLOYEE'
    dept_name: str = ""


def get_actor_by_emp_id(conn: sqlite3.Connection, emp_id: int) -> ActorContext:
    """Loads an ActorContext from the Employee table."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT e.emp_id, e.emp_code, e.first_name || ' ' || e.last_name AS full_name,
               e.role, d.dept_name
        FROM Employee e
        JOIN Department d ON e.dept_id = d.dept_id
        WHERE e.emp_id = ? AND e.status = 'ACTIVE'
        """,
        (int(emp_id),),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"AUTH_ERROR: Active employee emp_id={emp_id} not found.")
    return ActorContext(
        emp_id=int(row["emp_id"]),
        emp_code=row["emp_code"],
        full_name=row["full_name"],
        role=row["role"],
        dept_name=row["dept_name"],
    )


def require_hr_admin(actor: ActorContext, action_name: str) -> None:
    """RBAC Guard: Ensures the actor holds the HR_ADMIN role."""
    if not actor or actor.role != "HR_ADMIN":
        raise PermissionDeniedError(
            f"RBAC_ACCESS_DENIED: Actor '{actor.emp_code if actor else 'UNKNOWN'}' "
            f"(role='{actor.role if actor else 'NONE'}') is not authorized to perform '{action_name}'. "
            f"Requires role='HR_ADMIN'."
        )


def require_self_or_hr_admin(actor: ActorContext, target_emp_id: int, resource_name: str) -> None:
    """RBAC Guard: Allows HR_ADMIN full access, or EMPLOYEE access strictly to their own emp_id."""
    if not actor:
        raise PermissionDeniedError("RBAC_ACCESS_DENIED: Unauthenticated actor context.")
    if actor.role == "HR_ADMIN":
        return
    if actor.role == "EMPLOYEE" and int(actor.emp_id) == int(target_emp_id):
        return
    raise PermissionDeniedError(
        f"RBAC_ACCESS_DENIED: Employee '{actor.emp_code}' (emp_id={actor.emp_id}, role='EMPLOYEE') "
        f"attempted unauthorized access to '{resource_name}' belonging to emp_id={target_emp_id}. "
        f"Employees may only access their own records."
    )


# ============================================================================
# RBAC-Protected Read Queries (Row-Level Security Enforcement)
# ============================================================================

def rbac_get_employee_profile(
    conn: sqlite3.Connection, actor: ActorContext, target_emp_id: int
) -> Dict[str, Any]:
    """Returns employee profile & salary structure, enforcing self-or-admin RBAC."""
    require_self_or_hr_admin(actor, target_emp_id, "Employee Profile & Salary Structure")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            e.emp_id, e.emp_code, e.first_name, e.last_name,
            e.first_name || ' ' || e.last_name AS full_name,
            e.email, e.phone, e.hire_date, e.designation, e.role, e.status,
            d.dept_id, d.dept_code, d.dept_name, d.base_location,
            ss.basic_pay, ss.hra_percent, ss.da_percent, ss.special_allowance,
            ss.pf_percent, ss.professional_tax, ss.standard_check_in, ss.effective_from,
            fn_calculate_gross_salary(ss.basic_pay, ss.hra_percent, ss.da_percent, ss.special_allowance) AS contracted_gross
        FROM Employee e
        JOIN Department d ON e.dept_id = d.dept_id
        LEFT JOIN Salary_Structure ss ON e.emp_id = ss.emp_id
        WHERE e.emp_id = ?
        """,
        (int(target_emp_id),),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Employee emp_id={target_emp_id} not found.")
    return dict(row)


def rbac_list_employees(conn: sqlite3.Connection, actor: ActorContext) -> List[Dict[str, Any]]:
    """
    If actor is HR_ADMIN, returns all employees with salary structures.
    If actor is EMPLOYEE, returns ONLY their own employee record.
    """
    cur = conn.cursor()
    base_sql = """
        SELECT
            e.emp_id, e.emp_code, e.first_name, e.last_name,
            e.first_name || ' ' || e.last_name AS full_name,
            e.email, e.phone, e.hire_date, e.designation, e.role, e.status,
            d.dept_id, d.dept_code, d.dept_name, d.base_location,
            ss.basic_pay, ss.hra_percent, ss.da_percent, ss.special_allowance,
            ss.pf_percent, ss.professional_tax, ss.standard_check_in, ss.effective_from,
            fn_calculate_gross_salary(ss.basic_pay, ss.hra_percent, ss.da_percent, ss.special_allowance) AS contracted_gross
        FROM Employee e
        JOIN Department d ON e.dept_id = d.dept_id
        LEFT JOIN Salary_Structure ss ON e.emp_id = ss.emp_id
    """
    if actor.role == "HR_ADMIN":
        cur.execute(base_sql + " ORDER BY e.emp_id ASC")
    else:
        cur.execute(base_sql + " WHERE e.emp_id = ? ORDER BY e.emp_id ASC", (actor.emp_id,))
    return [dict(r) for r in cur.fetchall()]


def rbac_get_salary_slips(
    conn: sqlite3.Connection,
    actor: ActorContext,
    pay_month: Optional[int] = None,
    pay_year: Optional[int] = None,
    target_emp_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Returns salary slips enforced by RBAC policy."""
    if actor.role == "EMPLOYEE":
        if target_emp_id is not None and int(target_emp_id) != int(actor.emp_id):
            require_self_or_hr_admin(actor, int(target_emp_id), "Salary Slip")
        effective_emp_id = actor.emp_id
    else:
        effective_emp_id = target_emp_id
    return get_salary_slips(conn, pay_month=pay_month, pay_year=pay_year, emp_id=effective_emp_id)


def rbac_get_attendance_summary(
    conn: sqlite3.Connection,
    actor: ActorContext,
    pay_month: Optional[int] = None,
    pay_year: Optional[int] = None,
    target_emp_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Returns monthly attendance summary enforced by RBAC policy."""
    if actor.role == "EMPLOYEE":
        if target_emp_id is not None and int(target_emp_id) != int(actor.emp_id):
            require_self_or_hr_admin(actor, int(target_emp_id), "Monthly Attendance Summary")
        effective_emp_id = actor.emp_id
    else:
        effective_emp_id = target_emp_id
    return get_monthly_attendance_summary(
        conn, pay_month=pay_month, pay_year=pay_year, emp_id=effective_emp_id
    )


def rbac_get_late_marks_report(
    conn: sqlite3.Connection,
    actor: ActorContext,
    pay_month: Optional[int] = None,
    pay_year: Optional[int] = None,
    target_emp_id: Optional[int] = None,
    only_late: bool = False,
) -> List[Dict[str, Any]]:
    """Returns late-marks report enforced by RBAC policy."""
    if actor.role == "EMPLOYEE":
        if target_emp_id is not None and int(target_emp_id) != int(actor.emp_id):
            require_self_or_hr_admin(actor, int(target_emp_id), "Late-Marks Report")
        effective_emp_id = actor.emp_id
    else:
        effective_emp_id = target_emp_id
    return get_late_marks_report(
        conn,
        pay_month=pay_month,
        pay_year=pay_year,
        emp_id=effective_emp_id,
        only_late=only_late,
    )


def rbac_get_attendance_logs(
    conn: sqlite3.Connection,
    actor: ActorContext,
    pay_month: Optional[int] = None,
    pay_year: Optional[int] = None,
    target_emp_id: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Returns granular daily attendance logs enforced by RBAC."""
    if actor.role == "EMPLOYEE":
        if target_emp_id is not None and int(target_emp_id) != int(actor.emp_id):
            require_self_or_hr_admin(actor, int(target_emp_id), "Daily Attendance Logs")
        effective_emp_id = actor.emp_id
    else:
        effective_emp_id = target_emp_id

    sql = """
        SELECT
            a.attendance_id, a.emp_id, e.emp_code,
            e.first_name || ' ' || e.last_name AS employee_name,
            d.dept_name, a.att_date, a.check_in, a.check_out,
            a.work_hours, a.att_status, a.late_minutes, a.is_late, a.remarks
        FROM Attendance a
        JOIN Employee e ON a.emp_id = e.emp_id
        JOIN Department d ON e.dept_id = d.dept_id
        WHERE 1=1
    """
    params: List[Any] = []
    if effective_emp_id is not None:
        sql += " AND a.emp_id = ?"
        params.append(int(effective_emp_id))
    if pay_year is not None and pay_month is not None:
        sql += " AND strftime('%Y-%m', a.att_date) = ?"
        params.append(f"{int(pay_year):04d}-{int(pay_month):02d}")
    sql += " ORDER BY a.att_date DESC, a.emp_id ASC LIMIT ?"
    params.append(int(limit))
    cur = conn.cursor()
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def rbac_get_leave_requests(
    conn: sqlite3.Connection,
    actor: ActorContext,
    target_emp_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Returns leave requests enforced by RBAC."""
    if actor.role == "EMPLOYEE":
        if target_emp_id is not None and int(target_emp_id) != int(actor.emp_id):
            require_self_or_hr_admin(actor, int(target_emp_id), "Leave Requests")
        effective_emp_id = actor.emp_id
    else:
        effective_emp_id = target_emp_id

    sql = """
        SELECT
            lr.leave_id, lr.emp_id, e.emp_code,
            e.first_name || ' ' || e.last_name AS employee_name,
            d.dept_name, lr.leave_type_id, lt.type_code, lt.type_name, lt.is_paid,
            lr.start_date, lr.end_date,
            CAST(julianday(lr.end_date) - julianday(lr.start_date) + 1 AS INTEGER) AS total_days,
            lr.reason, lr.status, lr.approved_by,
            ap.first_name || ' ' || ap.last_name AS approver_name,
            lr.applied_on
        FROM Leave_Request lr
        JOIN Employee e ON lr.emp_id = e.emp_id
        JOIN Department d ON e.dept_id = d.dept_id
        JOIN Leave_Type lt ON lr.leave_type_id = lt.leave_type_id
        LEFT JOIN Employee ap ON lr.approved_by = ap.emp_id
        WHERE 1=1
    """
    params: List[Any] = []
    if effective_emp_id is not None:
        sql += " AND lr.emp_id = ?"
        params.append(int(effective_emp_id))
    sql += " ORDER BY lr.start_date DESC, lr.leave_id DESC"
    cur = conn.cursor()
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


# ============================================================================
# ACID Transactional Mutations (BEGIN / SAVEPOINT / COMMIT / ROLLBACK)
# ============================================================================

def transactional_update_salary_and_payroll(
    conn: sqlite3.Connection,
    actor: ActorContext,
    target_emp_id: int,
    new_basic_pay: float,
    new_special_allowance: float,
    hra_percent: Optional[float] = None,
    da_percent: Optional[float] = None,
    recalc_month: Optional[int] = 10,
    recalc_year: Optional[int] = 2026,
) -> Dict[str, Any]:
    """
    Phase 4 Atomic Transaction:
    Updates an employee's Salary_Structure and optionally re-calculates their Payroll
    for (recalc_month, recalc_year) inside a single atomic transaction.
    If any validation, CHECK constraint, trigger, or payroll procedure fails,
    executes a full ROLLBACK so neither Salary_Structure nor Payroll is partially modified.
    """
    require_hr_admin(actor, "Update Salary Structure & Recalculate Payroll")

    cur = conn.cursor()
    cur.execute("SAVEPOINT sp_salary_payroll_tx;")
    try:
        if hra_percent is not None and da_percent is not None:
            cur.execute(
                """
                UPDATE Salary_Structure
                SET basic_pay = ?,
                    special_allowance = ?,
                    hra_percent = ?,
                    da_percent = ?,
                    effective_from = DATE('now')
                WHERE emp_id = ?
                """,
                (
                    float(new_basic_pay),
                    float(new_special_allowance),
                    float(hra_percent),
                    float(da_percent),
                    int(target_emp_id),
                ),
            )
        else:
            cur.execute(
                """
                UPDATE Salary_Structure
                SET basic_pay = ?,
                    special_allowance = ?,
                    effective_from = DATE('now')
                WHERE emp_id = ?
                """,
                (float(new_basic_pay), float(new_special_allowance), int(target_emp_id)),
            )

        if cur.rowcount == 0:
            raise ValueError(f"Salary_Structure for emp_id={target_emp_id} does not exist.")

        payroll_snapshot = None
        if recalc_month is not None and recalc_year is not None:
            payroll_snapshot = sp_process_monthly_payroll(
                conn,
                emp_id=int(target_emp_id),
                pay_month=int(recalc_month),
                pay_year=int(recalc_year),
                payment_status="PROCESSED",
            )

        cur.execute("RELEASE SAVEPOINT sp_salary_payroll_tx;")
        conn.commit()
        return {
            "transaction_status": "COMMITTED",
            "emp_id": int(target_emp_id),
            "new_basic_pay": float(new_basic_pay),
            "new_special_allowance": float(new_special_allowance),
            "payroll_snapshot": payroll_snapshot,
        }
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT sp_salary_payroll_tx;")
        cur.execute("RELEASE SAVEPOINT sp_salary_payroll_tx;")
        conn.rollback()
        raise


def transactional_run_payroll(
    conn: sqlite3.Connection,
    actor: ActorContext,
    pay_month: int,
    pay_year: int,
    target_emp_id: Optional[int] = None,
    payment_status: str = "PROCESSED",
) -> List[Dict[str, Any]]:
    """
    Phase 4 Atomic Transaction:
    Runs monthly payroll for one employee or all active employees inside a SAVEPOINT/COMMIT block.
    """
    require_hr_admin(actor, "Run Monthly Payroll Engine")
    cur = conn.cursor()
    cur.execute("SAVEPOINT sp_run_payroll_tx;")
    try:
        if target_emp_id is not None:
            result = [
                sp_process_monthly_payroll(
                    conn,
                    emp_id=int(target_emp_id),
                    pay_month=int(pay_month),
                    pay_year=int(pay_year),
                    payment_status=payment_status,
                )
            ]
        else:
            result = sp_process_bulk_payroll(
                conn,
                pay_month=int(pay_month),
                pay_year=int(pay_year),
                payment_status=payment_status,
            )
        cur.execute("RELEASE SAVEPOINT sp_run_payroll_tx;")
        conn.commit()
        return result
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT sp_run_payroll_tx;")
        cur.execute("RELEASE SAVEPOINT sp_run_payroll_tx;")
        conn.rollback()
        raise


def transactional_record_attendance(
    conn: sqlite3.Connection,
    actor: ActorContext,
    emp_id: int,
    att_date: str,
    att_status: str,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Phase 4 Atomic Transaction:
    Records a daily attendance entry (validated by Phase 2 triggers & unique constraints).
    """
    require_hr_admin(actor, "Record Employee Attendance")
    cur = conn.cursor()
    cur.execute("SAVEPOINT sp_record_attendance_tx;")
    try:
        cur.execute(
            """
            INSERT INTO Attendance (emp_id, att_date, check_in, check_out, att_status, remarks)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(emp_id),
                att_date,
                check_in if check_in else None,
                check_out if check_out else None,
                att_status,
                remarks,
            ),
        )
        att_id = cur.lastrowid
        cur.execute("RELEASE SAVEPOINT sp_record_attendance_tx;")
        conn.commit()

        cur.execute("SELECT * FROM Attendance WHERE attendance_id = ?", (att_id,))
        return dict(cur.fetchone())
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT sp_record_attendance_tx;")
        cur.execute("RELEASE SAVEPOINT sp_record_attendance_tx;")
        conn.rollback()
        raise


def transactional_submit_leave_request(
    conn: sqlite3.Connection,
    actor: ActorContext,
    target_emp_id: int,
    leave_type_id: int,
    start_date: str,
    end_date: str,
    reason: str,
) -> Dict[str, Any]:
    """
    Phase 4 Atomic Transaction:
    Submits a leave request (allowed for own emp_id or HR_ADMIN).
    Protected by Phase 2 triggers:
      - trg_validate_leave_overlap_insert
      - trg_validate_leave_quota_insert
    """
    require_self_or_hr_admin(actor, int(target_emp_id), "Submit Leave Request")
    cur = conn.cursor()
    cur.execute("SAVEPOINT sp_submit_leave_tx;")
    try:
        cur.execute(
            """
            INSERT INTO Leave_Request (emp_id, leave_type_id, start_date, end_date, reason, status)
            VALUES (?, ?, ?, ?, ?, 'PENDING')
            """,
            (int(target_emp_id), int(leave_type_id), start_date, end_date, reason.strip()),
        )
        leave_id = cur.lastrowid
        cur.execute("RELEASE SAVEPOINT sp_submit_leave_tx;")
        conn.commit()

        cur.execute("SELECT * FROM Leave_Request WHERE leave_id = ?", (leave_id,))
        return dict(cur.fetchone())
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT sp_submit_leave_tx;")
        cur.execute("RELEASE SAVEPOINT sp_submit_leave_tx;")
        conn.rollback()
        raise


def transactional_decide_leave_request(
    conn: sqlite3.Connection,
    actor: ActorContext,
    leave_id: int,
    new_status: str,
) -> Dict[str, Any]:
    """
    Phase 4 Atomic Transaction:
    HR_ADMIN approves or rejects a leave request and syncs any matching Attendance rows.
    """
    require_hr_admin(actor, "Approve/Reject Leave Request")
    if new_status not in ("APPROVED", "REJECTED"):
        raise ValueError("new_status must be 'APPROVED' or 'REJECTED'.")

    cur = conn.cursor()
    cur.execute("SAVEPOINT sp_decide_leave_tx;")
    try:
        cur.execute(
            """
            UPDATE Leave_Request
            SET status = ?, approved_by = ?
            WHERE leave_id = ?
            """,
            (new_status, actor.emp_id, int(leave_id)),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Leave request leave_id={leave_id} not found.")

        cur.execute("SELECT * FROM Leave_Request WHERE leave_id = ?", (int(leave_id),))
        lr = dict(cur.fetchone())

        if new_status == "APPROVED":
            cur.execute(
                """
                UPDATE Attendance
                SET att_status = 'ON_LEAVE',
                    check_in = NULL,
                    check_out = NULL,
                    work_hours = 0.0,
                    late_minutes = 0,
                    is_late = 0,
                    remarks = 'Approved Leave (Synced)'
                WHERE emp_id = ?
                  AND date(att_date) BETWEEN date(?) AND date(?)
                """,
                (lr["emp_id"], lr["start_date"], lr["end_date"]),
            )

        cur.execute("RELEASE SAVEPOINT sp_decide_leave_tx;")
        conn.commit()
        return lr
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT sp_decide_leave_tx;")
        cur.execute("RELEASE SAVEPOINT sp_decide_leave_tx;")
        conn.rollback()
        raise


def transactional_create_employee(
    conn: sqlite3.Connection,
    actor: ActorContext,
    emp_code: str,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    hire_date: str,
    designation: str,
    dept_id: int,
    basic_pay: float,
    special_allowance: float = 10000.0,
    role: str = "EMPLOYEE",
) -> Dict[str, Any]:
    """
    Phase 4 Atomic Transaction:
    Creates a new Employee and their corresponding 1:1 Salary_Structure in one atomic transaction.
    """
    from backend.db import hash_password

    require_hr_admin(actor, "Create New Employee & Salary Structure")
    cur = conn.cursor()
    cur.execute("SAVEPOINT sp_create_employee_tx;")
    try:
        cur.execute(
            """
            INSERT INTO Employee (
                emp_code, first_name, last_name, email, phone,
                hire_date, designation, role, password_hash, status, dept_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (
                emp_code.strip().upper(),
                first_name.strip(),
                last_name.strip(),
                email.strip().lower(),
                phone.strip(),
                hire_date,
                designation.strip(),
                role,
                hash_password("pass123"),
                int(dept_id),
            ),
        )
        new_emp_id = cur.lastrowid
        cur.execute(
            """
            INSERT INTO Salary_Structure (
                emp_id, effective_from, basic_pay, hra_percent, da_percent,
                special_allowance, pf_percent, professional_tax, standard_check_in
            ) VALUES (?, ?, ?, 40.0, 15.0, ?, 12.0, 200.0, '09:15:00')
            """,
            (new_emp_id, hire_date, float(basic_pay), float(special_allowance)),
        )
        cur.execute("RELEASE SAVEPOINT sp_create_employee_tx;")
        conn.commit()
        return rbac_get_employee_profile(conn, actor, new_emp_id)
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT sp_create_employee_tx;")
        cur.execute("RELEASE SAVEPOINT sp_create_employee_tx;")
        conn.rollback()
        raise
