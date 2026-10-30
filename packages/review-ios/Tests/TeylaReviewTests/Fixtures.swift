import CoreGraphics
import Foundation
@testable import TeylaReview

enum Fixtures {
    /// <repo>/ — five levels above this file: TeylaReviewTests, Tests, review-ios, packages, <repo>.
    static var repoRoot: URL {
        var url = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { url.deleteLastPathComponent() }
        return url
    }

    static var captureDir: URL { repoRoot.appendingPathComponent("tests/fixtures/review-capture") }
    static var vector: [String: String] {
        let data = try! Data(contentsOf: repoRoot.appendingPathComponent("tests/fixtures/review-vector.json"))
        return try! JSONSerialization.jsonObject(with: data) as! [String: String]
    }

    static func anchor(_ id: String, _ rect: CGRect, seq: Int = 1, screen: String? = "sample.list", parent: String? = nil,
                       role: ReviewRole = .button, strings: [String] = []) -> Anchor {
        Anchor(id: id, screen: screen, parent: parent, role: role, bounds: rect, strings: strings,
               file: "SampleApp/ListView.swift", line: 10 + seq, seq: seq)
    }

    static let app = AppInfo(bundleId: "com.example.sampleapp", name: "Sample App", version: "1.4.0", build: "212",
                             commit: "3f9c2ab", configuration: .testflight)
    static let environment = EnvironmentInfo(os: "iOS 19.1", model: "iPhone16,2", locale: "es_ES", language: "es",
                                             appearance: "dark", dynamicType: "large",
                                             screen: ScreenSize(width: 390, height: 844, scale: 1))

    static func record(id: UUID = UUID(), element: Anchor? = nil, anchors: [Anchor] = [], text: String = "Make it bigger") -> CaptureRecord {
        CaptureBuilder.make(
            id: id, now: Date(timeIntervalSince1970: 1_793_394_845), device: "iPhone", app: app, environment: environment,
            screen: "sample.list", tap: TapInfo(x: 331.5, y: 782, accessibilityIdentifier: nil, accessibilityLabel: nil),
            element: element, accessibilityElementID: nil, anchors: anchors, text: text, input: .text, language: "en",
            pngSHA256: String(repeating: "0", count: 64), pixelWidth: 390, pixelHeight: 844, scale: 1,
            microphone: MicrophoneInfo(hostAudioInUse: false, category: "AVAudioSessionCategoryPlayback"))
    }

    static func tempDir() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("teyla-review-tests-" + UUID().uuidString)
        try! FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}
