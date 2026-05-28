# Installing & using Habitica-for-Claude on each surface

A script-backed Skill runs fully only inside **Claude Code** (CLI, IDE
extension, and the Claude Code desktop app) — those are the environments that
can execute the bundled Python and reach the network. For other surfaces, use
the MCP server or import the client directly.

| Surface | Works? | How |
| --- | --- | --- |
| Claude Code (CLI / IDE / desktop) | ✅ | Skill — install as a **plugin** or clone + `install.sh` |
| Claude Desktop, other MCP clients | ✅ | the **MCP server** (`mcp/habitica_mcp.py`) |
| Claude Agent SDK / custom agents | ✅ | the **MCP server**, or `import habitica_client` — see [agent-sdk.md](agent-sdk.md) |
| Claude API "skills" feature | ❌ | the API skill sandbox has **no network**, so HTTP calls can't run there — use the MCP server or client instead |
| Claude.ai web chat | ❌ | no local code execution |

## A. Claude Code — plugin (one-time, no clone)

```text
/plugin marketplace add maskull42/habitica-skill
/plugin install habitica@habitica-for-claude
```

Then configure credentials (below) and restart Claude Code. The skill is
available as `/habitica:habitica` and auto-triggers when you mention Habitica.

## B. Claude Code — clone + install script

```bash
git clone https://github.com/maskull42/habitica-skill.git
cd habitica-skill
./install.sh            # symlinks skills/habitica into ~/.claude/skills/
# ./install.sh --copy   # or copy instead of symlink
```

Restart Claude Code. The skill is available as `/habitica`.

## C. MCP server (Claude Desktop, Agent SDK, other MCP clients)

```bash
pip install -r mcp/requirements.txt
```

Register it with your client (Claude Desktop's config, or `claude mcp add`),
passing credentials via `env`:

```json
{
  "mcpServers": {
    "habitica": {
      "command": "python3",
      "args": ["/absolute/path/to/habitica-skill/mcp/habitica_mcp.py"],
      "env": {
        "HABITICA_USER_ID": "your-user-id",
        "HABITICA_API_TOKEN": "your-api-token"
      }
    }
  }
}
```

## Credentials

Get your **User ID** and **API Token** at
https://habitica.com/user/settings/api (Settings → Site Data / API).

Provide them by either:

- environment variables: `HABITICA_USER_ID`, `HABITICA_API_TOKEN`
  (optional `HABITICA_APP_NAME` to customize the `x-client` suffix); or
- a file at `~/.config/habitica/credentials` (then
  `chmod 600 ~/.config/habitica/credentials`):

  ```
  HABITICA_USER_ID=your-user-id
  HABITICA_API_TOKEN=your-api-token
  ```

Never commit credentials. Treat the API token like a password.
