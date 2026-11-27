import SwiftUI
import WebKit
import UniformTypeIdentifiers
import FoundationModels

enum MobilePanel: Int, Identifiable {
    case projectFolder, externalFolder, options, connection, workspace, gateways, sessions, omniDashboard, freeDashboard, freeKeys
    var id: Int { rawValue }
}

struct OriginalHome: View {
    @StateObject private var host = Host()
    @State private var panel: MobilePanel?
    @State private var refreshCount = 0
    @State private var openFilesAfterDismiss = false
    @State private var folderError: String?
    var body: some View {
        OriginalPage(host:host,refreshCount:refreshCount,open:{ panel = $0 })
            .sheet(item:$panel,onDismiss:{
                if openFilesAfterDismiss {
                    openFilesAfterDismiss = false
                    panel = .externalFolder
                } else { refreshCount += 1 }
            }) { item in
                switch item {
                case .projectFolder:
                    ProjectFolderPanel(studio:host.studio) {
                        openFilesAfterDismiss = true
                        panel = nil
                    }
                case .externalFolder:
                    ExternalProjectPicker(start:host.studio.files.root) { url in
                        if let url {
                            do { try host.studio.open(url) }
                            catch { folderError = error.localizedDescription }
                        }
                        panel = nil
                    }
                case .options:
                    NavigationStack {
                        List {
                            NavigationLink("المزودون وعنوان المضيف") { SettingsPanel(studio:host.studio,host:host) }
                            NavigationLink("اتصال بمضيف آخر") { Chat() }
                            NavigationLink("البوابات المحلية") { GatewayPanel(studio:host.studio) }
                            NavigationLink("ملفات المشروع ومراجعة التعديلات") { Workbench(studio:host.studio,host:host) }
                        }.navigationTitle("إعدادات الجهاز").toolbar { Button("تم") { panel = nil } }
                    }

                case .connection: Chat()
                case .gateways: GatewayPanel(studio:host.studio)
                case .omniDashboard: GatewayPanel(studio:host.studio,initialPage:URL(string:"http://127.0.0.1:20128"))
                case .freeDashboard: GatewayPanel(studio:host.studio,initialPage:URL(string:"http://127.0.0.1:3001"))
                case .freeKeys: GatewayPanel(studio:host.studio,initialPage:URL(string:"http://127.0.0.1:3001/keys"))
                case .sessions: SessionPanel(studio:host.studio)
                case .workspace: Workbench(studio:host.studio,host:host)
                }
            }
            .alert("تعذر اختيار المجلد",isPresented:Binding(get:{ folderError != nil && panel == nil },set:{ if !$0 { folderError = nil } })) {
                Button("موافق") { folderError = nil }
            } message: { Text(folderError ?? "") }
            .onAppear {
                host.start()
                #if targetEnvironment(simulator)
                if ProcessInfo.processInfo.arguments.contains("--test-mobile-gateways") {
                    MobileGateways.shared.set("free",enabled:true)
                    MobileGateways.shared.set("omni",enabled:true)
                }
                #endif
            }
    }
}

private struct OriginalPage: UIViewRepresentable {
    let host: Host
    let refreshCount: Int
    let open: (MobilePanel)->Void
    func makeCoordinator() -> Coordinator { Coordinator(host:host,open:open) }
    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let handler = context.coordinator
        let page = Bundle.main.url(forResource:"index",withExtension:"html",subdirectory:"OriginalUI")!
        let adapter = page.deletingLastPathComponent().appendingPathComponent("bridge.js")
        config.userContentController.addUserScript(WKUserScript(source:(try? String(contentsOf:adapter)) ?? "",injectionTime:.atDocumentStart,forMainFrameOnly:true))
        config.userContentController.addScriptMessageHandler(handler,contentWorld:.page,name:"mobile")
        let web = WKWebView(frame:.zero,configuration:config)
        web.navigationDelegate = handler
        web.uiDelegate = handler
        handler.page = page
        handler.currentWeb = web
        web.loadFileURL(page,allowingReadAccessTo:page.deletingLastPathComponent())
        return web
    }
    func updateUIView(_ webView: WKWebView, context: Context) {
        guard context.coordinator.lastRefresh != refreshCount else { return }
        context.coordinator.lastRefresh = refreshCount
        webView.evaluateJavaScript("if (typeof refreshState === 'function') { void refreshState(); }",completionHandler:nil)
    }
    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName:"mobile",contentWorld:.page)
    }
    @MainActor final class Coordinator: NSObject, WKScriptMessageHandlerWithReply, WKNavigationDelegate, WKUIDelegate {
        let host: Host
        let open: (MobilePanel)->Void
        weak var currentWeb: WKWebView?
        var lastRefresh = 0
        var page: URL?
        var studio: Studio { host.studio }
        init(host:Host,open:@escaping (MobilePanel)->Void) { self.host=host; self.open=open }
        func webView(_ webView:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping (WKNavigationActionPolicy)->Void) {
            decisionHandler(action.request.url?.standardizedFileURL == page?.standardizedFileURL ? .allow : .cancel)
        }
        func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage,
                                   replyHandler:@escaping (Any?,String?)->Void) {
            guard message.frameInfo.isMainFrame, message.webView?.url?.standardizedFileURL == page?.standardizedFileURL,
                  let payload = message.body as? [String:Any],let path = payload["path"] as? String else {
                replyHandler(nil,"Invalid page"); return
            }
            Task { do { replyHandler(try await route(path,payload["data"] as? [String:Any] ?? [:]),nil) }
                catch { replyHandler(nil,error.localizedDescription) } }
        }
        var appleReady: Bool {
            if #available(iOS 26, *) { return SystemLanguageModel.default.availability == .available }
            return false
        }
        #if targetEnvironment(simulator)
        func webView(_ web:WKWebView,didFinish navigation:WKNavigation!) {
            guard ProcessInfo.processInfo.arguments.contains("--test-mobile-gateways") else { return }
            let provider = Provider(name:"Simulator fixture",base:"http://127.0.0.1:18761/v1",model:"fixture",style:.openAI,free:true)
            studio.providers.append(provider)
            Task {
                do {
                    let script = """
                    for(let n=0;n<100 && !document.querySelector('#gwPills button');n++) await new Promise(r=>setTimeout(r,100));
                    await refreshState();
                    await selectGateway(provider);
                    document.querySelector('#quick').checked=true;
                    input.value='ui-bridge-question';
                    await send();
                    return S.messages.some(m=>m.role==='assistant' && m.display==='ui-bridge-ok');
                    """
                    let value = try await web.callAsyncJavaScript(script,arguments:["provider":provider.id.uuidString],in:nil,contentWorld:.page)
                    guard value as? Bool == true else { return }
                    let docs = FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0]
                    let folder = docs.appendingPathComponent(UUID().uuidString,isDirectory:true)
                    try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:false)
                    try studio.open(folder)
                    let edit = try studio.files.propose(path:"test.txt",replacement:"folder-write-ok",reason:"test",previouslyRead:[:])
                    try studio.files.apply(edit)
                    let reopened = Studio()
                    let saved = try reopened.files.read("test.txt")
                    guard reopened.notebookID == studio.notebookID, saved == Data("folder-write-ok".utf8) else { return }
                    try studio.open(docs.appendingPathComponent("Workspace",isDirectory:true))
                    let marker = FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("original-ui-passed")
                    try Data().write(to:marker)
                } catch { NSLog("Original UI check: %@",error.localizedDescription) }
            }
        }
        #endif
        /// Waits for the first-run unpack (can take minutes) and restarts a crashed gateway once.
        func waitForGateway(_ worker:String,name:String) async throws {
            let service = MobileGateways.shared
            if service.desired[worker] != true { service.set(worker,enabled:true) }
            else if service.failure(worker) != nil { service.restart(service.state["install"]?.hasPrefix("error:") == true ? "install" : worker) }
            var restarted = false
            let started = Date()
            while true {
                try Task.checkCancellation()
                service.refresh()
                if service.state[worker] == "listening" { return }
                let installing = (service.state["install"] ?? "installing") == "installing"
                studio.activity = installing ? "تجهيز " + name + " لأول تشغيل… قد يستغرق بضع دقائق" : "بدء " + name + "…"
                if let failure = service.failure(worker) {
                    guard !restarted else {
                        studio.activity = ""
                        throw LinkError.message(name + " لم تعمل: " + failure.dropFirst(6).trimmingCharacters(in:.whitespaces) + ". افتح البوابات المحلية لإعادة تشغيلها.")
                    }
                    restarted = true
                    service.restart(service.state["install"]?.hasPrefix("error:") == true ? "install" : worker)
                }
                if Date().timeIntervalSince(started) > (installing ? 900 : 180) {
                    studio.activity = ""
                    throw LinkError.message(name + " لم تجهز بعد. انتظر حتى تظهر «تعمل محليا» في البوابات المحلية ثم أعد الإرسال.")
                }
                try await Task.sleep(nanoseconds:500_000_000)
            }
        }
        func route(_ raw:String,_ data:[String:Any]) async throws -> Any {
            let uri = URLComponents(string:raw)
            let path = uri?.path ?? raw
            let service = MobileGateways.shared
            let pairs = [("omniroute","omni","OmniRoute",20128),("freellmapi","free","FreeLLMAPI",3001)]
            let gateway = data["gateway"] as? String ?? uri?.queryItems?.first(where:{$0.name == "gateway"})?.value ?? ""
            switch path {
            case "/api/state":
                var gateways:[[String:Any]] = pairs.map { id,worker,name,_ in
                    ["name":id,"type":id,"title":name,"installed":true,"can_start":true,"up":service.state[worker]=="listening","default_model":"auto"]
                } + [["name":"apple","type":"local","title":"Apple Intelligence","up":appleReady,"installed":true,"can_start":false,"default_model":"on-device"]]
                for p in studio.providers where p.enabled && p.style != .onDevice && !pairs.contains(where: { p.base == "http://127.0.0.1:\($0.3)/v1" }) {
                    gateways.append(["name":p.id.uuidString,"title":p.name,"type":"custom","up":true,"installed":true,"can_start":false,"default_model":p.model])
                }
                return ["version":"1.10.0","lang":"ar","brand":UserDefaults.standard.string(forKey:"display.brand") ?? "smarter","gateways":gateways,"project":studio.files.root.lastPathComponent,"notice":studio.message,"project_id":studio.notebookID,"default_gateway":"omniroute","efforts":[""],"permission_modes":["default"],"default_permission_mode":"default","fast_model":"auto","visual":["available":false]] as [String:Any]
            case "/mobile/options": open(.options); return [:] as [String:String]
            case "/api/accounts": return ["accounts":[["id":"default","name":"Default"]]]
            case "/api/auth": return ["loggedIn":false]
            case "/api/lang": return ["ok":true]
            case "/api/models":
                let base = pairs.first{$0.0==gateway}.map{"http://127.0.0.1:\($0.3)/v1"}
                return ["models":studio.providers.filter{$0.base==base}.map(\.model)]
            case "/api/gateway","/api/dashboard","/api/keys":
                guard let pair = pairs.first(where:{$0.0 == (data["name"] as? String ?? gateway)}) else { throw LinkError.message("هذا المزود لا يملك لوحة بوابة محلية") }
                if path == "/api/gateway" {
                    let start = data["action"] as? String == "start"
                    if start, service.desired[pair.1] == true, service.failure(pair.1) != nil {
                        service.restart(service.state["install"]?.hasPrefix("error:") == true ? "install" : pair.1)
                    } else { service.set(pair.1,enabled:start) }
                }
                else {
                    if service.desired[pair.1] != true { service.set(pair.1,enabled:true) }
                    if path == "/api/keys" {
                        open(.freeKeys)
                        return ["ok":false,"error":"تدار المفاتيح من لوحة FreeLLMAPI المحلية"] as [String:Any]
                    }
                    open(pair.1 == "omni" ? .omniDashboard : .freeDashboard)
                }
                return ["ok":true,"url":"about:blank","notes":[]] as [String:Any]
            case "/api/project":
                guard !studio.busy, studio.pending == nil else { throw LinkError.message("أكمل الطلب أو راجع التعديل قبل تغيير مجلد المشروع") }
                open(.projectFolder)
                return ["presented":true]
            case "/api/projects": if data["method"] as? String == "POST" { open(.workspace); throw LinkError.message("اختر مجلد المشروع من ملفات الجهاز") }; return ["projects":[]] as [String:Any]
            case "/api/chat":
                guard let question = data["text"] as? String, !question.isEmpty else { throw LinkError.message("أدخل السؤال") }
                let id=(data["conversation_id"] as? Int) ?? Int.random(in:1...2_000_000_000)
                let chosen:Provider
                if let pair=pairs.first(where:{$0.0==gateway}) {
                    let base="http://127.0.0.1:\(pair.3)/v1"
                    if service.state[pair.1] != "listening" {
                        try await waitForGateway(pair.1,name:pair.2)
                    }
                    var p: Provider
                    if let saved = studio.providers.first(where:{$0.base==base && $0.style == .gateway}) { p = saved }
                    else {
                        // Save the gateway as a provider so its key can be entered under Providers.
                        p = Provider(name:pair.2,base:base,model:"auto",style:.gateway,free:pair.1=="free")
                        try studio.addProvider(p)
                    }
                    if let model=data["model"] as? String,!model.isEmpty {p.model=model}
                    chosen=p
                } else if gateway=="apple" { chosen = .apple }
                else if let p = studio.providers.first(where: { $0.enabled && $0.id.uuidString == gateway }) { chosen = p }
                else { throw LinkError.message("اختر بوابة من القائمة") }
                let mode:AssistantMode = data["quick"] as? Bool == true ? .quick : (data["light"] as? Bool == true ? .light : .standard)
                let answer=try await studio.send(question,thread:"ui-\(id)",assistantMode:mode,preferred:chosen,allowFallback:data["failover"] as? Bool ?? false)
                if studio.pending != nil { open(.workspace) }
                return ["answer":answer,"id":id] as [String:Any]
            case "/api/stop": studio.stopRequest(); return ["ok":true]
            case "/api/shutdown": studio.stopRequest(); host.stop(); for pair in pairs where service.desired[pair.1]==true { service.set(pair.1,enabled:false) }; return ["ok":true]
            case "/api/memory": studio.setNotes(studio.book.notes+"\n"+(data["text"] as? String ?? "")); return ["ok":true]
            case "/api/conversations":
                let search = uri?.queryItems?.first(where:{$0.name=="q"})?.value ?? ""
                return ["conversations":studio.book.threads.compactMap { key,turns -> [String:Any]? in
                    guard key.hasPrefix("ui-"),let id=Int(key.dropFirst(3)),let first=turns.first else{return nil}
                    let title=studio.book.uiTitles?[key] ?? first.content
                    guard search.isEmpty || title.localizedCaseInsensitiveContains(search) else{return nil}
                    return ["id":id,"title":String(title.prefix(100))]
                }.sorted { ($0["id"] as? Int ?? 0) > ($1["id"] as? Int ?? 0) }]
            default:
                let parts=path.split(separator:"/")
                if parts.count>=3,parts[1]=="conversations",let id=Int(parts[2]) {
                    let key="ui-\(id)"
                    if data["method"] as? String=="DELETE" { try studio.changeOriginalChat(key,title:nil);return ["ok":true] }
                    if parts.last=="rename" { try studio.changeOriginalChat(key,title:data["title"] as? String ?? "");return ["ok":true] }
                    if parts.last=="export" {
                        let markdown=(studio.book.threads[key] ?? []).map { "## " + $0.role + "\n\n" + $0.content }.joined(separator:"\n\n")
                        let name="conversation-\(id).md"
                        let file=FileManager.default.temporaryDirectory.appendingPathComponent(name)
                        try Data(markdown.utf8).write(to:file,options:.atomic)
                        guard let web = currentWeb, let vc=presenter(web) else { throw LinkError.message("تعذرت مشاركة المحادثة") }
                        let sheet=UIActivityViewController(activityItems:[file],applicationActivities:nil)
                        sheet.popoverPresentationController?.sourceView=web
                        sheet.popoverPresentationController?.sourceRect=CGRect(x:web.bounds.midX,y:web.bounds.midY,width:1,height:1)
                        vc.present(sheet,animated:true)
                        return ["shared":true]
                    }
                    if parts.last=="report" {
                        let report=(studio.book.events ?? []).map{$0.when.ISO8601Format()+" "+$0.detail}.joined(separator:"\n")
                        return ["chars":report.count,"text":report,"path":"Allinone","name":"report.txt"] as [String:Any]
                    }
                    let messages=(studio.book.threads[key] ?? []).map { ["role":$0.role,"display":$0.content,"sent":$0.content] }
                    return ["conversation":["id":id,"running":false] as [String:Any],"messages":messages] as [String:Any]
                }
                if path.hasPrefix("/api/bridge/") { open(.sessions) }
                throw LinkError.message("هذه العملية غير متاحة في نسخة الجهاز")
            }
        }
        func presenter(_ web:WKWebView) -> UIViewController? {
            var vc=web.window?.rootViewController
            while let next=vc?.presentedViewController {vc=next}
            return vc
        }
        func webView(_ web:WKWebView,runJavaScriptConfirmPanelWithMessage message:String,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping (Bool)->Void) {
            guard let vc=presenter(web) else {completionHandler(false);return}
            let alert=UIAlertController(title:nil,message:message,preferredStyle:.alert)
            alert.addAction(UIAlertAction(title:"إلغاء",style:.cancel){_ in completionHandler(false)})
            alert.addAction(UIAlertAction(title:"موافق",style:.default){_ in completionHandler(true)})
            vc.present(alert,animated:true)
        }
        func webView(_ web:WKWebView,runJavaScriptTextInputPanelWithPrompt prompt:String,defaultText:String?,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping (String?)->Void) {
            guard let vc=presenter(web) else {completionHandler(nil);return}
            let alert=UIAlertController(title:prompt,message:nil,preferredStyle:.alert)
            alert.addTextField{$0.text=defaultText}
            alert.addAction(UIAlertAction(title:"إلغاء",style:.cancel){_ in completionHandler(nil)})
            alert.addAction(UIAlertAction(title:"موافق",style:.default){_ in completionHandler(alert.textFields?.first?.text)})
            vc.present(alert,animated:true)
        }
    }
}
