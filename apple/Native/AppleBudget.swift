import Foundation

/// Helpers for Apple's small on-device model. Nothing here imports FoundationModels,
/// so the logic can be tested on any build machine.
enum AppleBudget {
    static let toolPrefix = "Tool result (data):\n"

    private static func isArabic(_ s: Unicode.Scalar) -> Bool {
        switch s.value {
        case 0x0600...0x06FF, 0x0750...0x077F, 0x08A0...0x08FF, 0xFB50...0xFDFF, 0xFE70...0xFEFF: return true
        default: return false
        }
    }

    /// True when at least a fifth of the letters are Arabic. Code with a few Arabic strings stays false.
    static func isMostlyArabic(_ text: String) -> Bool {
        var letters = 0, arabic = 0
        for s in text.unicodeScalars where CharacterSet.letters.contains(s) {
            letters += 1
            if isArabic(s) { arabic += 1 }
        }
        return letters > 0 && arabic * 5 >= letters
    }

    private static func weight(_ s: Unicode.Scalar) -> Int { s.value < 0x80 ? 1 : 3 }

    /// Conservative token estimate: about three ASCII characters per token, one token per other character.
    static func tokens(_ text: String) -> Int {
        text.unicodeScalars.reduce(0) { $0 + weight($1) } / 3 + 1
    }

    static func clip(_ text: String, tokens limit: Int) -> String {
        guard limit > 0 else { return "" }
        guard tokens(text) > limit else { return text }
        var used = 0
        var end = text.startIndex
        for index in text.indices {
            let cost = text[index].unicodeScalars.reduce(0) { $0 + weight($1) }
            if (used + cost) / 3 >= limit - 4 { break }
            used += cost
            end = text.index(after: index)
        }
        return String(text[..<end]) + "\n[…truncated. Do not edit a file you only saw truncated.]"
    }

    struct Plan {
        var turns: [Turn]
        var dropped: [Turn]
    }

    /// Keeps the current request and as many recent steps as fit in `budget` tokens.
    /// Older conversation turns that do not fit are returned in `dropped` so they can be summarized.
    static func compact(_ turns: [Turn], budget: Int) -> Plan {
        guard let task = turns.lastIndex(where: { $0.role == "user" && !$0.content.hasPrefix(toolPrefix) }) else {
            var remaining = budget
            var kept: [Turn] = []
            for turn in turns.reversed() {
                let text = clip(turn.content, tokens: remaining)
                guard !text.isEmpty else { break }
                kept.insert(Turn(role: turn.role, content: text), at: 0)
                remaining -= tokens(text)
            }
            return Plan(turns: kept, dropped: [])
        }
        var remaining = budget
        let request = Turn(role: "user", content: clip(turns[task].content, tokens: max(100, budget / 3)))
        remaining -= tokens(request.content)
        var steps: [Turn] = []
        for turn in turns[(task + 1)...].reversed() {
            let cost = tokens(turn.content)
            if cost <= remaining {
                steps.insert(turn, at: 0); remaining -= cost
            } else if steps.isEmpty && remaining > 150 {
                let text = clip(turn.content, tokens: remaining - 20)
                steps.insert(Turn(role: turn.role, content: text), at: 0); remaining -= tokens(text)
            } else { break }
        }
        var history: [Turn] = []
        var dropped: [Turn] = []
        let earlier = Array(turns[..<task])
        for index in earlier.indices.reversed() {
            let cost = tokens(earlier[index].content)
            if cost <= remaining { history.insert(earlier[index], at: 0); remaining -= cost }
            else { dropped = Array(earlier[...index]); break }
        }
        return Plan(turns: history + [request] + steps, dropped: dropped)
    }

    static func transcript(_ turns: [Turn]) -> String {
        turns.map { turn -> String in
            if turn.content.hasPrefix(toolPrefix) { return "Tool result:\n" + String(turn.content.dropFirst(toolPrefix.count)) }
            return (turn.role == "assistant" ? "Assistant: " : "User: ") + turn.content
        }.joined(separator: "\n\n")
    }

    /// Splits text into runs so fenced code blocks stay untranslated.
    static func segments(_ text: String) -> [(code: Bool, text: String)] {
        let parts = text.components(separatedBy: "```")
        var result: [(code: Bool, text: String)] = []
        for (index, part) in parts.enumerated() {
            if index % 2 == 1 {
                let closed = index < parts.count - 1
                result.append((code: true, text: "```" + part + (closed ? "```" : "")))
            } else if !part.isEmpty {
                result.append((code: false, text: part))
            }
        }
        return result
    }

    static func isContextOverflow(_ description: String) -> Bool {
        ["exceededContextWindowSize", "contextSizeExceeded", "Context length", "context window"].contains { description.contains($0) }
    }

    /// Arabic explanation for a Foundation Models error, matched by case name so it works across SDK versions.
    static func message(for description: String) -> String? {
        func has(_ names: String...) -> Bool { names.contains { description.contains($0) } }
        if isContextOverflow(description) {
            return "الطلب أكبر من سياق نموذج Apple. اختر ملفا أصغر، أو استخدم «سؤال سريع»، أو اختر بوابة أخرى."
        }
        if has("unsupportedLanguageOrLocale", "unsupportedLanguage") {
            return "نموذج Apple لا يدعم لغة هذا النص. فعّل «ترجمة العربية تلقائيا» من الإعدادات أو اكتب بالإنجليزية."
        }
        if has("guardrailViolation") { return "أوقفت حماية Apple هذا الطلب أو جوابه. أعد صياغة الطلب." }
        if has("refusal") { return "رفض نموذج Apple الإجابة عن هذا الطلب." }
        if has("rateLimited") {
            return "قيّد النظام نموذج Apple مؤقتا، غالبا لأن التطبيق في الخلفية. أبق Allinone في المقدمة وأعد المحاولة."
        }
        if has("concurrentRequests") { return "نموذج Apple يعالج طلبا آخر. انتظر حتى ينتهي ثم أعد المحاولة." }
        if has("assetsUnavailable") {
            return "ملفات نموذج Apple غير جاهزة بعد. اترك الجهاز متصلا بالإنترنت والشاحن وأعد المحاولة لاحقا."
        }
        if has("decodingFailure", "unsupportedGuide", "unsupportedGenerationGuide") {
            return "لم يرجع نموذج Apple جوابا منظما. أعد المحاولة أو بسّط الطلب."
        }
        return nil
    }
}

enum TextWindow {
    /// The whole text when it fits in `maxChars`, otherwise a slice that starts near `line` (1-based).
    static func slice(_ text: String, line: Int, maxChars: Int) -> (text: String, complete: Bool) {
        if text.count <= maxChars { return (text, true) }
        let lines = text.components(separatedBy: "\n")
        let start = max(0, min(lines.count - 1, line - 1))
        var out: [String] = []
        var size = 0
        var next = start
        while next < lines.count, size + lines[next].count + 1 <= maxChars {
            out.append(lines[next]); size += lines[next].count + 1; next += 1
        }
        if out.isEmpty { out = [String(lines[start].prefix(maxChars))]; next = start + 1 }
        let more = next < lines.count ? " Read with line=\(next + 1) to continue, or use search." : ""
        let header = "Partial view: lines \(start + 1)-\(start + out.count) of \(lines.count).\(more) A file must fit whole before it can be edited."
        return (header + "\n" + out.joined(separator: "\n"), false)
    }
}
