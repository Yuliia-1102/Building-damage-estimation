"""Operator web system (stage 3).

A thin web layer over the evaluation code: it stores applications in SQLite, a separate worker process
(`python -m web.worker`) calls `core.service.get_engine().process(...)` in the background, and FastAPI +
Jinja2/HTMX render the Kanban board, the application page, projects and statistics. The evaluation code in
`core/`, `models/` and `pricedb/` is used, never changed (docs/web_system.md).
"""
