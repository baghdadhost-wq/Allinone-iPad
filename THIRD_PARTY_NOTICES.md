# Third-party software

Allinone does not include the source code of the programs below. Its installer
downloads them from their official sources into `runtime/` on your computer.

## OmniRoute
- Source: https://github.com/diegosouzapw/OmniRoute (npm package `omniroute`)
- License: MIT — Copyright (c) 2026 Cheaper Inference - Created by Diego Souza
- Modifications you make are stored as patches in `customizations/omniroute/` and remain under the MIT license terms of the original.

## FreeLLMAPI
- Source: https://github.com/tashfeenahmed/freellmapi
- License: MIT — Copyright (c) 2026 Tashfeen Ahmed
- The FreeLLMAPI README states it is intended for personal experimentation and learning, and that each upstream provider's terms still apply to traffic proxied through it.

## Claude Code
- Source: npm package `@anthropic-ai/claude-code` (https://code.claude.com/docs)
- © Anthropic PBC. Proprietary software; use is subject to Anthropic's terms. Allinone only installs the official package and configures it with documented settings (LLM gateway variables, `--settings`, `--mcp-config`, `--plugin-dir`).

## Node.js
- Source: https://nodejs.org/dist (official builds, verified against SHASUMS256.txt)
- License: MIT and bundled third-party licenses — see `runtime/node/LICENSE` after installation.

## Model providers
Providers you connect inside the gateways (Gemini, Groq, OpenRouter, DeepSeek, Qwen, …) are governed by the terms you accepted with each of them.
