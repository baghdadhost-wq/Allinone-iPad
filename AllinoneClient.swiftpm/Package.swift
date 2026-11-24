// swift-tools-version: 5.9
import PackageDescription
import AppleProductTypes

let package = Package(
    name: "AllinoneClient", platforms: [.iOS("16.0")],
    products: [
        .iOSApplication(
            name: "AllinoneClient", targets: ["Client"],
            bundleIdentifier: "app.baghdadhost.allinone.client",
            displayVersion: "0.1", bundleVersion: "1",
            appIcon: .placeholder(icon: .tv), accentColor: .presetColor(.blue),
            supportedDeviceFamilies: [.pad, .phone],
            supportedInterfaceOrientations: [.portrait, .landscapeLeft, .landscapeRight],
            capabilities: [.localNetwork(purposeString: "الاتصال بمضيف Allinone على شبكتك", bonjourServiceTypes: [])]
        )
    ],
    targets: [.executableTarget(name: "Client", path: ".")]
)
