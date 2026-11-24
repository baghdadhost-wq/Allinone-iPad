import Foundation

@main struct GatewayCheck {
    static func main() throws {
        for source in [AnswerSource.omni, .free] {
            for base in [source.defaultBase, String(source.defaultBase.dropLast(3)), source.defaultBase + "/"] {
                let engine = Engine(source: source, profile: GatewayProfile(base: base, model: "auto", key: "test"))
                let request = try engine.makeRequest("مرحبا")
                precondition(request.url?.path == "/v1/messages" && request.httpMethod == "POST")
                precondition(request.value(forHTTPHeaderField: "Authorization") == "Bearer test")
                precondition(request.value(forHTTPHeaderField: "anthropic-version") == "2023-06-01")
                let payload = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String:Any]
                precondition((payload["messages"] as? [[String:String]])?.first?["content"] == "مرحبا")
                let data = Data(#"{"content":[{"type":"thinking"},{"type":"text","text":"أهلا"}]}"#.utf8)
                let reply = try engine.decode(data)
                precondition(reply == "أهلا")
            }
        }
        print("Both gateway profiles passed request and response checks")
    }
}
