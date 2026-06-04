# Mem0 MCP Bridge (Dokploy)

MCP HTTP server gọi **Mem0 Server self-hosted** (cùng Postgres với `deploy/mem0-dokploy`).

Bridge hỗ trợ 2 lớp memory:

- **Legacy shared memory**: `add_memory`, `search_memories`, `list_memories`, `delete_memory`.
- **Multica Agentic scoped memory**: `remember_context`, `search_context`, `get_project_brief`, `summarize_handoff`.

Remote MCP yêu cầu project-scoped Bearer token qua `MCP_PROJECT_TOKENS`. Token nào chỉ được đọc/ghi đúng `org/product/project/repo` đã map.

Scoped memory dùng hierarchy:

```text
org -> product -> project -> repo -> task -> agent
```

`user_id` scoped:

```text
{org}:{product}:{project}
```

Ví dụ:

```text
multica:multica:ai-agentic
```

Budget gate giúp tiết kiệm embedding/token:

- không lưu raw chat history;
- không lưu log/tool output dài;
- chỉ lưu durable facts: decision, requirement, constraint, architecture, handoff, issue, preference, deployment, api, env;
- giới hạn mặc định `MEM0_MAX_MEMORY_CHARS=1500`;
- chỉ auto-save khi `importance >= MEM0_MIN_IMPORTANCE_TO_SAVE`.

| File | Mục đích |
| ---- | -------- |
| [HUONG-DAN-DOKPLOY-MCP.md](./HUONG-DAN-DOKPLOY-MCP.md) | Hướng dẫn deploy & cấu hình Cursor/Claude |
| [docs/2026-06-04-multica-agentic-shared-memory-design.md](./docs/2026-06-04-multica-agentic-shared-memory-design.md) | Design scoped memory cho Multica Agentic |
| [docker-compose.dokploy.yaml](./docker-compose.dokploy.yaml) | Compose cho Dokploy |
| [app/](./app/) | FastMCP bridge (Python) |
| [.env.example](./.env.example) | Biến môi trường |

**Điều kiện:** Mem0 Server đã chạy (`deploy/mem0-dokploy`) và có API key `m0sk_...`.
