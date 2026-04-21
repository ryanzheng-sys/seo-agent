-- Category 1: Active Buyers (AB) by domain / channel / device.
--
-- Source: analytics.v_active_buyers
--
-- Returned columns (used by RedashCollector.collect_ab_metrics):
--   date       DATE       — event date
--   hostname   VARCHAR    — full hostname (e.g. www.europages.fr)
--   platform   VARCHAR    — 'wlw' or 'ep' (already provided by the view)
--   channel    VARCHAR    — GA channel grouping (never NULL — '(none)' fallback)
--   device     VARCHAR    — desktop / mobile / tablet (or '(not set)')
--   ab         BIGINT     — COUNT(DISTINCT visitor_sk) who became Active Buyers
--   qdr_ab     BIGINT     — ABs with has_quality_direct_request = true
--   rfq_ab     BIGINT     — ABs with has_verified_rfq = true
--   pc_ab      BIGINT     — ABs with has_positive_connection = true
--
-- Redash parameters (Type: Date):
--   start_date   inclusive lower bound
--   end_date     inclusive upper bound
SELECT
    ab.date,
    ab.hostname,
    ab.platform,
    COALESCE(ab.channel, '(none)') AS channel,
    COALESCE(ab.device, '(not set)') AS device,
    COUNT(DISTINCT ab.visitor_sk) AS ab,
    COUNT(DISTINCT CASE WHEN ab.has_quality_direct_request THEN ab.visitor_sk END) AS qdr_ab,
    COUNT(DISTINCT CASE WHEN ab.has_verified_rfq THEN ab.visitor_sk END) AS rfq_ab,
    COUNT(DISTINCT CASE WHEN ab.has_positive_connection THEN ab.visitor_sk END) AS pc_ab
FROM analytics.v_active_buyers ab
WHERE ab.date >= '{{ start_date }}'
  AND ab.date <= '{{ end_date }}'
  AND REGEXP_INSTR(ab.hostname, 'stag') = 0
  AND (
    REGEXP_INSTR(ab.hostname, 'wlw') > 0
    OR REGEXP_INSTR(ab.hostname, 'europages') > 0
  )
GROUP BY 1, 2, 3, 4, 5
ORDER BY 1, 2
