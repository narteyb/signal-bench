# Task Definitions

Add a Post 1-style task by creating `src/signal_bench/tasks/<name>.py` with a
factory decorated by `@register_task`, adding the module import to
`tasks/__init__.py`, and adding a matching task entry to
`models/reference/manifest.yaml`.
