"""Mint Scraper as an MCP server: gives any MCP client (LM Studio, Claude, Latent Lab Explorer) a web_search tool.

Run over stdio:  python mint_mcp.py
"""
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from search_api import do_search

ENGINES = {"web": "ddg", "wikipedia": "wiki", "brave": "brave"}

server = MCPServer(name="mint-scraper", instructions="Web search for local AI agents.")


@server.tool(description="Search the web. engine: web (default; DuckDuckGo and other engines via ddgs), wikipedia, or brave (needs BRAVE_API_KEY).")
def web_search(query: str, engine: str = "web", max_results: int = 5) -> list[dict]:
    key = ENGINES.get(engine.lower())
    if key is None:
        raise ToolError(f"Unknown engine '{engine}'. Use one of: {', '.join(ENGINES)}.")
    results = do_search(query, key, max(1, min(max_results, 10)))
    # do_search reports a failed search as one result titled "... Error" with no link,
    # for people reading the web page. An MCP client gets a real tool error instead,
    # so it is not mistaken for a search result.
    if len(results) == 1 and results[0]["title"].endswith("Error") and not results[0]["link"]:
        raise ToolError(f"{engine} search failed: {results[0]['snippet']}")
    return results


if __name__ == "__main__":
    server.run("stdio")
