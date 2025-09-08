# aimodel/file_read/core/request_ctx.py
from contextvars import ContextVar

x_id_ctx: ContextVar[str] = ContextVar("x_id_ctx", default="")
id_token_ctx: ContextVar[str] = ContextVar("id_token_ctx", default="")
user_email_ctx: ContextVar[str] = ContextVar("user_email_ctx", default="")

def get_x_id() -> str: return x_id_ctx.get()
def set_x_id(val: str): x_id_ctx.set((val or "").strip())

def get_id_token() -> str: return id_token_ctx.get()
def set_id_token(val: str): id_token_ctx.set((val or "").strip())

def get_user_email() -> str: return user_email_ctx.get()
def set_user_email(val: str): user_email_ctx.set((val or "").strip())
