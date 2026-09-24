-- ZATCA engine dashboard: a dedicated, incrementally-updated summary table,
-- kept in sync via an AFTER INSERT trigger on ZATCA_INVOICE_LOGS.
--
-- Scope: ENGINE-mode reporting only (external API consumers using
-- stamp_id/engine_api_key against digital_stamps - e.g. ERPNext via the
-- ENGINE credential path). POS-mode reports are deliberately excluded - the
-- POS product has its own separate dashboard, so mixing its volume in here
-- would misrepresent what this dashboard is meant to show. The trigger
-- returns immediately for any log row whose action_type isn't
-- ENGINE_REPORT_DOCUMENT.
--
-- Every call to PKG_ZATCA_POS.report_invoice already inserts exactly one row
-- into ZATCA_INVOICE_LOGS regardless of mode. Rather than touch that
-- already-working procedure, this trigger piggybacks on that insert and
-- keeps a pre-aggregated table current - the dashboard reads a handful of
-- small rows instead of scanning/grouping the full log table on every load.
--
-- Grain: one row per (day, tenant, branch, environment, document_type,
-- zatca_status). Deliberately counts *reporting attempts*, not unique
-- invoices - a 3x-retried invoice that eventually succeeds shows up as up to
-- 3 attempt-rows (e.g. 2 FAILED + 1 REPORTED), by design.
--
-- Starts empty - no backfill from existing ZATCA_INVOICE_LOGS rows.

CREATE TABLE ZATCA_DASHBOARD_DAILY_STATS (
    STAT_DATE           DATE            NOT NULL,
    TENANT_ID           NUMBER          NOT NULL,
    BRANCH_ID           NUMBER          NOT NULL,
    ENVIRONMENT         VARCHAR2(20)    NOT NULL,
    DOCUMENT_TYPE       VARCHAR2(20)    NOT NULL,  -- INVOICE / CREDIT_NOTE
    ZATCA_STATUS        VARCHAR2(30)    NOT NULL,  -- REPORTED / CLEARED / FAILED / ERROR / ...
    ATTEMPT_COUNT       NUMBER          DEFAULT 0 NOT NULL,
    TOTAL_AMOUNT        NUMBER(18,2)    DEFAULT 0 NOT NULL,
    TAX_AMOUNT          NUMBER(18,2)    DEFAULT 0 NOT NULL,
    NET_AMOUNT          NUMBER(18,2)    DEFAULT 0 NOT NULL,
    FIRST_REPORTED_AT   TIMESTAMP,
    LAST_REPORTED_AT    TIMESTAMP,
    CONSTRAINT PK_ZATCA_DASH_STATS PRIMARY KEY (
        STAT_DATE, TENANT_ID, BRANCH_ID, ENVIRONMENT, DOCUMENT_TYPE, ZATCA_STATUS
    )
);

CREATE INDEX IDX_ZATCA_DASH_STATS_DATE ON ZATCA_DASHBOARD_DAILY_STATS (STAT_DATE);
CREATE INDEX IDX_ZATCA_DASH_STATS_TENANT ON ZATCA_DASHBOARD_DAILY_STATS (TENANT_ID, BRANCH_ID);

CREATE OR REPLACE TRIGGER TRG_ZATCA_DASH_STATS
AFTER INSERT ON ZATCA_INVOICE_LOGS
FOR EACH ROW
DECLARE
  l_document_type    VARCHAR2(20);
  l_total_amount     NUMBER(18,2) := 0;
  l_tax_amount       NUMBER(18,2) := 0;
  l_net_amount       NUMBER(18,2) := 0;
BEGIN
  -- Engine-user dashboard only - POS reports have their own dashboard.
  IF :NEW.action_type NOT LIKE 'ENGINE%' THEN
    RETURN;
  END IF;

  l_document_type := CASE WHEN :NEW.action_type LIKE '%CREDIT_NOTE%' THEN 'CREDIT_NOTE' ELSE 'INVOICE' END;

  BEGIN
    SELECT NVL(total_amount, 0), NVL(tax_amount, 0), NVL(net_amount, 0)
      INTO l_total_amount, l_tax_amount, l_net_amount
      FROM invoices
     WHERE invoice_id = :NEW.invoice_id;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      NULL; -- keep zeros rather than fail the whole insert over a stats join
  END;

  MERGE INTO ZATCA_DASHBOARD_DAILY_STATS d
  USING (
    SELECT
      TRUNC(:NEW.created_at)      AS stat_date,
      :NEW.tenant_id              AS tenant_id,
      :NEW.branch_id              AS branch_id,
      :NEW.environment            AS environment,
      l_document_type             AS document_type,
      NVL(:NEW.status, 'UNKNOWN') AS zatca_status
    FROM dual
  ) s
  ON (
    d.stat_date = s.stat_date AND d.tenant_id = s.tenant_id AND d.branch_id = s.branch_id
    AND d.environment = s.environment AND d.document_type = s.document_type
    AND d.zatca_status = s.zatca_status
  )
  WHEN MATCHED THEN UPDATE SET
    d.attempt_count     = d.attempt_count + 1,
    d.total_amount      = d.total_amount + l_total_amount,
    d.tax_amount        = d.tax_amount + l_tax_amount,
    d.net_amount        = d.net_amount + l_net_amount,
    d.last_reported_at  = :NEW.created_at
  WHEN NOT MATCHED THEN INSERT (
    stat_date, tenant_id, branch_id, environment, document_type,
    zatca_status, attempt_count, total_amount, tax_amount, net_amount,
    first_reported_at, last_reported_at
  ) VALUES (
    s.stat_date, s.tenant_id, s.branch_id, s.environment, s.document_type,
    s.zatca_status, 1, l_total_amount, l_tax_amount, l_net_amount,
    :NEW.created_at, :NEW.created_at
  );
EXCEPTION
  WHEN OTHERS THEN
    -- Never let a dashboard stats failure roll back or block real invoice
    -- reporting - swallow it.
    NULL;
END;
/

-- Example dashboard queries against the summary table:

-- Today's successful vs failed attempts by document type
-- SELECT document_type, zatca_status, SUM(attempt_count) AS attempts
--   FROM zatca_dashboard_daily_stats
--  WHERE stat_date = TRUNC(SYSDATE)
--  GROUP BY document_type, zatca_status
--  ORDER BY document_type, zatca_status;

-- Success rate and total reported value over the last 30 days
-- SELECT
--     SUM(CASE WHEN zatca_status IN ('REPORTED','CLEARED') THEN attempt_count ELSE 0 END) AS successful,
--     SUM(CASE WHEN zatca_status NOT IN ('REPORTED','CLEARED') THEN attempt_count ELSE 0 END) AS failed,
--     SUM(CASE WHEN zatca_status IN ('REPORTED','CLEARED') THEN total_amount ELSE 0 END) AS reported_value
--   FROM zatca_dashboard_daily_stats
--  WHERE stat_date >= TRUNC(SYSDATE) - 30;

-- Daily trend for a chart (last 14 days, successful attempts only)
-- SELECT stat_date, SUM(attempt_count) AS successful_invoices
--   FROM zatca_dashboard_daily_stats
--  WHERE zatca_status IN ('REPORTED','CLEARED')
--    AND stat_date >= TRUNC(SYSDATE) - 14
--  GROUP BY stat_date
--  ORDER BY stat_date;

-- Per-tenant/branch leaderboard (top engine users by successful attempts)
-- SELECT tenant_id, branch_id,
--        SUM(CASE WHEN zatca_status IN ('REPORTED','CLEARED') THEN attempt_count ELSE 0 END) AS successful
--   FROM zatca_dashboard_daily_stats
--  WHERE stat_date >= TRUNC(SYSDATE) - 30
--  GROUP BY tenant_id, branch_id
--  ORDER BY successful DESC;
