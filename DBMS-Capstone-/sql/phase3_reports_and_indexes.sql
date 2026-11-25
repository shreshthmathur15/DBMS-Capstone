-- ============================================================================
-- PHASE 3: QUERY & REPORT DEVELOPMENT + INDEX OPTIMIZATION
-- Uses the exact Phase 1 3NF Schema & Phase 2 Data
-- ============================================================================

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_monthly_attendance_summary;
DROP VIEW IF EXISTS v_employee_salary_slip;
DROP VIEW IF EXISTS v_late_marks_report;

-- ----------------------------------------------------------------------------
-- REPORT 1: MONTHLY ATTENDANCE SUMMARY VIEW & QUERY
-- Aggregates attendance by employee and (year, month)
-- ----------------------------------------------------------------------------
CREATE VIEW v_monthly_attendance_summary AS
SELECT
    e.emp_id,
    e.emp_code,
    e.first_name || ' ' || e.last_name AS employee_name,
    d.dept_name,
    e.designation,
    CAST(strftime('%Y', a.att_date) AS INTEGER) AS att_year,
    CAST(strftime('%m', a.att_date) AS INTEGER) AS att_month,
    strftime('%Y-%m', a.att_date)               AS period_label,
    COUNT(a.attendance_id)                      AS total_working_days,
    SUM(CASE WHEN a.att_status = 'PRESENT'  THEN 1 ELSE 0 END) AS full_present_days,
    SUM(CASE WHEN a.att_status = 'HALF_DAY' THEN 1 ELSE 0 END) AS half_days,
    SUM(CASE WHEN a.att_status = 'ON_LEAVE' THEN 1 ELSE 0 END) AS on_leave_days,
    SUM(CASE WHEN a.att_status = 'ABSENT'   THEN 1 ELSE 0 END) AS absent_days,
    ROUND(SUM(
        CASE
            WHEN a.att_status = 'PRESENT'  THEN 1.0
            WHEN a.att_status = 'HALF_DAY' THEN 0.5
            ELSE 0.0
        END
    ), 1) AS effective_present_days,
    SUM(CASE WHEN a.is_late = 1 THEN 1 ELSE 0 END) AS late_marks_count,
    ROUND(SUM(a.work_hours), 2) AS total_work_hours,
    ROUND(AVG(CASE WHEN a.work_hours > 0 THEN a.work_hours END), 2) AS avg_daily_hours,
    ROUND(
        (SUM(CASE WHEN a.att_status = 'PRESENT' THEN 1.0
                  WHEN a.att_status = 'HALF_DAY' THEN 0.5
                  WHEN a.att_status = 'ON_LEAVE' THEN 1.0
                  ELSE 0.0 END) * 100.0) / COUNT(a.attendance_id),
        2
    ) AS paid_attendance_pct
FROM Employee e
JOIN Department d ON e.dept_id = d.dept_id
JOIN Attendance a ON e.emp_id = a.emp_id
GROUP BY
    e.emp_id, e.emp_code, e.first_name, e.last_name,
    d.dept_name, e.designation,
    strftime('%Y', a.att_date), strftime('%m', a.att_date);


-- ----------------------------------------------------------------------------
-- REPORT 2: ITEMIZED EMPLOYEE SALARY SLIP VIEW & QUERY
-- Joins Employee, Department, Salary_Structure, and Payroll
-- ----------------------------------------------------------------------------
CREATE VIEW v_employee_salary_slip AS
SELECT
    p.payroll_id,
    p.pay_month,
    p.pay_year,
    printf('%04d-%02d', p.pay_year, p.pay_month) AS pay_period,
    e.emp_id,
    e.emp_code,
    e.first_name || ' ' || e.last_name AS employee_name,
    e.email,
    e.designation,
    e.hire_date,
    d.dept_code,
    d.dept_name,
    d.base_location,
    -- Standard Contractual Structure
    ss.basic_pay AS contracted_basic,
    ROUND(ss.basic_pay * ss.hra_percent / 100.0, 2) AS contracted_hra,
    ROUND(ss.basic_pay * ss.da_percent / 100.0, 2)  AS contracted_da,
    ss.special_allowance AS contracted_special_allowance,
    ROUND(
        ss.basic_pay
        + (ss.basic_pay * ss.hra_percent / 100.0)
        + (ss.basic_pay * ss.da_percent / 100.0)
        + ss.special_allowance,
        2
    ) AS contracted_gross,
    -- Monthly Attendance & Leave Summary on Slip
    p.working_days,
    p.present_days,
    p.paid_leave_days,
    p.lop_days,
    p.late_count,
    p.late_penalty_days,
    -- Earned Components
    p.basic_earned,
    p.hra_earned,
    p.da_earned,
    p.special_allowance_earned,
    p.gross_salary,
    -- Statutory & Attendance Deductions
    p.pf_deduction,
    p.professional_tax,
    p.income_tax_deduction,
    p.lop_deduction,
    p.total_deductions,
    p.net_salary,
    p.payment_status,
    p.processed_at
FROM Payroll p
JOIN Employee e          ON p.emp_id = e.emp_id
JOIN Department d        ON e.dept_id = d.dept_id
JOIN Salary_Structure ss ON e.emp_id = ss.emp_id;


-- ----------------------------------------------------------------------------
-- REPORT 3: LATE-MARKS & PUNCTUALITY DISCIPLINARY REPORT VIEW & QUERY
-- Tracks late check-ins (after standard_check_in 09:15:00), total late minutes,
-- and LOP penalty conversion (every 3 late marks = 0.5 day LOP deduction).
-- ----------------------------------------------------------------------------
CREATE VIEW v_late_marks_report AS
SELECT
    e.emp_id,
    e.emp_code,
    e.first_name || ' ' || e.last_name AS employee_name,
    d.dept_name,
    e.designation,
    ss.standard_check_in,
    CAST(strftime('%Y', a.att_date) AS INTEGER) AS att_year,
    CAST(strftime('%m', a.att_date) AS INTEGER) AS att_month,
    strftime('%Y-%m', a.att_date)               AS period_label,
    COUNT(CASE WHEN a.is_late = 1 THEN 1 END)   AS late_days_count,
    COALESCE(SUM(a.late_minutes), 0)            AS total_late_minutes,
    COALESCE(ROUND(AVG(CASE WHEN a.is_late = 1 THEN a.late_minutes END), 1), 0.0) AS avg_late_minutes_when_late,
    COALESCE(MAX(a.late_minutes), 0)            AS max_late_minutes,
    MAX(CASE WHEN a.is_late = 1 THEN a.check_in END) AS latest_check_in_time,
    ROUND((CAST(COUNT(CASE WHEN a.is_late = 1 THEN 1 END) / 3 AS INTEGER)) * 0.5, 1) AS penalty_lop_days,
    CASE
        WHEN COUNT(CASE WHEN a.is_late = 1 THEN 1 END) = 0 THEN 'EXCELLENT (0 Late)'
        WHEN COUNT(CASE WHEN a.is_late = 1 THEN 1 END) <= 2 THEN 'WARNING (1-2 Late)'
        ELSE 'PENALTY APPLIED (3+ Late -> LOP)'
    END AS punctuality_status
FROM Employee e
JOIN Department d        ON e.dept_id = d.dept_id
JOIN Salary_Structure ss ON e.emp_id = ss.emp_id
JOIN Attendance a        ON e.emp_id = a.emp_id
GROUP BY
    e.emp_id, e.emp_code, e.first_name, e.last_name,
    d.dept_name, e.designation, ss.standard_check_in,
    strftime('%Y', a.att_date), strftime('%m', a.att_date);


-- ============================================================================
-- SECTION 2: PERFORMANCE INDEXES FOR PHASE 3 REPORTS
-- ============================================================================

-- Composite covering index for Attendance reports (Monthly Attendance & Late-Marks)
CREATE INDEX IF NOT EXISTS idx_attendance_emp_date_late
    ON Attendance (emp_id, att_date, is_late, att_status, late_minutes, work_hours);

-- Equality-first + date-range composite covering index for Late-Marks Report scans
CREATE INDEX IF NOT EXISTS idx_attendance_date_late_emp
    ON Attendance (is_late, att_date, emp_id, late_minutes, check_in);

-- Composite index for Payroll period & employee lookups (Salary Slip Report)
CREATE INDEX IF NOT EXISTS idx_payroll_period_emp
    ON Payroll (pay_year, pay_month, emp_id);

-- Composite index for Leave overlap validation trigger & report lookups
CREATE INDEX IF NOT EXISTS idx_leave_emp_status_dates
    ON Leave_Request (emp_id, status, start_date, end_date);
