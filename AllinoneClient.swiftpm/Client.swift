import SwiftUI
import CryptoKit
import Security
import Network

final class HostTrust: NSObject, URLSessionDelegate, URLSessionTaskDelegate {
    let fingerprint: String
    init(_ fingerprint: String) { self.fingerprint = fingerprint }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate],
              let leaf = chain.first else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        let der = SecCertificateCopyData(leaf) as Data
        let digest = SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
        if digest == fingerprint {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

struct Reply: Decodable { let answer: String?; let error: String? }

struct Chat: View {
    @State private var native = true
    @State private var mode = AssistantMode.standard
    @State private var sessionID = UUID().uuidString
    @State private var address = ""
    @State private var fingerprint = ""
    @State private var token = ""
    @State private var question = ""
    @State private var output = ""
    @State private var waiting = false

    var body: some View {
        NavigationStack {
            Form {
                Section("الاتصال بالمضيف") {
                    Picker("المضيف", selection: $native) {
                        Text("تطبيق الآيباد").tag(true)
                        Text("مضيف HTTPS").tag(false)
                    }
                    TextField("عنوان IP والمنفذ", text: $address)
                    SecureField("رمز الاتصال", text: $token)
                    if !native { TextField("بصمة SHA-256 الظاهرة على المضيف", text: $fingerprint) }
                }.textInputAutocapitalization(.never).autocorrectionDisabled()
                Section("سؤالك") {
                    if native { Picker("طريقة الإجابة",selection:$mode) {
                        Text("برمجة").tag(AssistantMode.standard)
                        Text("سؤال سريع").tag(AssistantMode.quick)
                        Text("برمجة خفيفة").tag(AssistantMode.light)
                    }.pickerStyle(.segmented) }
                    if native { Button("محادثة جديدة") { sessionID = UUID().uuidString; question = ""; output = "" }.disabled(waiting) }
                    TextField("اكتب سؤالك", text: $question, axis: .vertical).lineLimit(3...10)
                    Button(waiting ? "بانتظار الجواب…" : "إرسال") { Task { await send() } }
                        .disabled(waiting || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                if !output.isEmpty { Section("النتيجة") { Text(output).textSelection(.enabled) } }
            }.navigationTitle("Allinone")
        }.environment(\.layoutDirection, .rightToLeft)
    }

    @MainActor func send() async {
        let raw = address.trimmingCharacters(in: .whitespacesAndNewlines)
        if native {
            waiting = true
            output = ""
            defer { waiting = false }
            do {
                output = try await LocalLink.ask(address: raw, code: token.trimmingCharacters(in: .whitespacesAndNewlines), question: question, sessionID: sessionID, mode: mode)
            } catch { output = error.localizedDescription }
            return
        }
        guard var url = URLComponents(string: raw.contains("://") ? raw : "https://" + raw),
              url.scheme == "https", let host = url.host, IPv4Address(host) != nil,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              (url.path.isEmpty || url.path == "/") else {
            output = "أدخل عنوان IPv4 والمنفذ الظاهرين على المضيف"; return
        }
        url.port = url.port ?? 8743
        url.path = "/ask"
        let pin = fingerprint.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard pin.count == 64, pin.allSatisfy({ $0.isHexDigit }), !token.isEmpty, let endpoint = url.url else {
            output = "أدخل رمز الاتصال وبصمة المضيف الكاملة"; return
        }
        waiting = true
        output = ""
        let session = URLSession(configuration: .ephemeral, delegate: HostTrust(pin), delegateQueue: nil)
        defer { waiting = false; session.finishTasksAndInvalidate() }
        do {
            var request = URLRequest(url: endpoint, timeoutInterval: 255)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue("Bearer " + token.trimmingCharacters(in: .whitespacesAndNewlines), forHTTPHeaderField: "Authorization")
            request.httpBody = try JSONEncoder().encode(["question": question])
            let (data, response) = try await session.data(for: request)
            let reply = try JSONDecoder().decode(Reply.self, from: data)
            output = (response as? HTTPURLResponse)?.statusCode == 200 ? reply.answer ?? "جواب فارغ" : reply.error ?? "خطأ من المضيف"
        } catch { output = "تعذر الاتصال. تحقق من العنوان والبصمة وحالة المضيف. " + error.localizedDescription }
    }
}

#if !UNIVERSAL_APP
@main struct AllinoneClientApp: App { var body: some Scene { WindowGroup { Chat() } } }
#endif
