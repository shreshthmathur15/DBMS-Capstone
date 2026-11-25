"""
Database Connection Manager & Phase 1–3 Initializer.
Manages SQLite connections with FK enforcement, registers Phase 2 stored functions,
executes Phase 1 DDL, Phase 2 Triggers & Realistic 3-Month Seed Data (12 Employees),
and Phase 3 Views & Indexes. Also exports sql/phase2_seed_data.sql.
"""

from __future__ import annotations
import datetime
import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Optional

from backend.procedures import register_sql_functions, sp_process_bulk_payroll

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "payroll_system.db"
SQL_DIR = BASE_DIR / "sql"


def hash_password(plain: str) -> str:
    """Deterministic SHA-256 password hash for authentication."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Returns a configured SQLite connection with:
      - Row factory (dict-like row access)
      - PRAGMA foreign_keys = ON
      - Registered Phase 2 SQL scalar functions
    """
    target_path = Path(db_path) if db_path else DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    register_sql_functions(conn)
    return conn


def _working_dates_for_month(year: int, month: int):
    """Returns all Monday-Friday dates for the given (year, month)."""
    start = datetime.date(year, month, 1)
    if month == 12:
        end = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    days = []
    curr = start
    while curr <= end:
        if curr.weekday() < 5:  # Monday (0) to Friday (4)
            days.append(curr)
        curr += datetime.timedelta(days=1)
    return days


def seed_realistic_data(conn: sqlite3.Connection, export_sql_path: Optional[Path] = None) -> None:
    """
    Populates realistic Phase 2 data covering:
      - 4 Departments
      - 12 Employees (2 HR_ADMIN, 10 EMPLOYEE)
      - 12 Salary_Structure records
      - 4 Leave_Type records
      - 20 Leave_Request records across Aug, Sep, Oct 2026
      - 792 Attendance records across 3 full months (Aug, Sep, Oct 2026)
      - 36 Monthly Payroll records computed via sp_process_bulk_payroll
    """
    cur = conn.cursor()

    # 1. Departments
    departments = [
        (1, "HR", "Human Resources & People Ops", "Bengaluru HQ"),
        (2, "ENG", "Core Software Engineering", "Bengaluru HQ"),
        (3, "FIN", "Finance, Tax & Compliance", "Mumbai Financial Center"),
        (4, "OPS", "Product & Cloud Operations", "Hyderabad Tech Park"),
    ]
    cur.executemany(
        "INSERT INTO Department (dept_id, dept_code, dept_name, base_location) VALUES (?, ?, ?, ?)",
        departments,
    )

    # 2. Employees (12 employees: 2 HR_ADMIN, 10 EMPLOYEE)
    default_pw = hash_password("pass123")
    admin_pw = hash_password("admin123")

    employees = [
        (1, "EMP001", "Aarav", "Mehta", "aarav.mehta@acmecorp.in", "+91-9820100101", "2022-03-15", "HR Director", "HR_ADMIN", admin_pw, "ACTIVE", 1),
        (2, "EMP002", "Neha", "Kulkarni", "neha.kulkarni@acmecorp.in", "+91-9820100102", "2023-06-01", "Senior HR Specialist", "HR_ADMIN", admin_pw, "ACTIVE", 1),
        (3, "EMP003", "Rohan", "Verma", "rohan.verma@acmecorp.in", "+91-9820100103", "2021-11-10", "Principal Software Architect", "EMPLOYEE", default_pw, "ACTIVE", 2),
        (4, "EMP004", "Priya", "Nair", "priya.nair@acmecorp.in", "+91-9820100104", "2023-01-20", "Senior Backend Engineer", "EMPLOYEE", default_pw, "ACTIVE", 2),
        (5, "EMP005", "Siddharth", "Iyer", "siddharth.iyer@acmecorp.in", "+91-9820100105", "2023-08-14", "Full-Stack Developer", "EMPLOYEE", default_pw, "ACTIVE", 2),
        (6, "EMP006", "Ananya", "Deshmukh", "ananya.deshmukh@acmecorp.in", "+91-9820100106", "2024-02-05", "Frontend Engineer", "EMPLOYEE", default_pw, "ACTIVE", 2),
        (7, "EMP007", "Vikram", "Rathore", "vikram.rathore@acmecorp.in", "+91-9820100107", "2022-07-18", "DevOps & SRE Lead", "EMPLOYEE", default_pw, "ACTIVE", 4),
        (8, "EMP008", "Kavya", "Sharma", "kavya.sharma@acmecorp.in", "+91-9820100108", "2022-09-01", "Finance Controller", "EMPLOYEE", default_pw, "ACTIVE", 3),
        (9, "EMP009", "Arjun", "Chatterjee", "arjun.chatterjee@acmecorp.in", "+91-9820100109", "2024-01-10", "Payroll & Tax Analyst", "EMPLOYEE", default_pw, "ACTIVE", 3),
        (10, "EMP010", "Meera", "Krishnan", "meera.krishnan@acmecorp.in", "+91-9820100110", "2023-04-12", "Product Manager", "EMPLOYEE", default_pw, "ACTIVE", 4),
        (11, "EMP011", "Devansh", "kapoor", "devansh.kapoor@acmecorp.in", "+91-9820100111", "2024-05-20", "Cloud Operations Engineer", "EMPLOYEE", default_pw, "ACTIVE", 4),
        (12, "EMP012", "Tanya", "Bhatia", "tanya.bhatia@acmecorp.in", "+91-9820100112", "2024-07-01", "QA Automation Engineer", "EMPLOYEE", default_pw, "ACTIVE", 2),
    ]
    # Fix capitalization of Kapoor
    employees[10] = (11, "EMP011", "Devansh", "Kapoor", "devansh.kapoor@acmecorp.in", "+91-9820100111", "2024-05-20", "Cloud Operations Engineer", "EMPLOYEE", default_pw, "ACTIVE", 4)

    cur.executemany(
        """
        INSERT INTO Employee (
            emp_id, emp_code, first_name, last_name, email, phone,
            hire_date, designation, role, password_hash, status, dept_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        employees,
    )

    # 3. Salary_Structure (1:1 with Employee)
    # (salary_id, emp_id, effective_from, basic_pay, hra_pct, da_pct, special_allowance, pf_pct, prof_tax, standard_check_in)
    salaries = [
        (1, 1, "2026-04-01", 95000.00, 40.0, 15.0, 22000.00, 12.0, 200.00, "09:15:00"),
        (2, 2, "2026-04-01", 62000.00, 40.0, 15.0, 12000.00, 12.0, 200.00, "09:15:00"),
        (3, 3, "2026-04-01", 115000.00, 40.0, 15.0, 28000.00, 12.0, 200.00, "09:15:00"),
        (4, 4, "2026-04-01", 82000.00, 40.0, 15.0, 16000.00, 12.0, 200.00, "09:15:00"),
        (5, 5, "2026-04-01", 68000.00, 40.0, 15.0, 11500.00, 12.0, 200.00, "09:15:00"),
        (6, 6, "2026-04-01", 54000.00, 40.0, 15.0, 9000.00, 12.0, 200.00, "09:15:00"),
        (7, 7, "2026-04-01", 88000.00, 40.0, 15.0, 18500.00, 12.0, 200.00, "09:15:00"),
        (8, 8, "2026-04-01", 90000.00, 40.0, 15.0, 20000.00, 12.0, 200.00, "09:15:00"),
        (9, 9, "2026-04-01", 52000.00, 40.0, 15.0, 8500.00, 12.0, 200.00, "09:15:00"),
        (10, 10, "2026-04-01", 78000.00, 40.0, 15.0, 15000.00, 12.0, 200.00, "09:15:00"),
        (11, 11, "2026-04-01", 48000.00, 40.0, 15.0, 7500.00, 12.0, 200.00, "09:15:00"),
        (12, 12, "2026-04-01", 44000.00, 40.0, 15.0, 6500.00, 12.0, 200.00, "09:15:00"),
    ]
    cur.executemany(
        """
        INSERT INTO Salary_Structure (
            salary_id, emp_id, effective_from, basic_pay, hra_percent, da_percent,
            special_allowance, pf_percent, professional_tax, standard_check_in
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        salaries,
    )

    # 4. Leave_Type
    leave_types = [
        (1, "CL", "Casual Leave", 12, 1),
        (2, "SL", "Sick / Medical Leave", 10, 1),
        (3, "EL", "Earned Privilege Leave", 15, 1),
        (4, "LOP", "Loss of Pay (Unpaid Leave)", 30, 0),
    ]
    cur.executemany(
        "INSERT INTO Leave_Type (leave_type_id, type_code, type_name, annual_quota, is_paid) VALUES (?, ?, ?, ?, ?)",
        leave_types,
    )

    # 5. Leave_Request across Aug, Sep, Oct 2026 (Non-overlapping per employee!)
    # (leave_id, emp_id, leave_type_id, start_date, end_date, reason, status, approved_by, applied_on)
    leave_requests = [
        # August 2026 Approved Leaves
        (1, 3, 1, "2026-08-10", "2026-08-11", "Family function in Pune", "APPROVED", 1, "2026-08-03 10:15:00"),
        (2, 4, 2, "2026-08-18", "2026-08-19", "Viral fever and medical rest", "APPROVED", 1, "2026-08-17 19:30:00"),
        (3, 5, 1, "2026-08-24", "2026-08-24", "Personal bank documentation", "APPROVED", 2, "2026-08-20 11:00:00"),
        (4, 7, 4, "2026-08-27", "2026-08-28", "Extended personal travel (Unpaid LOP)", "APPROVED", 1, "2026-08-18 14:20:00"),
        (5, 9, 2, "2026-08-13", "2026-08-14", "Dental surgery recovery", "APPROVED", 2, "2026-08-11 09:45:00"),
        (6, 11, 1, "2026-08-06", "2026-08-06", "Passport renewal appointment", "APPROVED", 2, "2026-08-01 16:10:00"),

        # September 2026 Approved & Rejected Leaves
        (7, 2, 3, "2026-09-07", "2026-09-08", "Annual family trip", "APPROVED", 1, "2026-08-29 12:00:00"),
        (8, 3, 2, "2026-09-16", "2026-09-16", "Migraine and medical checkup", "APPROVED", 1, "2026-09-15 21:00:00"),
        (9, 6, 1, "2026-09-21", "2026-09-22", "Sister wedding ceremony", "APPROVED", 2, "2026-09-10 10:30:00"),
        (10, 8, 3, "2026-09-10", "2026-09-11", "Home relocation", "APPROVED", 1, "2026-09-02 15:40:00"),
        (11, 10, 1, "2026-09-25", "2026-09-25", "Parent health checkup", "APPROVED", 1, "2026-09-20 09:30:00"),
        (12, 12, 4, "2026-09-28", "2026-09-29", "Unpaid personal leave for exam", "APPROVED", 2, "2026-09-18 17:05:00"),
        (13, 5, 3, "2026-09-14", "2026-09-18", "Peak release week vacation request", "REJECTED", 1, "2026-09-05 11:20:00"),

        # October 2026 Approved & Pending Leaves
        (14, 1, 3, "2026-10-12", "2026-10-13", "Personal festive break", "APPROVED", 2, "2026-10-02 10:00:00"),
        (15, 4, 1, "2026-10-08", "2026-10-09", "Hometown visit", "APPROVED", 1, "2026-10-01 14:15:00"),
        (16, 5, 2, "2026-10-19", "2026-10-20", "Seasonal flu recovery", "APPROVED", 2, "2026-10-18 20:10:00"),
        (17, 7, 1, "2026-10-22", "2026-10-22", "Property registration", "APPROVED", 1, "2026-10-15 11:45:00"),
        (18, 11, 4, "2026-10-15", "2026-10-16", "Unpaid personal errand", "APPROVED", 2, "2026-10-09 16:00:00"),
        # Pending future leaves in November 2026 for HR Admin approval workflow demo
        (19, 3, 3, "2026-11-18", "2026-11-20", "Attending family wedding in Jaipur", "PENDING", None, "2026-11-05 10:20:00"),
        (20, 6, 1, "2026-11-23", "2026-11-24", "Personal travel", "PENDING", None, "2026-11-08 14:50:00"),
    ]
    cur.executemany(
        """
        INSERT INTO Leave_Request (
            leave_id, emp_id, leave_type_id, start_date, end_date,
            reason, status, approved_by, applied_on
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        leave_requests,
    )

    # Build lookup of approved leave dates per employee: (emp_id, date_str) -> is_paid
    approved_leave_map = {}
    for lr in leave_requests:
        _, emp_id, lt_id, s_str, e_str, _, status, _, _ = lr
        if status == "APPROVED":
            s_dt = datetime.date.fromisoformat(s_str)
            e_dt = datetime.date.fromisoformat(e_str)
            curr = s_dt
            while curr <= e_dt:
                approved_leave_map[(emp_id, curr.isoformat())] = lt_id
                curr += datetime.timedelta(days=1)

    # 6. Realistic Attendance across 3 Months: Aug 2026 (8), Sep 2026 (9), Oct 2026 (10)
    # Design specific punctuality & attendance profiles so all 3 Phase 3 reports have rich, meaningful variety:
    # - Emp 5 (Siddharth), Emp 7 (Vikram), Emp 9 (Arjun), Emp 11 (Devansh), Emp 12 (Tanya) have deliberate late marks (3 to 6 per month)
    # - Emp 3 (Rohan), Emp 4 (Priya), Emp 6 (Ananya), Emp 10 (Meera) have 1-2 occasional late marks
    # - Emp 1 (Aarav), Emp 2 (Neha), Emp 8 (Kavya) have 0 late marks (exemplary punctuality)
    late_schedule_by_emp = {
        1: [],
        2: [],
        3: [(2, "09:28:00"), (14, "09:34:00")],  # 2 late marks -> Warning, 0 penalty
        4: [(5, "09:24:00")],  # 1 late mark -> Warning, 0 penalty
        5: [(1, "09:35:00"), (6, "09:42:00"), (11, "09:29:00"), (17, "09:50:00")],  # 4 late marks -> 0.5 day LOP penalty
        6: [(4, "09:22:00"), (12, "09:31:00")],  # 2 late marks
        7: [(0, "09:45:00"), (3, "09:38:00"), (8, "09:55:00"), (13, "09:27:00"), (16, "09:40:00"), (19, "10:05:00")],  # 6 late marks -> 1.0 day LOP penalty
        8: [],
        9: [(2, "09:33:00"), (7, "09:48:00"), (15, "09:26:00")],  # 3 late marks -> 0.5 day LOP penalty
        10: [(9, "09:25:00")],  # 1 late mark
        11: [(1, "09:36:00"), (5, "09:52:00"), (10, "09:41:00"), (14, "09:30:00")],  # 4 late marks -> 0.5 day LOP penalty
        12: [(3, "09:29:00"), (8, "09:44:00"), (12, "09:37:00")],  # 3 late marks -> 0.5 day LOP penalty
    }

    # Unexcused ABSENT / HALF_DAY overrides (day index inside the month)
    absent_idx_by_emp_month = {
        (6, 8): {15: "HALF_DAY"},
        (7, 9): {11: "ABSENT"},
        (9, 10): {6: "HALF_DAY"},
        (11, 9): {4: "ABSENT"},
        (12, 8): {18: "ABSENT"},
        (12, 10): {9: "HALF_DAY"},
    }

    for year, month in [(2026, 8), (2026, 9), (2026, 10)]:
        work_dates = _working_dates_for_month(year, month)
        for emp in employees:
            emp_id = emp[0]
            late_map = dict(late_schedule_by_emp.get(emp_id, []))
            special_days = absent_idx_by_emp_month.get((emp_id, month), {})

            for idx, dt in enumerate(work_dates):
                d_str = dt.isoformat()
                if (emp_id, d_str) in approved_leave_map:
                    cur.execute(
                        """
                        INSERT INTO Attendance (emp_id, att_date, check_in, check_out, att_status, remarks)
                        VALUES (?, ?, NULL, NULL, 'ON_LEAVE', 'Approved Leave')
                        """,
                        (emp_id, d_str),
                    )
                elif idx in special_days and special_days[idx] == "ABSENT":
                    cur.execute(
                        """
                        INSERT INTO Attendance (emp_id, att_date, check_in, check_out, att_status, remarks)
                        VALUES (?, ?, NULL, NULL, 'ABSENT', 'Uninformed Absence (LOP)')
                        """,
                        (emp_id, d_str),
                    )
                elif idx in special_days and special_days[idx] == "HALF_DAY":
                    cur.execute(
                        """
                        INSERT INTO Attendance (emp_id, att_date, check_in, check_out, att_status, remarks)
                        VALUES (?, ?, '09:05:00', '13:35:00', 'HALF_DAY', 'Half-day personal emergency')
                        """,
                        (emp_id, d_str),
                    )
                elif idx in late_map:
                    c_in = late_map[idx]
                    c_out = "18:30:00"
                    cur.execute(
                        """
                        INSERT INTO Attendance (emp_id, att_date, check_in, check_out, att_status, remarks)
                        VALUES (?, ?, ?, ?, 'PRESENT', 'Late check-in recorded by biometric gate')
                        """,
                        (emp_id, d_str, c_in, c_out),
                    )
                else:
                    # Deterministic on-time check-in between 08:52 and 09:12
                    minute = 52 + ((emp_id * 3 + idx * 5 + month) % 20)
                    if minute >= 60:
                        c_in = f"09:{minute - 60:02d}:00"
                    else:
                        c_in = f"08:{minute:02d}:00"
                    out_min = 10 + ((emp_id + idx * 7) % 35)
                    c_out = f"18:{out_min:02d}:00"
                    cur.execute(
                        """
                        INSERT INTO Attendance (emp_id, att_date, check_in, check_out, att_status, remarks)
                        VALUES (?, ?, ?, ?, 'PRESENT', 'Regular shift')
                        """,
                        (emp_id, d_str, c_in, c_out),
                    )

    # 7. Process Monthly Payroll across all 3 months via Phase 2 Stored Procedure
    sp_process_bulk_payroll(conn, 8, 2026, payment_status="PAID")
    sp_process_bulk_payroll(conn, 9, 2026, payment_status="PAID")
    sp_process_bulk_payroll(conn, 10, 2026, payment_status="PROCESSED")

    conn.commit()

    # Export deterministic SQL seed file if requested
    if export_sql_path:
        _export_seed_sql(conn, export_sql_path)


def _export_seed_sql(conn: sqlite3.Connection, export_path: Path) -> None:
    """Exports all seeded rows from the 7 Phase 1 tables into sql/phase2_seed_data.sql."""
    tables = [
        "Department",
        "Employee",
        "Salary_Structure",
        "Leave_Type",
        "Leave_Request",
        "Attendance",
        "Payroll",
    ]
    lines = [
        "-- ============================================================================",
        "-- PHASE 2 (Part C): REALISTIC SAMPLE DATA (12 Employees across 3 Months)",
        "-- Coverage: August 2026, September 2026, October 2026",
        "-- ============================================================================",
        "PRAGMA foreign_keys = ON;",
        "BEGIN TRANSACTION;",
        "",
    ]
    cur = conn.cursor()
    for tbl in tables:
        lines.append(f"-- Table: {tbl}")
        cur.execute(f"SELECT * FROM {tbl}")
        rows = cur.fetchall()
        if not rows:
            continue
        col_names = rows[0].keys()
        col_list = ", ".join(col_names)
        for r in rows:
            vals = []
            for c in col_names:
                v = r[c]
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    escaped = str(v).replace("'", "''")
                    vals.append(f"'{escaped}'")
            lines.append(f"INSERT INTO {tbl} ({col_list}) VALUES ({', '.join(vals)});")
        lines.append("")
    lines.append("COMMIT;")
    export_path.write_text("\n".join(lines), encoding="utf-8")


def init_database(db_path: Optional[Path] = None, force_reset: bool = False) -> sqlite3.Connection:
    """
    Initializes the complete Phase 1–3 database if not already initialized (or if force_reset=True).
    """
    target_path = Path(db_path) if db_path else DB_PATH
    if force_reset and target_path.exists():
        target_path.unlink()

    already_initialized = False
    if target_path.exists():
        conn = get_connection(target_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Payroll'")
        if cur.fetchone():
            cur.execute("SELECT COUNT(*) AS cnt FROM Employee")
            if cur.fetchone()["cnt"] >= 10:
                already_initialized = True
        if already_initialized:
            return conn
        conn.close()

    conn = get_connection(target_path)
    # 1. Execute Phase 1 DDL
    ddl_sql = (SQL_DIR / "phase1_schema_ddl.sql").read_text(encoding="utf-8")
    conn.executescript(ddl_sql)

    # 2. Execute Phase 2 Triggers
    triggers_sql = (SQL_DIR / "phase2_procedures_triggers.sql").read_text(encoding="utf-8")
    conn.executescript(triggers_sql)

    # 3. Re-enable foreign keys after executescript and seed realistic data
    conn.execute("PRAGMA foreign_keys = ON;")
    seed_sql_path = SQL_DIR / "phase2_seed_data.sql"
    seed_realistic_data(conn, export_sql_path=seed_sql_path if target_path == DB_PATH else None)

    # 4. Execute Phase 3 Views & Indexes
    reports_sql = (SQL_DIR / "phase3_reports_and_indexes.sql").read_text(encoding="utf-8")
    conn.executescript(reports_sql)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.commit()
    return conn
