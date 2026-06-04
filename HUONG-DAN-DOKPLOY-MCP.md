# Deploy MCP Bridge → Mem0 Server (Dokploy)

MCP cho AI agent (Cursor, Claude Code, Codex, …) gọi **cùng memory** với Mem0 Server đã deploy ở [`deploy/mem0-dokploy`](../mem0-dokploy/HUONG-DAN-DOKPLOY.md).

```text
AI Client  --HTTPS-->  mem0-mcp-bridge (/mcp)  --HTTPS-->  mem0-api (REST + X-API-Key)
                                                      └── Postgres (memory thật)
```

Bridge này chỉ **proxy REST** sang Mem0 OSS — không thêm datastore riêng.

---

## 0. Điều kiện tiên quyết

| Đã xong | Kiểm tra |
|---------|----------|
| Mem0 Server deploy | `https://mem0-api.ten-ban.com/docs` mở được |
| API key | `m0sk_...` từ Dashboard → API Keys |
| `user_id` team | Thống nhất `team-shared` (hoặc tên khác) |

---

## 1. Cấu trúc thư mục (repo riêng)

```
deploy/mem0-mcp-dokploy/
├── HUONG-DAN-DOKPLOY-MCP.md    ← file này
├── README.md
├── docker-compose.dokploy.yaml
├── .env.example
└── app/
    ├── Dockerfile
    ├── server.py               ← FastMCP, legacy + scoped tools
    └── requirements.txt
└── docs/
    └── 2026-06-04-multica-agentic-shared-memory-design.md
```

**Không** trộn vào `deploy/mem0-dokploy/` — hai Compose service độc lập trên Dokploy.

---

## 2. Đưa code lên Git (cho Dokploy)

### Cách A — Repo riêng `mem0-mcp-bridge`

```bash
cd deploy/mem0-mcp-dokploy
git init
git add .
git commit -m "Mem0 MCP bridge for Dokploy"
git remote add origin https://github.com/<user>/mem0-mcp-bridge.git
git push -u origin main
```

### Cách B — Cùng monorepo `test-agentic`

Trên Dokploy:

- **Repository:** repo chứa `deploy/mem0-mcp-dokploy`
- **Compose path:** `deploy/mem0-mcp-dokploy/docker-compose.dokploy.yaml`

---

## 3. Tạo Compose service trên Dokploy

1. **Project** → **Add Service** → **Compose** (service mới, tách Mem0 Server).
2. **Provider:** Git repo (A hoặc B ở trên).
3. **Compose File Path:** `docker-compose.dokploy.yaml` (hoặc `deploy/mem0-mcp-dokploy/docker-compose.dokploy.yaml`).
4. **Environment:**

```env
MEM0_API_URL=https://mem0-api.ten-ban.com
MEM0_API_KEY=m0sk_...
MEM0_DEFAULT_USER_ID=team-shared
MEM0_DEFAULT_ORG=multica
MEM0_DEFAULT_PRODUCT=multica
MEM0_DEFAULT_PROJECT=ai-agentic
MEM0_MAX_MEMORY_CHARS=1500
MEM0_MIN_IMPORTANCE_TO_SAVE=3
MEM0_DEDUP_SEARCH_TOP_K=5

# Project-scoped MCP auth
# Format: org:product:project:token[:repo]
MCP_PROJECT_TOKENS=multica:multica:ai-agentic:token_agentic_xxx,multica:multica:sim-manager:token_sim_xxx
MCP_ALLOW_UNAUTHENTICATED=false
MCP_ALLOW_CROSS_SCOPE_DELETE=false
```

| Biến | Bắt buộc | Ghi chú |
|------|----------|---------|
| `MEM0_API_URL` | Có | URL **public** API Mem0 (HTTPS). Không dùng `http://localhost` |
| `MEM0_API_KEY` | Có (auth bật) | Header `X-API-Key` |
| `MEM0_DEFAULT_USER_ID` | Khuyến nghị | Legacy shared memory, mặc định `team-shared` |
| `MEM0_DEFAULT_ORG` | Khuyến nghị | Scoped memory mặc định, ví dụ `multica` |
| `MEM0_DEFAULT_PRODUCT` | Khuyến nghị | Product mặc định, ví dụ `multica` |
| `MEM0_DEFAULT_PROJECT` | Khuyến nghị | Project mặc định, ví dụ `ai-agentic` |
| `MEM0_MAX_MEMORY_CHARS` | Khuyến nghị | Giới hạn mỗi memory để tiết kiệm embedding, mặc định `1500` |
| `MEM0_MIN_IMPORTANCE_TO_SAVE` | Khuyến nghị | Chỉ auto-save memory đủ quan trọng, mặc định `3` |
| `MEM0_DEDUP_SEARCH_TOP_K` | Khuyến nghị | Số kết quả dùng để dò trùng hash, mặc định `5` |
| `MCP_PROJECT_TOKENS` | Có | Map token → scope dự án, format `org:product:project:token[:repo]` |
| `MCP_ALLOW_UNAUTHENTICATED` | Không | Chỉ bật `true` khi dev local; production để `false` |
| `MCP_ALLOW_CROSS_SCOPE_DELETE` | Không | Delete theo memory id không xác minh scope được; production để `false` |

5. **Domains** (Traefik):

| Service | Host ví dụ | Port container | Path |
|---------|------------|----------------|------|
| `mem0-mcp-bridge` | `mem0-mcp.ten-ban.com` | **8080** | `/` (MCP endpoint: `/mcp`) |

Không bind host port — giống Mem0 Server.

6. **Advanced → Volumes:** để trống (stateless bridge).

7. **Deploy**.

---

## 4. MCP tools exposed

### Scoped tools cho Multica Agentic

| Tool | Mục đích |
| ---- | -------- |
| `remember_context` | Lưu durable context theo `org/product/project/repo/task`, có budget + dedupe gate |
| `search_context` | Tìm context theo scope hẹp trước, có thể widen lên project/product/global |
| `get_project_brief` | Lấy brief ngắn cho agent mới khi bắt đầu task |
| `summarize_handoff` | Lưu handoff compact giữa các AI agent |

Scope hierarchy:

```text
org -> product -> project -> repo -> task -> agent
```

`user_id` scoped mặc định:

```text
{org}:{product}:{project}
```

Ví dụ:

```text
multica:multica:ai-agentic
multica:multica:sim-manager
```

Chỉ lưu facts bền vững: decisions, requirements, constraints, architecture, deployment/env, blockers, handoff. Không lưu full chat/log/raw tool output.

### Legacy tools

| Tool | Mem0 REST |
| ---- | --------- |
| `add_memory` | `POST /memories` |
| `search_memories` | `POST /search` |
| `list_memories` | `GET /memories?user_id=` |
| `delete_memory` | `DELETE /memories/{id}` |

Agent vẫn có thể truyền `user_id` khác mặc định khi gọi legacy tool.

---

## 5. Cấu hình AI clients

### Cursor

#### Cách 1 — một MCP endpoint chung, scope theo tool params

Settings → MCP hoặc `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "mem0-shared": {
      "url": "https://mem0-mcp.ten-ban.com/mcp",
      "headers": {
        "Authorization": "Bearer token_sim_xxx"
      }
    }
  }
}
```

Sau đó trong project rule / instruction của từng repo, bắt agent dùng scoped tools với scope riêng:

```text
Use MCP server mem0-shared for Multica Agentic memory.
On start, call get_project_brief(org="multica", product="multica", project="sim-manager", repo="multica-api").
When saving durable context, call remember_context with org="multica", product="multica", project="sim-manager", repo="multica-api".
Do not save raw chat history, logs, or full files.
```

Đây là cách linh hoạt nhất nếu một agent làm nhiều project vì cùng endpoint nhưng đổi `project/repo/task` per call. Server vẫn kiểm tra Bearer token: token map vào project nào thì chỉ cho scope project đó. Nếu agent truyền project khác, tool bị chặn.

#### Cách 2 — nhiều alias cùng URL, dễ nhìn trong từng workspace

```json
{
  "mcpServers": {
    "mem0-multica-sim-manager": {
      "url": "https://mem0-mcp.ten-ban.com/mcp",
      "headers": {
        "Authorization": "Bearer token_sim_xxx"
      }
    },
    "mem0-multica-ai-agentic": {
      "url": "https://mem0-mcp.ten-ban.com/mcp",
      "headers": {
        "Authorization": "Bearer token_agentic_xxx"
      }
    }
  }
}
```

Alias chỉ giúp dễ nhớ; server vẫn là một. Scope thật vẫn phải truyền qua `remember_context`, `search_context`, `get_project_brief`, `summarize_handoff`.

#### Cách 3 — nhiều MCP deployment nếu cần cô lập mạnh

Tạo nhiều Dokploy service/endpoint, mỗi endpoint set env khác:

```env
MEM0_DEFAULT_ORG=multica
MEM0_DEFAULT_PRODUCT=multica
MEM0_DEFAULT_PROJECT=sim-manager
```

Cách này cô lập hơn nhưng tốn vận hành hơn. Khuyến nghị chỉ dùng cho khách hàng/dự án cần boundary bảo mật riêng.

Restart Cursor sau khi lưu.

### Claude Code (HTTP / streamable)

```bash
claude mcp add --scope user mem0-shared \
  --transport http \
  --url https://mem0-mcp.ten-ban.com/mcp
```

(Phiên bản CLI hỗ trợ `http` / streamable — nếu chỉ có `stdio`, dùng tunnel hoặc client hỗ trợ remote MCP.)

### Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.mem0-shared]
url = "https://mem0-mcp.ten-ban.com/mcp"
```

### Mem0 cloud MCP (tham khảo — không dùng khi self-hosted)

```json
"url": "https://mcp.mem0.ai/mcp/"
```

---

## 6. Bảo mật

Endpoint MCP **không có auth sẵn**. Khuyến nghị:

1. **Traefik middleware** — Basic Auth, IP allowlist, hoặc forward auth trước `/mcp`.
2. **Không** publish MCP ra internet công khai không bảo vệ.
3. `MEM0_API_KEY` chỉ nằm trong **Environment** Dokploy (service MCP), không commit Git.

Mem0 API vẫn yêu cầu `X-API-Key` — key nằm phía server MCP, client Cursor không cần biết key nếu chỉ gọi MCP.

---

## 7. Mạng Docker (2 Compose trên cùng VPS)

| Cách | `MEM0_API_URL` |
|------|----------------|
| **Khuyến nghị** | `https://mem0-api.ten-ban.com` (qua Traefik) |
| Nội bộ (nâng cao) | Gắn 2 stack cùng `external` network + `http://mem0:8000` — tên service phải khớp project Mem0 |

`http://mem0:8000` **chỉ** hoạt động nếu hai stack share network; mặc định Dokploy **tách** network → dùng URL public.

---

## 8. Kiểm tra

```bash
# Từ máy bạn (sau khi có domain + optional auth)
curl -sI https://mem0-mcp.ten-ban.com/mcp

# Mem0 API trực tiếp (có key)
curl -s https://mem0-api.ten-ban.com/auth/setup-status \
  -H "X-API-Key: m0sk_..."
```

Trong Cursor: thử gọi `remember_context` với nội dung ngắn kiểu *"Multica AI Agentic dùng scoped Mem0 memory, không lưu raw chat history"*, `project=ai-agentic`, `scope=project`, `memory_type=decision`, `importance=4` → kiểm tra Dashboard Mem0 → Memories, `user_id=multica:multica:ai-agentic`.

---

## 9. Xử lý sự cố

| Triệu chứng | Nguyên nhân | Xử lý |
|-------------|-------------|--------|
| MCP 401 / mem0 API error | Sai `MEM0_API_KEY` | Tạo key mới trên Mem0 Dashboard |
| Cannot connect to mem0 | `MEM0_API_URL` sai / network | Dùng HTTPS domain API, không localhost |
| Tool không xuất hiện | Cursor chưa restart | Restart IDE |
| Memory không chung | Khác `user_id` | Set `MEM0_DEFAULT_USER_ID` + nhắc agent trong prompt |
| Build fail | Thiếu RAM | Build local, push image registry |

---

## 10. So với `mem0-dokploy`

| | `mem0-dokploy` | `mem0-mcp-dokploy` |
|--|----------------|-------------------|
| Vai trò | API + DB + Dashboard | MCP cho agent |
| Bắt buộc | Có | Sau khi Mem0 Server chạy |
| Volume | `postgres_db` | Không |
| Client | REST / Dashboard | MCP HTTP |

---

### Tóm tắt

1. Deploy **Mem0 Server** trước (`mem0-dokploy`).  
2. Tạo service Compose mới → repo `mem0-mcp-dokploy` → path `docker-compose.dokploy.yaml`.  
3. Env: `MEM0_API_URL` + `MEM0_API_KEY` + `MEM0_DEFAULT_USER_ID`.  
4. Domain → `mem0-mcp.*`, port **8080**, client URL `https://mem0-mcp.*/mcp`.  
5. Bảo vệ MCP bằng Traefik; memory vẫn một nguồn trên Mem0 Server.
