# PadLocal
Standalone iPad text chat using a pinned PrismML llama.cpp fork and Apple Metal. The IPA contains the engine and no weights. The catalog downloads one verified GGUF at a time from Hugging Face to Application Support. The only network requests are for model metadata and downloads. Chats are in memory. Deleting the app removes its downloaded files.

Qwen is the smallest option. Available process RAM is sampled live; model files, context and Metal allocations require separate memory. Larger models may exceed the app's memory allowance. The catalog is text-only. Every generation reloads one model and releases it afterwards. The context is 1,536 tokens with up to 256 generated tokens; older complete turns are dropped when needed.

The default engine runs without CPU JIT. An experimental, opt-in arm64 CPU JIT specializes two float multipliers for repetition penalties. It does not compile the model. It checks debugger attachment, requests writable then executable memory from iPadOS, and reports denied permissions. No special entitlement or debugger enabler is shipped, and a side-loaded signature alone does not enable this feature.

On macOS with Xcode, CMake and XcodeGen, run bash build-engine.sh, xcodegen generate, then open PadLocal.xcodeproj. Select your development team for device installation. The branch workflow builds an unsigned device IPA. Model licenses and cards are provided by the respective maintainers on Hugging Face.

The Xcode target requests Apple's increased-memory-limit capability. Whether a signed installation receives additional RAM depends on its profile, OS and hardware. The AOT/Metal path works without debugger attachment.
