-- ============================================================================
-- PHASE 4: SECURITY, ROLE-BASED ACCESS CONTROL (RBAC) & TRANSACTION MANAGEMENT
-- Uses the exact Phase 1–3 Schema & Views
-- ============================================================================

/*
===============================================================================
SECTION 1: POSTGRESQL / MYSQL 8.0 NATIVE RBAC (GRANT, REVOKE & RLS POLICIES)
===============================================================================

-- 1. Create Database Roles
CREATE ROLE role_hr_admin NOLOGIN;
CREATE ROLE role_employee NOLOGIN;

-- 2. HR / Admin Role: Full Privileges across all 7 tables and views
GRANT SELECT, INSERT, UPDATE, DELETE ON Department       TO role_hr_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON Employee         TO role_hr_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON Salary_Structure TO role_hr_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON Leave_Type       TO role_hr_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON Leave_Request    TO role_hr_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON Attendance       TO role_hr_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON Payroll          TO role_hr_admin;
GRANT SELECT ON v_monthly_attendance_summary, v_employee_salary_slip, v_late_marks_report TO role_hr_admin;

-- 3. Employee Role: Strictly Read-Only on Own Records (+ Submit Own Leave Request)
REVOKE ALL PRIVILEGES ON Department, Employee, Salary_Structure, Leave_Type, Leave_Request, Attendance, Payroll FROM role_employee;

GRANT SELECT ON Department, Leave_Type TO role_employee;
GRANT SELECT ON Employee, Salary_Structure, Attendance, Payroll, Leave_Request TO role_employee;
GRANT INSERT (emp_id, leave_type_id, start_date, end_date, reason) ON Leave_Request TO role_employee;

-- 4. Row-Level Security (RLS) in PostgreSQL so Employee can ONLY see own rows
ALTER TABLE Employee         ENABLE ROW LEVEL SECURITY;
ALTER TABLE Salary_Structure ENABLE ROW LEVEL SECURITY;
ALTER TABLE Attendance       ENABLE ROW LEVEL SECURITY;
ALTER TABLE Leave_Request    ENABLE ROW LEVEL SECURITY;
ALTER TABLE Payroll          ENABLE ROW LEVEL SECURITY;

-- HR Admin bypasses RLS (full access)
CREATE POLICY hr_admin_all_access ON Payroll
    TO role_hr_admin USING (true) WITH CHECK (true);

-- Employee can only SELECT rows matching their authenticated session emp_id
CREATE POLICY emp_self_read_payroll ON Payroll
    FOR SELECT TO role_employee
    USING (emp_id = current_setting('app.current_emp_id')::INTEGER);

CREATE POLICY emp_self_read_attendance ON Attendance
    FOR SELECT TO role_employee
    USING (emp_id = current_setting('app.current_emp_id')::INTEGER);

CREATE POLICY emp_self_read_salary ON Salary_Structure
    FOR SELECT TO role_employee
    USING (emp_id = current_setting('app.current_emp_id')::INTEGER);

CREATE POLICY emp_self_leave_access ON Leave_Request
    FOR ALL TO role_employee
    USING (emp_id = current_setting('app.current_emp_id')::INTEGER)
    WITH CHECK (emp_id = current_setting('app.current_emp_id')::INTEGER);
*/

-- ============================================================================
-- SECTION 2: TRANSACTIONAL SALARY & PAYROLL UPDATE PATTERNS (COMMIT / ROLLBACK)
-- ============================================================================

/*
-- Pattern A: Atomic Salary Revision & Payroll Recalculation (COMMIT on success)
BEGIN TRANSACTION;

SAVEPOINT sp_before_salary_revision;

UPDATE Salary_Structure
   SET basic_pay         = 95000.00,
       special_allowance = 18000.00,
       effective_from    = '2026-10-01'
 WHERE emp_id = 3;

-- Re-compute October 2026 payroll inside the same transaction
CALL sp_process_monthly_payroll(3, 10, 2026);

-- Verify net_salary integrity before committing
COMMIT;


-- Pattern B: Automatic ROLLBACK when a constraint or trigger fails mid-transaction
BEGIN TRANSACTION;

UPDATE Salary_Structure
   SET basic_pay = -15000.00   -- Violates CHECK (basic_pay > 0) & trg_validate_salary_positive_update
 WHERE emp_id = 3;

-- Database raises ABORT/ERROR; transaction rolls back completely so Salary_Structure
-- and Payroll remain untouched.
ROLLBACK;
*/
