# planner/tools/__init__.py
# Agents import everything from here. Never import tool modules directly.

from .exceptions import (
    OverwriteProtectionError,
    ReadOnlyFileError,
    LLMCallError,
    LLMConfigError,
    LLMParseError,
    InvalidStatusError,
    SearchUnavailableError,
)

from .file_tools import (
    read_file,
    write_file,
    append_file,
    scaffold_planner,
    list_planner_files,
    file_exists,
    clear_file,
    read_section,
)

from .llm_tools import (
    get_llm_client,
    get_llm,
    llm_call,
    llm_call_with_retry,
    llm_call_json,
    stream_llm_call,
    PROVIDER_REGISTRY,
    get_active_provider,
    get_active_model,
    set_active_provider,
    set_active_model,
    set_api_key,
    get_api_key_status,
    list_providers,
)

from .tracker_tools import (
    read_tracker,
    update_file_status,
    add_blocker,
    resolve_blocker,
    append_change_log,
    get_next_pending_file,
    get_status_summary,
    initialize_tracker,
)

from .ascii_tools import (
    build_graph_from_description,
    render_ascii_diagram,
    generate_diagram_from_files,
    render_ascii_fallback,
    write_ascii_diagram,
    diagram_to_rich_text,
)

from .mermaid_tools import (
    generate_mermaid,
    render_mermaid_to_text,
    write_diagram,
    validate_mermaid,
)

from .editor_tools import (
    open_in_editor,
    detect_editor,
)

from .diff_tools import (
    semantic_diff,
    raw_diff,
)

from .search_tools import (
    web_search,
    search_enabled,
)

from .validation_tools import (
    validate_file_structure,
    check_frontend_signals,
    check_consistency,
    file_is_complete,
)
