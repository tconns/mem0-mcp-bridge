"""
MCP bridge → Mem0 self-hosted REST API (OSS).
Đồng bộ memory với stack deploy/mem0-dokploy (Postgres, user_id chung).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.server.dependencies import get_access_token

MEM0_API_URL = os.environ.get("MEM0_API_URL", "http://mem0:8000").rstrip("/")
MEM0_API_KEY = os.environ.get("MEM0_API_KEY", "")
DEFAULT_USER_ID = os.environ.get("MEM0_DEFAULT_USER_ID", "team-shared")
DEFAULT_ORG = os.environ.get("MEM0_DEFAULT_ORG", "multica")
DEFAULT_PRODUCT = os.environ.get("MEM0_DEFAULT_PRODUCT", "multica")
DEFAULT_PROJECT = os.environ.get("MEM0_DEFAULT_PROJECT", "ai-agentic")
MCP_PROJECT_TOKENS = os.environ.get("MCP_PROJECT_TOKENS", "")
MCP_ALLOW_UNAUTHENTICATED = os.environ.get("MCP_ALLOW_UNAUTHENTICATED", "false").lower() == "true"
MCP_ALLOW_CROSS_SCOPE_DELETE = os.environ.get("MCP_ALLOW_CROSS_SCOPE_DELETE", "false").lower() == "true"
MAX_MEMORY_CHARS = int(os.environ.get("MEM0_MAX_MEMORY_CHARS", "1500"))
MIN_IMPORTANCE_TO_SAVE = int(os.environ.get("MEM0_MIN_IMPORTANCE_TO_SAVE", "3"))
DEDUP_SEARCH_TOP_K = int(os.environ.get("MEM0_DEDUP_SEARCH_TOP_K", "5"))
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8080"))

Scope = Literal["global", "product", "project", "repo", "task"]
MemoryType = Literal[
    "decision",
    "requirement",
    "constraint",
    "architecture",
    "handoff",
    "issue",
    "preference",
    "deployment",
    "api",
    "env",
    "note",
]
Source = Literal["human", "agent", "doc", "commit", "tool"]
ProjectAuth = dict[str, str | None]


def _parse_project_tokens(raw: str) -> dict[str, ProjectAuth]:
    tokens: dict[str, ProjectAuth] = {}
    for entry in raw.split(","):
        item = entry.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) < 4:
            continue
        org, product, project, token = parts[:4]
        repo = parts[4] if len(parts) >= 5 else None
        clean_token = token.strip()
        if clean_token:
            tokens[clean_token] = {
                "org": org.strip() or DEFAULT_ORG,
                "product": product.strip() or DEFAULT_PRODUCT,
                "project": project.strip() or DEFAULT_PROJECT,
                "repo": repo.strip() if repo else None,
            }
    return tokens


PROJECT_TOKENS = _parse_project_tokens(MCP_PROJECT_TOKENS)
TOKEN_VERIFIER = StaticTokenVerifier(
    tokens={
        token: {
            "client_id": f"{context['org']}:{context['product']}:{context['project']}",
            "scopes": ["memory:read", "memory:write"],
            "org": context["org"],
            "product": context["product"],
            "project": context["project"],
            "repo": context["repo"],
        }
        for token, context in PROJECT_TOKENS.items()
    },
    required_scopes=["memory:read"],
)

mcp = FastMCP(
    "mem0-shared",
    instructions=(
        "Long-term memory via self-hosted Mem0. "
        f"Default user_id is '{DEFAULT_USER_ID}'. "
        "For Multica Agentic work, prefer scoped tools: remember_context, "
        "search_context, get_project_brief, summarize_handoff. "
        "Store durable distilled facts only; never store raw chat history or long logs."
    ),
    auth=None if MCP_ALLOW_UNAUTHENTICATED else TOKEN_VERIFIER,
)


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if MEM0_API_KEY:
        h["X-API-Key"] = MEM0_API_KEY
    return h


def _uid(user_id: str | None) -> str:
    return (user_id or "").strip() or DEFAULT_USER_ID


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _auth_context() -> ProjectAuth:
    if MCP_ALLOW_UNAUTHENTICATED:
        return {
            "org": DEFAULT_ORG,
            "product": DEFAULT_PRODUCT,
            "project": DEFAULT_PROJECT,
            "repo": None,
        }
    token = get_access_token()
    if token is None:
        raise PermissionError("Missing authenticated MCP access token.")
    claims = token.claims or {}
    return {
        "org": str(claims.get("org") or DEFAULT_ORG),
        "product": str(claims.get("product") or DEFAULT_PRODUCT),
        "project": str(claims.get("project") or DEFAULT_PROJECT),
        "repo": claims.get("repo"),
    }


def _enforced_scope(
    org: str | None,
    product: str | None,
    project: str | None,
    repo: str | None = None,
) -> tuple[str, str, str, str | None]:
    context = _auth_context()
    allowed_org = str(context["org"] or DEFAULT_ORG)
    allowed_product = str(context["product"] or DEFAULT_PRODUCT)
    allowed_project = str(context["project"] or DEFAULT_PROJECT)
    allowed_repo = context.get("repo")

    for label, requested, allowed in (
        ("org", _clean(org), allowed_org),
        ("product", _clean(product), allowed_product),
        ("project", _clean(project), allowed_project),
    ):
        if requested and requested != allowed:
            raise PermissionError(f"Token is not allowed for {label}={requested}.")

    requested_repo = _clean(repo)
    if allowed_repo and requested_repo and requested_repo != allowed_repo:
        raise PermissionError(f"Token is not allowed for repo={requested_repo}.")
    return allowed_org, allowed_product, allowed_project, requested_repo or allowed_repo


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip()


def _source_hash(content: str) -> str:
    return hashlib.sha256(_normalize_content(content).lower().encode("utf-8")).hexdigest()


def _scoped_user_id(org: str | None, product: str | None, project: str | None) -> str:
    org_value = _clean(org) or DEFAULT_ORG
    product_value = _clean(product) or DEFAULT_PRODUCT
    project_value = _clean(project) or DEFAULT_PROJECT
    return f"{org_value}:{product_value}:{project_value}"


def _metadata(
    *,
    org: str | None,
    product: str | None,
    project: str | None,
    repo: str | None,
    task: str | None,
    scope: Scope,
    memory_type: MemoryType,
    importance: int,
    agent_id: str | None,
    source: Source,
    source_hash: str,
) -> dict[str, Any]:
    return {
        "org": _clean(org) or DEFAULT_ORG,
        "product": _clean(product) or DEFAULT_PRODUCT,
        "project": _clean(project) or DEFAULT_PROJECT,
        "repo": _clean(repo),
        "task": _clean(task),
        "scope": scope,
        "memory_type": memory_type,
        "importance": importance,
        "agent_id": _clean(agent_id),
        "source": source,
        "source_hash": source_hash,
    }


def _compact_item(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    mem = item.get("memory") or item.get("text") or item.get("content") or str(item)
    mid = item.get("id", "?")
    metadata = item.get("metadata") or {}
    tags = []
    for key in ("scope", "memory_type", "importance", "repo", "task", "agent_id"):
        value = metadata.get(key)
        if value is not None:
            tags.append(f"{key}={value}")
    suffix = f" ({', '.join(tags)})" if tags else ""
    return f"- [{mid}] {mem}{suffix}"


def _metadata_matches(item: Any, filters: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return True
    metadata = item.get("metadata") or {}
    if not metadata:
        return True
    for key, expected in filters.items():
        if expected is None:
            continue
        if metadata.get(key) != expected:
            return False
    return True


async def _post_memory(payload: dict[str, Any]) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{MEM0_API_URL}/memories", headers=_headers(), json=payload)
        r.raise_for_status()
        return r.text


async def _search_raw(query: str, user_id: str, top_k: int) -> list[Any]:
    payload: dict[str, Any] = {"query": query, "user_id": user_id, "top_k": top_k}
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{MEM0_API_URL}/search", headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()
    if isinstance(data, dict):
        results = data.get("results") or []
    elif isinstance(data, list):
        results = data
    else:
        results = []
    return results


async def _list_raw(user_id: str) -> list[Any]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(
            f"{MEM0_API_URL}/memories",
            headers=_headers(),
            params={"user_id": user_id},
        )
        r.raise_for_status()
        data = r.json()
    if isinstance(data, dict):
        return data.get("results") or []
    if isinstance(data, list):
        return data
    return []


@mcp.tool()
async def remember_context(
    content: str,
    org: str | None = None,
    product: str | None = None,
    project: str | None = None,
    repo: str | None = None,
    task: str | None = None,
    scope: Scope = "project",
    memory_type: MemoryType = "note",
    importance: int = 3,
    agent_id: str | None = None,
    source: Source = "agent",
) -> str:
    """Save durable scoped Multica Agentic context; rejects low-value or duplicate memory."""
    normalized = _normalize_content(content)
    if not normalized:
        return "Skipped: empty content."
    if len(normalized) > MAX_MEMORY_CHARS:
        return f"Skipped: content is {len(normalized)} chars; max is {MAX_MEMORY_CHARS}. Summarize first."
    if importance < MIN_IMPORTANCE_TO_SAVE:
        return f"Skipped: importance={importance}; minimum auto-save importance is {MIN_IMPORTANCE_TO_SAVE}."

    org, product, project, repo = _enforced_scope(org, product, project, repo)
    user_id = _scoped_user_id(org, product, project)
    content_hash = _source_hash(normalized)
    duplicate_probe = await _search_raw(content_hash, user_id, DEDUP_SEARCH_TOP_K)
    if any(content_hash in json.dumps(item, ensure_ascii=False) for item in duplicate_probe):
        return f"Skipped: duplicate source_hash={content_hash[:12]}."

    metadata = _metadata(
        org=org,
        product=product,
        project=project,
        repo=repo,
        task=task,
        scope=scope,
        memory_type=memory_type,
        importance=importance,
        agent_id=agent_id,
        source=source,
        source_hash=content_hash,
    )
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": normalized}],
        "user_id": user_id,
        "metadata": metadata,
    }
    if agent_id:
        payload["agent_id"] = agent_id
    await _post_memory(payload)
    return f"Saved scoped memory user_id={user_id} type={memory_type} scope={scope} hash={content_hash[:12]}."


@mcp.tool()
async def search_context(
    query: str,
    org: str | None = None,
    product: str | None = None,
    project: str | None = None,
    repo: str | None = None,
    task: str | None = None,
    scope: Scope | None = None,
    memory_type: MemoryType | None = None,
    top_k: int = 8,
    widen: bool = True,
) -> str:
    """Search scoped Multica Agentic memory, starting narrow and widening only when needed."""
    normalized_query = _normalize_content(query)
    if not normalized_query:
        return "No query provided."

    org, product, project, repo = _enforced_scope(org, product, project, repo)
    user_ids = [_scoped_user_id(org, product, project)]
    if widen:
        for candidate in (
            _scoped_user_id(org, product, "global"),
            _scoped_user_id(org, "global", "global"),
        ):
            if candidate not in user_ids:
                user_ids.append(candidate)

    filters = {
        "repo": _clean(repo),
        "task": _clean(task),
        "scope": scope,
        "memory_type": memory_type,
    }
    output: list[str] = []
    seen: set[str] = set()

    for user_id in user_ids:
        results = await _search_raw(normalized_query, user_id, top_k)
        filtered = [item for item in results if _metadata_matches(item, filters)]
        for item in filtered:
            line = _compact_item(item)
            if line not in seen:
                seen.add(line)
                output.append(f"{user_id} {line}")
        if output and not widen:
            break

    if not output:
        return "No scoped context found."
    return "Scoped context:\n" + "\n".join(output[:top_k])


@mcp.tool()
async def get_project_brief(
    org: str | None = None,
    product: str | None = None,
    project: str | None = None,
    repo: str | None = None,
    task: str | None = None,
    top_k: int = 12,
) -> str:
    """Get high-signal project context for agent onboarding."""
    queries = [
        "requirements constraints decisions architecture active issues deployment env conventions handoff",
        "important project brief context",
    ]
    lines: list[str] = []
    seen: set[str] = set()
    for query in queries:
        result = await search_context(
            query=query,
            org=org,
            product=product,
            project=project,
            repo=repo,
            task=task,
            top_k=top_k,
            widen=True,
        )
        if result.startswith("Scoped context:\n"):
            for line in result.splitlines()[1:]:
                if line not in seen:
                    seen.add(line)
                    lines.append(line)
    if not lines:
        return "No project brief memories found."
    return "Project brief:\n" + "\n".join(lines[:top_k])


@mcp.tool()
async def summarize_handoff(
    done: str,
    decisions: str = "",
    blockers: str = "",
    next_steps: str = "",
    org: str | None = None,
    product: str | None = None,
    project: str | None = None,
    repo: str | None = None,
    task: str | None = None,
    scope: Scope = "task",
    importance: int = 4,
    agent_id: str | None = None,
) -> str:
    """Save a compact handoff memory for the next AI agent."""
    sections = [
        f"Done: {_normalize_content(done)}",
        f"Decisions: {_normalize_content(decisions)}" if decisions.strip() else "",
        f"Blockers: {_normalize_content(blockers)}" if blockers.strip() else "",
        f"Next steps: {_normalize_content(next_steps)}" if next_steps.strip() else "",
    ]
    content = "\n".join(section for section in sections if section)
    return await remember_context(
        content=content,
        org=org,
        product=product,
        project=project,
        repo=repo,
        task=task,
        scope=scope,
        memory_type="handoff",
        importance=importance,
        agent_id=agent_id,
        source="agent",
    )


@mcp.tool()
async def add_memory(
    content: str,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> str:
    """Save text to shared Mem0 memory."""
    org, product, project, _repo = _enforced_scope(None, None, None)
    enforced_user_id = _scoped_user_id(org, product, project)
    if user_id and user_id != enforced_user_id:
        raise PermissionError(f"Token is not allowed for user_id={user_id}.")
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": content}],
        "user_id": enforced_user_id,
    }
    if agent_id:
        payload["agent_id"] = agent_id
    return await _post_memory(payload)


@mcp.tool()
async def search_memories(
    query: str,
    user_id: str | None = None,
    top_k: int = 10,
) -> str:
    """Semantic search over Mem0 memories."""
    org, product, project, _repo = _enforced_scope(None, None, None)
    enforced_user_id = _scoped_user_id(org, product, project)
    if user_id and user_id != enforced_user_id:
        raise PermissionError(f"Token is not allowed for user_id={user_id}.")
    results = await _search_raw(query, enforced_user_id, top_k)
    if not results:
        return "No memories found."
    return "Memories:\n" + "\n".join(_compact_item(item) for item in results)


@mcp.tool()
async def list_memories(user_id: str | None = None) -> str:
    """List memories for a user_id."""
    org, product, project, _repo = _enforced_scope(None, None, None)
    uid = _scoped_user_id(org, product, project)
    if user_id and user_id != uid:
        raise PermissionError(f"Token is not allowed for user_id={user_id}.")
    results = await _list_raw(uid)
    if not results:
        return f"No memories for user_id={uid}."
    return f"user_id={uid}\n" + "\n".join(_compact_item(item) for item in results)


@mcp.tool()
async def delete_memory(memory_id: str) -> str:
    """Delete one memory by ID."""
    _auth_context()
    if not MCP_ALLOW_CROSS_SCOPE_DELETE:
        return "Delete disabled: set MCP_ALLOW_CROSS_SCOPE_DELETE=true only for trusted admin deployments."
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.delete(f"{MEM0_API_URL}/memories/{memory_id}", headers=_headers())
        r.raise_for_status()
        return f"Deleted {memory_id}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
