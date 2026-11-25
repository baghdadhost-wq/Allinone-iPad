import SwiftUI
import WebKit

@MainActor final class PagePreview: NSObject, ObservableObject, WKNavigationDelegate {
    let browser: WKWebView
    @Published var status = ""
    @Published var snapshot: UIImage?
    private var ready = false
    private var expected = ""
    override init() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        browser = WKWebView(frame:.zero,configuration:config)
        super.init()
        browser.navigationDelegate = self
    }
    func load(_ html: String, expecting: String) async throws {
        ready = false
        snapshot = nil
        expected = expecting
        status = "تحميل الصفحة…"
        let rules = #"[{"trigger":{"url-filter":"^(https?|wss?|file|ftp):"},"action":{"type":"block"}}]"#
        let list: WKContentRuleList? = try await WKContentRuleListStore.default().compileContentRuleList(forIdentifier:"AllinonePreview-v1",encodedContentRuleList:rules)
        guard let list else { throw LinkError.message("تعذر إعداد المعاينة") }
        let content = browser.configuration.userContentController
        content.removeAllContentRuleLists()
        content.add(list)
        browser.loadHTMLString(html,baseURL:nil)
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(navigationAction.request.url?.absoluteString == "about:blank" ? .allow : .cancel)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        ready = true
        Task { await check() }
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { status = error.localizedDescription }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { ready = false; status = "توقف عرض الصفحة" }
    func check() async {
        guard ready else { return }
        do {
            let text = try await browser.evaluateJavaScript("document.body?.innerText ?? ''") as? String ?? ""
            let ok = expected.isEmpty ? !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty : text.contains(expected)
            let config = WKSnapshotConfiguration()
            config.snapshotWidth = NSNumber(value:min(960.0, max(1.0, Double(browser.bounds.width))))
            snapshot = try await browser.takeSnapshot(configuration:config)
            status = ok ? "نجح فحص النص المرئي" : "فشل الفحص: لم يظهر النص المطلوب"
        } catch { status = error.localizedDescription }
    }
}

private struct WebSurface: UIViewRepresentable {
    let web: WKWebView
    func makeUIView(context: Context) -> WKWebView { web }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

struct PreviewPanel: View {
    @ObservedObject var studio: Studio
    @StateObject private var page = PagePreview()
    @State private var path = "index.html"
    @State private var expected = ""
    @Environment(\.dismiss) var dismiss
    var body: some View {
        NavigationStack {
            VStack {
                TextField("ملف HTML داخل المشروع",text:$path).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("نص يتوقع ظهوره (اختياري)",text:$expected)
                HStack {
                    Button("فتح وفحص") {
                        Task {
                            do {
                                let html = String(decoding:try studio.files.read(path),as:UTF8.self)
                                try await page.load(html,expecting:expected)
                            } catch { page.status = error.localizedDescription }
                        }
                    }
                    Button("إعادة فحص الشاشة") { Task { await page.check() } }
                }
                Text(page.status).font(.footnote)
                WebSurface(web:page.browser)
                if let shot = page.snapshot {
                    ShareLink(item:Image(uiImage:shot),preview:SharePreview("لقطة الاختبار",image:Image(uiImage:shot))) { Text("مشاركة لقطة الشاشة") }
                }
            }.padding().navigationTitle("اختبار صفحة HTML مستقلة")
                .onChange(of:page.status) { status in if !status.isEmpty { studio.track(path + " · " + status) } }
                .toolbar { Button("تم") { dismiss() } }
        }
    }
}
