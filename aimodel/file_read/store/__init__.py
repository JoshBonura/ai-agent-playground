from .chats import (
    ChatMessageRow,
    upsert_on_first_message, update_last, append_message,
    delete_message, delete_messages_batch, list_messages,
    list_paged, delete_batch,
    merge_chat, merge_chat_new, edit_message, set_summary, get_summary,  # ← add these
)
from .index import ChatMeta
from .pending import (
    enqueue_pending, apply_pending_for, process_all_pending, list_pending_sessions,
)

__all__ = [
    # chats
    "ChatMessageRow",
    "upsert_on_first_message", "update_last", "append_message",
    "delete_message", "delete_messages_batch", "list_messages",
    "list_paged", "delete_batch",
    "merge_chat", "merge_chat_new", "edit_message",  # ← add these
    # index
    "ChatMeta",
    # pending
    "enqueue_pending", "apply_pending_for", "process_all_pending", "list_pending_sessions", "set_summary", "get_summary"
]
