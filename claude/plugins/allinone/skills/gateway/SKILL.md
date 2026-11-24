---
name: gateway
description: Show which Allinone gateway (OmniRoute or FreeLLMAPI) and model this session uses, and list available models.
argument-hint: [filter]
disable-model-invocation: true
---

1. Call `gateway_info` (MCP server `allinone`) and report the gateway, URL and model.
2. Call `gateway_models` with filter "$ARGUMENTS" and show the list (group similar ids, at most 40 lines).
3. Remind the user they can switch the model inside Claude Code with `/model <id>`, or choose the other gateway by restarting with `allinone`.
