import SwiftUI
import UniformTypeIdentifiers

struct Workbench: View {
    @ObservedObject var studio: Studio
    @ObservedObject var host: Host
    @State private var assistantMode = AssistantMode.standard
    @State private var prompt = ""
    @State private var picking = false
    @State private var settings = false
    @State private var projectPanel = false
    @State private var sessionPanel = false
    @State private var previewPanel = false
    @AppStorage("display.brand") private var brand = "smarter"
    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let proposal = studio.pending { EditReview(proposal: proposal, studio: studio) }
                else {
                    ScrollViewReader { proxy in
                        ScrollView {
                            LazyVStack(alignment:.leading,spacing:16) {
                                ForEach(studio.book.threads[studio.hostThread] ?? []) { turn in
                                    VStack(alignment:.leading,spacing:5) {
                                        Text(turn.role == "user" ? "أنت" : (brand.isEmpty ? "Allinone" : brand)).font(.caption.bold()).foregroundStyle(.secondary)
                                        Text(turn.content).textSelection(.enabled)
                                    }.frame(maxWidth:.infinity,alignment:.leading).id(turn.id)
                                }
                            }.padding()
                        }.onChange(of: studio.book.threads[studio.hostThread]?.last?.id) { id in
                            if let id { proxy.scrollTo(id,anchor:.bottom) }
                        }
                    }
                    if !studio.activity.isEmpty { HStack { ProgressView(); Text(studio.activity); Button("إيقاف") { studio.stopRequest() } }.font(.footnote).padding(5) }
                    if !studio.served.isEmpty { Text(studio.served).font(.caption).foregroundStyle(.secondary) }
                    if !studio.message.isEmpty { Text(studio.message).font(.footnote).foregroundStyle(.red).padding(.horizontal) }
                    if !studio.partial.isEmpty { ScrollView { Text(studio.partial).textSelection(.enabled) }.frame(maxHeight:100) }
                    Picker("طريقة الإجابة",selection:$assistantMode) {
                        Text("برمجة").tag(AssistantMode.standard)
                        Text("سؤال سريع").tag(AssistantMode.quick)
                        Text("برمجة خفيفة").tag(AssistantMode.light)
                    }.pickerStyle(.segmented).padding(.horizontal).disabled(studio.busy)
                    Divider()
                    HStack(alignment:.bottom) {
                        TextField("اسأل عن المشروع أو اطلب تعديلا…",text:$prompt,axis:.vertical).lineLimit(1...6)
                        Button("إرسال") {
                            let value = prompt
                            Task {
                                do { _ = try await studio.send(value,assistantMode:assistantMode); if prompt == value { prompt = "" } }
                                catch { studio.message = error.localizedDescription }
                            }
                        }.buttonStyle(.borderedProminent).disabled(studio.busy || prompt.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                    }.padding()
                }
            }
            .navigationTitle(studio.files.root.lastPathComponent)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement:.navigationBarLeading) {
                    Menu {
                        Button("فتح مجلد مشروع") { picking = true }.disabled(studio.busy || studio.pending != nil)
                        Button("اختبار صفحة HTML ولقطة شاشة") { previewPanel = true }
                        Button("ملفات ومهام وذاكرة") { projectPanel = true }
                        Button("المحادثات والتقارير والتبادل اليدوي") { sessionPanel = true }
                        Button("محادثة جديدة") { studio.newChat() }.disabled(studio.busy || studio.pending != nil)
                    } label: { Label("المشروع",systemImage:"folder") }
                }
                ToolbarItem(placement:.navigationBarTrailing) {
                    Button { settings = true } label: { Label("المزودون والاتصال", systemImage:"slider.horizontal.3") }
                }
            }
            .fileImporter(isPresented:$picking,allowedContentTypes:[.folder]) { result in
                do { try studio.open(result.get()) } catch { studio.message = error.localizedDescription }
            }
            .sheet(isPresented:$sessionPanel) { SessionPanel(studio:studio) }
            .sheet(isPresented:$settings) { SettingsPanel(studio:studio,host:host) }
            .sheet(isPresented:$previewPanel) { PreviewPanel(studio:studio) }
            .sheet(isPresented:$projectPanel) { ProjectPanel(studio:studio) }
        }
    }
}

private struct EditReview: View {
    let proposal: EditProposal
    @ObservedObject var studio: Studio
    @State private var showOld = false
    var body: some View {
        VStack(alignment:.leading) {
            Label(proposal.original == nil ? "إنشاء ملف" : "مراجعة تعديل",systemImage:"doc.text").font(.headline)
            Text(proposal.path).font(.system(.body,design:.monospaced)).textSelection(.enabled)
            Text(proposal.reason).font(.callout)
            Picker("المعاينة",selection:$showOld) {
                Text("المقترح").tag(false); Text("الحالي").tag(true)
            }.pickerStyle(.segmented)
            ScrollView([.horizontal,.vertical]) {
                Text(verbatim:showOld ? proposal.original.map { String(decoding:$0,as:UTF8.self) } ?? "ملف جديد" : proposal.replacement)
                    .font(.system(.footnote, design:.monospaced)).textSelection(.enabled)
            }.frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading).environment(\.layoutDirection,.leftToRight)
            if !studio.message.isEmpty { Text(studio.message).foregroundStyle(.red) }
            HStack {
                Button("تطبيق التعديل") { do { try studio.review(apply:true) } catch { studio.message = error.localizedDescription } }.buttonStyle(.borderedProminent)
                Button("رفض") { try? studio.review(apply:false) }.buttonStyle(.bordered)
            }
        }.padding()
    }
}

private struct ProjectPanel: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var studio: Studio
    @State private var task = ""
    @State private var listing = ""
    var body: some View {
        NavigationStack {
            Form {
                Section("مجلد المشروع") { Text(listing.isEmpty ? "المجلد فارغ" : listing).font(.system(.footnote,design:.monospaced)).textSelection(.enabled) }
                Section("ذاكرة المشروع") {
                    TextField("تعليمات وملاحظات للجلسات",text: Binding(get:{ studio.book.notes },set:studio.setNotes),axis:.vertical).lineLimit(2...8)
                }
                Section("المهام") {
                    HStack { TextField("مهمة جديدة",text:$task); Button("إضافة") { studio.addTask(task); task = "" }.disabled(task.isEmpty) }
                    ForEach(studio.book.tasks) { item in
                        HStack {
                            Text(item.prompt); Spacer()
                            if item.done { Image(systemName:"checkmark") }
                            else {
                                Button("تشغيل") {
                                    dismiss()
                                    Task { do { _ = try await studio.send(item.prompt,task:item.id) } catch { studio.message = error.localizedDescription } }
                                }.disabled(studio.busy || studio.pending != nil)
                            }
                        }
                    }
                }
            }.navigationTitle("المشروع").toolbar { Button("تم") { dismiss() } }
            .onAppear { do { listing = try studio.files.list("") } catch { listing = error.localizedDescription } }
        }
    }
}

struct SettingsPanel: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var studio: Studio
    @ObservedObject var host: Host
    @State private var gateways = false
    @State private var editor: Provider?
    var body: some View {
        NavigationStack {
            Form {
                Button("تشغيل OmniRoute وFreeLLMAPI محليا") { gateways = true }
                Section("التوجيه داخل الآيباد") {
                    Toggle("الانتقال تلقائيا إلى مزود احتياطي",isOn:$studio.failover)
                    Picker("الطريقة",selection:$studio.mode) {
                        Text("الأولوية ثم الاحتياطي").tag(RouteMode.priority)
                        Text("تدوير المزودين المجانيين").tag(RouteMode.freePool)
                    }
                    Text("تحدد القائمة ترتيب المحاولة. المسار المجاني يستخدم المزودين الذين تعلّمهم كمجانيين.").font(.footnote)
                }
                Section("المزودون") {
                    ForEach(studio.providers) { p in
                        Button { editor = p } label: {
                            HStack { VStack(alignment:.leading) { Text(p.name); Text(p.model).font(.caption).foregroundStyle(.secondary) }; Spacer()
                                if !p.enabled { Text("معطل").font(.caption) } }
                        }
                    }
                    .onMove { from,to in studio.providers.move(fromOffsets:from,toOffset:to); try? studio.saveProviders() }
                    .onDelete { offsets in
                        do {
                            for index in offsets.sorted(by:>) { try Credentials.save("",studio.providers[index].id); studio.providers.remove(at:index) }
                            try studio.saveProviders()
                        } catch { studio.message = error.localizedDescription }
                    }
                    Button("إضافة مزود") { editor = Provider(name:"",base:"",model:"",style:.openAI,free:false) }
                }
                Section("اتصال الأجهزة") {
                    Text(host.state)
                    if !host.code.isEmpty {
                        Text(host.address.isEmpty ? "اتصل بشبكة Wi-Fi" : host.address).textSelection(.enabled)
                        Text(host.code).font(.system(.footnote,design:.monospaced)).textSelection(.enabled)
                        Button("نسخ رمز الاقتران") {
                            UIPasteboard.general.setItems([["public.utf8-plain-text":host.code]],options:[.localOnly:true,.expirationDate:Date().addingTimeInterval(300)])
                        }
                    }
                    Button(host.code.isEmpty ? "بدء المضيف" : "إيقاف المضيف") { if host.code.isEmpty { host.start() } else { host.stop() } }
                }
            }.navigationTitle("الإعدادات").toolbar { EditButton(); Button("تم") { dismiss() } }
            .sheet(isPresented:$gateways) { GatewayPanel(studio:studio) }
            .sheet(item:$editor) { p in ProviderEditor(studio:studio,provider:p) }
        }
    }
}

private struct ProviderEditor: View {
    @Environment(\.dismiss) var dismiss
    @ObservedObject var studio: Studio
    @State var provider: Provider
    @State private var key = ""
    @State private var error = ""
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Menu("إعدادات مزود جاهزة") {
                        Button("OmniRoute") { preset("OmniRoute","http://127.0.0.1:20128/v1",.gateway); provider.model = "auto" }
                        Button("FreeLLMAPI") { preset("FreeLLMAPI","http://127.0.0.1:3001/v1",.gateway); provider.model = "auto" }
                        Button("OpenAI") { preset("OpenAI","https://api.openai.com/v1",.openAI) }
                        Button("Anthropic") { preset("Anthropic","https://api.anthropic.com/v1",.anthropic) }
                        Button("Groq") { preset("Groq","https://api.groq.com/openai/v1",.openAI) }
                        Button("Gemini") { preset("Gemini","https://generativelanguage.googleapis.com/v1beta/openai",.openAI) }
                        Button("OpenRouter") { preset("OpenRouter","https://openrouter.ai/api/v1",.openAI) }
                        Button("Apple Intelligence") { provider.name = "Apple Intelligence"; provider.model = "on-device"; provider.style = .onDevice; provider.free = true; provider.base = ""; key = "" }
                    }
                    TextField("الاسم",text:$provider.name)
                    Picker("الواجهة",selection:$provider.style) {
                        Text("بوابة Messages").tag(APIStyle.gateway); Text("OpenAI-compatible").tag(APIStyle.openAI); Text("Anthropic Messages").tag(APIStyle.anthropic); Text("Apple على الجهاز").tag(APIStyle.onDevice)
                    }
                    if provider.style != .onDevice {
                        TextField("Base URL",text:$provider.base).keyboardType(.URL).onChange(of:provider.base) { _ in key = "" }
                        if provider.name == "OmniRoute" {
                            Menu("اختيار توجيه OmniRoute") {
                                Button("تلقائي للبرمجة") { provider.model = "auto/coding" }
                                Button("تلقائي سريع") { provider.model = "auto/fast" }
                            }
                        }
                        TextField("معرّف النموذج من حسابك",text:$provider.model)
                        SecureField("API key",text:$key)
                    }
                    Toggle("مشمول بالمسار المجاني",isOn:$provider.free)
                    Toggle("مفعّل",isOn:$provider.enabled)
                }.textInputAutocapitalization(.never).autocorrectionDisabled()
                if !error.isEmpty { Text(error).foregroundStyle(.red) }
            }.navigationTitle("إعداد المزود").toolbar {
                Button("إلغاء") { dismiss() }
                Button("حفظ") {
                    do { try studio.storeProvider(provider,key:key); dismiss() } catch { self.error = error.localizedDescription }
                }
            }.onAppear { do { key = try Credentials.key(provider.id) } catch { self.error = error.localizedDescription } }
        }
    }
    private func preset(_ name: String,_ url: String,_ style: APIStyle) {
        provider.name = name; provider.base = url; provider.style = style; provider.model = ""; provider.free = false; key = ""
    }
}
