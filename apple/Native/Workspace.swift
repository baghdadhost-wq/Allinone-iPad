import Foundation

struct EditProposal: Identifiable {
    let id = UUID()
    let path: String
    let original: Data?
    let replacement: String
    let reason: String
    let root: URL
}

struct ProjectFiles {
    let root: URL
    static let maxBytes = 96 * 1024
    private let ignored: Set<String> = ["node_modules","DerivedData","Pods","build","runtime"]

    func url(_ relative: String, allowRoot: Bool = false) throws -> URL {
        if relative.isEmpty && allowRoot { return root }
        let parts = relative.components(separatedBy:"/")
        guard relative.utf8.count < 1024, parts.allSatisfy({ !$0.isEmpty && !$0.hasPrefix(".") && !ignored.contains($0) &&
            !$0.contains("\\") && !$0.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) }) else {
            throw LinkError.message("مسار خارج ملفات المشروع المسموح بها")
        }
        var target = root
        for part in parts {
            target = target.appendingPathComponent(part)
            if (try? FileManager.default.destinationOfSymbolicLink(atPath:target.path)) != nil {
                throw LinkError.message("مسار يتضمن رابطا رمزيا")
            }
        }
        return target
    }

    func list(_ relative: String) throws -> String {
        let dir = try url(relative, allowRoot:true)
        return try FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys:[.isDirectoryKey,.isSymbolicLinkKey], options:.skipsHiddenFiles)
            .filter { !ignored.contains($0.lastPathComponent) }.sorted { $0.lastPathComponent < $1.lastPathComponent }.prefix(150)
            .compactMap { child in
                let v = try child.resourceValues(forKeys:[.isDirectoryKey,.isSymbolicLinkKey])
                return v.isSymbolicLink == true ? nil : child.lastPathComponent + (v.isDirectory == true ? "/" : "")
            }.joined(separator:"\n")
    }
    func read(_ path: String) throws -> Data {
        let file = try url(path)
        let v = try file.resourceValues(forKeys:[.fileSizeKey,.isRegularFileKey])
        guard v.isRegularFile == true, (v.fileSize ?? Int.max) <= Self.maxBytes else { throw LinkError.message("الملف كبير أو غير نصي") }
        let h = try FileHandle(forReadingFrom:file)
        defer { try? h.close() }
        let data = try h.read(upToCount:Self.maxBytes + 1) ?? Data()
        guard data.count <= Self.maxBytes, !data.contains(0), String(data:data,encoding:.utf8) != nil else { throw LinkError.message("يتطلب ملف UTF-8 صغيرا") }
        return data
    }

    func search(_ needle: String) throws -> String {
        guard !needle.isEmpty else { throw LinkError.message("أدخل عبارة بحث") }
        var results = [String](), visited = 0, consumed = 0
        let keys: [URLResourceKey] = [.isDirectoryKey,.isSymbolicLinkKey,.isRegularFileKey,.fileSizeKey]
        let searchRoot = root.resolvingSymlinksInPath().standardizedFileURL
        guard let walker = FileManager.default.enumerator(at:searchRoot,includingPropertiesForKeys:keys,options:.skipsHiddenFiles) else { return "" }
        while let file = walker.nextObject() as? URL {
            visited += 1
            if visited > 1200 || results.count >= 30 || consumed > 3 * 1024 * 1024 { break }
            let v = try file.resourceValues(forKeys:Set(keys))
            if v.isSymbolicLink == true || ignored.contains(file.lastPathComponent) { walker.skipDescendants(); continue }
            guard v.isRegularFile == true, let size = v.fileSize, size <= Self.maxBytes else { continue }
            consumed += size
            let components = file.resolvingSymlinksInPath().standardizedFileURL.pathComponents
            guard components.starts(with:searchRoot.pathComponents) else { continue }
            let relative = components.dropFirst(searchRoot.pathComponents.count).joined(separator:"/")
            guard let data = try? read(relative), let content = String(data:data,encoding:.utf8) else { continue }
            for (index,line) in content.components(separatedBy:.newlines).enumerated() where line.localizedCaseInsensitiveContains(needle) {
                results.append("\(relative):\(index+1) " + String(line.prefix(180)))
                if results.count == 30 { break }
            }
        }
        return results.isEmpty ? "No matches in the scanned files." : results.joined(separator:"\n")
    }

    func propose(path: String, replacement: String, reason: String, previouslyRead: [String:Data]) throws -> EditProposal {
        let file = try url(path)
        guard replacement.utf8.count <= Self.maxBytes else { throw LinkError.message("التعديل أطول من الحد المسموح") }
        var old: Data?
        if FileManager.default.fileExists(atPath:file.path) {
            guard let snapshot = previouslyRead[path], try read(path) == snapshot else { throw LinkError.message("اقرأ النسخة الحالية من الملف أولا") }
            old = snapshot
        }
        return EditProposal(path:path,original:old,replacement:replacement,reason:reason,root:root)
    }

    func apply(_ change: EditProposal) throws {
        guard root == change.root else { throw LinkError.message("تغير مجلد المشروع") }
        let file = try url(change.path)
        var outer: NSError?
        var inner: Error?
        try FileManager.default.createDirectory(at:file.deletingLastPathComponent(),withIntermediateDirectories:true)
        NSFileCoordinator().coordinate(writingItemAt:file, options:[], error:&outer) { destination in
            do {
                _ = try url(change.path)
                let exists = FileManager.default.fileExists(atPath:destination.path)
                if let original = change.original {
                    guard exists, try read(change.path) == original else { throw LinkError.message("تغير الملف منذ المعاينة؛ اطلب تعديلا جديدا") }
                } else if exists { throw LinkError.message("تم إنشاء الملف منذ المعاينة") }
                let data = Data(change.replacement.utf8)
                if exists {
                    let perms = try FileManager.default.attributesOfItem(atPath:destination.path)[.posixPermissions]
                    try data.write(to:destination, options:.atomic)
                    if let perms { try FileManager.default.setAttributes([.posixPermissions:perms], ofItemAtPath:destination.path) }
                } else { try data.write(to:destination, options:.withoutOverwriting) }
            } catch { inner = error }
        }
        if let inner { throw inner }; if let outer { throw outer }
    }
}
