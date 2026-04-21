-- Category 1: Overall Performance Monitoring
-- Daily Unique Visitors (UV) by hostname, platform, channel, device.
--
-- Source: metrics_layer.ga_user_metrics (web only — app traffic uses a
--         separate view, see analytics.v_web_app_uv_data for the union).
--
-- Returned columns (used by RedashCollector.collect_uv_metrics):
--   date       DATE       — event date
--   hostname   VARCHAR    — full hostname (e.g. www.europages.fr)
--   platform   VARCHAR    — 'wlw' or 'ep'
--   channel    VARCHAR    — GA channel grouping (never NULL — '(none)' fallback)
--   device     VARCHAR    — desktop / mobile / tablet (or '(not set)')
--   uv         BIGINT     — COUNT(DISTINCT visitor_sk)
--
-- Redash parameters (Type: Date):
--   start_date   inclusive lower bound
--   end_date     inclusive upper bound
SELECT
    date,
    hostname,
    CASE
        WHEN REGEXP_INSTR(hostname, 'wlw') > 0 THEN 'wlw'
        WHEN REGEXP_INSTR(hostname, 'europages') > 0 THEN 'ep'
    END AS platform,
    COALESCE(channel, '(none)') AS channel,
    COALESCE(device, '(not set)') AS device,
    COUNT(DISTINCT visitor_sk) AS uv
FROM metrics_layer.ga_user_metrics
WHERE date >= '{{ start_date }}'
  AND date <= '{{ end_date }}'
  AND REGEXP_INSTR(hostname, 'stag') = 0
  AND (
    REGEXP_INSTR(hostname, 'wlw') > 0
    OR REGEXP_INSTR(hostname, 'europages') > 0
  )
GROUP BY 1, 2, 3, 4, 5
ORDER BY 1, 2
