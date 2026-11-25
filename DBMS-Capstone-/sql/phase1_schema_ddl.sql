-- ============================================================================
-- PHASE 1 & PHASE 2 (Part A): 3NF RELATIONAL SCHEMA DDL
-- Theme: Payroll & Attendance Management System
-- Normalization Level: Strict Third Normal Form (3NF / BCNF)
-- Note: This exact schema is locked in Phase 1 and used unchanged across Phases 2–5.
-- ============================================================================

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS Payroll;
DROP TABLE IF EXISTS Attendance;
DROP TABLE IF EXISTS Leave_Request;
DROP TABLE IF EXISTS Leave_Type;
DROP TABLE IF EXISTS Salary_Structure;
DROP TABLE IF EXISTS Employee;
DROP TABLE IF EXISTS Department;

-- ----------------------------------------------------------------------------
-- 1. DEPARTMENT (Eliminates transitive dependency: emp_id -> dept_id -> dept_name, base_location)
-- ----------------------------------------------------------------------------
CREATE TABLE Department (
    dept_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_code       VARCHAR(10)  NOT NULL UNIQUE,
    dept_name       VARCHAR(100) NOT NULL UNIQUE,
    base_location   VARCHAR(100) NOT NULL
);

-- ----------------------------------------------------------------------------
-- 2. EMPLOYEE (Core Entity: Stores employee identity, department FK, and RBAC role)
-- ----------------------------------------------------------------------------
CREATE TABLE Employee (
    emp_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_code        VARCHAR(15)  NOT NULL UNIQUE,
    first_name      VARCHAR(50)  NOT NULL,
    last_name       VARCHAR(50)  NOT NULL,
    email           VARCHAR(120) NOT NULL UNIQUE,
    phone           VARCHAR(20)  NOT NULL,
    hire_date       DATE         NOT NULL,
    designation     VARCHAR(80)  NOT NULL,
    role            VARCHAR(20)  NOT NULL DEFAULT 'EMPLOYEE'
                    CHECK (role IN ('HR_ADMIN', 'EMPLOYEE')),
    password_hash   VARCHAR(128) NOT NULL,
    status          VARCHAR(15)  NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE', 'INACTIVE')),
    dept_id         INTEGER      NOT NULL,
    CONSTRAINT fk_employee_dept
        FOREIGN KEY (dept_id) REFERENCES Department(dept_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ----------------------------------------------------------------------------
-- 3. SALARY_STRUCTURE (Core Entity: Salary — 1:1 with Employee)
-- Stores base pay and statutory component rates. Derived amounts are not stored
-- here to strictly preserve 3NF (no transitive/derived dependencies).
-- ----------------------------------------------------------------------------
CREATE TABLE Salary_Structure (
    salary_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id              INTEGER        NOT NULL UNIQUE,
    effective_from      DATE           NOT NULL,
    basic_pay           NUMERIC(12, 2) NOT NULL CHECK (basic_pay > 0),
    hra_percent         NUMERIC(5, 2)  NOT NULL DEFAULT 40.00 CHECK (hra_percent >= 0 AND hra_percent <= 100),
    da_percent          NUMERIC(5, 2)  NOT NULL DEFAULT 15.00 CHECK (da_percent >= 0 AND da_percent <= 100),
    special_allowance   NUMERIC(12, 2) NOT NULL DEFAULT 0.00  CHECK (special_allowance >= 0),
    pf_percent          NUMERIC(5, 2)  NOT NULL DEFAULT 12.00 CHECK (pf_percent >= 0 AND pf_percent <= 30),
    professional_tax    NUMERIC(8, 2)  NOT NULL DEFAULT 200.00 CHECK (professional_tax >= 0),
    standard_check_in   TIME           NOT NULL DEFAULT '09:15:00',
    CONSTRAINT fk_salary_employee
        FOREIGN KEY (emp_id) REFERENCES Employee(emp_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

-- ----------------------------------------------------------------------------
-- 4. LEAVE_TYPE (Eliminates transitive dependency: leave_id -> leave_type_id -> type_name, annual_quota, is_paid)
-- ----------------------------------------------------------------------------
CREATE TABLE Leave_Type (
    leave_type_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    type_code       VARCHAR(10) NOT NULL UNIQUE,
    type_name       VARCHAR(50) NOT NULL UNIQUE,
    annual_quota    INTEGER     NOT NULL CHECK (annual_quota >= 0),
    is_paid         INTEGER     NOT NULL DEFAULT 1 CHECK (is_paid IN (0, 1))
);

-- ----------------------------------------------------------------------------
-- 5. LEAVE_REQUEST (Core Entity: Leave — 1:N with Employee)
-- ----------------------------------------------------------------------------
CREATE TABLE Leave_Request (
    leave_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id          INTEGER      NOT NULL,
    leave_type_id   INTEGER      NOT NULL,
    start_date      DATE         NOT NULL,
    end_date        DATE         NOT NULL,
    reason          VARCHAR(255) NOT NULL,
    status          VARCHAR(15)  NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    approved_by     INTEGER      NULL,
    applied_on      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_leave_dates CHECK (end_date >= start_date),
    CONSTRAINT fk_leave_employee
        FOREIGN KEY (emp_id) REFERENCES Employee(emp_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_leave_type
        FOREIGN KEY (leave_type_id) REFERENCES Leave_Type(leave_type_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_leave_approver
        FOREIGN KEY (approved_by) REFERENCES Employee(emp_id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

-- ----------------------------------------------------------------------------
-- 6. ATTENDANCE (Core Entity: Attendance — 1:N with Employee, Unique per (emp_id, att_date))
-- ----------------------------------------------------------------------------
CREATE TABLE Attendance (
    attendance_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id          INTEGER        NOT NULL,
    att_date        DATE           NOT NULL,
    check_in        TIME           NULL,
    check_out       TIME           NULL,
    work_hours      NUMERIC(4, 2)  NOT NULL DEFAULT 0.00 CHECK (work_hours >= 0 AND work_hours <= 24),
    att_status      VARCHAR(15)    NOT NULL
                    CHECK (att_status IN ('PRESENT', 'ABSENT', 'HALF_DAY', 'ON_LEAVE')),
    late_minutes    INTEGER        NOT NULL DEFAULT 0 CHECK (late_minutes >= 0),
    is_late         INTEGER        NOT NULL DEFAULT 0 CHECK (is_late IN (0, 1)),
    remarks         VARCHAR(200)   NULL,
    CONSTRAINT uq_attendance_emp_date UNIQUE (emp_id, att_date),
    CONSTRAINT fk_attendance_employee
        FOREIGN KEY (emp_id) REFERENCES Employee(emp_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

-- ----------------------------------------------------------------------------
-- 7. PAYROLL (Core Entity: Monthly Payroll Disbursement — 1:N with Employee)
-- Captures the immutable monthly historical snapshot computed by the Payroll Engine.
-- ----------------------------------------------------------------------------
CREATE TABLE Payroll (
    payroll_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id                      INTEGER        NOT NULL,
    pay_month                   INTEGER        NOT NULL CHECK (pay_month BETWEEN 1 AND 12),
    pay_year                    INTEGER        NOT NULL CHECK (pay_year BETWEEN 2020 AND 2100),
    working_days                INTEGER        NOT NULL CHECK (working_days > 0 AND working_days <= 31),
    present_days                NUMERIC(4, 1)  NOT NULL DEFAULT 0.0 CHECK (present_days >= 0),
    paid_leave_days             NUMERIC(4, 1)  NOT NULL DEFAULT 0.0 CHECK (paid_leave_days >= 0),
    lop_days                    NUMERIC(4, 1)  NOT NULL DEFAULT 0.0 CHECK (lop_days >= 0),
    late_count                  INTEGER        NOT NULL DEFAULT 0   CHECK (late_count >= 0),
    late_penalty_days           NUMERIC(4, 1)  NOT NULL DEFAULT 0.0 CHECK (late_penalty_days >= 0),
    basic_earned                NUMERIC(12, 2) NOT NULL CHECK (basic_earned >= 0),
    hra_earned                  NUMERIC(12, 2) NOT NULL CHECK (hra_earned >= 0),
    da_earned                   NUMERIC(12, 2) NOT NULL CHECK (da_earned >= 0),
    special_allowance_earned    NUMERIC(12, 2) NOT NULL CHECK (special_allowance_earned >= 0),
    gross_salary                NUMERIC(12, 2) NOT NULL CHECK (gross_salary >= 0),
    pf_deduction                NUMERIC(12, 2) NOT NULL CHECK (pf_deduction >= 0),
    professional_tax            NUMERIC(12, 2) NOT NULL CHECK (professional_tax >= 0),
    income_tax_deduction        NUMERIC(12, 2) NOT NULL CHECK (income_tax_deduction >= 0),
    lop_deduction               NUMERIC(12, 2) NOT NULL CHECK (lop_deduction >= 0),
    total_deductions            NUMERIC(12, 2) NOT NULL CHECK (total_deductions >= 0),
    net_salary                  NUMERIC(12, 2) NOT NULL CHECK (net_salary >= 0),
    payment_status              VARCHAR(15)    NOT NULL DEFAULT 'PROCESSED'
                                CHECK (payment_status IN ('DRAFT', 'PROCESSED', 'PAID')),
    processed_at                DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_payroll_emp_period UNIQUE (emp_id, pay_month, pay_year),
    CONSTRAINT fk_payroll_employee
        FOREIGN KEY (emp_id) REFERENCES Employee(emp_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
