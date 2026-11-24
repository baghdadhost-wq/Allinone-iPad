import Foundation
import FoundationModels

struct Engine {
    let local: Bool
    let base: String
    let model: String
    let key: String

    func answer(_ question: String) async throws -> String {
        if local {
            if #available(iOS 26.0, *) {
                guard SystemLanguageModel.default.availability == .available else {
                    throw LinkError.message("نموذج Apple المحلي غير جاهز. تحقق من Apple Intelligence أو اختر بوابة نماذج.")
                }
                return try await LanguageModelSession().respond(to: question).content
            }
            throw LinkError.message("النموذج المحلي يحتاج iPadOS 26 أو أحدث")
        }
        guard let root = URL(string: base), let host = root.host, root.query == nil, root.fragment == nil,
              root.user == nil, root.password == nil,
              root.scheme == "https" || (root.scheme == "http" && ["localhost","127.0.0.1","::1","[::1]"].contains(host)),
              !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw LinkError.message("تحقق من رابط البوابة واسم النموذج. استخدم HTTPS للبوابة البعيدة.")
        }
        var request = URLRequest(url: root.appendingPathComponent("chat/completions"), timeoutInterval: 100)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !key.isEmpty { request.setValue("Bearer " + key, forHTTPHeaderField: "Authorization") }
        request.httpBody = try JSONSerialization.data(withJSONObject: ["model":model,"messages":[["role":"user","content":question]]])
        let session = URLSession(configuration: .ephemeral, delegate: NoRedirect(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data,response) = try await session.data(for: request)
        guard let status = (response as? HTTPURLResponse)?.statusCode, (200..<300).contains(status) else {
            throw LinkError.message("تعذر الوصول إلى النموذج. تحقق من عنوان البوابة والمفتاح واسم النموذج.")
        }
        struct Completion: Decodable {
            struct Choice: Decodable { struct Message: Decodable { let content: String }; let message: Message }
            let choices: [Choice]
        }
        guard let text = try JSONDecoder().decode(Completion.self, from: data).choices.first?.message.content else {
            throw LinkError.message("لم ترجع البوابة جوابا")
        }
        return text
    }
}
private final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
