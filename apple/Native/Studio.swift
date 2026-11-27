import Foundation
import SwiftUI

struct SavedTask: Identifiable, Codable {
    var id = UUID()
    var prompt: String
    var done = false
}
struct Notebook: Codable {
    var threads: [String:[Turn]] = [:]
    var checkpoint: Checkpoint?
    var events: [RunEvent]?
    var uiTitles: [String:String]?
    var activeChat: String?
    var notes = ""
    var tasks: [SavedTask] = []
}
@MainActor final class Studio: ObservableObject {
    @Published var providers: [Provider]
    @Published var mode: RouteMode { didSet { UserDefaults.standard.set(mode.rawValue,forKey:"routing.mode") } }
    @Published private(set) var files: ProjectFiles
    @Published private(set) var book = Notebook()
    @Published private(set) var pending: EditProposal?
    @Published private(set) var busy = false
    @Published var activity = ""
    @Published var message = ""
    @Published var partial = ""
    @Published var failover = (UserDefaults.standard.object(forKey:"routing.failover") as? Bool ?? true) {
        didSet { UserDefaults.standard.set(failover,forKey:"routing.failover") }
    }
    @Published var served = ""
    private let router = NativeRouter()
    private(set) var notebookID = "builtin"
    private var scopedURL: URL?
    private var pendingThread: String?
    private var pendingTask: UUID?
    private let storage: URL
    var hostThread: String { book.activeChat ?? "host" }
    var activeRequest: Task<AgentReply,Error>?
    func stopRequest() { activeRequest?.cancel() }
    func track(_ detail: String) {
        var events = book.events ?? []
        events.append(RunEvent(when: Date(), detail: detail))
        book.events = Array(events.suffix(300))
        save()
    }
    func changeOriginalChat(_ key:String,title:String?) throws {
        guard !busy, pending == nil,book.threads[key] != nil else { throw LinkError.message("تعذر تغيير المحادثة الآن") }
        var names=book.uiTitles ?? [:]
        names[key]=title
        if title == nil { book.threads.removeValue(forKey:key) }
        book.uiTitles=names
        save()
    }
    func selectChat(_ id: String) {
        guard !busy, pending == nil else { return }
        book.activeChat = id
        served = ""
        save()
    }
    func clearCheckpoint() { book.checkpoint = nil; save() }
    func importReply(_ raw: String) throws {
        guard !busy, pending == nil else { throw LinkError.message("أكمل الطلب الحالي أولا") }
        let change = try ManualExchange.proposal(raw, files:files)
        if let change { pending = change; pendingThread = hostThread }
        append("assistant", change?.reason ?? raw, hostThread)
        track("استيراد جواب يدوي")
    }
    private var undoChange: EditProposal?
    func undo() throws {
        guard !busy, pending == nil, let change = undoChange, change.root == files.root else { throw LinkError.message("لا يوجد تعديل قابل للتراجع في هذه الجلسة") }
        try files.undo(change)
        undoChange = nil
        track("تراجع عن " + change.path)
    }

    init() {
        let defaults = UserDefaults.standard
        mode = RouteMode(rawValue:defaults.string(forKey:"routing.mode") ?? "") ?? .priority
        providers = defaults.data(forKey:"routing.providers").flatMap { try? JSONDecoder().decode([Provider].self,from:$0) } ?? [.apple]
        let manager = FileManager.default
        storage = manager.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("AllinoneStudio")
        let builtin = manager.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("Workspace")
        files = ProjectFiles(root:builtin)
        do {
            try manager.createDirectory(at:builtin,withIntermediateDirectories:true)
            try manager.createDirectory(at:storage,withIntermediateDirectories:true)
            if let data = defaults.data(forKey:"project.bookmark"), let id = defaults.string(forKey:"project.identifier") {
                var stale = false
                let url = try? URL(resolvingBookmarkData:data,options:[],relativeTo:nil,bookmarkDataIsStale:&stale)
                if let url, Self.isInsideDocuments(url) || url.startAccessingSecurityScopedResource() {
                    scopedURL = Self.isInsideDocuments(url) ? nil : url
                    files = ProjectFiles(root:url); notebookID = id
                    if stale, let fresh = try? url.bookmarkData(options:.minimalBookmark,includingResourceValuesForKeys:nil,relativeTo:nil) {
                        defaults.set(fresh,forKey:"project.bookmark")
                    }
                } else {
                    // Tell the user instead of silently switching back to the built-in folder.
                    defaults.removeObject(forKey:"project.bookmark")
                    defaults.removeObject(forKey:"project.identifier")
                    let name = url?.lastPathComponent ?? "المحفوظ"
                    message = "تعذر فتح مجلد المشروع «" + name + "». تم الرجوع إلى Workspace. اختر المجلد من جديد من زر المشروع."
                }
            }
            try load()
        } catch { message = error.localizedDescription }
    }
    deinit { scopedURL?.stopAccessingSecurityScopedResource() }

    private static func isInsideDocuments(_ url: URL) -> Bool {
        let documents = FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0]
            .resolvingSymlinksInPath().standardizedFileURL.path
        let path = url.resolvingSymlinksInPath().standardizedFileURL.path
        return path == documents || path.hasPrefix(documents + "/")
    }

    func open(_ url: URL) throws {
        guard !busy, pending == nil else { throw LinkError.message("أكمل الجلسة ومراجعة التعديل قبل تغيير المشروع") }
        if url.standardizedFileURL == files.root.standardizedFileURL { return }
        let local = Self.isInsideDocuments(url)
        let access = !local && url.startAccessingSecurityScopedResource()
        guard local || access else { throw LinkError.message("تعذر الوصول إلى المجلد المختار") }
        do {
            let properties = try url.resourceValues(forKeys:[.isDirectoryKey,.isWritableKey])
            guard properties.isDirectory == true, properties.isWritable != false else { throw LinkError.message("اختر مجلدا يسمح بحفظ الملفات") }
            let data = try url.bookmarkData(options:.minimalBookmark,includingResourceValuesForKeys:nil,relativeTo:nil)
            let next = ProjectFiles(root:url); _ = try next.list("")
            var ids = UserDefaults.standard.dictionary(forKey:"project.ids") as? [String:String] ?? [:]
            let builtin = FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("Workspace")
            let id = url.resolvingSymlinksInPath().standardizedFileURL.path == builtin.resolvingSymlinksInPath().standardizedFileURL.path ? "builtin" : ids[url.standardizedFileURL.path] ?? UUID().uuidString
            let nextBook = try notebook(id)
            ids[url.standardizedFileURL.path] = id
            UserDefaults.standard.set(ids,forKey:"project.ids")
            UserDefaults.standard.set(data,forKey:"project.bookmark")
            UserDefaults.standard.set(id,forKey:"project.identifier")
            scopedURL?.stopAccessingSecurityScopedResource()
            undoChange = nil; scopedURL = access ? url : nil; notebookID = id; files = next; book = nextBook; served = ""; message = ""
        } catch { if access { url.stopAccessingSecurityScopedResource() }; throw error }
    }
    private func notebook(_ id: String) throws -> Notebook {
        let url = storage.appendingPathComponent(id + ".json")
        guard FileManager.default.fileExists(atPath:url.path) else { return Notebook() }
        return try JSONDecoder().decode(Notebook.self,from:Data(contentsOf:url))
    }
    private func load() throws { book = try notebook(notebookID) }
    private func save() {
        do { try JSONEncoder().encode(book).write(to:storage.appendingPathComponent(notebookID + ".json"),options:.atomic) }
        catch { message = "تعذر حفظ الجلسة: " + error.localizedDescription }
    }
    func saveProviders() throws {
        UserDefaults.standard.set(try JSONEncoder().encode(providers),forKey:"routing.providers")
    }
    func addProvider(_ p: Provider) throws {
        guard !providers.contains(where: { $0.id == p.id }) else { return }
        providers.append(p)
        try saveProviders()
    }
    func storeProvider(_ p: Provider, key: String) throws {
        if p.style != .onDevice { _ = try NativeAPI.endpoint(p) }
        guard !p.name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else { throw LinkError.message("أدخل اسم المزود") }
        try Credentials.save(key,p.id)
        if let index = providers.firstIndex(where: { $0.id == p.id }) { providers[index] = p }
        else { providers.insert(p,at:0) }
        try saveProviders()
    }

    func setNotes(_ notes: String) { book.notes = String(notes.prefix(8000)); save() }
    func addTask(_ prompt: String) { if !prompt.isEmpty { book.tasks.append(SavedTask(prompt:prompt)); save() } }
    func newChat() { guard !busy, pending == nil else { return }; selectChat(UUID().uuidString) }
    private func append(_ role: String,_ text: String,_ thread: String) {
        book.threads[thread,default:[]].append(Turn(role:role,content:text))
        if let turns = book.threads[thread], turns.count > 100 { book.threads[thread] = Array(turns.suffix(100)) }
        save()
    }
    func send(_ input: String, thread requestedThread: String? = nil, task: UUID? = nil, assistantMode: AssistantMode = .standard, preferred: Provider? = nil, allowFallback: Bool? = nil) async throws -> String {
        let prompt = input.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !prompt.isEmpty, prompt.utf8.count <= 60000 else { throw LinkError.message("تحقق من طول الطلب") }
        guard !busy else { throw LinkError.message("المضيف مشغول. حاول بعد قليل.") }
        guard pending == nil else { throw LinkError.message("يوجد تعديل بانتظار المراجعة على المضيف") }
        let thread = requestedThread ?? hostThread
        let history = book.threads[thread] ?? []
        busy = true; message = ""; activity = "بانتظار النموذج…"
        defer { busy = false; activity = ""; partial = "" }
        let config = preferred.map { first in [first] + providers.filter { $0.id != first.id && $0.base != first.base } } ?? providers
        let selected:RouteMode = preferred == nil ? mode : .priority
        let switchOnFailure = allowFallback ?? failover
        book.checkpoint = Checkpoint(prompt:prompt,thread:thread,task:task,mode:assistantMode)
        track("بدء الطلب")
        let operation = Task { try await CodingAgent.run(prompt:prompt,history:history,notes:self.book.notes,files:self.files,mode:assistantMode,ask: { system,turns in
            try await self.router.respond(providers:config,mode:selected,system:system,turns:turns,failover:switchOnFailure) { provider,instructions,messages in
                if assistantMode == .quick && provider.style != .onDevice {
                    return try await NativeAPI.stream(provider,system:instructions,turns:messages) { draft in
                        if thread == self.hostThread { self.partial = draft }
                    }
                }
                return try await NativeAPI.reply(provider,system:instructions,turns:messages)
            }
        },activity: { self.activity = $0; self.track($0) }) }
        activeRequest = operation
        defer { activeRequest = nil }
        let response: AgentReply
        do { response = try await operation.value }
        catch { track("توقف الطلب: " + error.localizedDescription); throw error }
        track("وصول جواب من " + response.servedBy)
        append("user", prompt, thread)
        served = response.servedBy
        var text = response.answer
        if let proposal = response.proposal {
            pending = proposal; pendingThread = thread; pendingTask = task
            text += "\nبانتظار موافقة المضيف على " + proposal.path
        } else if let task { markDone(task) }
        if response.proposal == nil { clearCheckpoint() }
        append("assistant",text,thread)
        return text
    }
    private func markDone(_ id: UUID) {
        if let i = book.tasks.firstIndex(where: { $0.id == id }) { book.tasks[i].done = true; save() }
    }
    func review(apply: Bool) throws {
        guard let pending else { return }
        if apply {
            do {
                try files.verifyProposal(pending)
                try files.apply(pending)
                undoChange = pending
                guard try files.read(pending.path) == Data(pending.replacement.utf8) else { throw LinkError.message("اختلف المحتوى المحفوظ عن المعاينة") }
                track("تطابق النص المحفوظ مع المقترح: " + pending.path)
                if let task = pendingTask { markDone(task) }
            } catch { track("تعذر التحقق أو الحفظ: " + error.localizedDescription); throw error }
        }
        append("assistant",(apply ? "تم حفظ التعديل في " : "تم رفض التعديل على ") + pending.path,pendingThread ?? hostThread)
        clearCheckpoint(); track(apply ? "موافقة وحفظ" : "رفض التعديل")
        self.pending = nil; pendingThread = nil; pendingTask = nil
    }
}
