"""Local, single-user editor for the LLM Wiki (stdlib only)."""

from .core import (  # noqa: F401
    ALLOWED_TYPES,
    AlreadyExistsError,
    ConcurrencyError,
    EditorError,
    PageNotFoundError,
    PathEscapeError,
    build_skeleton,
    create_page,
    list_pages,
    read_page,
    save_page,
)
