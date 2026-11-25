"""The MCP server (review T17.F2): four read-only tools over an in-memory MCP session, as a client agent sees them."""
import asyncio
import json

import pytest
from mcp.client.client import Client

from copilot import config
from copilot.mcp_server import server

TOOLS = {"search_regulations", "validate_invoice", "compare_countries", "list_rules"}


def session(*calls):
    """Run tool calls in one client session: [(name, arguments), ...] -> results (structured content)."""
    async def go():
        async with Client(server, raise_exceptions=True) as client:
            tools = await client.list_tools()
            results = []
            for name, arguments in calls:
                result = await client.call_tool(name, arguments)
                results.append((result.is_error, result.structured_content
                                or json.loads(result.content[0].text) if not result.is_error
                                else result.content[0].text))
            return tools, results
    return asyncio.run(go())


def test_four_read_only_tools_are_listed():
    tools, _ = session()
    listed = {t.name: t for t in tools.tools}
    assert set(listed) == TOOLS
    for tool in listed.values():
        assert tool.annotations.read_only_hint is True and tool.annotations.destructive_hint is False
        assert tool.description


def test_search_is_date_aware():
    _, [(error, before), (_, after)] = session(
        ("search_regulations", {"query": "Orlavia reporting deadline hours", "as_of": "2025-11-15",
                                "countries": ["OL"]}),
        ("search_regulations", {"query": "Orlavia reporting deadline hours", "as_of": "2026-05-15",
                                "countries": ["OL"], "k": 3}))
    assert error is False and before["as_of"] == "2025-11-15" and before["passages"]
    assert all(p["country"] in ("OL", None) or p["doc_id"].startswith("COM") for p in before["passages"])
    assert "OL-AM-12" not in {p["doc_id"] for p in before["passages"]}      # published 1 December 2025
    assert len(after["passages"]) <= 3 and {"ref", "text", "valid_from"} <= set(after["passages"][0])


def test_validate_invoice_is_the_engine():
    xml = (config.SAMPLES_DIR / "ks-demo-old-rate-no-ksk-total.xml").read_text(encoding="utf-8")
    _, [(_, report), (_, bad)] = session(("validate_invoice", {"xml": xml, "transaction_type": "B2B"}),
                                         ("validate_invoice", {"xml": "<not-xml"}))
    assert [f["rule_id"] for f in report["findings"]] == ["KS-04", "KS-05"] and report["valid"] is False
    assert [f["rule_id"] for f in bad["findings"]] == ["XML-00"]


def test_compare_and_list_rules():
    _, [(_, table), (_, listed), (_, everything)] = session(
        ("compare_countries", {"countries": ["VD", "KS"], "as_of": "2026-05-15"}),
        ("list_rules", {"country": "OL", "as_of": "2026-05-15"}),
        ("list_rules", {}))
    assert table["countries"] == ["KS", "VD"] and set(table["aspects"]) >= {"model", "archiving", "currency"}
    assert all(p["doc_id"].startswith("KS-") for p in table["aspects"]["archiving"]["KS"])
    ids = [r["id"] for r in listed["rules"]]
    assert any(i.startswith("OL-") for i in ids) and not any(i.startswith(("VD-", "KS-")) for i in ids)
    assert len(everything["rules"]) == 30


@pytest.mark.parametrize("name, arguments, message", [
    ("compare_countries", {"countries": ["VD"]}, "at least two"),
    ("search_regulations", {"query": "x", "countries": ["FR"]}, "Unknown country"),
    ("list_rules", {"country": "FR"}, "Unknown country"),
    ("search_regulations", {"query": "x", "as_of": "next week"}, "YYYY-MM-DD"),
])
def test_bad_arguments_are_tool_errors(name, arguments, message):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, arguments)
    result = asyncio.run(go())
    assert result.is_error and message in result.content[0].text


def test_an_oversized_invoice_is_refused(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_KB", 1)

    async def go():
        async with Client(server) as client:
            return await client.call_tool("validate_invoice", {"xml": "x" * 2048})
    result = asyncio.run(go())
    assert result.is_error and "larger than 1 KB" in result.content[0].text


def test_the_stdio_server_starts_as_a_client_would_start_it():
    """`python -m copilot.mcp_server`, the command in the README's client config, over a real stdio pipe."""
    import os
    import sys

    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=["-m", "copilot.mcp_server"], env=dict(os.environ),
                                   cwd=str(config.BASE_DIR))

    async def go():
        async with Client(params, read_timeout_seconds=60) as client:
            tools = await client.list_tools()
            listed = await client.call_tool("list_rules", {"country": "KS"})
            return {t.name for t in tools.tools}, listed
    names, listed = asyncio.run(go())
    assert names == TOOLS and not listed.is_error
