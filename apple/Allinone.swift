import SwiftUI

struct AllinoneHome: View {
    enum Role: String { case host, client }
    @StateObject private var host = Host()
    @AppStorage("AllinoneRole") private var savedRole = UIDevice.current.userInterfaceIdiom == .pad ? "host" : "client"

    var body: some View {
        VStack(spacing: 0) {
            Picker("طريقة الاستخدام", selection: $savedRole) {
                Text("مضيف").tag(Role.host.rawValue)
                Text("اتصال بمضيف").tag(Role.client.rawValue)
            }.pickerStyle(.segmented).padding()
            if savedRole == Role.host.rawValue {
                Workbench(studio:host.studio,host:host)
            } else {
                Chat()
            }
        }
        .environment(\.layoutDirection,.rightToLeft)
        .onAppear { if savedRole == Role.host.rawValue { host.start() } }
        .onChange(of: savedRole) { role in
            if role == Role.host.rawValue { host.start() } else { host.stop() }
        }
    }
}

@main struct AllinoneApp: App { var body: some Scene { WindowGroup { AllinoneHome() } } }
