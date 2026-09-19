from howzo import mcp
from howzo.db import db, upsert


def test_initialize():
    resp = mcp.mcp_handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2024-11-05"}})
    assert resp["result"]["serverInfo"]["name"] == "howzo"
    assert resp["result"]["serverInfo"]["version"] == mcp.__version__


def test_initialize_without_params_uses_default_protocol():
    resp = mcp.mcp_handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["result"]["protocolVersion"] == "2024-11-05"


def test_notification_returns_none():
    assert mcp.mcp_handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping():
    resp = mcp.mcp_handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert resp == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_tools_list():
    resp = mcp.mcp_handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"howzo_ask", "howzo_whatis", "howzo_list"}


def test_tools_call_whatis(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWZO_DB", str(tmp_path))
    c = db()
    upsert(c, "jq", "brew", "1.7", "", "commandline JSON processor")
    c.commit()
    c.close()
    resp = mcp.mcp_handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                           "params": {"name": "howzo_whatis", "arguments": {"tool": "jq"}}})
    text = resp["result"]["content"][0]["text"]
    assert text.startswith("jq")
    assert "commandline JSON processor" in text
    assert not resp["result"].get("isError")


def test_tools_call_unknown_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("HOWZO_DB", str(tmp_path))
    resp = mcp.mcp_handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                           "params": {"name": "howzo_bogus", "arguments": {}}})
    assert resp["result"]["isError"] is True


def test_unknown_method():
    resp = mcp.mcp_handle({"jsonrpc": "2.0", "id": 6, "method": "bogus"})
    assert resp["error"]["code"] == -32601
