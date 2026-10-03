"""Live smoke tests: real web searches through the HTTP API and the MCP server.

Run:  python tests/test_live.py   (needs an internet connection)
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_http_api():
    import Mint_Scraper
    client = Mint_Scraper.app.test_client()
    assert client.get("/health").get_json()["flask"] == "green"
    data = client.get("/search?q=Greater Sudbury Ontario").get_json()
    assert data["sources"] and data["sources"][0]["link"].startswith("http"), data
    print("HTTP /search ok:", data["sources"][0]["title"])
    assert client.post("/engine", json={"engine": "Wikipedia"}).get_json()["ok"]
    wiki = client.get("/search?q=Sudbury Basin").get_json()
    assert "wikipedia.org" in wiki["sources"][0]["link"], wiki
    print("HTTP Wikipedia ok:", wiki["sources"][0]["title"])


async def _mcp():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, "mint_mcp.py")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            assert "web_search" in names, names
            result = await session.call_tool("web_search", {"query": "Model Context Protocol", "max_results": 3})
            text = "".join(getattr(c, "text", "") for c in result.content)
            assert "http" in text, text[:300]
            print("MCP web_search ok:", text[:120].replace("\n", " "))


def test_mcp_server():
    asyncio.run(_mcp())


if __name__ == "__main__":
    test_http_api()
    test_mcp_server()
    print("all live tests passed")
