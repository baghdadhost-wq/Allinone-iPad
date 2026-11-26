import SwiftUI
import WebKit

@MainActor final class MobileGateways: ObservableObject {
    static let shared = MobileGateways()
    private let dir = FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("MobileGateways")
    @Published private(set) var desired = [String:Bool]()
    @Published private(set) var state = [String:String]()
    @Published var problem = ""
    private var timer: Timer?
    func set(_ name: String, enabled: Bool) {
        do {
            let fm = FileManager.default
            try fm.createDirectory(at:dir,withIntermediateDirectories:true)
            var next = desired
            next[name] = enabled
            try JSONEncoder().encode(next).write(to:dir.appendingPathComponent("desired.json"),options:.atomic)
            let bundle = Bundle.main.bundleURL
            guard fm.fileExists(atPath:bundle.appendingPathComponent("gateways.dat").path) else { throw LinkError.message("ملفات البوابتين مفقودة") }
            if timer == nil {
                try? fm.removeItem(at:dir.appendingPathComponent("state.json"))
                EmbeddedNode.start(bundle.appendingPathComponent("supervisor.cjs").path,state:dir.path,bundle:bundle.path)
                timer = Timer.scheduledTimer(withTimeInterval:1,repeats:true) { [weak self] _ in Task { @MainActor in self?.refresh() } }
            }
            desired = next
            problem = ""
        } catch { problem = error.localizedDescription }
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
    func makeUIView(context: Context) -> WKWebView {
        let view = WKWebView()
        view.load(URLRequest(url:url))
        return view
    }
    func updateUIView(_ view: WKWebView,context: Context) {}
}

struct GatewayPanel: View {
    @ObservedObject var service = MobileGateways.shared
    @State private var selected: URL?
    @State private var copied = false
    @Environment(\.dismiss) var dismiss
    var body: some View {
        NavigationStack {
            Group {
                if let selected { GatewayDashboard(url:selected) }
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
                                    Text(endpoint + "/v1").textSelection(.enabled)
                                    Button("فتح لوحة " + name) { selected = URL(string:endpoint) }.disabled(status != "listening")
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
            }.navigationTitle("البوابات المحلية").navigationBarTitleDisplayMode(.inline)
             .toolbar { Button(selected == nil ? "تم" : "رجوع") { if selected == nil { dismiss() } else { selected = nil } } }
        }
    }
}
