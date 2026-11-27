import SwiftUI
import WebKit

@MainActor final class MobileGateways: ObservableObject {
    static let shared = MobileGateways()
    private let dir = FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("MobileGateways")
    @Published private(set) var desired = [String:Bool]()
    @Published private(set) var state = [String:String]()
    @Published var problem = ""
    private var timer: Timer?
    private init() {
        // Restore the last choice so gateways that were on keep running after a relaunch.
        if let data = try? Data(contentsOf:dir.appendingPathComponent("desired.json")),
           let saved = try? JSONDecoder().decode([String:Bool].self,from:data) {
            desired = saved
            if saved.values.contains(true) {
                do { try startSupervisor() } catch { problem = error.localizedDescription }
            }
        }
    }
    private func startSupervisor() throws {
        guard timer == nil else { return }
        let bundle = Bundle.main.bundleURL
        guard FileManager.default.fileExists(atPath:bundle.appendingPathComponent("gateways.dat").path) else { throw LinkError.message("ملفات البوابتين مفقودة") }
        try? FileManager.default.removeItem(at:dir.appendingPathComponent("state.json"))
        EmbeddedNode.start(bundle.appendingPathComponent("supervisor.cjs").path,state:dir.path,bundle:bundle.path)
        timer = Timer.scheduledTimer(withTimeInterval:1,repeats:true) { [weak self] _ in Task { @MainActor in self?.refresh() } }
    }
    func set(_ name: String, enabled: Bool) {
        do {
            try FileManager.default.createDirectory(at:dir,withIntermediateDirectories:true)
            var next = desired
            next[name] = enabled
            try JSONEncoder().encode(next).write(to:dir.appendingPathComponent("desired.json"),options:.atomic)
            try startSupervisor()
            desired = next
            problem = ""
        } catch { problem = error.localizedDescription }
    }
    /// Ask the supervisor to restart a stopped or crashed gateway now ("install" retries unpacking).
    func restart(_ name: String) {
        if name != "install", desired[name] != true { set(name,enabled:true); return }
        try? Data().write(to:dir.appendingPathComponent("restart-" + name))
        if name != "install" { state[name] = "starting" } else { state["install"] = "installing" }
    }
    func failure(_ name: String) -> String? {
        for key in [name,"install"] { if let value = state[key], value.hasPrefix("error:") { return value } }
        return nil
    }
    func refresh() {
        guard let data = try? Data(contentsOf:dir.appendingPathComponent("state.json")),
              let next = try? JSONDecoder().decode([String:String].self,from:data) else { return }
        if state != next { state = next }
    }
    func password() -> String? { try? String(contentsOf:dir.appendingPathComponent("omni-password"),encoding:.utf8) }
}

private struct GatewayDashboard: UIViewRepresentable {
    let url: URL
    let view: WKWebView
    func makeUIView(context: Context) -> WKWebView {
        view.load(URLRequest(url:url))
        return view
    }
    func updateUIView(_ view: WKWebView,context: Context) {}
}

struct GatewayPanel: View {
    @ObservedObject var service = MobileGateways.shared
    @ObservedObject var studio: Studio
    var initialPage: URL? = nil
    @State private var openedInitialPage = false
    @State private var web = WKWebView()
    @State private var resultMessage = ""
    @State private var choosing = false

    private func openWhenReady() {
        guard !openedInitialPage, let initialPage else { return }
        let worker = initialPage.port == 3001 ? "free" : "omni"
        guard service.state[worker] == "listening" else { return }
        openedInitialPage = true
        selected = initialPage
    }
    private func selectFastModel() async {
        guard !choosing else { return }
        choosing = true
        defer { choosing = false }
        do {
            let script = """
            if (location.origin !== 'http://127.0.0.1:3001') throw Error('افتح لوحة FreeLLMAPI المحلية');
            const token = localStorage.getItem('freellmapi_dashboard_token');
            async function dashboard(path) {
              const response = await fetch(path, {mode:'same-origin',redirect:'error',
                headers:token ? {Authorization:'Bearer '+token} : {}});
              if (!response.ok) throw Error('افتح لوحة المفاتيح وسجل الدخول (' + response.status + ')');
              return response.json();
            }
            const [catalog, keys] = await Promise.all([dashboard('/api/models'), dashboard('/api/keys/providers')]);
            const active = new Set(keys.providers.filter(p => p.enabledKeyCount > 0).map(p => p.platform));
            const models = (Array.isArray(catalog) ? catalog : catalog.models).filter(m => m.enabled !== false &&
              m.supportsTools && active.has(m.platform) && m.contextWindow >= 32000 && m.modelId);
            models.sort((a,b) => (a.speedRank || 999) - (b.speedRank || 999) ||
              b.contextWindow - a.contextWindow || (a.intelligenceRank || 999) - (b.intelligenceRank || 999));
            return models[0]?.modelId || '';
            """
            let value = try await web.callAsyncJavaScript(script,arguments:[:],in:nil,contentWorld:.defaultClient)
            guard let model = value as? String, !model.isEmpty else {
                throw LinkError.message("لا يوجد نموذج مفعّل يدعم الأدوات وسياق 32000")
            }
            let base = "http://127.0.0.1:3001/v1"
            var provider = studio.providers.first { $0.base == base && $0.style == .gateway } ??
                Provider(name:"FreeLLMAPI",base:base,model:model,style:.gateway,free:true)
            provider.model = model
            try studio.storeProvider(provider,key:Credentials.key(provider.id))
            resultMessage = "تم اختيار " + model
        } catch { resultMessage = error.localizedDescription }
    }
    @State private var selected: URL?
    @State private var copied = false
    @Environment(\.dismiss) var dismiss
    var body: some View {
        NavigationStack {
            Group {
                if let selected {
                    VStack {
                        GatewayDashboard(url:selected,view:web).id(selected)
                        if selected.port == 3001 {
                            Button("اختيار أسرع نموذج متاح يدعم الأدوات") { Task { await selectFastModel() } }.disabled(choosing)
                            if !resultMessage.isEmpty { Text(resultMessage).font(.caption).textSelection(.enabled) }
                        }
                    }
                }
                else {
                    Form {
                        ForEach(["omni","free"],id:\.self) { id in
                            let name = id == "omni" ? "OmniRoute" : "FreeLLMAPI"
                            let endpoint = id == "omni" ? "http://127.0.0.1:20128" : "http://127.0.0.1:3001"
                            Section(name) {
                                Toggle("تشغيل على هذا الجهاز",isOn:Binding(get:{service.desired[id] ?? false},set:{service.set(id,enabled:$0)}))
                                if service.desired[id] == true {
                                    let status = service.state[id] ?? service.state["install"] ?? "installing"
                                    Text(["installing":"جار تجهيز الملفات لأول تشغيل…","ready":"جار بدء البوابة…","starting":"جار بدء البوابة…","listening":"تعمل محليا","stopped":"متوقفة"][status] ?? status)
                                    if status.hasPrefix("error:") {
                                        Button("إعادة تشغيل " + name) { service.restart(service.state["install"]?.hasPrefix("error:") == true ? "install" : id) }
                                    }
                                    Text(endpoint + "/v1").textSelection(.enabled)
                                    Button("فتح لوحة " + name) { selected = URL(string:endpoint) }.disabled(status != "listening")
                                    if id == "free" && status == "listening" {
                                        Button("مفاتيح المزودين") { selected = URL(string:endpoint + "/keys") }
                                    }
                                    if id == "omni" && status == "listening" {
                                        Button(copied ? "تم نسخ كلمة المرور" : "نسخ كلمة مرور اللوحة الأولية") {
                                            if let value = service.password() {
                                                UIPasteboard.general.setItems([["public.utf8-plain-text":value]],options:[.localOnly:true,.expirationDate:Date().addingTimeInterval(60)])
                                                copied = true
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        Text("بعد إعداد حساب المزود في لوحة البوابة أضف قالب البوابة من قائمة المزودين لاستخدامها في المحادثة. أبق التطبيق مفتوحا أثناء العمل.").font(.footnote)
                        if !service.problem.isEmpty { Text(service.problem) }
                    }
                }
            }.onAppear { openWhenReady() }.onChange(of:service.state) { _ in openWhenReady() }.navigationTitle("البوابات المحلية").navigationBarTitleDisplayMode(.inline)
             .toolbar { Button(selected == nil ? "تم" : "رجوع") { if selected == nil { dismiss() } else { selected = nil } } }
        }
    }
}
