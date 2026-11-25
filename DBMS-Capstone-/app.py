"""
Phase 5: Integrated Role-Based Web Application (Flask).
Connects directly to the Phase 1–4 SQLite database, stored functions/procedures,
triggers, report views, indexes, and RBAC + ACID transaction layer.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.db import get_connection, hash_password, init_database
from backend.rbac import (
    ActorContext,
    PermissionDeniedError,
    get_actor_by_emp_id,
    rbac_get_attendance_logs,
    rbac_get_attendance_summary,
    rbac_get_employee_profile,
    rbac_get_late_marks_report,
    rbac_get_leave_requests,
    rbac_get_salary_slips,
    rbac_list_employees,
    transactional_create_employee,
    transactional_decide_leave_request,
    transactional_record_attendance,
    transactional_run_payroll,
    transactional_submit_leave_request,
    transactional_update_salary_and_payroll,
)
from backend.reports import benchmark_index_execution_plan
from tests.run_phase4_tests import run_all_phase4_tests

app = Flask(__name__)
app.secret_key = "payroll-attendance-dbms-phase5-secret-key"

# Ensure database is initialized on startup
init_database(force_reset=False).close()


def get_current_actor(conn) -> ActorContext:
    """Resolves the active user from session or query param, defaulting to EMP001 (HR_ADMIN)."""
    emp_id = session.get("emp_id", 1)
    try:
        return get_actor_by_emp_id(conn, int(emp_id))
    except Exception:
        session["emp_id"] = 1
        return get_actor_by_emp_id(conn, 1)


@app.route("/")
def dashboard():
    conn = get_connection()
    try:
        # Optional quick role switch via ?switch_emp_id=
        switch_id = request.args.get("switch_emp_id")
        if switch_id:
            session["emp_id"] = int(switch_id)

        actor = get_current_actor(conn)
        pay_month = int(request.args.get("month", 10))
        pay_year = int(request.args.get("year", 2026))
        slip_emp_id = request.args.get("slip_emp_id")
        if slip_emp_id:
            selected_slip_emp_id = int(slip_emp_id)
        else:
            selected_slip_emp_id = actor.emp_id if actor.role == "EMPLOYEE" else 3

        cur = conn.cursor()
        # List all accounts for the top-bar Role Switcher (demo convenience)
        cur.execute(
            """
            SELECT e.emp_id, e.emp_code, e.first_name || ' ' || e.last_name AS full_name,
                   e.role, e.designation, d.dept_name
            FROM Employee e
            JOIN Department d ON e.dept_id = d.dept_id
            WHERE e.status = 'ACTIVE'
            ORDER BY CASE WHEN e.role = 'HR_ADMIN' THEN 0 ELSE 1 END, e.emp_id ASC
            """
        )
        all_accounts = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM Department ORDER BY dept_id ASC")
        departments = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM Leave_Type ORDER BY leave_type_id ASC")
        leave_types = [dict(r) for r in cur.fetchall()]

        # RBAC-scoped data fetches
        employees = rbac_list_employees(conn, actor)
        attendance_summary = rbac_get_attendance_summary(
            conn, actor, pay_month=pay_month if pay_month > 0 else None, pay_year=pay_year
        )
        salary_slips = rbac_get_salary_slips(
            conn, actor, pay_month=pay_month if pay_month > 0 else None, pay_year=pay_year
        )
        late_report = rbac_get_late_marks_report(
            conn, actor, pay_month=pay_month if pay_month > 0 else None, pay_year=pay_year
        )
        leave_requests = rbac_get_leave_requests(conn, actor)
        attendance_logs = rbac_get_attendance_logs(
            conn,
            actor,
            pay_month=pay_month if pay_month > 0 else None,
            pay_year=pay_year,
            limit=60,
        )

        # Detailed single employee salary slip for printable slip card
        try:
            active_slip_list = rbac_get_salary_slips(
                conn,
                actor,
                pay_month=pay_month if pay_month > 0 else 10,
                pay_year=pay_year,
                target_emp_id=selected_slip_emp_id,
            )
            featured_slip = active_slip_list[0] if active_slip_list else (salary_slips[0] if salary_slips else None)
        except PermissionDeniedError:
            featured_slip = salary_slips[0] if salary_slips else None

        # KPI Summary Metrics
        total_net_payroll = round(sum(float(s["net_salary"]) for s in salary_slips), 2)
        total_gross_payroll = round(sum(float(s["gross_salary"]) for s in salary_slips), 2)
        total_tax_deducted = round(sum(float(s["income_tax_deduction"]) for s in salary_slips), 2)
        total_late_events = sum(int(r["late_days_count"]) for r in late_report)
        pending_leaves_count = sum(1 for lr in leave_requests if lr["status"] == "PENDING")
        avg_attendance_pct = (
            round(
                sum(float(a["paid_attendance_pct"]) for a in attendance_summary) / len(attendance_summary),
                1,
            )
            if attendance_summary
            else 0.0
        )

        # Schema row counts for Phase 1–2 badge
        table_counts = {}
        for tbl in [
            "Department",
            "Employee",
            "Salary_Structure",
            "Leave_Type",
            "Leave_Request",
            "Attendance",
            "Payroll",
        ]:
            table_counts[tbl] = cur.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()["c"]

        return render_template(
            "index.html",
            actor=actor,
            all_accounts=all_accounts,
            departments=departments,
            leave_types=leave_types,
            employees=employees,
            attendance_summary=attendance_summary,
            salary_slips=salary_slips,
            featured_slip=featured_slip,
            selected_slip_emp_id=selected_slip_emp_id,
            late_report=late_report,
            leave_requests=leave_requests,
            attendance_logs=attendance_logs,
            pay_month=pay_month,
            pay_year=pay_year,
            kpis={
                "visible_employees": len(employees),
                "total_net_payroll": total_net_payroll,
                "total_gross_payroll": total_gross_payroll,
                "total_tax_deducted": total_tax_deducted,
                "total_late_events": total_late_events,
                "pending_leaves_count": pending_leaves_count,
                "avg_attendance_pct": avg_attendance_pct,
            },
            table_counts=table_counts,
        )
    finally:
        conn.close()


@app.route("/api/switch-role", methods=["POST"])
def api_switch_role():
    data = request.get_json(silent=True) or request.form
    emp_id = int(data.get("emp_id", 1))
    conn = get_connection()
    try:
        actor = get_actor_by_emp_id(conn, emp_id)
        session["emp_id"] = actor.emp_id
        return jsonify({"ok": True, "actor": actor.__dict__})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/salary-slip/<int:target_emp_id>", methods=["GET"])
def api_get_employee_salary_slip(target_emp_id: int):
    """RBAC-protected endpoint to fetch a specific employee's salary slip."""
    pay_month = int(request.args.get("month", 10))
    pay_year = int(request.args.get("year", 2026))
    conn = get_connection()
    try:
        actor = get_current_actor(conn)
        slips = rbac_get_salary_slips(
            conn, actor, pay_month=pay_month, pay_year=pay_year, target_emp_id=target_emp_id
        )
        if not slips:
            return jsonify({"ok": False, "error": "No salary slip found for the selected period."}), 404
        return jsonify({"ok": True, "actor": actor.__dict__, "slip": slips[0]})
    except PermissionDeniedError as exc:
        return jsonify({"ok": False, "error_type": "RBAC_FORBIDDEN", "error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/admin/update-salary", methods=["POST"])
def api_update_salary():
    """Phase 4 Transactional Salary Structure Update + Payroll Recalculation."""
    data = request.get_json(silent=True) or request.form
    conn = get_connection()
    try:
        actor = get_current_actor(conn)
        res = transactional_update_salary_and_payroll(
            conn,
            actor=actor,
            target_emp_id=int(data["emp_id"]),
            new_basic_pay=float(data["basic_pay"]),
            new_special_allowance=float(data.get("special_allowance", 10000.0)),
            recalc_month=int(data.get("recalc_month", 10)),
            recalc_year=int(data.get("recalc_year", 2026)),
        )
        return jsonify({"ok": True, "result": res})
    except PermissionDeniedError as exc:
        return jsonify({"ok": False, "error_type": "RBAC_FORBIDDEN", "error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error_type": "TRANSACTION_ROLLED_BACK", "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/admin/create-employee", methods=["POST"])
def api_create_employee():
    """Phase 4 Transactional New Employee + 1:1 Salary Structure Creation."""
    data = request.get_json(silent=True) or request.form
    conn = get_connection()
    try:
        actor = get_current_actor(conn)
        emp = transactional_create_employee(
            conn,
            actor=actor,
            emp_code=str(data["emp_code"]),
            first_name=str(data["first_name"]),
            last_name=str(data["last_name"]),
            email=str(data["email"]),
            phone=str(data["phone"]),
            hire_date=str(data.get("hire_date", "2026-10-01")),
            designation=str(data["designation"]),
            dept_id=int(data["dept_id"]),
            basic_pay=float(data["basic_pay"]),
            special_allowance=float(data.get("special_allowance", 10000.0)),
            role=str(data.get("role", "EMPLOYEE")),
        )
        return jsonify({"ok": True, "employee": emp})
    except PermissionDeniedError as exc:
        return jsonify({"ok": False, "error_type": "RBAC_FORBIDDEN", "error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error_type": "TRANSACTION_ROLLED_BACK", "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/admin/run-payroll", methods=["POST"])
def api_run_payroll():
    """Phase 2 & 4 Transactional Monthly Payroll Execution."""
    data = request.get_json(silent=True) or request.form
    conn = get_connection()
    try:
        actor = get_current_actor(conn)
        pay_month = int(data.get("pay_month", 10))
        pay_year = int(data.get("pay_year", 2026))
        emp_id_raw = data.get("emp_id")
        target_emp_id = int(emp_id_raw) if emp_id_raw not in (None, "", "ALL") else None
        rows = transactional_run_payroll(
            conn,
            actor=actor,
            pay_month=pay_month,
            pay_year=pay_year,
            target_emp_id=target_emp_id,
            payment_status=str(data.get("payment_status", "PROCESSED")),
        )
        return jsonify(
            {
                "ok": True,
                "processed_count": len(rows),
                "pay_month": pay_month,
                "pay_year": pay_year,
            }
        )
    except PermissionDeniedError as exc:
        return jsonify({"ok": False, "error_type": "RBAC_FORBIDDEN", "error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error_type": "TRANSACTION_ROLLED_BACK", "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/admin/record-attendance", methods=["POST"])
def api_record_attendance():
    """Phase 2 & 4 Transactional Attendance Entry (with Trigger Validation)."""
    data = request.get_json(silent=True) or request.form
    conn = get_connection()
    try:
        actor = get_current_actor(conn)
        row = transactional_record_attendance(
            conn,
            actor=actor,
            emp_id=int(data["emp_id"]),
            att_date=str(data["att_date"]),
            att_status=str(data["att_status"]),
            check_in=str(data.get("check_in") or "").strip() or None,
            check_out=str(data.get("check_out") or "").strip() or None,
            remarks=str(data.get("remarks") or "").strip() or None,
        )
        return jsonify({"ok": True, "attendance": row})
    except PermissionDeniedError as exc:
        return jsonify({"ok": False, "error_type": "RBAC_FORBIDDEN", "error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error_type": "TRIGGER_OR_CONSTRAINT_REJECTED", "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/leave/submit", methods=["POST"])
def api_submit_leave():
    """Phase 2 & 4 Transactional Leave Request Submission (Self or HR_ADMIN)."""
    data = request.get_json(silent=True) or request.form
    conn = get_connection()
    try:
        actor = get_current_actor(conn)
        target_emp_id = int(data.get("emp_id", actor.emp_id))
        lr = transactional_submit_leave_request(
            conn,
            actor=actor,
            target_emp_id=target_emp_id,
            leave_type_id=int(data["leave_type_id"]),
            start_date=str(data["start_date"]),
            end_date=str(data["end_date"]),
            reason=str(data["reason"]),
        )
        return jsonify({"ok": True, "leave_request": lr})
    except PermissionDeniedError as exc:
        return jsonify({"ok": False, "error_type": "RBAC_FORBIDDEN", "error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error_type": "TRIGGER_OR_CONSTRAINT_REJECTED", "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/admin/decide-leave", methods=["POST"])
def api_decide_leave():
    """Phase 4 Transactional Leave Approval / Rejection (HR_ADMIN only)."""
    data = request.get_json(silent=True) or request.form
    conn = get_connection()
    try:
        actor = get_current_actor(conn)
        lr = transactional_decide_leave_request(
            conn,
            actor=actor,
            leave_id=int(data["leave_id"]),
            new_status=str(data["status"]),
        )
        return jsonify({"ok": True, "leave_request": lr})
    except PermissionDeniedError as exc:
        return jsonify({"ok": False, "error_type": "RBAC_FORBIDDEN", "error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error_type": "TRANSACTION_ROLLED_BACK", "error": str(exc)}), 400
    finally:
        conn.close()


@app.route("/api/diagnostics/explain-and-tests", methods=["GET"])
def api_explain_and_tests():
    """Runs Phase 3 EXPLAIN QUERY PLAN benchmark and Phase 4 16-case test suite live."""
    conn = get_connection()
    try:
        explain_bench = benchmark_index_execution_plan(conn)
        test_suite = run_all_phase4_tests(conn)
        return jsonify(
            {
                "ok": True,
                "explain_benchmark": explain_bench,
                "test_suite": test_suite,
            }
        )
    finally:
        conn.close()


@app.route("/api/admin/reset-demo-db", methods=["POST"])
def api_reset_demo_db():
    """Resets the database back to the clean Phase 2 12-employee x 3-month seed state."""
    conn = init_database(force_reset=True)
    conn.close()
    session["emp_id"] = 1
    return jsonify({"ok": True, "message": "Database reset to initial Phase 2 seed state."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050)) if "os" in globals() else 5050
    app.run(host="127.0.0.1", port=port, debug=False)
