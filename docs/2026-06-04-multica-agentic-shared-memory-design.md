# Multica Agentic Shared Memory MCP Design

## Goal

Multica has multiple independent AI agents/machines. They need shared durable project context without rereading full historical chat transcripts. The MCP bridge should store distilled, scoped memories in Mem0 so agents can retrieve concise context for the current org/product/project/repo/task.

## Non-goals

- Do not store raw chat history as memory.
- Do not dump full files, tool logs, or transient reasoning into vector memory.
- Do not replace source control, issue trackers, or design docs.
- Do not require one MCP deployment per small task.

## Recommended approach

Use a hybrid scoped memory model with project-scoped MCP tokens:

- `user_id` partitions large contexts: `org:product:project`.
- Metadata scopes the memory inside that partition: `repo`, `task`, `scope`, `memory_type`, `importance`, `agent_id`, `source`, `source_hash`.
- Project Bearer tokens map to allowed `org/product/project/repo` and are enforced server-side.
- New purpose-built tools guide agents to save/search the right kind of context.
- Existing generic tools remain for backward compatibility but are constrained to the token scope.

## Scope hierarchy

```text
org -> product -> project -> repo -> task -> agent
```

Example values:

```text
org: multica
product: multica
project: ai-agentic | sim-manager | crm | billing
repo: test-agentic | multica-api | multica-web
task: gate1-discovery | dokploy-mcp | memory-bridge
agent: ba | architect | backend | frontend | devops | reviewer
```

`user_id` format:

```text
{org}:{product}:{project}
```

Example:

```text
multica:multica:ai-agentic
multica:multica:sim-manager
```

## Metadata schema

```json
{
  "org": "multica",
  "product": "multica",
  "project": "ai-agentic",
  "repo": "test-agentic",
  "task": "memory-bridge",
  "scope": "project",
  "memory_type": "decision",
  "importance": 4,
  "agent_id": "architect",
  "source": "human",
  "source_hash": "sha256-normalized-content"
}
```

Allowed `scope`:

- `global`
- `product`
- `project`
- `repo`
- `task`

Project token format:

```text
org:product:project:token[:repo]
```

Example:

```env
MCP_PROJECT_TOKENS=multica:multica:ai-agentic:token_agentic_xxx,multica:multica:sim-manager:token_sim_xxx
```

Requests must send:

```text
Authorization: Bearer <project-token>
```

If a token maps to `multica/multica/sim-manager`, the server rejects attempts to read or write `project=ai-agentic`. Optional `repo` in the token narrows access further.

Allowed `memory_type`:

- `decision`
- `requirement`
- `constraint`
- `architecture`
- `handoff`
- `issue`
- `preference`
- `deployment`
- `api`
- `env`
- `note`

## Tools

### `remember_context`

Save durable context. It normalizes content, checks budget, computes a hash, searches for duplicates, and writes to Mem0 only if useful.

Inputs:

- `content`
- `org`, `product`, `project`
- optional `repo`, `task`, `agent_id`
- `scope`
- `memory_type`
- `importance`
- `source`

Rules:

- Reject empty content.
- Reject content over the configured character budget.
- Reject low-importance content below auto-save threshold.
- Skip likely duplicates using `source_hash` search.

### `search_context`

Search scoped memories. It starts narrow and can widen if needed.

Inputs:

- `query`
- `org`, `product`
- optional `project`, `repo`, `task`, `scope`, `memory_type`
- `top_k`
- `widen`

Search order when `widen=true`:

1. task/repo/project scope
2. project scope
3. product scope
4. global scope

### `get_project_brief`

Retrieve high-importance context for onboarding an agent at start of work.

Prioritizes:

- requirements
- constraints
- decisions
- architecture
- active issues
- deployment/env conventions

### `summarize_handoff`

Store compact structured handoff between agents.

Inputs:

- `done`
- `decisions`
- `blockers`
- `next_steps`
- same scope fields as `remember_context`

Saves one `memory_type=handoff` memory.

## Embedding/token budget policy

Only save memory if it is durable and useful across sessions.

Save:

- confirmed decisions
- stable business/technical constraints
- architecture boundaries
- deployment conventions
- unresolved blockers
- handoff summaries
- stable user/project preferences

Do not save:

- full chat transcripts
- raw logs
- one-off Q&A
- speculative reasoning not accepted by user
- repeated facts
- full source files
- low-value tool output

Default gates:

```text
MAX_MEMORY_CHARS=1500
MIN_IMPORTANCE_TO_SAVE=3
DEDUP_SEARCH_TOP_K=5
```

## Agent workflow

At start:

```text
1. get_project_brief(org, product, project, repo, task)
2. search_context(query, narrow scope)
3. widen only if context is insufficient
```

During work:

```text
1. remember_context only for durable facts
2. use memory_type + scope explicitly
3. prefer concise summaries over raw data
```

At handoff/end:

```text
1. summarize_handoff(done, decisions, blockers, next_steps)
2. store only what the next agent needs
```

## Error handling

- Mem0 API errors bubble up with clear MCP tool errors.
- Duplicate detection is best-effort; false negatives are acceptable.
- Metadata filtering is best-effort because Mem0 OSS search behavior may vary by version.
- The bridge should still return compact output even if metadata is missing from older memories.

## Backward compatibility

Keep existing tools:

- `add_memory`
- `search_memories`
- `list_memories`
- `delete_memory`

Add new scoped tools without removing old behavior.

## Success criteria

- Multiple Multica agents can retrieve shared project context with short queries.
- Agents do not need full historic Multica design chat context.
- Memory store remains concise through budget, importance, and duplicate gates.
- Existing MCP clients continue working.
