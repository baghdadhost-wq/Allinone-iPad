import Foundation

enum Check: Error { case failed(String) }
func verify(_ value: Bool,_ message: String) throws { if !value { throw Check.failed(message) } }
@main struct NativeStudioCheck {
    @MainActor static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:root) }
        let workspace = ProjectFiles(root:root)
        let target = root.appendingPathComponent("main.swift")
        try Data("let n = 1\n".utf8).write(to:target)
        let outside = root.deletingLastPathComponent()
        try FileManager.default.createSymbolicLink(at:root.appendingPathComponent("escape"),withDestinationURL:outside)
        for path in ["../test", "/etc/passwd", ".git/config", "escape/anything"] {
            do { _ = try workspace.url(path); throw Check.failed("unconfined path") } catch is LinkError {}
        }
        let found = try workspace.search("let n")
        try verify(found.contains("main.swift:1"),"search")
        let history = [Turn(role:"user",content:"first"),Turn(role:"assistant",content:"second")]
        let direct = try await CodingAgent.run(prompt:"third",history:history,notes:"private note",files:workspace,mode:.quick,ask:{ system,turns in
            try verify(!system.contains("private note") && turns.map(\.content) == ["first","second","third"],"quick context")
            return (#"{"action":"read","path":"main.swift"}"#,"fixture")
        },activity:{ _ in preconditionFailure("Quick mode invoked a tool") })
        try verify(direct.proposal == nil && direct.answer.contains("main.swift"),"quick answer is plain text")
        let checkpoint = Checkpoint(prompt:"third",thread:"host",task:nil,mode:.quick)
        let restored = try JSONDecoder().decode(Checkpoint.self,from:JSONEncoder().encode(checkpoint))
        try verify(restored.mode == .quick,"resume mode")
        let legacy = try JSONDecoder().decode(Checkpoint.self,from:Data(#"{"prompt":"old","thread":"host"}"#.utf8))
        try verify(legacy.mode == nil,"legacy checkpoint")
        var calls = 0
        let result = try await CodingAgent.run(prompt:"Change n",history:[],notes:"Swift",files:workspace,ask:{system,turns in
            calls += 1
            let action: [String:String]
            switch calls {
            case 1: action = ["action":"list","path":""]
            case 2:
                try verify(turns.last!.content.contains("main.swift"),"list result"); action = ["action":"read","path":"main.swift"]
            default:
                try verify(turns.last!.content.contains("let n = 1"),"read result")
                action = ["action":"edit","path":"main.swift","text":"let n = 2\n","reason":"Update constant"]
            }
            return (String(decoding:try JSONSerialization.data(withJSONObject:action),as:UTF8.self),"fixture")
        },activity:{_ in})
        guard let edit = result.proposal else { throw Check.failed("missing review") }
        try verify(try Data(contentsOf:target) == Data("let n = 1\n".utf8),"wrote before approval")
        try workspace.apply(edit)
        try verify(try Data(contentsOf:target) == Data("let n = 2\n".utf8),"approved write")
        do { try workspace.apply(edit); throw Check.failed("stale update") } catch is LinkError {}
        let new = try workspace.propose(path:"module/example.swift",replacement:"hello",reason:"create",previouslyRead:[:])
        try workspace.apply(new)
        try verify(try workspace.read("module/example.swift") == Data("hello".utf8),"create")
        try workspace.undo(new)
        try verify(!FileManager.default.fileExists(atPath:root.appendingPathComponent(new.path).path),"undo creation")
        try workspace.undo(edit)
        try verify(try workspace.read(edit.path) == edit.original,"undo edit")
        let invalid = try workspace.propose(path:"config.json",replacement:"{bad",reason:"check",previouslyRead:[:])
        var invalidRejected = false
        do { try workspace.verifyProposal(invalid) } catch { invalidRejected = true }
        try verify(invalidRejected,"invalid JSON")
        let handover = try ManualExchange.handover(prompt:"inspect",selected:"main.swift",studioNotes:"project",turns:[],files:workspace)
        try verify(handover.contains("let n = 1"),"manual handover")
        let imported = try ManualExchange.proposal(#"{"action":"edit","path":"main.swift","text":"new"}"#,files:workspace)
        try verify(imported?.original == edit.original,"review imported edit")
        let a = Provider(name:"A",base:"https://example.org/v1",model:"first",style:.openAI,free:false)
        let b = Provider(name:"B",base:"https://example.org/v1",model:"second",style:.anthropic,free:true)
        let c = Provider(name:"C",base:"https://example.org/v1",model:"third",style:.openAI,free:true)
        let router = NativeRouter()
        var visited:[String] = []
        let (_,served) = try await router.respond(providers:[a,b,c],mode:.priority,system:"test",turns:[],generate:{ p,_,_ in
            visited.append(p.name)
            if p.id == a.id { throw UpstreamFailure(reason:"429",delay:30) }
            return "reply"
        })
        try verify(visited == ["A","B"] && served.contains("B"),"ordered failover")
        visited = []
        for _ in 0..<2 {
            _ = try await router.respond(providers:[a,b,c],mode:.freePool,system:"test",turns:[],generate:{p,_,_ in visited.append(p.name);return "ok"})
        }
        try verify(visited == ["B","C"],"free pool rotation")
        for p in [a,b] {
            let r = try NativeAPI.request(p,key:"testkey",system:"instructions",turns:[Turn(role:"user",content:"hello")])
            try verify(r.url!.path == (p.style == .openAI ? "/v1/chat/completions" : "/v1/messages"),"route")
            try verify(r.value(forHTTPHeaderField:p.style == .openAI ? "Authorization":"x-api-key") != nil,"auth")
        }
        print("PASS: list/search/read, review before write, create, stale write and path checks, ordered failover, free rotation, provider formats")
    }
}
