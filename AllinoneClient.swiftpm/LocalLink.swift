import Foundation
import Network
import Security

enum LinkError: Error, LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

enum LocalLink {
    static let port: UInt16 = 8744
    static let limit = 1024 * 1024

    static func parameters(code: String) throws -> NWParameters {
        guard let secret = Data(base64Encoded: code), secret.count == 32 else {
            throw LinkError.message("انسخ رمز الاقتران الكامل من الآيباد")
        }
        let tls = NWProtocolTLS.Options()
        let options = tls.securityProtocolOptions
        sec_protocol_options_set_min_tls_protocol_version(options, .TLSv12)
        sec_protocol_options_set_max_tls_protocol_version(options, .TLSv12)
        sec_protocol_options_append_tls_ciphersuite(options,
            tls_ciphersuite_t(rawValue: UInt16(TLS_PSK_WITH_AES_128_GCM_SHA256))!)
        let key = secret.withUnsafeBytes { DispatchData(bytes: $0) }
        let identity = Data("allinone-v1".utf8).withUnsafeBytes { DispatchData(bytes: $0) }
        sec_protocol_options_add_pre_shared_key(options, key as __DispatchData, identity as __DispatchData)
        let params = NWParameters(tls: tls, tcp: NWProtocolTCP.Options())
        params.allowLocalEndpointReuse = true
        return params
    }

    static func read(_ connection: NWConnection, limit: Int) async throws -> Data {
        func exact(_ count: Int) async throws -> Data {
            try await withCheckedThrowingContinuation { continuation in
                connection.receive(minimumIncompleteLength: count, maximumLength: count) { data, _, _, error in
                    if let error { continuation.resume(throwing: error) }
                    else if let data, data.count == count { continuation.resume(returning: data) }
                    else { continuation.resume(throwing: LinkError.message("انقطع الاتصال بالمضيف")) }
                }
            }
        }
        let header = try await exact(4)
        let length = header.reduce(0) { ($0 << 8) + Int($1) }
        guard (1...limit).contains(length) else { throw LinkError.message("حجم الرسالة غير مقبول") }
        return try await exact(length)
    }

    static func write(_ message: [String:String], to connection: NWConnection) async throws {
        let data = try JSONEncoder().encode(message)
        guard data.count <= limit else { throw LinkError.message("الرسالة طويلة جدا") }
        var count = UInt32(data.count).bigEndian
        var frame = withUnsafeBytes(of: &count) { Data($0) }
        frame.append(data)
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void,Error>) in
            connection.send(content: frame, completion: .contentProcessed { error in
                if let error { continuation.resume(throwing: error) }
                else { continuation.resume(returning: ()) }
            })
        }
    }

    static func ask(address: String, code: String, question: String) async throws -> String {
        let parts = address.split(separator: ":", omittingEmptySubsequences: false)
        guard (1...2).contains(parts.count), IPv4Address(String(parts[0])) != nil,
              let port = NWEndpoint.Port(parts.count == 2 ? String(parts[1]) : String(Self.port)) else {
            throw LinkError.message("أدخل عنوان IP والمنفذ الظاهرين في تطبيق المضيف")
        }
        let connection = NWConnection(host: NWEndpoint.Host(String(parts[0])), port: port, using: try parameters(code: code))
        connection.start(queue: DispatchQueue.global(qos: .userInitiated))
        let deadline = DispatchWorkItem { connection.cancel() }
        DispatchQueue.global().asyncAfter(deadline: .now() + 150, execute: deadline)
        defer { deadline.cancel(); connection.cancel() }
        try await write(["question":question], to: connection)
        let bytes = try await read(connection, limit: limit)
        let reply = try JSONDecoder().decode([String:String].self, from: bytes)
        guard let answer = reply["answer"] else { throw LinkError.message(reply["error"] ?? "تعذر الحصول على جواب") }
        return answer
    }
}
