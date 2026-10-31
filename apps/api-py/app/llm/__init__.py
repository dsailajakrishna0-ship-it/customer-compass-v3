"""Model access. Importing this package loads app.config first, which sets the LiteLLM defaults
it must see before litellm is imported."""

import warnings

import app.config  # noqa: F401

# litellm's own type definitions make Pydantic print this harmless warning once; keep it out of the logs
warnings.filterwarnings("ignore", message=".*ReadOnly.*qualifier", category=UserWarning)
