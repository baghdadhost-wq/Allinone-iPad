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
    let studio = Studio()
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

    private func serve(_ peer: NWConnection) async {
        let id = ObjectIdentifier(peer)
        peers[id] = peer
        peer.start(queue: .global(qos: .userInitiated))
        let deadline = DispatchWorkItem { peer.cancel() }
        DispatchQueue.global().asyncAfter(deadline: .now() + 305, execute: deadline)
        defer { deadline.cancel(); peer.cancel(); peers[id] = nil }
        do {
            let data = try await LocalLink.read(peer, limit: LocalLink.limit)
            let payload = try JSONDecoder().decode([String:String].self, from: data)
            guard let question = payload["question"] else { throw LinkError.message("السؤال فارغ") }
            let thread = payload["session"].flatMap(UUID.init(uuidString:))?.uuidString ?? UUID().uuidString
            let reply = try await studio.send(question,thread:thread,assistantMode:payload["mode"].flatMap(AssistantMode.init(rawValue:)) ?? .standard)
            try await LocalLink.write(["answer":reply], to: peer)
        } catch { try? await LocalLink.write(["error":error.localizedDescription], to: peer) }
    }
}

