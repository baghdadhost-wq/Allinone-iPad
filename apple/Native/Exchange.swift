import Foundation

struct RunEvent: Codable {
    let when: Date
    let detail: String
}
struct Checkpoint: Codable {
    let prompt: String
    let thread: String
    let task: UUID?
    var mode: AssistantMode? = nil
}
enum ManualExchange {
    struct Patch: Decodable { let action: String; let path: String; let text: String; let reason: String? }
    static func proposal(_ raw: String, files: ProjectFiles) throws -> EditProposal? {
        let trimmed = raw.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.utf8.count < 128000 else { throw LinkError.message("تحقق من حجم الجواب") }
        guard trimmed.hasPrefix("{") else { return nil }
        let patch = try JSONDecoder().decode(Patch.self,from:Data(trimmed.utf8))
        guard patch.action == "edit" else { throw LinkError.message("يتطلب التعديل إجراء edit") }
        let file = try files.url(patch.path)
        var prior = [String:Data]()
        if FileManager.default.fileExists(atPath:file.path) { prior[patch.path] = try files.read(patch.path) }
        return try files.propose(path:patch.path,replacement:patch.text,reason:patch.reason ?? patch.path,previouslyRead:prior)
    }
    static func handover(prompt: String, selected: String, studioNotes: String, turns: [Turn], files: ProjectFiles) throws -> String {
        var result = "Goal:\n" + prompt + "\nProject instructions:\n" + studioNotes + "\nProject listing:\n" + (try files.list(""))
        for turn in turns.suffix(8) { result += "\n" + turn.role + ": " + String(turn.content.prefix(1500)) }
        if !selected.isEmpty { result += "\nFile " + selected + "\n" + String(String(decoding:try files.read(selected),as:UTF8.self).prefix(24000)) }
        return result + "\nReturn plain text or one JSON object containing action=edit, path, reason, and text (full new file)."
    }
}
extension ProjectFiles {
    func verifyProposal(_ change: EditProposal) throws {
        let data = Data(change.replacement.utf8)
        switch (change.path as NSString).pathExtension.lowercased() {
        case "json":
            _ = try JSONSerialization.jsonObject(with:data,options:.fragmentsAllowed)
        case "plist":
            _ = try PropertyListSerialization.propertyList(from:data,options:[],format:nil)
        default: break
        }
    }
    func undo(_ change: EditProposal) throws {
        let written = Data(change.replacement.utf8)
        guard root == change.root, try read(change.path) == written else { throw LinkError.message("تغير الملف بعد الحفظ") }
        if let original = change.original {
            try apply(EditProposal(path:change.path,original:written,replacement:String(decoding:original,as:UTF8.self),reason:"Undo",root:root))
        } else {
            let dest = try url(change.path)
            var outer: NSError?
            var inner: Error?
            NSFileCoordinator().coordinate(writingItemAt:dest,options:.forDeleting,error:&outer) { at in
                do {
                    guard try read(change.path) == written else { throw LinkError.message("تغير الملف بعد الحفظ") }
                    try FileManager.default.removeItem(at:at)
                } catch { inner = error }
            }
            if let inner { throw inner }
            if let outer { throw outer }
        }
    }
}
