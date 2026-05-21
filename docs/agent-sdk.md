# Using Habitica from the Claude Agent SDK / API

Two supported integration paths for embedding Habitica in your own agent.

## Path 1 (recommended): the MCP server

The Agent SDK consumes MCP servers directly, so this is the cleanest option and
reuses the same guarded tools the rest of this project ships.

```bash
pip install -r mcp/requirements.txt
```

Point the SDK at `mcp/habitica_mcp.py` as a stdio MCP server, passing
credentials through its environment (`HABITICA_USER_ID`, `HABITICA_API_TOKEN`).
Tools include `list_tasks`, `get_stats`, `add_task`, `complete_task`,
`score_task`, `delete_task` (and the checklist/tag tools). Destructive or costly
tools (`delete_task`, `delete_tag`, `score_task` down on a daily/todo, scoring a
reward up) require `confirm=true`, so your agent must confirm with the user
before retrying with confirmation.

## Path 2: import the client directly

For a pure-Python agent, skip MCP and call the stdlib client. It has no
dependencies.

```python
import sys
sys.path.insert(0, "skills/habitica/scripts")  # or install it on PYTHONPATH
from habitica_client import HabiticaClient, HabiticaError

client = HabiticaClient()  # reads HABITICA_USER_ID / HABITICA_API_TOKEN
try:
    todos = client.list_tasks("todos")
    for t in todos:
        print(t.get("text"), t.get("id") or t.get("_id"))
    client.create_task(type="todo", text="Written from my agent")
except HabiticaError as e:
    print("Habitica error:", e.detailed())
```

Your agent owns the guardrails in this path — gate destructive calls
(`delete_task`, `delete_tag`, `score_task(..., 'down')` on dailies/todos, and
scoring rewards) behind user confirmation yourself.

## Not supported: the Claude API "skills" feature

The hosted API skill sandbox executes code **without network access**, so a
skill that makes HTTP calls to Habitica cannot run there. Use Path 1 or Path 2
instead. (The filesystem Skill in `skills/habitica` is for Claude Code, which
does have network and a Python runtime.)
