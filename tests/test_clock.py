"""One business clock (review T17.A8, T25.S7): "today" comes from `config.today()` only, in the business time zone,
so a UTC container does not move the date between 00:00 and 02:00 (03:00 in summer) Sofia time, and FROZEN_TODAY
freezes every use of it."""
import re
from datetime import UTC, datetime
from pathlib import Path

from test_graph import final, graph, route_answer, run  # noqa: F401  (graph is a fixture)

from copilot import attachments, config

ROOT = Path(__file__).resolve().parents[1]


def test_an_unreadable_invoice_uses_the_frozen_today(graph, fake_lm, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "FROZEN_TODAY", "2026-03-31")
    fake_lm.script("route", route_answer("validate"))
    result = final(run(graph, "Validate", attachment_id=attachments.save(b"<not-xml")))
    assert result["dates"] == ["2026-03-31"]


def test_today_is_the_business_date_not_the_server_date(monkeypatch):
    monkeypatch.setattr(config, "FROZEN_TODAY", "")
    monkeypatch.setattr(config, "BUSINESS_TZ", "Europe/Sofia")
    late_utc = datetime(2026, 11, 25, 22, 30, tzinfo=UTC)        # 00:30 on the 26th in Sofia
    assert config.today(now=late_utc).isoformat() == "2026-11-26"
    monkeypatch.setattr(config, "BUSINESS_TZ", "UTC")
    assert config.today(now=late_utc).isoformat() == "2026-11-25"


def test_no_naive_clock_outside_the_config_module():
    naive = re.compile(r"\bdate\.today\(\)|\bdatetime\.now\(\)|\bdatetime\.today\(\)|\bdatetime\.utcnow\(\)")
    offenders = [f"{path.relative_to(ROOT)}:{n}" for path in [*ROOT.glob("copilot/**/*.py"), ROOT / "server.py"]
                 if path.name != "config.py"
                 for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if naive.search(line)]
    assert offenders == []
