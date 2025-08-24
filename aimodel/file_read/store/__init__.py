from .chats import (
    ChatMessageRow,
    upsert_on_first_message, update_last, append_message,
    delete_message, delete_messages_batch, list_messages,
    list_paged, delete_batch,
    merge_chat, merge_chat_new, edit_message, set_summary, get_summary,  # ← add these
)
from .index import ChatMeta

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
    "set_summary", "get_summary"
]
