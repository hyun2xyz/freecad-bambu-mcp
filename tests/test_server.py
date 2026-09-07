import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_mcp_stdio_roundtrip_and_execution_annotations(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"workspace": str(tmp_path)}), encoding="utf-8")

    async def run():
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "freecad_bambu_mcp.cli", "--config", str(cfg), "serve"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                tools = {t.name: t for t in listing.tools}
                assert len(tools) == 12
                for name in ("cad_execute", "prepare_job", "start_print"):
                    assert tools[name].annotations.destructiveHint
                    assert tools[name].annotations.openWorldHint
                result = await session.call_tool("capabilities", {})
                assert not result.isError
                data = json.loads(result.content[0].text)
                assert data["workspace"] == str(tmp_path.resolve())
                assert data["trusted_python"] is False
                assert data["printers"] == {}
                result = await session.call_tool("start_print", {"job_id": "0" * 20, "sha256": "0" * 64})
                assert result.isError
    asyncio.run(run())
