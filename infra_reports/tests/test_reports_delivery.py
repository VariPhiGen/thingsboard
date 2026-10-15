import smtplib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from infra_reports import delivery, healthcheck, pipeline, state
from infra_reports.charts import nice_ticks, svg_line_chart
from infra_reports.collect import DeviceSummary, classify
from infra_reports.config import DEFAULT_PROFILES, REPORT_TZ, ConfigError, Settings
from infra_reports.delivery import ReportError, render_pdf, send_email
from infra_reports.layout import fmt_latest, fmt_val, is_fresh
from infra_reports.metrics import BUCKET_MS
from infra_reports.reports import REPORTS, generate_dg_set_html, generate_lt_panels_html

START = 1_000 * BUCKET_MS
END = START + 48 * BUCKET_MS


def device(name, category, telemetry=None, ts=START + 10, **extra):
    telemetry = telemetry or {}
    base = {
        "id": name, "name": name, "type": DEFAULT_PROFILES[category][0], "category": category,
        "is_active": True, "last_activity": "2026-10-12 23:59:58",
        "telemetry": telemetry, "telemetry_ts": {k: ts for k in telemetry},
        "agg_24h": {}, "energy_24h_kwh": None, "energy_coverage": None,
        "alarms_count": 0, "alarm_types": {}, "active_alarms": [],
        "series_start_ts": START, "series_end_ts": END, "historical": True, "series_24h": {},
    }
    base.update(extra)
    return base


def settings(**overrides):
    values = dict(
        tb_urls=[], tb_tenant_user="", tb_tenant_pass="", tb_sysadmin_user="", tb_sysadmin_pass="", tb_tenant_id="",
        pdf_urls=["http://pdf"], smtp_host="smtp.x", smtp_port=465, smtp_user="u@x.com", smtp_pass="p",
        smtp_from="u@x.com", smtp_from_name="Ops", recipients=["a@x.com"], telegram_bot_token="", telegram_chat_ids=[],
        profiles=DEFAULT_PROFILES,
    )
    values.update(overrides)
    return Settings(**values)


class LayoutTest(unittest.TestCase):
    def test_fmt_val(self):
        self.assertIn("1,234.6 kW", fmt_val("1234.56", "kW"))
        self.assertIn("N/A", fmt_val("N/A", "kW"))
        self.assertNotIn("kW", fmt_val("N/A", "kW"))
        self.assertIn("Sensor Offline", fmt_val("32767", "°C"))
        self.assertIn("Sensor Error", fmt_val("error", "%"))
        self.assertIn("&lt;script&gt;", fmt_val("<script>"))

    def test_staleness(self):
        fresh = device("D", "dg", {"power_kw": "5"})
        stale = device("D", "dg", {"power_kw": "5"}, ts=START - 1)
        self.assertTrue(is_fresh(fresh, "power_kw"))
        self.assertFalse(is_fresh(stale, "power_kw"))
        self.assertIn("as of", fmt_latest(stale, "power_kw", "kW"))
        self.assertNotIn("as of", fmt_latest(fresh, "power_kw", "kW"))

    def test_classify_by_profile_not_name(self):
        self.assertEqual(classify({"name": "Anything", "type": "woodward_kg1500"}, DEFAULT_PROFILES), "dg")
        self.assertIsNone(classify({"name": "DG Set 9", "type": "default"}, DEFAULT_PROFILES))


class ChartsTest(unittest.TestCase):
    def test_nice_ticks_cover_range(self):
        ticks = nice_ticks(81.7, 100.0)
        self.assertLessEqual(ticks[0], 81.7)
        self.assertGreaterEqual(ticks[-1], 100.0)
        self.assertEqual(nice_ticks(0, 0)[0] < 0 < nice_ticks(0, 0)[-1], True)

    def test_empty_chart(self):
        self.assertIn("No valid readings", svg_line_chart([("a", "#000", [None, None])], START))
        self.assertIn("<path", svg_line_chart([("a", "#000", [1.0, 2.0, None, 3.0])], START))


class ReportsTest(unittest.TestCase):
    def summary(self, devices):
        return DeviceSummary(devices, START, END, historical=True)

    def test_all_reports_render_with_and_without_devices(self):
        full = self.summary([
            device("DG <1>", "dg", {"power_kw": "10", "dg_status": "RUNNING"}, energy_24h_kwh=100.0, energy_coverage=0.95,
                   agg_24h={"energy_kwh_24h_delta": 1000.0}, alarms_count=3, alarm_types={"DG Offline": 3}),
            device("LT", "lt", {"Transformer_1_voltage": "433", "Transformer_1_power": "500"}),
            device("Fire", "fire", {"cylinder_pressure_1": "true", "relay_online": "true"}),
            device("RO", "ro", {"tds": "123", "ph": "7.4"}),
        ])
        for _, _, _, render in REPORTS:
            for summary in (full, self.summary([])):
                html = render(summary)
                self.assertIn("</html>", html)
                self.assertNotIn("📊", html)

    def test_fire_report_has_no_trend_graph(self):
        html = REPORTS[2][3](self.summary([device("Fire", "fire", {"cylinder_pressure_1": "true"})]))
        self.assertNotIn("Time Series Trends", html)
        self.assertNotIn("<svg", html)

    def test_dg_energy_and_meter_mismatch(self):
        html = generate_dg_set_html(self.summary([
            device("DG1", "dg", {}, energy_24h_kwh=100.0, energy_coverage=0.95, agg_24h={"energy_kwh_24h_delta": 1000.0}),
        ]))
        self.assertIn("100.0 kWh", html)          # KPI uses integrated power, not the meter
        self.assertIn("10.0x of power", html)     # meter disagreement is flagged
        self.assertIn("DG1", html)

    def test_names_are_escaped(self):
        html = generate_dg_set_html(self.summary([device("<b>x</b>", "dg")]))
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)

    def test_stale_lt_values_not_counted_as_live(self):
        html = generate_lt_panels_html(self.summary([
            device("LT", "lt", {"Transformer_1_voltage": "433", "Transformer_1_power": "678"}, ts=START - 1),
        ]))
        self.assertIn("NO LIVE DATA", html)
        self.assertIn("0.0 kW", html)  # total power excludes the stale 678 kW


class DeliveryTest(unittest.TestCase):
    reports = [{"name": "R", "filename": "r.pdf", "pdf_bytes": b"%PDF-1.4"}]

    def test_refuses_to_send_with_missing_pdf(self):
        with mock.patch.object(smtplib, "SMTP_SSL") as smtp:
            with self.assertRaises(ReportError):
                send_email(settings(), [{"name": "R", "filename": "r.pdf", "pdf_bytes": None}], ["a@x.com"])
            smtp.assert_not_called()

    def test_requires_recipients(self):
        with self.assertRaises(ConfigError):
            send_email(settings(), self.reports, [])

    def setUp(self):
        patcher = mock.patch.object(delivery, "record_success")
        self.record_success = patcher.start()
        self.addCleanup(patcher.stop)

    def test_sends_once_with_all_attachments(self):
        day = datetime(2026, 10, 12, tzinfo=REPORT_TZ)
        reports = [dict(self.reports[0], report_day=day)]
        with mock.patch.object(smtplib, "SMTP_SSL") as smtp:
            server = smtp.return_value.__enter__.return_value = smtp.return_value
            server.send_message.return_value = {"b@x.com": (550, b"no")}
            self.assertTrue(send_email(settings(), reports, ["a@x.com", "b@x.com"]))
            msg = server.send_message.call_args.args[0]
            self.assertEqual([p.get_filename() for p in msg.iter_attachments()], ["r.pdf"])
            self.assertIn("12 Oct 2026", msg["Subject"])  # subject carries the report day, not today
        self.record_success.assert_called_once_with(day, ["a@x.com"], ["r.pdf"])

    def test_auth_failure_is_not_retried(self):
        with mock.patch.object(smtplib, "SMTP_SSL") as smtp, mock.patch.object(delivery.time, "sleep"):
            smtp.return_value.__enter__.return_value = smtp.return_value
            smtp.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
            with self.assertRaises(ReportError):
                send_email(settings(), self.reports, ["a@x.com"])
            self.assertEqual(smtp.call_count, 1)

    def test_render_pdf_validates_content(self):
        session = mock.Mock()
        session.post.return_value = mock.Mock(status_code=200, content=b"<html>error</html>", text="")
        with self.assertRaises(ReportError):
            render_pdf(session, "http://pdf", "<html/>", "x.pdf")

    def test_build_reports_fails_closed(self):
        summary = DeviceSummary([], START, END, historical=True)
        with mock.patch.object(pipeline, "resolve_pdf_service", return_value="http://pdf"), \
                mock.patch.object(pipeline, "render_pdf", side_effect=[b"%PDF", ReportError("boom")]):
            with self.assertRaises(ReportError):
                pipeline.build_reports(summary, settings(), session=mock.Mock())

    def test_alert_without_telegram_config_does_not_raise(self):
        delivery.send_failure_alert(settings(), "stage", RuntimeError("x"))
        delivery.send_failure_alert(None, "stage", RuntimeError("x"))


class CollectTest(unittest.TestCase):
    def test_propagated_alarms_are_not_counted(self):
        from infra_reports.collect import collect_device
        client = mock.Mock()
        client.timeseries_keys.return_value = []
        client.latest.return_value = {}
        client.history.return_value = {}
        client.alarms.return_value = [
            {"type": "DG Offline", "originator": {"id": "dg1"}},
            {"type": "Engine Overspeed", "originator": {"id": "dg2"}},  # propagated from another DG
        ]
        dev = collect_device(client, {"id": {"id": "dg1"}, "name": "DG1", "type": "woodward_kg1500"},
                             "dg", START, END, historical=True)
        self.assertEqual(dev["alarms_count"], 1)
        self.assertEqual(dev["alarm_types"], {"DG Offline": 1})


class HealthCheckTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "last_success.json"
        self.now = datetime(2026, 10, 15, 9, 0, tzinfo=REPORT_TZ)

    def test_record_roundtrip_and_check(self):
        cfg = settings(recipients=["a@x.com", "b@x.com"])
        self.assertIn("no successful", healthcheck.check(cfg, self.now, self.path))
        state.record_success(datetime(2026, 10, 13, tzinfo=REPORT_TZ), ["a@x.com", "b@x.com"], ["r.pdf"], self.path)
        self.assertIn("2026-10-14 was not emailed", healthcheck.check(cfg, self.now, self.path))
        state.record_success(datetime(2026, 10, 14, tzinfo=REPORT_TZ), ["a@x.com"], ["r.pdf"], self.path)
        self.assertIn("not to: b@x.com", healthcheck.check(cfg, self.now, self.path))
        state.record_success(datetime(2026, 10, 14, tzinfo=REPORT_TZ), ["b@x.com", "a@x.com"], ["r.pdf"], self.path)
        self.assertIsNone(healthcheck.check(cfg, self.now, self.path))


class CliTest(unittest.TestCase):
    def test_no_action_is_an_error(self):
        import generate_separate_pdfs_report as cli
        with self.assertRaises(SystemExit) as ctx, mock.patch("sys.stderr"):
            cli.main([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
