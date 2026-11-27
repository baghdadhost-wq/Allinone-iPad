import SwiftUI
import CryptoKit

struct Entry: Identifiable {
    let name: String
    let repo: String
    let file: String
    let estimate: Int64
    var id: String { repo }
    static let choices = [
        Entry(name:"Qwen 3.5 4B · Abliterated",repo:"privastudio/qwen3.5-abliterated",file:"Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf",estimate:2_710_000_000),
        Entry(name:"Gemma 4 E4B · Heretic",repo:"spale04/gemma-4-E4B-it-heretic-GGUF",file:"gemma-4-E4B-it-heretic-Q4_K_M-imat.gguf",estimate:5_300_000_000),
        Entry(name:"Bonsai 2 27B · Heretic",repo:"OS-Software/Ternary-Bonsai-2-27B-Uncensored-Heretic-GGUF",file:"Ternary-Bonsai-2-27B-Uncensored-Heretic-PTQ1_0.gguf",estimate:5_950_000_000)
    ]
}
struct Issue: LocalizedError {
    let text: String
    init(_ s:String){text=s}
    var errorDescription:String? {text}
}
func sizeText(_ bytes:Int64)->String { ByteCountFormatter.string(fromByteCount:bytes,countStyle:.decimal) }
let files = FileManager.default
let models = files.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Models",isDirectory:true)
func disk()->Int64 { (try? models.resourceValues(forKeys:[.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage) ?? 0 }

struct Card: Decodable {
    struct Sibling: Decodable {
        struct Blob: Decodable { let sha256:String; let size:Int64 }
        let rfilename:String
        let lfs:Blob?
    }
    let sha:String
    let siblings:[Sibling]
}
func download(_ entry:Entry,status:@escaping @Sendable (String)->Void) async throws {
    let api=URL(string:"https://huggingface.co/api/models/"+entry.repo+"?blobs=true")!
    let (metadata,response)=try await URLSession.shared.data(from:api)
    guard (response as? HTTPURLResponse)?.statusCode == 200 else {throw Issue("تعذرت قراءة معلومات النموذج.")}
    let card=try JSONDecoder().decode(Card.self,from:metadata)
    guard let blob=card.siblings.first(where:{$0.rfilename==entry.file})?.lfs, blob.size>0,
          blob.sha256.count==64,card.sha.count==40 else {throw Issue("تعذر التحقق من بصمة الملف.")}
    guard disk()>blob.size+300_000_000 else {throw Issue("مساحة التخزين المتاحة غير كافية.")}
    status("تنزيل "+sizeText(blob.size)+"…")
    let url=URL(string:"https://huggingface.co/"+entry.repo+"/resolve/"+card.sha+"/"+entry.file)!
    let (temp,reply)=try await URLSession.shared.download(from:url)
    defer {try? files.removeItem(at:temp)}
    guard (reply as? HTTPURLResponse)?.statusCode==200 else {throw Issue("فشل تنزيل الأوزان.")}
    status("التحقق من سلامة الأوزان…")
    let handle=try FileHandle(forReadingFrom:temp)
    defer {try? handle.close()}
    var hash=SHA256(),length:Int64=0
    while let data=try handle.read(upToCount:1<<20), !data.isEmpty {
        try Task.checkCancellation()
        hash.update(data:data);length+=Int64(data.count)
    }
    guard length==blob.size,hash.finalize().map({String(format:"%02x",$0)}).joined()==blob.sha256.lowercased() else {throw Issue("بصمة الملف لا تطابق النسخة المنشورة.")}
    try Task.checkCancellation()
    try files.moveItem(at:temp,to:models.appendingPathComponent(entry.file))
}

struct Message:Identifiable {
    let id=UUID()
    let role:String
    var content:String
}
@MainActor final class Chat:ObservableObject {
    @Published var entry=Entry.choices[0]
    @Published var turns:[Message]=[]
    @Published var prompt=""
    @Published var status=""
    @Published var busy=false
    @Published var fetching=false
    @Published var jit=false
    @Published var installed=false
    var task:Task<Void,Never>?
    init(){
        do {
            try files.createDirectory(at:models,withIntermediateDirectories:true)
            var url=models,values=URLResourceValues();values.isExcludedFromBackup=true;try url.setResourceValues(values)
        } catch {status=error.localizedDescription}
        refresh()
    }
    var path:URL {models.appendingPathComponent(entry.file)}
    func refresh(){installed=files.fileExists(atPath:path.path)}
    func select(_ value:Entry){guard !busy else{return};entry=value;turns=[];status="";refresh()}
    func remove(){ guard !busy else{return};do {try files.removeItem(at:path);turns=[];refresh()}catch{status=error.localizedDescription} }
    func fetch(){
        guard !busy else{return};busy=true;fetching=true;status="قراءة معلومات الملف…"
        let current=entry
        task=Task {
            defer{busy=false;fetching=false;refresh();task=nil}
            do {try await download(current){msg in Task{@MainActor in self.status=msg}};status="جاهز للعمل دون اتصال"}
            catch {status=Task.isCancelled ? "ألغي التنزيل" : error.localizedDescription}
        }
    }
    func stop(){ if fetching {task?.cancel()}else{PLStop()} }
    func send(){
        let q=prompt.trimmingCharacters(in:.whitespacesAndNewlines)
        guard installed,!busy,!q.isEmpty else{return}
        guard q.utf8.count<100_000 else {status="الرسالة طويلة جدا";return}
        guard Int64(PLAvailable()) > entry.estimate+350_000_000 else {
            status="هامش RAM المتاح منخفض لهذا النموذج. أغلق التطبيقات الأخرى أو اختر نموذجا أصغر.";return
        }
        PLResetStop();busy=true;status="تحميل النموذج إلى الذاكرة…";prompt=""
        turns.append(Message(role:"user",content:q))
        let history=turns.map{["role":$0.role,"content":$0.content]}
        let answer=Message(role:"assistant",content:"")
        turns.append(answer)
        let source=path.path,useJit=jit
        Task {
            let result=await Task.detached(priority:.userInitiated){() -> (String,String?) in
                var error:NSString?
                let reply=PLGenerate(source,history,useJit,{ draft in
                    Task { @MainActor in
                        if self.busy,self.turns.last?.id==answer.id {self.turns[self.turns.count-1].content=draft;self.status="جار التوليد على الجهاز…"}
                    }
                },&error)
                return (reply,error as String?)
            }.value
            if result.0.isEmpty {
                turns.removeLast(2);prompt=q
            } else {turns[turns.count-1].content=result.0}
            status=result.1 ?? (result.0.isEmpty ? "توقف التوليد دون نص" : "اكتمل الرد المحلي")
            busy=false
        }
    }
}
@main struct PadLocalApp:App {
    @StateObject var chat=Chat()
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    @State private var attached = PLDebugAttached()
    @State private var tunnelMessage = ""
    @State private var confirmDelete=false
    var body:some Scene {WindowGroup {NavigationStack {
        List {
            Section("النموذج المحلي"){
                Picker("النموذج",selection:Binding(get:{chat.entry.id},set:{id in if let e=Entry.choices.first(where:{$0.id==id}){chat.select(e)}})){
                    ForEach(Entry.choices){Text($0.name).tag($0.id)}
                }.disabled(chat.busy)
                Text("حجم التنزيل التقريبي "+sizeText(chat.entry.estimate))
                if chat.installed {Button("حذف الأوزان من الجهاز",role:.destructive){confirmDelete=true}.disabled(chat.busy)}
                else {Button("تنزيل النموذج"){chat.fetch()}.disabled(chat.busy)}
            }
            Section("موارد الجهاز"){
                TimelineView(.periodic(from:.now,by:2)){_ in
                    VStack(alignment:.leading){
                        Text("RAM المتاحة للتطبيق: "+sizeText(Int64(PLAvailable())))
                        Text("التخزين المتاح: "+sizeText(disk()))
                    }.monospacedDigit()
                }
                Button("فتح LocalDevVPN للاتصال") {
                    guard let url = URL(string: "localdevvpn://enable") else { return }
                    openURL(url) { opened in
                        tunnelMessage = opened ? "ارجع إلى PadLocal بعد الاتصال." : "تعذر فتح LocalDevVPN. تأكد من تثبيته."
                    }
                }.disabled(chat.busy)
                if !tunnelMessage.isEmpty { Text(tunnelMessage).font(.footnote) }
                Button("فحص اتصال المصحح") { attached = PLDebugAttached() }
                Text(attached ? "المصحح متصل" : "بانتظار اتصال المصحح").font(.footnote)
                Toggle("CPU JIT التجريبي لعقوبة التكرار",isOn:$chat.jit).disabled(chat.busy || (!attached && !chat.jit))
                Text("الاستدلال يستخدم Metal. يتطلب خيار JIT مصححا متصلا وإذن تنفيذ من النظام.").font(.footnote)
            }
            Section("المحادثة المحلية"){
                ForEach(chat.turns){m in VStack(alignment:.leading){Text(m.role=="user" ? "أنت" : chat.entry.name).font(.caption);Text(m.content).textSelection(.enabled)}}
                TextField("اكتب رسالتك",text:$chat.prompt,axis:.vertical).lineLimit(1...5)
                if chat.busy {Button("إيقاف"){chat.stop()}}
                else {Button("إرسال"){chat.send()}.disabled(!chat.installed || chat.prompt.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)}
                if !chat.turns.isEmpty {Button("محادثة جديدة"){chat.turns=[];chat.status=""}.disabled(chat.busy)}
                if !chat.status.isEmpty {Text(chat.status).font(.footnote)}
            }
        }.navigationTitle("PadLocal")
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { attached = PLDebugAttached() }
        }
        .confirmationDialog("حذف أوزان هذا النموذج؟",isPresented:$confirmDelete){Button("حذف",role:.destructive){chat.remove()}}
    }.environment(\.layoutDirection,.rightToLeft)}}
}
