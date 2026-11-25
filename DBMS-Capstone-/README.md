# Payroll & Attendance Management System (Phases 1–5)

**Group Leader:** Harshwardhan (`Roll No: 2501730330`)  
**Group Members:** Tanish Kumar, Surya Pratap, Shreshth Mathur, Aarush Rajput  
**Program:** B.Tech CSE (AI/ML) — Section C | **University:** School of Engineering & Technology, K.R. Mangalam University

A complete, end-to-end relational database and role-based web application implementing all **five sequential phases** of the **Payroll & Attendance System** specification. Every phase strictly uses the immutable **Phase 1 Third Normal Form (3NF)** schema across SQL scripts, stored functions/procedures, validation triggers, indexed analytical views, RBAC security policies, ACID transactions, automated test cases, and the interactive Flask Web UI.

---

## Project Directory Structure

```text
payroll_attendance_system/
├── README.md                              # Setup, architecture, and execution guide
├── app.py                                 # Phase 5: Role-Based Flask Web Application
├── templates/
│   └── index.html                         # Phase 5: HR_ADMIN & EMPLOYEE Interactive Portal
├── backend/
│   ├── __init__.py
│   ├── db.py                              # Phase 1-3 Database Initializer & 3-Month Seed Generator
│   ├── procedures.py                      # Phase 2: Stored Functions & Payroll Stored Procedures
│   ├── reports.py                         # Phase 3: Report Queries & EXPLAIN Plan Benchmark
│   └── rbac.py                            # Phase 4: RBAC Security Guards & ACID Transactions
├── sql/
│   ├── phase1_schema_ddl.sql              # Phase 1 & 2A: 3NF Relational Schema DDL (7 Tables)
│   ├── phase2_procedures_triggers.sql     # Phase 2B: Validation Triggers + Stored Functions/Procedures
│   ├── phase2_seed_data.sql               # Phase 2C: Exported SQL Seed Data (12 Employees x 3 Months)
│   ├── phase3_reports_and_indexes.sql     # Phase 3: 3 Analytical Report Views + Composite Indexes
│   └── phase4_rbac_and_transactions.sql   # Phase 4: GRANT/REVOKE, Row-Level Security & ACID Patterns
├── tests/
│   ├── run_phase4_tests.py                # Phase 4: Automated 16-Case Verification & EXPLAIN Suite
│   └── test_results_output.txt            # Saved Execution Trace (Reports + EXPLAIN + 16/16 Tests)
└── docs/
    └── PROJECT_REPORT_PHASES_1_TO_5.md    # Complete Phase 1–5 Academic Report & Scaling Analysis
```

---

## Quick Start Instructions

### 1. Run the Phase 1–4 Verification & 16-Case Automated Test Suite
```bash
cd /Users/harshwardhan/.gemini/antigravity/scratch/payroll_attendance_system
python3 tests/run_phase4_tests.py
```
This initializes `database/payroll_system.db` using the exact Phase 1 DDL, creates all Phase 2 triggers and stored functions, seeds 12 employees across 3 months (August, September, October 2026 — 780 attendance rows, 20 leave requests, 36 payroll records), generates the three Phase 3 analytical reports, benchmarks the `EXPLAIN QUERY PLAN` before and after indexing, and runs all **16 Phase 4 test cases (16/16 PASS)**.

### 2. Launch the Phase 5 Role-Based Web Application
```bash
cd /Users/harshwardhan/.gemini/antigravity/scratch/payroll_attendance_system
python3 app.py
```
Then open **`http://127.0.0.1:5050`** in your browser.

---

## Demo Accounts & Role-Based Access Control (RBAC)

Use the **Active Session (RBAC)** dropdown in the top navigation bar to switch instantaneously between roles:

| Employee Code | Name | Role | Access Scope |
| :--- | :--- | :--- | :--- |
| **`EMP001`** | Aarav Mehta (HR Director) | `HR_ADMIN` | Full CRUD access: onboard employees, revise salary structures in atomic transactions, run `sp_process_bulk_payroll`, approve/reject leaves, log attendance, and view organization-wide reports. |
| **`EMP002`** | Neha Kulkarni (Sr. HR Specialist) | `HR_ADMIN` | Full administrative access. |
| **`EMP003`** | Rohan Verma (Principal Architect) | `EMPLOYEE` | **Row-Level Scoped (`emp_id = 3`)**: Read-only access to own salary slip, own attendance summary, and own punctuality logs; can submit own leave requests; blocked (`HTTP 403 RBAC_ACCESS_DENIED`) from viewing other employees' records or mutating salary/payroll. |
| **`EMP007`** | Vikram Rathore (DevOps Lead) | `EMPLOYEE` | **Row-Level Scoped (`emp_id = 7`)**: Demonstrates 6 late arrivals in October 2026 (`1.0 day` LOP penalty) and itemized LOP deduction on payslip. |
