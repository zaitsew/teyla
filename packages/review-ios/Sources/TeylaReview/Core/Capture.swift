import CoreGraphics
import Foundation

// The capture format, version 1. docs/REVIEW.md and templates/review/capture.schema.json describe
// the same keys. An optional that is nil is left out of the JSON; null is never written.

enum ReviewFormat {
    static let version = 1
    static let pngName = "capture.png"
    static let jsonName = "capture.json"
    static let sigName = "capture.sig"
    static let statusName = "status.json"
    static let maxAnchors = 200
    static let maxStrings = 20
    static let maxCommentLength = 8000
}

/// What an element is, in one word. Raw values are the strings in the capture.
public enum ReviewRole: String, Codable, CaseIterable, Sendable {
    case button, text, field, image, list, cell, toggle, container, other
}

/// Where a capture is. The package writes the first state; the Mac side writes the rest.
public enum ReviewStatus: String, Codable, CaseIterable, Comparable, Sendable {
    case savedOnPhone = "saved_on_phone"
    case received
    case prReady = "pr_ready"
    case verifiedOnDevice = "verified_on_device"

    public var rank: Int { Self.allCases.firstIndex(of: self) ?? 0 }
    public static func < (a: Self, b: Self) -> Bool { a.rank < b.rank }

    public var title: String {
        switch self {
        case .savedOnPhone: return "Saved on phone"
        case .received: return "Received"
        case .prReady: return "PR ready"
        case .verifiedOnDevice: return "Verified on device"
        }
    }
}

struct Rect: Codable, Equatable {
    var x: Double
    var y: Double
    var width: Double
    var height: Double

    init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x.rounded2; self.y = y.rounded2; self.width = width.rounded2; self.height = height.rounded2
    }

    init(_ r: CGRect) { self.init(x: Double(r.origin.x), y: Double(r.origin.y), width: Double(r.size.width), height: Double(r.size.height)) }
}

extension Double {
    /// Two decimals, so a capture does not carry float noise such as 331.49999.
    var rounded2: Double { (self * 100).rounded() / 100 }
}

struct SourceInfo: Codable, Equatable {
    var file: String
    var line: Int
}

struct AnchorInfo: Codable, Equatable {
    var id: String
    var screen: String?
    var parent: String?
    var role: ReviewRole
    var bounds: Rect
    var strings: [String]?
    var source: SourceInfo?
}

struct ElementInfo: Codable, Equatable {
    enum MatchedBy: String, Codable { case anchor, accessibilityIdentifier = "accessibility_identifier" }
    var id: String
    var matchedBy: MatchedBy
    var screen: String?
    var parent: String?
    var role: ReviewRole?
    var bounds: Rect?
    var strings: [String]?
    var source: SourceInfo?

    enum CodingKeys: String, CodingKey {
        case id, matchedBy = "matched_by", screen, parent, role, bounds, strings, source
    }
}

struct TapInfo: Codable, Equatable {
    var x: Double
    var y: Double
    var accessibilityIdentifier: String?
    var accessibilityLabel: String?

    enum CodingKeys: String, CodingKey {
        case x, y, accessibilityIdentifier = "accessibility_identifier", accessibilityLabel = "accessibility_label"
    }
}

struct AppInfo: Codable, Equatable {
    var bundleId: String
    var name: String?
    var version: String
    var build: String
    var commit: String?
    var configuration: BuildChannel

    enum CodingKeys: String, CodingKey {
        case bundleId = "bundle_id", name, version, build, commit, configuration
    }
}

struct ScreenSize: Codable, Equatable {
    var width: Double
    var height: Double
    var scale: Double
}

struct EnvironmentInfo: Codable, Equatable {
    var os: String
    var model: String
    var locale: String
    var language: String?
    var appearance: String
    var dynamicType: String
    var screen: ScreenSize

    enum CodingKeys: String, CodingKey {
        case os, model, locale, language, appearance, dynamicType = "dynamic_type", screen
    }
}

struct CommentInfo: Codable, Equatable {
    enum Input: String, Codable { case text, speech }
    var text: String
    var input: Input
    var language: String?
}

struct ScreenshotInfo: Codable, Equatable {
    var file: String
    var width: Int
    var height: Int
    var scale: Double
    var sha256: String
}

struct MicrophoneInfo: Codable, Equatable {
    var hostAudioInUse: Bool
    var category: String?

    enum CodingKeys: String, CodingKey { case hostAudioInUse = "host_audio_in_use", category }
}

/// capture.json.
struct CaptureRecord: Codable, Equatable {
    var v: Int
    var id: String
    var created: String
    var device: String
    var app: AppInfo
    var environment: EnvironmentInfo
    var screen: String?
    var tap: TapInfo?
    var element: ElementInfo?
    var anchors: [AnchorInfo]
    var comment: CommentInfo
    var screenshot: ScreenshotInfo
    var microphone: MicrophoneInfo
}

enum CaptureCoding {
    static func encoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return e
    }

    static func decoder() -> JSONDecoder { JSONDecoder() }

    static func iso(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "UTC")
        return f.string(from: date)
    }

    static func parseISO(_ text: String) -> Date? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: text)
    }
}

/// Builds a record from what the overlay collected. No UIKit, so the tests build records too.
enum CaptureBuilder {
    static func make(
        id: UUID = UUID(), now: Date, device: String, app: AppInfo, environment: EnvironmentInfo,
        screen: String?, tap: TapInfo?, element: Anchor?, accessibilityElementID: String?,
        anchors: [Anchor], text: String, input: CommentInfo.Input, language: String?,
        pngSHA256: String, pixelWidth: Int, pixelHeight: Int, scale: Double, microphone: MicrophoneInfo
    ) -> CaptureRecord {
        var elementInfo: ElementInfo?
        if let a = element {
            elementInfo = ElementInfo(
                id: a.id, matchedBy: .anchor, screen: a.screen, parent: a.parent, role: a.role,
                bounds: Rect(a.bounds), strings: a.strings.isEmpty ? nil : Array(a.strings.prefix(ReviewFormat.maxStrings)),
                source: SourceInfo(file: a.file, line: a.line))
        } else if let ident = accessibilityElementID, !ident.isEmpty {
            elementInfo = ElementInfo(id: ident, matchedBy: .accessibilityIdentifier, screen: nil, parent: nil, role: nil,
                                      bounds: nil, strings: nil, source: nil)
        }
        let infos = anchors.prefix(ReviewFormat.maxAnchors).map { a in
            AnchorInfo(id: a.id, screen: a.screen, parent: a.parent, role: a.role, bounds: Rect(a.bounds),
                       strings: a.strings.isEmpty ? nil : Array(a.strings.prefix(ReviewFormat.maxStrings)),
                       source: SourceInfo(file: a.file, line: a.line))
        }
        return CaptureRecord(
            v: ReviewFormat.version, id: id.uuidString.lowercased(), created: CaptureCoding.iso(now), device: device,
            app: app, environment: environment, screen: screen, tap: tap, element: elementInfo, anchors: Array(infos),
            comment: CommentInfo(text: String(text.prefix(ReviewFormat.maxCommentLength)), input: input, language: language),
            screenshot: ScreenshotInfo(file: ReviewFormat.pngName, width: pixelWidth, height: pixelHeight, scale: scale, sha256: pngSHA256),
            microphone: microphone)
    }
}
