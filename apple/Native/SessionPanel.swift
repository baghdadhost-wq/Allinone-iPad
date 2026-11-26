import SwiftUI

struct SessionPanel: View {
    @ObservedObject var studio: Studio
    @Environment(\.dismiss) var dismiss
    @AppStorage("display.brand") private var brand = "smarter"
    @State private var goal = ""
    @State private var file = ""
    @State private var outgoing = ""
    @State private var incoming = ""
    @State private var errorText = ""
    @State private var shortReport = false
    @State private var filter = ""
    private var report: String {
        (shortReport ? Array((studio.book.events ?? []).suffix(10)) : (studio.book.events ?? [])).map { $0.when.ISO8601Format() + "  " + $0.detail }.joined(separator:"\n")
    }
    var body: some View {
        NavigationStack {
            Form {
                if let job = studio.book.checkpoint, !studio.busy, studio.pending == nil {
                    Section("طلب غير مكتمل") {
                        Text(job.prompt)
                        Button("استئناف") {
                            studio.selectChat(job.thread)
                            dismiss()
                            Task { do { _ = try await studio.send(job.prompt,thread:job.thread,task:job.task,assistantMode:job.mode ?? .standard) } catch { studio.message = error.localizedDescription } }
                        }
                        Button("إلغاء الاستئناف") { studio.clearCheckpoint() }
                    }
                }
                Section("محادثات المشروع") {
                    TextField("بحث في المحادثات",text:$filter)
                    ForEach(studio.book.threads.keys.sorted(),id:\.self) { key in
                        let turns = studio.book.threads[key] ?? []
                        if filter.isEmpty || turns.contains(where:{ $0.content.localizedCaseInsensitiveContains(filter) }) {
                            Button(String((turns.first?.content ?? key).prefix(100))) { studio.selectChat(key); dismiss() }.disabled(studio.busy || studio.pending != nil)
                        }
                    }
                    ShareLink(item:(studio.book.threads[studio.hostThread] ?? []).map { $0.role + "\n" + $0.content }.joined(separator:"\n\n")) { Text("تصدير المحادثة") }
                }
                Section("التبادل اليدوي مع الحساب الذي تختاره") {
                    TextField("المطلوب",text:$goal,axis:.vertical)
                    TextField("مسار ملف اختياري لإرفاقه",text:$file).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Button("تحضير الطلب ومعاينته") {
                        do { outgoing = try ManualExchange.handover(prompt:goal,selected:file,studioNotes:studio.book.notes,turns:studio.book.threads[studio.hostThread] ?? [],files:studio.files); errorText = "" }
                        catch { errorText = error.localizedDescription }
                    }
                    if !outgoing.isEmpty {
                        DisclosureGroup("معاينة النص قبل مشاركته") { Text(outgoing).textSelection(.enabled) }
                        ShareLink(item:outgoing) { Text("مشاركة الطلب") }
                        Link("فتح موقع الحساب",destination:URL(string:"https://claude.ai/")!)
                    }
                    TextField("الصق الجواب أو تعديل JSON",text:$incoming,axis:.vertical)
                    Button("استيراد ومراجعة") {
                        do { try studio.importReply(incoming); dismiss() } catch { errorText = error.localizedDescription }
                    }.disabled(studio.busy || studio.pending != nil)
                }
                Section("سجل التنفيذ") {
                    Toggle("تقرير مختصر لآخر عشر خطوات",isOn:$shortReport)
                    DisclosureGroup("عرض الأوقات والخطوات") { Text(report).font(.caption).textSelection(.enabled) }
                    ShareLink(item:report) { Text("مشاركة التقرير") }
                    Button("تراجع عن آخر تعديل") { do { try studio.undo(); errorText = "تم التراجع" } catch { errorText = error.localizedDescription } }
                }
                TextField("اسم عرض المساعد",text:$brand)
                if !errorText.isEmpty { Text(errorText).foregroundStyle(.secondary) }
            }.navigationTitle("جلسات المشروع").toolbar { Button("تم") { dismiss() } }
        }
    }
}
