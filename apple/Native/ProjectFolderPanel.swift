import SwiftUI
import UniformTypeIdentifiers

/// Local projects can be selected even when the Files provider is unavailable.
struct ProjectFolderPanel: View {
    @ObservedObject var studio: Studio
    let browseExternal: () -> Void
    @Environment(\.dismiss) private var dismiss
    private let documents: URL
    @State private var current: URL
    @State private var folders: [URL] = []
    @State private var naming = false
    @State private var name = ""
    @State private var problem = ""

    init(studio: Studio,browseExternal:@escaping () -> Void) {
        self.browseExternal = browseExternal
        self.studio = studio
        let root = FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].resolvingSymlinksInPath().standardizedFileURL
        documents = root
        let active = studio.files.root.resolvingSymlinksInPath().standardizedFileURL
        _current = State(initialValue: active.path.hasPrefix(root.path + "/") ? active : root)
    }

    var body: some View {
        NavigationStack {
            List {
                Section("الموقع الحالي") {
                    Text(current.path == documents.path ? "Allinone" : current.lastPathComponent)
                    Button("استخدام هذا المجلد") { select(current) }
                        .accessibilityIdentifier("confirmProjectFolder")
                }
                Section("مجلدات Allinone على هذا الجهاز") {
                    if current.path != documents.path {
                        Button("المجلد الأعلى") { current = current.deletingLastPathComponent() }
                    }
                    ForEach(folders,id:\.self) { folder in
                        Button { current = folder } label: { Label(folder.lastPathComponent,systemImage:"folder") }
                    }
                    Button("إنشاء مجلد جديد") { name = ""; naming = true }
                        .accessibilityIdentifier("createProjectFolder")
                }
                Button("اختيار موقع آخر من الملفات",action:browseExternal)
                if !problem.isEmpty { Text(problem).foregroundStyle(.red) }
            }
            .navigationTitle("مجلد المشروع")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement:.cancellationAction) { Button("إلغاء") { dismiss() } } }
            .onAppear { listFolders() }
            .onChange(of:current) { _ in listFolders() }
            .alert("مجلد جديد",isPresented:$naming) {
                TextField("اسم المجلد",text:$name)
                Button("إنشاء") { create() }
                Button("إلغاء",role:.cancel) {}
            }

        }
    }

    private func listFolders() {
        do {
            let keys: Set<URLResourceKey> = [.isDirectoryKey,.isSymbolicLinkKey]
            folders = try FileManager.default.contentsOfDirectory(at:current,includingPropertiesForKeys:Array(keys),options:.skipsHiddenFiles)
                .filter { url in
                    let values = try url.resourceValues(forKeys:keys)
                    return values.isDirectory == true && values.isSymbolicLink != true
                }.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
            problem = ""
        } catch { folders = []; problem = error.localizedDescription }
    }

    private func create() {
        let component = name.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !component.isEmpty, !component.hasPrefix("."), !component.contains("/"),
              !component.unicodeScalars.contains(where:CharacterSet.controlCharacters.contains) else {
            problem = "أدخل اسما صالحا للمجلد"; return
        }
        do {
            let url = current.appendingPathComponent(component,isDirectory:true)
            try FileManager.default.createDirectory(at:url,withIntermediateDirectories:false)
            current = url
        } catch { problem = error.localizedDescription }
    }

    private func select(_ url: URL) {
        do { try studio.open(url); dismiss() }
        catch { problem = error.localizedDescription }
    }
}

struct ExternalProjectPicker: UIViewControllerRepresentable {
    let start: URL
    let finish: (URL?) -> Void

    func makeCoordinator() -> Delegate { Delegate(finish) }
    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes:[.folder],asCopy:false)
        picker.directoryURL = start
        picker.delegate = context.coordinator
        return picker
    }
    func updateUIViewController(_ picker: UIDocumentPickerViewController, context: Context) {}

    final class Delegate: NSObject, UIDocumentPickerDelegate {
        let finish: (URL?) -> Void
        init(_ finish: @escaping (URL?) -> Void) { self.finish = finish }
        func documentPicker(_ controller: UIDocumentPickerViewController,didPickDocumentsAt urls:[URL]) { finish(urls.first) }
        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) { finish(nil) }
    }
}
