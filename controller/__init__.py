"""Allinone — a Python controller that runs Claude Code through a gateway of your choice.

Layers (matching the project diagram):

    Python Controller (this package)
        -> Claude Code            (installed locally, configured per session)
            -> API gateway        (OmniRoute or FreeLLMAPI, chosen at launch)
                -> model providers (DeepSeek, Gemini, Qwen, ... configured in the gateway)
"""

__version__ = "1.0.0"
