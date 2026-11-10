import Foundation
import ImageIO
import UniformTypeIdentifiers

// What the Share extension saves and the app delivers (docs/TASTE.md, "From the phone"). This file is compiled
// into both targets and depends on nothing else in the app: the extension never holds the relay key and never
// touches the iCloud folder. It writes a request into the App Group container; the app signs it and writes the
// signed folder into the relay the next time it is open (`AppModel.flushTasteQueue`).

/// One like or dislike the owner shared. `url` and `imageFile` are never both set, and one of them always is.
struct TasteRequest: Codable, Equatable, Sendable {
    var id: String
    /// ISO 8601, UTC, whole seconds: `2026-11-09T10:00:00Z`.
    var created: String
    /// `like` or `dislike`.
    var verdict: String
    var url: String?
    /// The picture's file name inside the request's folder (`image.jpg`).
    var imageFile: String?
    /// The owner's own words, as typed or dictated. Empty when they said nothing.
    var sentence: String
}

enum TasteInput {
    static let appGroup = "group.com.zaitsew.teyla"
    static let maxImageBytes = 5 * 1024 * 1024
    static let maxSentence = 8000
    static let maxURL = 2000
    static let imageName = "image.jpg"

    /// An http(s) link without spaces, or nil. The Mac checks the same rule again.
    static func link(from string: String) -> String? {
        let s = string.trimmingCharacters(in: .whitespacesAndNewlines)
        guard s.count <= maxURL, !s.contains(where: \.isWhitespace),
              let url = URL(string: s), let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https", url.host?.isEmpty == false else { return nil }
        return s
    }

    /// The first http(s) link inside a piece of shared text (some apps share a title and a link as plain text).
    static func firstLink(inText text: String) -> String? {
        for word in text.split(whereSeparator: \.isWhitespace) {
            if let l = link(from: String(word)) { return l }
        }
        return nil
    }

    /// The picture as a JPEG of at most `maxBytes`: re-encoded, and shrunk step by step until it fits. EXIF
    /// (location, camera) is dropped by the re-encode. nil when the data is not an image.
    static func jpeg(from data: Data, maxBytes: Int = maxImageBytes) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              CGImageSourceGetCount(source) > 0 else { return nil }
        var longest = 4096
        for _ in 0..<6 {
            let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                            kCGImageSourceCreateThumbnailWithTransform: true,
                                            kCGImageSourceThumbnailMaxPixelSize: longest]
            guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
            for quality in [0.8, 0.6, 0.4] {
                let out = NSMutableData()
                guard let dest = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
                CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
                guard CGImageDestinationFinalize(dest) else { return nil }
                if out.length <= maxBytes { return out as Data }
            }
            longest = longest * 2 / 3
        }
        return nil
    }

    static func now() -> String { Date().formatted(.iso8601) }
}

/// The folder the extension writes to and the app empties. A request is a folder `<id>/request.json` (+ `image.jpg`),
/// written whole and then renamed into place, so the app never reads half a request.
struct TasteQueue: Sendable {
    let root: URL

    init(root: URL) { self.root = root }

    /// The App Group's `taste-queue`, or nil when the group is not available (a build without the entitlement).
    static func shared() -> TasteQueue? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: TasteInput.appGroup)
            .map { TasteQueue(root: $0.appending(path: "taste-queue", directoryHint: .isDirectory)) }
    }

    func enqueue(_ request: TasteRequest, image: Data?) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        let temp = root.appending(path: ".\(request.id).tmp", directoryHint: .isDirectory)
        try? fm.removeItem(at: temp)
        try fm.createDirectory(at: temp, withIntermediateDirectories: true)
        do {
            if let image { try image.write(to: temp.appending(path: TasteInput.imageName)) }
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
            try encoder.encode(request).write(to: temp.appending(path: "request.json"))
            try fm.moveItem(at: temp, to: root.appending(path: request.id, directoryHint: .isDirectory))
        } catch {
            try? fm.removeItem(at: temp)
            throw error
        }
    }

    struct Queued: Sendable {
        var request: TasteRequest
        var image: Data?
    }

    /// Every request waiting, oldest first. A folder that does not read is skipped, and left for the next pass.
    func pending() -> [Queued] {
        let fm = FileManager.default
        guard let names = try? fm.contentsOfDirectory(atPath: root.path) else { return [] }
        var out: [Queued] = []
        for name in names.sorted() where !name.hasPrefix(".") {
            let dir = root.appending(path: name, directoryHint: .isDirectory)
            guard let data = try? Data(contentsOf: dir.appending(path: "request.json")),
                  let request = try? JSONDecoder().decode(TasteRequest.self, from: data), request.id == name else { continue }
            var image: Data?
            if request.imageFile != nil {
                image = try? Data(contentsOf: dir.appending(path: TasteInput.imageName))
                if image == nil { continue }
            }
            out.append(Queued(request: request, image: image))
        }
        return out.sorted { $0.request.created < $1.request.created }
    }

    func remove(id: String) {
        try? FileManager.default.removeItem(at: root.appending(path: id, directoryHint: .isDirectory))
    }
}
