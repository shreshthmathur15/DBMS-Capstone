-- ============================================================================
-- PHASE 2 (Part B): STORED FUNCTIONS, PROCEDURES & VALIDATION TRIGGERS
-- Uses the exact Phase 1 3NF Schema (Department, Employee, Salary_Structure,
-- Leave_Type, Leave_Request, Attendance, Payroll)
-- ============================================================================

PRAGMA foreign_keys = ON;

DROP TRIGGER IF EXISTS trg_validate_leave_overlap_insert;
DROP TRIGGER IF EXISTS trg_validate_leave_overlap_update;
DROP TRIGGER IF EXISTS trg_validate_leave_quota_insert;
DROP TRIGGER IF EXISTS trg_validate_attendance_before_insert;
DROP TRIGGER IF EXISTS trg_validate_attendance_before_update;
DROP TRIGGER IF EXISTS trg_compute_attendance_metrics_insert;
DROP TRIGGER IF EXISTS trg_compute_attendance_metrics_update;
DROP TRIGGER IF EXISTS trg_validate_salary_positive_insert;
DROP TRIGGER IF EXISTS trg_validate_salary_positive_update;

-- ============================================================================
-- SECTION 1: DATABASE TRIGGERS FOR LEAVE & ATTENDANCE VALIDATION
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Trigger 1A: Reject invalid or overlapping leave dates on INSERT
-- Prevents an employee from submitting a leave request that overlaps with an
-- existing APPROVED or PENDING leave request:
-- Overlap condition: (NEW.start_date <= existing.end_date) AND (NEW.end_date >= existing.start_date)
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_validate_leave_overlap_insert
BEFORE INSERT ON Leave_Request
FOR EACH ROW
BEGIN
    -- 1. Validate chronological date order
    SELECT CASE
        WHEN date(NEW.end_date) < date(NEW.start_date) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [LEAVE_DATE_ORDER]: Leave end_date cannot be earlier than start_date.')
    END;

    -- 2. Reject overlapping APPROVED or PENDING leave dates for the same employee
    SELECT CASE
        WHEN NEW.status IN ('PENDING', 'APPROVED') AND EXISTS (
            SELECT 1
            FROM Leave_Request lr
            WHERE lr.emp_id = NEW.emp_id
              AND lr.status IN ('PENDING', 'APPROVED')
              AND date(NEW.start_date) <= date(lr.end_date)
              AND date(NEW.end_date) >= date(lr.start_date)
        ) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [LEAVE_OVERLAP]: Overlapping approved or pending leave dates exist for this employee.')
    END;
END;

-- ----------------------------------------------------------------------------
-- Trigger 1B: Reject overlapping leave dates on UPDATE (e.g., when approving/modifying)
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_validate_leave_overlap_update
BEFORE UPDATE ON Leave_Request
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN date(NEW.end_date) < date(NEW.start_date) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [LEAVE_DATE_ORDER]: Leave end_date cannot be earlier than start_date.')
    END;

    SELECT CASE
        WHEN NEW.status IN ('PENDING', 'APPROVED') AND EXISTS (
            SELECT 1
            FROM Leave_Request lr
            WHERE lr.emp_id = NEW.emp_id
              AND lr.leave_id != NEW.leave_id
              AND lr.status IN ('PENDING', 'APPROVED')
              AND date(NEW.start_date) <= date(lr.end_date)
              AND date(NEW.end_date) >= date(lr.start_date)
        ) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [LEAVE_OVERLAP]: Updating this leave creates an overlap with an existing approved/pending leave.')
    END;
END;

-- ----------------------------------------------------------------------------
-- Trigger 2: Validate Annual Leave Quota on INSERT
-- Rejects paid leave requests that exceed the annual_quota in Leave_Type
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_validate_leave_quota_insert
BEFORE INSERT ON Leave_Request
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN (
            SELECT lt.is_paid FROM Leave_Type lt WHERE lt.leave_type_id = NEW.leave_type_id
        ) = 1
        AND (
            COALESCE((
                SELECT SUM(CAST(julianday(lr.end_date) - julianday(lr.start_date) + 1 AS INTEGER))
                FROM Leave_Request lr
                WHERE lr.emp_id = NEW.emp_id
                  AND lr.leave_type_id = NEW.leave_type_id
                  AND lr.status = 'APPROVED'
                  AND strftime('%Y', lr.start_date) = strftime('%Y', NEW.start_date)
            ), 0) + CAST(julianday(NEW.end_date) - julianday(NEW.start_date) + 1 AS INTEGER)
        ) > (
            SELECT lt.annual_quota FROM Leave_Type lt WHERE lt.leave_type_id = NEW.leave_type_id
        ) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [LEAVE_QUOTA_EXCEEDED]: Requested leave days exceed annual quota for this leave type.')
    END;
END;

-- ----------------------------------------------------------------------------
-- Trigger 3A: Validate Attendance Entry BEFORE INSERT
-- 1. Rejects marking PRESENT or HALF_DAY on an APPROVED leave date.
-- 2. Requires check_in time when status is PRESENT or HALF_DAY.
-- 3. Rejects check_out <= check_in when both are present.
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_validate_attendance_before_insert
BEFORE INSERT ON Attendance
FOR EACH ROW
BEGIN
    -- 1. Cannot mark PRESENT or HALF_DAY on an APPROVED leave date
    SELECT CASE
        WHEN NEW.att_status IN ('PRESENT', 'HALF_DAY') AND EXISTS (
            SELECT 1
            FROM Leave_Request lr
            WHERE lr.emp_id = NEW.emp_id
              AND lr.status = 'APPROVED'
              AND date(NEW.att_date) BETWEEN date(lr.start_date) AND date(lr.end_date)
        ) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [ATTENDANCE_ON_APPROVED_LEAVE]: Cannot mark PRESENT/HALF_DAY on an approved leave date.')
    END;

    -- 2. PRESENT / HALF_DAY requires check_in time
    SELECT CASE
        WHEN NEW.att_status IN ('PRESENT', 'HALF_DAY') AND NEW.check_in IS NULL THEN
            RAISE(ABORT, 'TRIGGER_ERROR [MISSING_CHECK_IN]: check_in time is required when attendance status is PRESENT or HALF_DAY.')
    END;

    -- 3. Validate check_out > check_in
    SELECT CASE
        WHEN NEW.check_in IS NOT NULL AND NEW.check_out IS NOT NULL
             AND time(NEW.check_out) <= time(NEW.check_in) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [INVALID_CHECK_OUT]: check_out time must be strictly after check_in time.')
    END;
END;

-- ----------------------------------------------------------------------------
-- Trigger 3B: Validate Attendance Entry BEFORE UPDATE
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_validate_attendance_before_update
BEFORE UPDATE ON Attendance
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.att_status IN ('PRESENT', 'HALF_DAY') AND EXISTS (
            SELECT 1
            FROM Leave_Request lr
            WHERE lr.emp_id = NEW.emp_id
              AND lr.status = 'APPROVED'
              AND date(NEW.att_date) BETWEEN date(lr.start_date) AND date(lr.end_date)
        ) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [ATTENDANCE_ON_APPROVED_LEAVE]: Cannot mark PRESENT/HALF_DAY on an approved leave date.')
    END;

    SELECT CASE
        WHEN NEW.att_status IN ('PRESENT', 'HALF_DAY') AND NEW.check_in IS NULL THEN
            RAISE(ABORT, 'TRIGGER_ERROR [MISSING_CHECK_IN]: check_in time is required when attendance status is PRESENT or HALF_DAY.')
    END;

    SELECT CASE
        WHEN NEW.check_in IS NOT NULL AND NEW.check_out IS NOT NULL
             AND time(NEW.check_out) <= time(NEW.check_in) THEN
            RAISE(ABORT, 'TRIGGER_ERROR [INVALID_CHECK_OUT]: check_out time must be strictly after check_in time.')
    END;
END;

-- ----------------------------------------------------------------------------
-- Trigger 4A: Auto-Compute Late Minutes, Late Flag & Work Hours AFTER INSERT
-- Compares check_in against Salary_Structure.standard_check_in (default 09:15:00)
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_compute_attendance_metrics_insert
AFTER INSERT ON Attendance
FOR EACH ROW
WHEN NEW.check_in IS NOT NULL
BEGIN
    UPDATE Attendance
    SET
        late_minutes = CASE
            WHEN NEW.att_status IN ('PRESENT', 'HALF_DAY')
                 AND (strftime('%s', time(NEW.check_in)) - strftime('%s', time(COALESCE(
                     (SELECT ss.standard_check_in FROM Salary_Structure ss WHERE ss.emp_id = NEW.emp_id),
                     '09:15:00'
                 )))) > 0
            THEN CAST((strftime('%s', time(NEW.check_in)) - strftime('%s', time(COALESCE(
                     (SELECT ss.standard_check_in FROM Salary_Structure ss WHERE ss.emp_id = NEW.emp_id),
                     '09:15:00'
                 )))) / 60 AS INTEGER)
            ELSE 0
        END,
        is_late = CASE
            WHEN NEW.att_status IN ('PRESENT', 'HALF_DAY')
                 AND (strftime('%s', time(NEW.check_in)) - strftime('%s', time(COALESCE(
                     (SELECT ss.standard_check_in FROM Salary_Structure ss WHERE ss.emp_id = NEW.emp_id),
                     '09:15:00'
                 )))) > 0
            THEN 1
            ELSE 0
        END,
        work_hours = CASE
            WHEN NEW.check_out IS NOT NULL
            THEN ROUND((strftime('%s', time(NEW.check_out)) - strftime('%s', time(NEW.check_in))) / 3600.0, 2)
            ELSE NEW.work_hours
        END
    WHERE attendance_id = NEW.attendance_id;
END;

-- ----------------------------------------------------------------------------
-- Trigger 4B: Auto-Compute Late Minutes, Late Flag & Work Hours AFTER UPDATE
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_compute_attendance_metrics_update
AFTER UPDATE OF check_in, check_out, att_status ON Attendance
FOR EACH ROW
BEGIN
    UPDATE Attendance
    SET
        late_minutes = CASE
            WHEN NEW.check_in IS NOT NULL AND NEW.att_status IN ('PRESENT', 'HALF_DAY')
                 AND (strftime('%s', time(NEW.check_in)) - strftime('%s', time(COALESCE(
                     (SELECT ss.standard_check_in FROM Salary_Structure ss WHERE ss.emp_id = NEW.emp_id),
                     '09:15:00'
                 )))) > 0
            THEN CAST((strftime('%s', time(NEW.check_in)) - strftime('%s', time(COALESCE(
                     (SELECT ss.standard_check_in FROM Salary_Structure ss WHERE ss.emp_id = NEW.emp_id),
                     '09:15:00'
                 )))) / 60 AS INTEGER)
            ELSE 0
        END,
        is_late = CASE
            WHEN NEW.check_in IS NOT NULL AND NEW.att_status IN ('PRESENT', 'HALF_DAY')
                 AND (strftime('%s', time(NEW.check_in)) - strftime('%s', time(COALESCE(
                     (SELECT ss.standard_check_in FROM Salary_Structure ss WHERE ss.emp_id = NEW.emp_id),
                     '09:15:00'
                 )))) > 0
            THEN 1
            ELSE 0
        END,
        work_hours = CASE
            WHEN NEW.check_in IS NOT NULL AND NEW.check_out IS NOT NULL
            THEN ROUND((strftime('%s', time(NEW.check_out)) - strftime('%s', time(NEW.check_in))) / 3600.0, 2)
            ELSE 0.00
        END
    WHERE attendance_id = NEW.attendance_id;
END;

-- ----------------------------------------------------------------------------
-- Trigger 5: Salary Structure Guard (Rejects non-positive basic_pay)
-- ----------------------------------------------------------------------------
CREATE TRIGGER trg_validate_salary_positive_insert
BEFORE INSERT ON Salary_Structure
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.basic_pay <= 0 THEN
            RAISE(ABORT, 'TRIGGER_ERROR [INVALID_SALARY]: basic_pay must be strictly greater than 0.')
        WHEN NEW.special_allowance < 0 THEN
            RAISE(ABORT, 'TRIGGER_ERROR [INVALID_SALARY]: special_allowance cannot be negative.')
    END;
END;

CREATE TRIGGER trg_validate_salary_positive_update
BEFORE UPDATE ON Salary_Structure
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.basic_pay <= 0 THEN
            RAISE(ABORT, 'TRIGGER_ERROR [INVALID_SALARY]: basic_pay must be strictly greater than 0.')
        WHEN NEW.special_allowance < 0 THEN
            RAISE(ABORT, 'TRIGGER_ERROR [INVALID_SALARY]: special_allowance cannot be negative.')
    END;
END;


-- ============================================================================
-- SECTION 2: POSTGRESQL (PL/pgSQL) & MYSQL 8.0 STORED FUNCTIONS & PROCEDURES
-- (Equivalent procedural definitions registered in SQLite via Python/SQL bridge)
-- ============================================================================
/*
-------------------------------------------------------------------------------
-- 2.1 Stored Function: fn_calculate_income_tax(p_annual_gross NUMERIC)
-- Progressive Slab-Based Annual Income Tax & Monthly TDS Calculation:
--   - Standard Deduction: Rs. 75,000
--   - 0 to 4,00,000       : 0%
--   - 4,00,001 to 8,00,000: 5%
--   - 8,00,001 to 12,00,000: 10%
--   - 12,00,001 to 16,00,000: 15%
--   - Above 16,00,000     : 20%
--   - Plus 4% Health & Education Cess; divided by 12 for monthly deduction.
-------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_calculate_income_tax(p_annual_gross NUMERIC)
RETURNS NUMERIC(12, 2)
LANGUAGE plpgsql
AS $$
DECLARE
    v_taxable NUMERIC(12, 2);
    v_annual_tax NUMERIC(12, 2) := 0;
BEGIN
    v_taxable := GREATEST(0, p_annual_gross - 75000.00);

    IF v_taxable <= 400000 THEN
        v_annual_tax := 0;
    ELSIF v_taxable <= 800000 THEN
        v_annual_tax := (v_taxable - 400000) * 0.05;
    ELSIF v_taxable <= 1200000 THEN
        v_annual_tax := 20000 + (v_taxable - 800000) * 0.10;
    ELSIF v_taxable <= 1600000 THEN
        v_annual_tax := 60000 + (v_taxable - 1200000) * 0.15;
    ELSE
        v_annual_tax := 120000 + (v_taxable - 1600000) * 0.20;
    END IF;

    -- Rebate under Section 87A if taxable income <= 7,00,000
    IF v_taxable <= 700000 THEN
        v_annual_tax := 0;
    END IF;

    -- Add 4% Health & Education Cess and convert to monthly TDS
    RETURN ROUND((v_annual_tax * 1.04) / 12.0, 2);
END;
$$;

-------------------------------------------------------------------------------
-- 2.2 Stored Procedure: sp_process_monthly_payroll(p_emp_id INT, p_month INT, p_year INT)
-- Calculates attendance metrics, paid leaves, LOP days, late penalty (every 3
-- late marks = 0.5 day LOP), prorated earnings, PF, PT, TDS, and Net Salary.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_process_monthly_payroll(
    p_emp_id INT,
    p_month  INT,
    p_year   INT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_basic             NUMERIC(12,2);
    v_hra_pct           NUMERIC(5,2);
    v_da_pct            NUMERIC(5,2);
    v_special           NUMERIC(12,2);
    v_pf_pct            NUMERIC(5,2);
    v_pt                NUMERIC(8,2);
    v_working_days      INT;
    v_present_days      NUMERIC(4,1);
    v_paid_leave_days   NUMERIC(4,1);
    v_unpaid_absences   NUMERIC(4,1);
    v_late_count        INT;
    v_late_penalty_days NUMERIC(4,1);
    v_total_lop_days    NUMERIC(4,1);
    v_full_gross        NUMERIC(12,2);
    v_lop_deduction     NUMERIC(12,2);
    v_pay_ratio         NUMERIC(8,4);
    v_basic_earned      NUMERIC(12,2);
    v_hra_earned        NUMERIC(12,2);
    v_da_earned         NUMERIC(12,2);
    v_special_earned    NUMERIC(12,2);
    v_gross_earned      NUMERIC(12,2);
    v_pf_deduction      NUMERIC(12,2);
    v_tds_deduction     NUMERIC(12,2);
    v_total_deductions  NUMERIC(12,2);
    v_net_salary        NUMERIC(12,2);
BEGIN
    -- 1. Fetch Employee's Salary Structure
    SELECT basic_pay, hra_percent, da_percent, special_allowance, pf_percent, professional_tax
      INTO v_basic, v_hra_pct, v_da_pct, v_special, v_pf_pct, v_pt
      FROM Salary_Structure
     WHERE emp_id = p_emp_id;

    -- 2. Aggregate Monthly Attendance
    SELECT COUNT(*),
           COALESCE(SUM(CASE WHEN att_status = 'PRESENT' THEN 1.0
                             WHEN att_status = 'HALF_DAY' THEN 0.5
                             ELSE 0.0 END), 0.0),
           COALESCE(SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END), 0)
      INTO v_working_days, v_present_days, v_late_count
      FROM Attendance
     WHERE emp_id = p_emp_id
       AND EXTRACT(MONTH FROM att_date) = p_month
       AND EXTRACT(YEAR FROM att_date)  = p_year;

    -- 3. Count Paid Leave Days vs Unpaid Leave / Absent Days
    SELECT COALESCE(SUM(
        CASE WHEN a.att_status = 'ON_LEAVE' AND EXISTS (
            SELECT 1 FROM Leave_Request lr
            JOIN Leave_Type lt ON lr.leave_type_id = lt.leave_type_id
            WHERE lr.emp_id = a.emp_id
              AND lr.status = 'APPROVED'
              AND lt.is_paid = 1
              AND a.att_date BETWEEN lr.start_date AND lr.end_date
        ) THEN 1.0 ELSE 0.0 END
    ), 0.0)
      INTO v_paid_leave_days
      FROM Attendance a
     WHERE a.emp_id = p_emp_id
       AND EXTRACT(MONTH FROM a.att_date) = p_month
       AND EXTRACT(YEAR FROM a.att_date)  = p_year;

    -- 4. Compute Late Penalty (Every 3 late marks = 0.5 day LOP) & Total LOP
    v_late_penalty_days := FLOOR(v_late_count / 3) * 0.5;
    v_unpaid_absences   := GREATEST(0.0, v_working_days - (v_present_days + v_paid_leave_days));
    v_total_lop_days    := v_unpaid_absences + v_late_penalty_days;

    -- 5. Compute Full Gross & LOP Deduction
    v_full_gross     := v_basic + (v_basic * v_hra_pct / 100.0) + (v_basic * v_da_pct / 100.0) + v_special;
    v_lop_deduction  := ROUND((v_full_gross / v_working_days) * v_total_lop_days, 2);
    v_pay_ratio      := GREATEST(0.0, (v_working_days - v_total_lop_days) / v_working_days);

    v_basic_earned   := ROUND(v_basic * v_pay_ratio, 2);
    v_hra_earned     := ROUND((v_basic * v_hra_pct / 100.0) * v_pay_ratio, 2);
    v_da_earned      := ROUND((v_basic * v_da_pct / 100.0) * v_pay_ratio, 2);
    v_special_earned := ROUND(v_special * v_pay_ratio, 2);
    v_gross_earned   := ROUND(v_basic_earned + v_hra_earned + v_da_earned + v_special_earned, 2);

    -- 6. Statutory Deductions (PF on earned basic, PT, TDS via fn_calculate_income_tax)
    v_pf_deduction     := ROUND(v_basic_earned * (v_pf_pct / 100.0), 2);
    v_tds_deduction    := fn_calculate_income_tax(v_gross_earned * 12.0);
    v_total_deductions := ROUND(v_pf_deduction + v_pt + v_tds_deduction + v_lop_deduction, 2);
    v_net_salary       := GREATEST(0.0, ROUND(v_full_gross - v_total_deductions, 2));

    -- 7. Upsert into Payroll
    INSERT INTO Payroll (
        emp_id, pay_month, pay_year, working_days, present_days, paid_leave_days,
        lop_days, late_count, late_penalty_days, basic_earned, hra_earned, da_earned,
        special_allowance_earned, gross_salary, pf_deduction, professional_tax,
        income_tax_deduction, lop_deduction, total_deductions, net_salary,
        payment_status, processed_at
    ) VALUES (
        p_emp_id, p_month, p_year, v_working_days, v_present_days, v_paid_leave_days,
        v_total_lop_days, v_late_count, v_late_penalty_days, v_basic_earned, v_hra_earned,
        v_da_earned, v_special_earned, v_gross_earned, v_pf_deduction, v_pt,
        v_tds_deduction, v_lop_deduction, v_total_deductions, v_net_salary,
        'PROCESSED', CURRENT_TIMESTAMP
    )
    ON CONFLICT (emp_id, pay_month, pay_year) DO UPDATE SET
        working_days             = EXCLUDED.working_days,
        present_days             = EXCLUDED.present_days,
        paid_leave_days          = EXCLUDED.paid_leave_days,
        lop_days                 = EXCLUDED.lop_days,
        late_count               = EXCLUDED.late_count,
        late_penalty_days        = EXCLUDED.late_penalty_days,
        basic_earned             = EXCLUDED.basic_earned,
        hra_earned               = EXCLUDED.hra_earned,
        da_earned                = EXCLUDED.da_earned,
        special_allowance_earned = EXCLUDED.special_allowance_earned,
        gross_salary             = EXCLUDED.gross_salary,
        pf_deduction             = EXCLUDED.pf_deduction,
        professional_tax         = EXCLUDED.professional_tax,
        income_tax_deduction     = EXCLUDED.income_tax_deduction,
        lop_deduction            = EXCLUDED.lop_deduction,
        total_deductions         = EXCLUDED.total_deductions,
        net_salary               = EXCLUDED.net_salary,
        payment_status           = 'PROCESSED',
        processed_at             = CURRENT_TIMESTAMP;
END;
$$;
*/
