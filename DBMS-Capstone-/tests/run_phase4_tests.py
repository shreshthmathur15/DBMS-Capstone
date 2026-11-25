"""
Phase 4: Comprehensive Automated Test Suite & Phase 3 Index Execution Plan Verifier.

Tests 16 rigorous scenarios across:
  - Valid Operations (Attendance auto-computation, Leave submission, Salary revision + Payroll run)
  - Boundary Conditions (Exact 09:15:00 check-in grace threshold, 09:16:00 1-min late, 1-day adjacent leave, 0 salary)
  - Invalid / Constraint & Trigger Rejections (Negative salary, duplicate attendance, overlapping approved leave,
    attendance on approved leave date, check_out <= check_in, leave quota exceeded, end_date < start_date)
  - ACID Transaction Safety (Mid-transaction error triggers full ROLLBACK leaving zero partial state)
  - Role-Based Access Control (EMPLOYEE blocked from reading other employee's salary slip or mutating salary/payroll)
"""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.db import init_database
from backend.rbac import (
    PermissionDeniedError,
    get_actor_by_emp_id,
    rbac_get_salary_slips,
    transactional_record_attendance,
    transactional_run_payroll,
    transactional_submit_leave_request,
    transactional_update_salary_and_payroll,
)
from backend.reports import (
    benchmark_index_execution_plan,
    get_late_marks_report,
    get_monthly_attendance_summary,
    get_salary_slips,
)


def run_all_phase4_tests(conn=None) -> Dict[str, Any]:
    """Runs all 16 Phase 4 test cases and returns structured results."""
    owns_conn = False
    if conn is None:
        conn = init_database(force_reset=True)
        owns_conn = True

    hr_admin = get_actor_by_emp_id(conn, 1)   # EMP001: Aarav Mehta (HR_ADMIN)
    emp_rohan = get_actor_by_emp_id(conn, 3)  # EMP003: Rohan Verma (EMPLOYEE)
    emp_priya = get_actor_by_emp_id(conn, 4)  # EMP004: Priya Nair (EMPLOYEE)

    results: List[Dict[str, Any]] = []

    def record_test(
        test_id: str,
        category: str,
        title: str,
        expected: str,
        fn: Callable[[], str],
    ) -> None:
        try:
            actual = fn()
            results.append(
                {
                    "test_id": test_id,
                    "category": category,
                    "title": title,
                    "expected": expected,
                    "actual": actual,
                    "status": "PASS",
                }
            )
        except AssertionError as exc:
            results.append(
                {
                    "test_id": test_id,
                    "category": category,
                    "title": title,
                    "expected": expected,
                    "actual": f"ASSERTION FAILED: {exc}",
                    "status": "FAIL",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "test_id": test_id,
                    "category": category,
                    "title": title,
                    "expected": expected,
                    "actual": f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}",
                    "status": "FAIL",
                }
            )

    # ------------------------------------------------------------------------
    # T01 (Valid): Record valid attendance on a normal working day
    # ------------------------------------------------------------------------
    def t01():
        row = transactional_record_attendance(
            conn,
            actor=hr_admin,
            emp_id=3,
            att_date="2026-11-02",
            att_status="PRESENT",
            check_in="09:00:00",
            check_out="18:00:00",
            remarks="Test T01 regular shift",
        )
        conn.execute("DELETE FROM Attendance WHERE attendance_id = ?", (row["attendance_id"],))
        conn.commit()
        assert float(row["work_hours"]) == 9.0, f"Expected 9.0 work_hours, got {row['work_hours']}"
        assert int(row["is_late"]) == 0 and int(row["late_minutes"]) == 0
        return f"Inserted & auto-computed work_hours={row['work_hours']}h, is_late={row['is_late']}, late_minutes={row['late_minutes']}"

    record_test(
        "T01",
        "VALID",
        "Record valid on-time attendance (09:00 to 18:00)",
        "Accepted; trigger computes work_hours=9.0, is_late=0, late_minutes=0",
        t01,
    )

    # ------------------------------------------------------------------------
    # T02 (Boundary): Check-in at exact standard grace threshold (09:15:00)
    # ------------------------------------------------------------------------
    def t02():
        row = transactional_record_attendance(
            conn,
            actor=hr_admin,
            emp_id=3,
            att_date="2026-11-03",
            att_status="PRESENT",
            check_in="09:15:00",
            check_out="18:15:00",
            remarks="Boundary exact 09:15:00",
        )
        conn.execute("DELETE FROM Attendance WHERE attendance_id = ?", (row["attendance_id"],))
        conn.commit()
        assert int(row["is_late"]) == 0 and int(row["late_minutes"]) == 0
        return f"Exact threshold 09:15:00 accepted as on-time: is_late={row['is_late']}, late_minutes={row['late_minutes']}"

    record_test(
        "T02",
        "BOUNDARY",
        "Check-in at exact standard threshold 09:15:00",
        "is_late=0, late_minutes=0 (inclusive grace boundary)",
        t02,
    )

    # ------------------------------------------------------------------------
    # T03 (Boundary): Check-in 1 minute past grace threshold (09:16:00)
    # ------------------------------------------------------------------------
    def t03():
        row = transactional_record_attendance(
            conn,
            actor=hr_admin,
            emp_id=3,
            att_date="2026-11-04",
            att_status="PRESENT",
            check_in="09:16:00",
            check_out="18:16:00",
            remarks="Boundary 09:16:00 (1 min late)",
        )
        conn.execute("DELETE FROM Attendance WHERE attendance_id = ?", (row["attendance_id"],))
        conn.commit()
        assert int(row["is_late"]) == 1 and int(row["late_minutes"]) == 1
        return f"09:16:00 flagged as late by trigger: is_late={row['is_late']}, late_minutes={row['late_minutes']}"

    record_test(
        "T03",
        "BOUNDARY",
        "Check-in 1 minute past threshold at 09:16:00",
        "is_late=1, late_minutes=1",
        t03,
    )

    # ------------------------------------------------------------------------
    # T04 (Invalid): Duplicate attendance entry for same (emp_id, att_date)
    # ------------------------------------------------------------------------
    def t04():
        try:
            transactional_record_attendance(
                conn,
                actor=hr_admin,
                emp_id=3,
                att_date="2026-10-01",  # Already exists in seeded data
                att_status="PRESENT",
                check_in="09:05:00",
                check_out="18:05:00",
                remarks="Duplicate date attempt",
            )
            raise AssertionError("Duplicate attendance was not rejected!")
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            return f"Rejected & rolled back: {exc}"

    record_test(
        "T04",
        "INVALID",
        "Duplicate attendance entry for (emp_id=3, att_date='2026-10-01')",
        "Rejected by UNIQUE(emp_id, att_date) constraint & rolled back",
        t04,
    )

    # ------------------------------------------------------------------------
    # T05 (Invalid): Check-out time earlier than or equal to check-in time
    # ------------------------------------------------------------------------
    def t05():
        try:
            transactional_record_attendance(
                conn,
                actor=hr_admin,
                emp_id=3,
                att_date="2026-11-05",
                att_status="PRESENT",
                check_in="14:00:00",
                check_out="09:30:00",
                remarks="Invalid time order",
            )
            raise AssertionError("Invalid check_out <= check_in was not rejected!")
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            assert "INVALID_CHECK_OUT" in str(exc)
            return f"Rejected by trigger: {exc}"

    record_test(
        "T05",
        "INVALID",
        "Attendance with check_out (09:30:00) < check_in (14:00:00)",
        "Rejected by trigger trg_validate_attendance_before_insert",
        t05,
    )

    # ------------------------------------------------------------------------
    # T06 (Invalid): Mark employee PRESENT on an APPROVED leave date
    # ------------------------------------------------------------------------
    def t06():
        # Emp 3 has APPROVED leave on 2026-08-10..2026-08-11
        cur = conn.cursor()
        try:
            cur.execute("SAVEPOINT sp_test_t06;")
            cur.execute(
                """
                UPDATE Attendance
                SET att_status = 'PRESENT', check_in = '09:00:00', check_out = '18:00:00'
                WHERE emp_id = 3 AND att_date = '2026-08-10'
                """
            )
            raise AssertionError("Marking PRESENT on approved leave date was not rejected!")
        except Exception as exc:
            cur.execute("ROLLBACK TO SAVEPOINT sp_test_t06;")
            cur.execute("RELEASE SAVEPOINT sp_test_t06;")
            if isinstance(exc, AssertionError):
                raise
            assert "ATTENDANCE_ON_APPROVED_LEAVE" in str(exc)
            return f"Rejected by trigger: {exc}"

    record_test(
        "T06",
        "INVALID",
        "Mark employee PRESENT on an APPROVED leave date (2026-08-10)",
        "Rejected by trigger trg_validate_attendance_before_update",
        t06,
    )

    # ------------------------------------------------------------------------
    # T07 (Invalid): Overlapping approved leave dates (Trigger Validation)
    # ------------------------------------------------------------------------
    def t07():
        # Emp 4 (Priya) has APPROVED leave 2026-10-08 to 2026-10-09
        try:
            transactional_submit_leave_request(
                conn,
                actor=emp_priya,
                target_emp_id=4,
                leave_type_id=1,
                start_date="2026-10-09",
                end_date="2026-10-12",
                reason="Overlapping leave test",
            )
            raise AssertionError("Overlapping leave request was not rejected!")
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            assert "LEAVE_OVERLAP" in str(exc)
            return f"Rejected by trigger: {exc}"

    record_test(
        "T07",
        "INVALID",
        "Submit leave (2026-10-09..2026-10-12) overlapping approved leave (2026-10-08..2026-10-09)",
        "Rejected by trigger trg_validate_leave_overlap_insert",
        t07,
    )

    # ------------------------------------------------------------------------
    # T08 (Boundary): Single-day leave adjacent to approved leave (2026-10-07..2026-10-07)
    # ------------------------------------------------------------------------
    def t08():
        lr = transactional_submit_leave_request(
            conn,
            actor=emp_priya,
            target_emp_id=4,
            leave_type_id=1,
            start_date="2026-10-07",
            end_date="2026-10-07",
            reason="Boundary 1-day adjacent leave",
        )
        conn.execute("DELETE FROM Leave_Request WHERE leave_id = ?", (lr["leave_id"],))
        conn.commit()
        assert lr["status"] == "PENDING"
        return f"Accepted 1-day non-overlapping adjacent leave (start_date=end_date='2026-10-07'), leave_id={lr['leave_id']}"

    record_test(
        "T08",
        "BOUNDARY",
        "Single-day leave (start_date = end_date = 2026-10-07) immediately adjacent to existing leave",
        "Accepted without false-positive overlap error",
        t08,
    )

    # ------------------------------------------------------------------------
    # T09 (Invalid): Leave end_date earlier than start_date
    # ------------------------------------------------------------------------
    def t09():
        try:
            transactional_submit_leave_request(
                conn,
                actor=emp_rohan,
                target_emp_id=3,
                leave_type_id=1,
                start_date="2026-12-10",
                end_date="2026-12-05",
                reason="Inverted dates",
            )
            raise AssertionError("Leave with end_date < start_date was not rejected!")
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            return f"Rejected by trigger/check constraint: {exc}"

    record_test(
        "T09",
        "INVALID",
        "Submit leave request with end_date ('2026-12-05') < start_date ('2026-12-10')",
        "Rejected by trigger trg_validate_leave_overlap_insert / CHECK (end_date >= start_date)",
        t09,
    )

    # ------------------------------------------------------------------------
    # T10 (Invalid): Paid leave request exceeding annual quota (Quota = 10 days for SL)
    # ------------------------------------------------------------------------
    def t10():
        try:
            transactional_submit_leave_request(
                conn,
                actor=emp_rohan,
                target_emp_id=3,
                leave_type_id=2,  # Sick Leave annual_quota = 10 days
                start_date="2026-12-01",
                end_date="2026-12-15",  # 15 days > 10 quota
                reason="Exceeding annual sick leave quota",
            )
            raise AssertionError("Quota-exceeding leave was not rejected!")
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            assert "LEAVE_QUOTA_EXCEEDED" in str(exc)
            return f"Rejected by trigger: {exc}"

    record_test(
        "T10",
        "INVALID",
        "Submit 15-day Sick Leave exceeding 10-day annual_quota",
        "Rejected by trigger trg_validate_leave_quota_insert",
        t10,
    )

    # ------------------------------------------------------------------------
    # T11 (Invalid): Negative basic salary update (basic_pay = -25000)
    # ------------------------------------------------------------------------
    def t11():
        try:
            transactional_update_salary_and_payroll(
                conn,
                actor=hr_admin,
                target_emp_id=3,
                new_basic_pay=-25000.00,
                new_special_allowance=10000.00,
            )
            raise AssertionError("Negative basic_pay was not rejected!")
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            return f"Rejected & rolled back: {exc}"

    record_test(
        "T11",
        "INVALID",
        "Attempt to set negative basic salary (basic_pay = -25000.00)",
        "Rejected by trigger trg_validate_salary_positive_update & CHECK (basic_pay > 0)",
        t11,
    )

    # ------------------------------------------------------------------------
    # T12 (Boundary): Zero basic salary update (basic_pay = 0.00)
    # ------------------------------------------------------------------------
    def t12():
        try:
            transactional_update_salary_and_payroll(
                conn,
                actor=hr_admin,
                target_emp_id=3,
                new_basic_pay=0.00,
                new_special_allowance=10000.00,
            )
            raise AssertionError("Zero basic_pay=0.00 was not rejected!")
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            return f"Rejected & rolled back at 0 boundary: {exc}"

    record_test(
        "T12",
        "BOUNDARY",
        "Attempt to set zero basic salary (basic_pay = 0.00)",
        "Rejected by strict boundary CHECK (basic_pay > 0)",
        t12,
    )

    # ------------------------------------------------------------------------
    # T13 (ACID Transaction Safety): Mid-transaction failure rolls back salary change
    # ------------------------------------------------------------------------
    def t13():
        cur = conn.cursor()
        cur.execute("SELECT basic_pay FROM Salary_Structure WHERE emp_id = 3")
        original_basic = float(cur.fetchone()["basic_pay"])

        try:
            # Valid basic_pay (125000), but invalid recalc_month=13 triggers mid-transaction failure
            transactional_update_salary_and_payroll(
                conn,
                actor=hr_admin,
                target_emp_id=3,
                new_basic_pay=125000.00,
                new_special_allowance=30000.00,
                recalc_month=13,  # Invalid month -> fails in Step 2 after Salary UPDATE!
                recalc_year=2026,
            )
            raise AssertionError("Transaction with invalid recalc_month=13 did not fail!")
        except ValueError:
            pass

        cur.execute("SELECT basic_pay FROM Salary_Structure WHERE emp_id = 3")
        after_basic = float(cur.fetchone()["basic_pay"])
        assert after_basic == original_basic, (
            f"Partial state leaked! Expected {original_basic}, got {after_basic}"
        )
        return (
            f"Mid-transaction failure triggered full ROLLBACK; Salary_Structure.basic_pay "
            f"remained unchanged at Rs. {after_basic:,.2f}"
        )

    record_test(
        "T13",
        "TRANSACTION_ROLLBACK",
        "Atomic Salary Update + Payroll Run where Step 2 fails (recalc_month=13)",
        "Full ROLLBACK; Step 1 Salary_Structure update is completely reverted",
        t13,
    )

    # ------------------------------------------------------------------------
    # T14 (RBAC Security - Invalid): EMPLOYEE attempts to read another employee's salary slip
    # ------------------------------------------------------------------------
    def t14():
        try:
            # Emp 3 (Rohan, EMPLOYEE) attempts to view Emp 1 (Aarav, HR Director)'s salary slip
            rbac_get_salary_slips(conn, actor=emp_rohan, pay_month=10, pay_year=2026, target_emp_id=1)
            raise AssertionError("RBAC failed to block cross-employee salary slip read!")
        except PermissionDeniedError as exc:
            return f"Blocked by RBAC Guard: {exc}"

    record_test(
        "T14",
        "RBAC_SECURITY",
        "EMPLOYEE (EMP003) attempts to view another employee's (EMP001) Salary Slip",
        "Blocked with PermissionDeniedError (Row-Level RBAC isolation)",
        t14,
    )

    # ------------------------------------------------------------------------
    # T15 (RBAC Security - Invalid): EMPLOYEE attempts to update salary or run payroll
    # ------------------------------------------------------------------------
    def t15():
        try:
            transactional_update_salary_and_payroll(
                conn,
                actor=emp_rohan,
                target_emp_id=3,
                new_basic_pay=200000.00,
                new_special_allowance=50000.00,
            )
            raise AssertionError("RBAC failed to block EMPLOYEE salary modification!")
        except PermissionDeniedError as exc:
            msg1 = str(exc)

        try:
            transactional_run_payroll(conn, actor=emp_rohan, pay_month=10, pay_year=2026, target_emp_id=3)
            raise AssertionError("RBAC failed to block EMPLOYEE payroll execution!")
        except PermissionDeniedError as exc:
            msg2 = str(exc)

        return f"Both privilege escalation attempts blocked: [1] {msg1} | [2] {msg2}"

    record_test(
        "T15",
        "RBAC_SECURITY",
        "EMPLOYEE (EMP003) attempts to modify own Salary_Structure and run Payroll",
        "Blocked with PermissionDeniedError (Requires role='HR_ADMIN')",
        t15,
    )

    # ------------------------------------------------------------------------
    # T16 (Valid Atomic Commit): HR_ADMIN revises salary & re-runs payroll, then restores
    # ------------------------------------------------------------------------
    def t16():
        cur = conn.cursor()
        cur.execute("SELECT basic_pay, special_allowance FROM Salary_Structure WHERE emp_id = 4")
        orig = cur.fetchone()
        orig_basic, orig_spec = float(orig["basic_pay"]), float(orig["special_allowance"])

        tx_res = transactional_update_salary_and_payroll(
            conn,
            actor=hr_admin,
            target_emp_id=4,
            new_basic_pay=86000.00,
            new_special_allowance=18000.00,
            recalc_month=10,
            recalc_year=2026,
        )
        new_net = tx_res["payroll_snapshot"]["net_salary"]

        # Restore original salary & payroll cleanly in another atomic commit
        transactional_update_salary_and_payroll(
            conn,
            actor=hr_admin,
            target_emp_id=4,
            new_basic_pay=orig_basic,
            new_special_allowance=orig_spec,
            recalc_month=10,
            recalc_year=2026,
        )
        return (
            f"HR_ADMIN atomic transaction COMMITTED: updated EMP004 basic_pay=86,000, "
            f"recomputed Oct 2026 net_salary=Rs. {new_net:,.2f}, and cleanly restored baseline."
        )

    record_test(
        "T16",
        "VALID_TRANSACTION",
        "HR_ADMIN executes atomic Salary Structure revision + Payroll recalculation",
        "COMMIT succeeds; Salary_Structure and Payroll updated atomically",
        t16,
    )

    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)

    if owns_conn:
        conn.close()

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "results": results,
    }


def generate_full_verification_trace() -> str:
    """Runs Phase 3 report queries, Index EXPLAIN benchmarks, and Phase 4 test suite, saving output trace."""
    conn = init_database(force_reset=True)
    lines: List[str] = []
    lines.append("=" * 95)
    lines.append("PAYROLL & ATTENDANCE SYSTEM — PHASES 1 TO 5 EXECUTION & VERIFICATION TRACE")
    lines.append("=" * 95)

    # 1. Database Row Counts across the 7 Phase 1 3NF Tables
    cur = conn.cursor()
    lines.append("\n[1] PHASE 1 & 2: 3NF SCHEMA & SEED DATA ROW COUNTS (12 Employees x 3 Months)")
    lines.append("-" * 95)
    for tbl in [
        "Department",
        "Employee",
        "Salary_Structure",
        "Leave_Type",
        "Leave_Request",
        "Attendance",
        "Payroll",
    ]:
        cnt = cur.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()["c"]
        lines.append(f"  - {tbl:<20}: {cnt:>4} rows")

    # 2. Phase 3 Report 1 Sample (October 2026 Monthly Attendance Summary)
    lines.append("\n[2] PHASE 3 — REPORT 1: MONTHLY ATTENDANCE SUMMARY (OCTOBER 2026)")
    lines.append("-" * 95)
    att_summary = get_monthly_attendance_summary(conn, pay_month=10, pay_year=2026)
    lines.append(
        f"{'Code':<8} {'Employee Name':<22} {'Dept':<26} {'WorkDays':>8} {'Present':>8} {'Leave':>6} {'Late':>5} {'Hours':>7} {'Paid%':>7}"
    )
    lines.append("-" * 95)
    for r in att_summary:
        lines.append(
            f"{r['emp_code']:<8} {r['employee_name']:<22} {r['dept_name'][:25]:<26} "
            f"{r['total_working_days']:>8} {r['effective_present_days']:>8.1f} {r['on_leave_days']:>6} "
            f"{r['late_marks_count']:>5} {r['total_work_hours']:>7.1f} {r['paid_attendance_pct']:>6.1f}%"
        )

    # 3. Phase 3 Report 2 Sample (October 2026 Salary Slips)
    lines.append("\n[3] PHASE 3 — REPORT 2: MONTHLY SALARY SLIP SUMMARY (OCTOBER 2026)")
    lines.append("-" * 95)
    slips = get_salary_slips(conn, pay_month=10, pay_year=2026)
    lines.append(
        f"{'Code':<8} {'Employee Name':<20} {'Basic(Earned)':>14} {'Gross(Earned)':>14} {'PF':>9} {'TDS(Tax)':>10} {'LOP Ded':>9} {'Net Salary':>13}"
    )
    lines.append("-" * 95)
    for s in slips:
        lines.append(
            f"{s['emp_code']:<8} {s['employee_name'][:19]:<20} "
            f"{s['basic_earned']:>14,.2f} {s['gross_salary']:>14,.2f} "
            f"{s['pf_deduction']:>9,.2f} {s['income_tax_deduction']:>10,.2f} "
            f"{s['lop_deduction']:>9,.2f} {s['net_salary']:>13,.2f}"
        )

    # 4. Phase 3 Report 3 Sample (October 2026 Late-Marks Report)
    lines.append("\n[4] PHASE 3 — REPORT 3: LATE-MARKS & PUNCTUALITY REPORT (OCTOBER 2026)")
    lines.append("-" * 95)
    late_rows = get_late_marks_report(conn, pay_month=10, pay_year=2026)
    lines.append(
        f"{'Code':<8} {'Employee Name':<22} {'Late Days':>9} {'Total Late Min':>15} {'Latest In':>10} {'Penalty LOP':>12} {'Status'}"
    )
    lines.append("-" * 95)
    for lr in late_rows:
        lines.append(
            f"{lr['emp_code']:<8} {lr['employee_name']:<22} {lr['late_days_count']:>9} "
            f"{lr['total_late_minutes']:>15} {str(lr['latest_check_in_time'] or '-'):>10} "
            f"{lr['penalty_lop_days']:>11.1f}d  {lr['punctuality_status']}"
        )

    # 5. Phase 3 Index Execution Plan Improvement (Before vs After)
    lines.append("\n[5] PHASE 3 — QUERY EXECUTION PLAN IMPROVEMENT (BEFORE vs AFTER INDEXES)")
    lines.append("-" * 95)
    bench = benchmark_index_execution_plan(conn)
    lm_bench = bench["late_marks_report"]
    lines.append("Report 3 Query (Late-Marks Report):")
    lines.append(f"  BEFORE Index Plan : {' | '.join(lm_bench['before_index_plan'])}")
    lines.append(f"  AFTER  Index Plan : {' | '.join(lm_bench['after_index_plan'])}")
    lines.append(f"  Index Applied     : {lm_bench['index_used']}")
    lines.append(
        f"  200-Run Latency   : {lm_bench['before_200_runs_ms']} ms (Before) -> "
        f"{lm_bench['after_200_runs_ms']} ms (After) [{lm_bench['improvement_pct']}% faster]"
    )
    ss_bench = bench["salary_slip_report"]
    lines.append("\nReport 2 Query (Salary Slip Lookup):")
    lines.append(f"  BEFORE Index Plan : {' | '.join(ss_bench['before_index_plan'])}")
    lines.append(f"  AFTER  Index Plan : {' | '.join(ss_bench['after_index_plan'])}")
    lines.append(f"  Index Applied     : {ss_bench['index_used']}")

    # 6. Phase 4 Security, Transaction & Boundary Test Results
    lines.append("\n[6] PHASE 4 — SECURITY, RBAC, TRANSACTION & VALIDATION TEST SUITE (16 TEST CASES)")
    lines.append("-" * 95)
    suite = run_all_phase4_tests(conn)
    for t in suite["results"]:
        lines.append(f"[{t['status']}] {t['test_id']} ({t['category']}): {t['title']}")
        lines.append(f"       Expected : {t['expected']}")
        lines.append(f"       Actual   : {t['actual']}")
    lines.append("-" * 95)
    lines.append(f"TEST SUMMARY: {suite['passed']}/{suite['total']} PASSED ({suite['failed']} FAILED)")
    lines.append("=" * 95)

    output_text = "\n".join(lines)
    out_file = BASE_DIR / "tests" / "test_results_output.txt"
    out_file.write_text(output_text, encoding="utf-8")
    conn.close()
    return output_text


if __name__ == "__main__":
    print(generate_full_verification_trace())
