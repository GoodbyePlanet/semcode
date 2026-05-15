from server.embeddings.factory import close_embedding_provider, get_embedding_provider
from . import jina as _jina  # noqa: F401
from . import jina_api as _jina_api  # noqa: F401
from . import voyage as _voyage  # noqa: F401
from . import openai as _openai  # noqa: F401
from . import ollama as _ollama  # noqa: F401

__all__ = ["get_embedding_provider", "close_embedding_provider"]
