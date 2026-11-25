import Foundation
import FoundationModels
import Security

enum RouteMode: String, Codable, CaseIterable { case priority, freePool }

enum APIStyle: String, Codable, CaseIterable { case openAI, anthropic, gateway, onDevice }

struct Provider: Identifiable, Codable, Equatable {
    var id = UUID()
    var name: String
    var base: String
    var model: String
    var style: APIStyle
    var free: Bool
    var enabled = true
    static let apple = Provider(name: "Apple Intelligence", base: "", model: "on-device", style: .onDevice, free: true)
}

enum Credentials {
    private static func query(_ id: UUID) -> [String:Any] {
        [kSecClass as String:kSecClassGenericPassword, kSecAttrService as String:"app.baghdadhost.allinone.providers",
         kSecAttrAccount as String:id.uuidString]
    }
    static func key(_ id: UUID) throws -> String {
        var q = query(id); q[kSecReturnData as String] = true
        var result: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &result)
        if status == errSecItemNotFound { return "" }
        guard status == errSecSuccess, let data = result as? Data, let value = String(data: data, encoding: .utf8) else {
            throw LinkError.message("تعذرت قراءة مفتاح المزود من Keychain")
        }
        return value
    }
    static func save(_ value: String, _ id: UUID) throws {
        let q = query(id)
        if value.isEmpty {
            let code = SecItemDelete(q as CFDictionary)
            guard code == errSecItemNotFound || code == errSecSuccess else { throw LinkError.message("تعذر حذف مفتاح المزود") }
            return
        }
        let data = Data(value.utf8)
        var item = q
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        var status = SecItemAdd(item as CFDictionary, nil)
        if status == errSecDuplicateItem {
            status = SecItemUpdate(q as CFDictionary, [kSecValueData as String:data] as CFDictionary)
        }
        guard status == errSecSuccess else { throw LinkError.message("تعذر حفظ مفتاح المزود") }
    }
}

struct Turn: Codable, Identifiable {
    var id = UUID()
    let role: String
    let content: String
}

struct UpstreamFailure: Error, LocalizedError {
    let reason: String
    let delay: TimeInterval
    var errorDescription: String? { reason }
}

private final class KeepOrigin: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

enum NativeAPI {
    static func endpoint(_ provider: Provider) throws -> URL {
        let s = provider.base.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let c = URLComponents(string: s), let host = c.host, let u = c.url, !host.isEmpty,
              c.user == nil, c.password == nil, c.query == nil, c.fragment == nil,
              c.scheme == "https" || (c.scheme == "http" && ["localhost","127.0.0.1","[::1]"].contains(host)),
              !provider.model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw LinkError.message("أدخل عنوان API صالحا واسم النموذج")
        }
        return u.appendingPathComponent((provider.style == .anthropic || provider.style == .gateway) ? "messages" : "chat/completions")
    }

    static func request(_ provider: Provider, key: String, system: String, turns: [Turn]) throws -> URLRequest {
        var request = URLRequest(url: try endpoint(provider), timeoutInterval: 55)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var messages = turns.map { ["role":$0.role, "content":$0.content] }
        var body: [String:Any] = ["model":provider.model]
        if (provider.style == .anthropic || provider.style == .gateway) {
            body["system"] = system; body["max_tokens"] = 4096
            request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
            if !key.isEmpty {
                if provider.style == .gateway { request.setValue("Bearer " + key, forHTTPHeaderField:"Authorization") }
                else { request.setValue(key, forHTTPHeaderField:"x-api-key") }
            }
        } else {
            messages.insert(["role":"system","content":system], at: 0)
            if !key.isEmpty { request.setValue("Bearer " + key, forHTTPHeaderField:"Authorization") }
        }
        body["messages"] = messages
        request.httpBody = try JSONSerialization.data(withJSONObject:body)
        return request
    }

    static func reply(_ provider: Provider, system: String, turns: [Turn]) async throws -> String {
        if provider.style == .onDevice {
            if #available(iOS 26, macOS 26, *) {
                guard SystemLanguageModel.default.availability == .available else {
                    throw LinkError.message("نموذج Apple غير متاح على الجهاز بهذه الإعدادات")
                }
                let prompt = turns.map { $0.role + ": " + $0.content }.joined(separator:"\n")
                return try await LanguageModelSession(instructions: system).respond(to: prompt).content
            }
            throw LinkError.message("يتطلب النموذج المحلي iPadOS 26 أو أحدث")
        }
        let request = try request(provider, key: Credentials.key(provider.id), system: system, turns: turns)
        let session = URLSession(configuration:.ephemeral, delegate:KeepOrigin(), delegateQueue:nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for:request)
        guard let http = response as? HTTPURLResponse else { throw LinkError.message("تعذرت قراءة استجابة المزود") }
        guard (200..<300).contains(http.statusCode) else {
            let retry = TimeInterval(http.value(forHTTPHeaderField:"Retry-After") ?? "") ?? 30
            throw UpstreamFailure(reason:"HTTP \(http.statusCode)", delay:http.statusCode == 429 ? max(1,min(3600,retry)) : 0)
        }
        guard let payload = try JSONSerialization.jsonObject(with:data) as? [String:Any] else { throw LinkError.message("استجابة غير صالحة") }
        if (provider.style == .anthropic || provider.style == .gateway), let blocks = payload["content"] as? [[String:Any]] {
            let s = blocks.filter { $0["type"] as? String == "text" }.compactMap { $0["text"] as? String }.joined(separator:"\n")
            if !s.isEmpty { return s }
        }
        if let choices = payload["choices"] as? [[String:Any]], let msg = choices.first?["message"] as? [String:Any],
           let s = msg["content"] as? String, !s.isEmpty { return s }
        throw LinkError.message("لم يرجع المزود نصا")
    }
}

@MainActor final class NativeRouter {
    private var cooldown = [UUID:Date]()
    private var lastFree: UUID?
    typealias Generate = (Provider,String,[Turn]) async throws -> String
    func respond(providers: [Provider], mode: RouteMode, system: String, turns: [Turn],
                 generate: Generate = NativeAPI.reply) async throws -> (String,String) {
        var candidates = providers.filter { $0.enabled && (mode != .freePool || $0.free) && (cooldown[$0.id] ?? .distantPast) <= Date() }
        if mode == .freePool, let lastFree, let i = candidates.firstIndex(where: { $0.id == lastFree }) {
            candidates = Array(candidates.dropFirst(i+1)) + Array(candidates.prefix(i+1))
        }
        guard !candidates.isEmpty else { throw LinkError.message("لا يوجد مزود جاهز لهذا المسار. راجع المزودين وحدود الاستخدام.") }
        var failures = [String]()
        for p in candidates {
            try Task.checkCancellation()
            do {
                let text = try await generate(p,system,turns)
                if mode == .freePool { lastFree = p.id }
                return (text,p.name + " · " + p.model)
            } catch {
                try Task.checkCancellation()
                if let e = error as? UpstreamFailure, e.delay > 0 { cooldown[p.id] = Date().addingTimeInterval(e.delay) }
                failures.append(p.name + ": " + error.localizedDescription)
            }
        }
        throw LinkError.message(failures.joined(separator:"\n"))
    }
}
