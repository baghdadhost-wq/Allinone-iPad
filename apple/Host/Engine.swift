import Foundation
import FoundationModels

enum AnswerSource: String, CaseIterable, Identifiable {
    case omni = "OmniRoute", free = "FreeLLMAPI", local = "Apple Intelligence", custom = "OpenAI-compatible"
    var id: Self { self }
    var defaultBase: String {
        switch self {
        case .omni: return "http://127.0.0.1:20128/v1"
        case .free: return "http://127.0.0.1:3001/v1"
        case .local, .custom: return ""
        }
    }
    var usesMessages: Bool { self == .omni || self == .free }
}

struct GatewayProfile {
    var base: String
    var model: String
    var key: String
}

struct Engine {
    let source: AnswerSource
    let profile: GatewayProfile

    func makeRequest(_ question: String) throws -> URLRequest {
        let raw = profile.base.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let components = URLComponents(string: raw), let host = components.host,
              let url = components.url, components.query == nil, components.fragment == nil,
              components.user == nil, components.password == nil,
              components.scheme == "https" || (components.scheme == "http" && ["localhost","127.0.0.1","::1","[::1]"].contains(host)),
              !profile.model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw LinkError.message("تحقق من عنوان البوابة واسم النموذج. استخدم HTTPS للبوابة البعيدة.")
        }
        let api = url.lastPathComponent == "v1" ? url : url.appendingPathComponent("v1")
        let endpoint = source.usesMessages ? "messages" : "chat/completions"
        var request = URLRequest(url: api.appendingPathComponent(endpoint), timeoutInterval: 100)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if source.usesMessages { request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version") }
        if !profile.key.isEmpty {
            request.setValue("Bearer " + profile.key, forHTTPHeaderField: "Authorization")
        }
        var payload: [String:Any] = ["model": profile.model, "messages":[["role":"user","content":question]]]
        if source.usesMessages { payload["max_tokens"] = 4096 }
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        return request
    }

    func decode(_ data: Data) throws -> String {
        struct Messages: Decodable {
            struct Block: Decodable { let type: String; let text: String? }
            let content: [Block]
        }
        struct Completion: Decodable {
            struct Choice: Decodable { struct Message: Decodable { let content: String }; let message: Message }
            let choices: [Choice]
        }
        if source.usesMessages {
            let blocks = try JSONDecoder().decode(Messages.self, from: data).content
            let text = blocks.filter { $0.type == "text" }.compactMap { $0.text }.joined(separator:"\n")
            if !text.isEmpty { return text }
        } else if let text = try JSONDecoder().decode(Completion.self, from: data).choices.first?.message.content, !text.isEmpty { return text }
        throw LinkError.message("لم ترجع البوابة جوابا نصيا")
    }

    func answer(_ question: String) async throws -> String {
        if source == .local {
            if #available(iOS 26.0, macOS 26.0, *) {
                guard SystemLanguageModel.default.availability == .available else {
                    throw LinkError.message("نموذج Apple المحلي غير جاهز. تحقق من إعداد Apple Intelligence.")
                }
                return try await LanguageModelSession().respond(to: question).content
            }
            throw LinkError.message("النموذج المحلي يحتاج iPadOS 26 أو أحدث")
        }
        let request = try makeRequest(question)
        let session = URLSession(configuration: .ephemeral, delegate: NoRedirect(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data,response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw LinkError.message("رفضت البوابة الطلب (HTTP \(status)). تحقق من المفتاح والنموذج في البوابة.")
        }
        return try decode(data)
    }
}
private final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
