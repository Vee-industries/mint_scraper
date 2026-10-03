# Mint Scraper

Web search for local AI. Mint Scraper gives locally run AI assistants live web results, through two interfaces:

- **MCP server** (`mint_mcp.py`): a `web_search` tool for any Model Context Protocol client, such as LM Studio or Claude. Built as the search tool for [Latent Lab Explorer](https://github.com/Vee-industries), my local AI agent engine.
- **HTTP API** (`Mint_Scraper.py`): a small Flask service on `127.0.0.1:5055`, with an optional system tray icon for switching engines.

No AI account or cloud AI service is needed. Search queries go to the search engine you choose.

## Engines

| Engine | Source | Key needed |
|---|---|---|
| `web` (default) | DuckDuckGo and other engines, through the [`ddgs`](https://pypi.org/project/ddgs/) library | No |
| `wikipedia` | Wikipedia's official API | No |
| `brave` | Brave Search API | `BRAVE_API_KEY` |

## Install

```
python -m venv venv
venv\Scripts\activate          # Windows; use source venv/bin/activate elsewhere
pip install -r requirements.txt
```

## Use it as an MCP server

Add it to your MCP client's config (for LM Studio, `mcp.json`):

```json
{
  "mcpServers": {
    "mint-scraper": {
      "command": "C:/path/to/mint-scraper/venv/Scripts/python.exe",
      "args": ["C:/path/to/mint-scraper/mint_mcp.py"]
    }
  }
}
```

The assistant then has a `web_search(query, engine="web", max_results=5)` tool that returns a list of results, each with `title`, `link` and `snippet`.

## Use it as an HTTP API

```
python Mint_Scraper.py            # API plus tray icon
python Mint_Scraper.py --no-tray  # API only
```

| Endpoint | What it does |
|---|---|
| `GET /search?q=...` | Search with the current engine; returns `answer` (top result) and `sources` |
| `GET /engine`, `POST /engine` | Read or set the engine: `Web`, `Wikipedia`, `Brave` |
| `GET /health` | Status |
| `GET /shutdown` | Stop the server |

The server listens on `127.0.0.1` only. To require a key, set `MINT_API_KEYS="name:token,name2:token2"`, then send `Authorization: Bearer <token>`. With no keys set, authentication is off and the log says so. Set `MINT_PORT` to change the port.

## Test

```
python tests/test_live.py
```

Runs real searches through the HTTP API and through the MCP server started by an MCP client. Needs an internet connection.

## License

MIT. See [LICENSE](LICENSE).
