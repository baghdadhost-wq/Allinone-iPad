import Foundation
import Network
import Darwin
import CryptoKit

@main struct LocalLinkCheck {
    static func main() async throws {
        alarm(55)
        let code = SymmetricKey(size: .bits256).withUnsafeBytes { Data($0).base64EncodedString() }
        let listener = try NWListener(using: LocalLink.parameters(code: code), on: .any)
        let prompt = String(repeating: "اختبار ", count: 2400)
        listener.newConnectionHandler = { connection in
            connection.start(queue: .global())
            FileHandle.standardError.write(Data("Received incoming connection\n".utf8))
            Task {
                defer { connection.cancel() }
                do {
                    let request = try await LocalLink.read(connection, limit: 65536)
                    let body = try JSONDecoder().decode([String:String].self, from: request)
                    guard body["question"] == prompt else { throw LinkError.message("Incorrect request") }
                    try await LocalLink.write(["answer":prompt], to: connection)
                } catch { print("Test peer:", error.localizedDescription) }
            }
        }
        let port: UInt16 = try await withCheckedThrowingContinuation { continuation in
            var resumed = false // NWListener dispatches these states serially.
            listener.stateUpdateHandler = { state in
                guard !resumed else { return }
                switch state {
                case .ready:
                    resumed = true
                    continuation.resume(returning: listener.port!.rawValue)
                case .failed(let error):
                    resumed = true
                    continuation.resume(throwing: error)
                default: break
                }
            }
            listener.start(queue: .global())
        }
        defer { listener.cancel() }
        let address = "127.0.0.1:" + String(port)
        FileHandle.standardError.write(Data("Paired request to loopback\n".utf8))
        let answer = try await LocalLink.ask(address: address, code: code, question: prompt)
        guard answer == prompt else { throw LinkError.message("Incorrect reply") }
        FileHandle.standardError.write(Data("Valid pairing round-trip succeeded\n".utf8))
        let badCode = SymmetricKey(size: .bits256).withUnsafeBytes { Data($0).base64EncodedString() }
        do {
            _ = try await LocalLink.ask(address: address, code: badCode, question: prompt)
        } catch { print("Round-trip passed, wrong pairing key rejected"); return }
        throw LinkError.message("Wrong pairing key was accepted")
    }
}
