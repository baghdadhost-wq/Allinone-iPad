import SwiftUI
import Network
import CryptoKit
import Darwin

private func wifiAddress() -> String? {
    var first: UnsafeMutablePointer<ifaddrs>?
    guard getifaddrs(&first) == 0, let first else { return nil }
    defer { freeifaddrs(first) }
    for item in sequence(first: first, next: { $0.pointee.ifa_next }) {
        let entry = item.pointee
        guard String(cString: entry.ifa_name) == "en0", let address = entry.ifa_addr,
              address.pointee.sa_family == UInt8(AF_INET) else { continue }
        var buffer = [CChar](repeating: 0, count: Int(NI_MAXHOST))
        if getnameinfo(address, socklen_t(address.pointee.sa_len), &buffer, socklen_t(buffer.count), nil, 0, NI_NUMERICHOST) == 0 {
            return String(cString: buffer)
        }
    }
    return nil
}

@MainActor final class Host: ObservableObject {
    @Published var state = "بدء التشغيل…"
    @Published var address = ""
    @Published var code = ""
    @Published var busy = false
    @Published var source = AnswerSource.omni
    @Published var profiles: [AnswerSource:GatewayProfile] = Dictionary(uniqueKeysWithValues: AnswerSource.allCases.map {
        ($0, GatewayProfile(base: $0.defaultBase, model: $0 == .custom ? "" : "auto", key: ""))
    })
    var profile: GatewayProfile {
        get { profiles[source] ?? GatewayProfile(base: source.defaultBase, model: "auto", key: "") }
        set { profiles[source] = newValue }
    }
    private var listener: NWListener?
    private var monitor: NWPathMonitor?
    private var peers: [ObjectIdentifier:NWConnection] = [:]

    func start() {
        guard listener == nil else { return }
        code = SymmetricKey(size: .bits256).withUnsafeBytes { Data($0).base64EncodedString() }
        do {
            let next = try NWListener(using: LocalLink.parameters(code: code), on: NWEndpoint.Port(rawValue: LocalLink.port)!)
            listener = next
            next.newConnectionHandler = { [weak self] peer in
                Task { @MainActor in
                    guard let self, self.peers.count < 12 else { peer.cancel(); return }
                    await self.serve(peer)
                }
            }
            next.stateUpdateHandler = { [weak self, weak next] status in
                Task { @MainActor in
                    guard let self, self.listener === next else { return }
                    switch status {
                    case .ready: self.state = "المضيف يعمل"; self.refreshAddress()
                    case .failed(let error): self.stop(); self.state = error.localizedDescription
                    case .waiting(let error): self.state = error.localizedDescription
                    default: break
                    }
                }
            }
            let path = NWPathMonitor()
            path.pathUpdateHandler = { [weak self] _ in Task { @MainActor in self?.refreshAddress() } }
            path.start(queue: DispatchQueue.global()); monitor = path
            next.start(queue: .main)
        } catch { state = error.localizedDescription }
    }

    func refreshAddress() { address = wifiAddress().map { "\($0):\(LocalLink.port)" } ?? "" }

    func stop() {
        listener?.cancel(); listener = nil
        monitor?.cancel(); monitor = nil
        peers.values.forEach { $0.cancel() }
        address = ""; code = ""; state = "المضيف متوقف"
    }

    func ask(_ prompt: String) async throws -> String {
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.utf8.count <= 60_000 else { throw LinkError.message("تحقق من طول السؤال") }
        guard !busy else { throw LinkError.message("المضيف يجيب عن سؤال آخر، حاول بعد قليل") }
        busy = true
        defer { busy = false }
        return try await Engine(source: source, profile: profile).answer(text)
    }

    private func serve(_ peer: NWConnection) async {
        let id = ObjectIdentifier(peer)
        peers[id] = peer
        peer.start(queue: .global(qos: .userInitiated))
        let deadline = DispatchWorkItem { peer.cancel() }
        DispatchQueue.global().asyncAfter(deadline: .now() + 145, execute: deadline)
        defer { deadline.cancel(); peer.cancel(); peers[id] = nil }
        do {
            let data = try await LocalLink.read(peer, limit: 65536)
            let payload = try JSONDecoder().decode([String:String].self, from: data)
            guard let question = payload["question"] else { throw LinkError.message("السؤال فارغ") }
            let reply = try await ask(question)
            try await LocalLink.write(["answer":reply], to: peer)
        } catch { try? await LocalLink.write(["error":error.localizedDescription], to: peer) }
    }
}

struct Dashboard: View {
    @ObservedObject var host: Host
    @State private var question = ""
    @State private var answer = ""
    @Environment(\.scenePhase) private var phase

    var body: some View {
        NavigationStack {
            Form {
                Section("الاتصال من جهاز آخر") {
                    Text(host.state)
                    if !host.code.isEmpty {
                        LabeledContent("عنوان Wi-Fi", value: host.address.isEmpty ? "اتصل بشبكة Wi-Fi" : host.address)
                        Text("رمز الاقتران")
                        Text(host.code).font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                        Button("نسخ رمز الاقتران") { UIPasteboard.general.setItems([["public.utf8-plain-text":host.code]], options: [.localOnly:true,.expirationDate:Date().addingTimeInterval(300)]) }
                    }
                    Button(host.code.isEmpty ? "بدء المضيف" : "إيقاف المضيف") {
                        if host.code.isEmpty { host.start() } else { host.stop() }
                    }
                }
                Section("مصدر الإجابة") {
                    Picker("المصدر", selection: $host.source) {
                        ForEach(AnswerSource.allCases) { source in Text(source.rawValue).tag(source) }
                    }
                    if host.source != .local {
                        TextField("Base URL", text: $host.profile.base)
                        TextField("Model ID", text: $host.profile.model)
                        SecureField("API Key", text: $host.profile.key)
                    }
                }.textInputAutocapitalization(.never).autocorrectionDisabled()
                Section("اسأل من الآيباد") {
                    TextField("سؤالك", text: $question, axis: .vertical)
                    Button(host.busy ? "بانتظار الجواب…" : "إرسال") {
                        Task { do { answer = try await host.ask(question) } catch { answer = error.localizedDescription } }
                    }.disabled(host.busy || question.isEmpty)
                }
                if !answer.isEmpty { Section("النتيجة") { Text(answer).textSelection(.enabled) } }
            }.navigationTitle("Allinone Host")
        }.environment(\.layoutDirection,.rightToLeft)

        .onChange(of: phase) { phase in if phase == .active { host.refreshAddress() } }
    }
}
