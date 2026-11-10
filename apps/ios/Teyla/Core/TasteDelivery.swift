import CryptoKit
import Foundation

// The signed folder the Mac reads from `outbox/taste/<uuid>/` (src/teyla/taste_wire.py is the other half, and
// tests/fixtures/taste-drop-vector.json is the contract both reproduce).

/// `taste.json`. Every key is always present (`url` or `image` is null), because the Mac accepts exactly these eight.
struct TasteDropFile: Codable, Equatable, Sendable {
    var v = 1
    var id: String
    var created: String
    var device: String
    var verdict: String
    var url: String?
    var image: String?
    var sentence: String

    enum CodingKeys: String, CodingKey { case v, id, created, device, verdict, url, image, sentence }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(v, forKey: .v)
        try c.encode(id, forKey: .id)
        try c.encode(created, forKey: .created)
        try c.encode(device, forKey: .device)
        try c.encode(verdict, forKey: .verdict)
        try c.encode(url, forKey: .url)         // `encode`, not `encodeIfPresent`: null stays in the file
        try c.encode(image, forKey: .image)
        try c.encode(sentence, forKey: .sentence)
    }
}

struct TasteDrop: Equatable, Sendable {
    static let domain = "teyla-taste-v1"
    static let jsonName = "taste.json"
    static let sigName = "taste.sig"

    var json: Data
    var sig: String
    var image: Data?
    var id: String

    /// The signed message: the tag, the id, the time, then the SHA-256 of the JSON bytes and of the picture's
    /// bytes (empty when there is none), joined with `\n`. The bytes that are written are the bytes that are hashed.
    static func message(id: String, created: String, json: Data, image: Data?) -> String {
        [domain, id, created, sha256(json), sha256(image ?? Data())].joined(separator: "\n")
    }

    static func sha256(_ data: Data) -> String { RelayCrypto.hex(Data(SHA256.hash(data: data))) }

    /// Checks the request the same way the Mac does, then builds and signs the drop.
    static func make(_ request: TasteRequest, image: Data?, device: String, key: Data) throws -> TasteDrop {
        guard OutboxEntry.isUUID(request.id) else { throw RelayError.invalidField("id") }
        guard OutboxEntry.isISOTime(request.created) else { throw RelayError.invalidField("created") }
        guard OutboxEntry.isDevice(device) else { throw RelayError.invalidField("device") }
        guard request.verdict == "like" || request.verdict == "dislike" else { throw RelayError.invalidField("verdict") }
        let sentence = request.sentence.trimmingCharacters(in: .whitespacesAndNewlines)
        guard sentence.unicodeScalars.count <= TasteInput.maxSentence, !sentence.contains("\u{0}") else {
            throw RelayError.textTooLong
        }
        let hasImage = request.imageFile != nil
        guard hasImage != (request.url != nil) else { throw RelayError.invalidField("url") }
        if let url = request.url, TasteInput.link(from: url) != url { throw RelayError.invalidField("url") }
        if hasImage {
            guard let image, !image.isEmpty, image.count <= TasteInput.maxImageBytes else { throw RelayError.invalidField("image") }
        }
        let file = TasteDropFile(id: request.id, created: request.created, device: device, verdict: request.verdict,
                                 url: request.url, image: hasImage ? TasteInput.imageName : nil, sentence: sentence)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        let json = try encoder.encode(file)
        let sig = RelayCrypto.hmacHex(key: key, message: Data(message(id: request.id, created: request.created,
                                                                      json: json, image: hasImage ? image : nil).utf8))
        return TasteDrop(json: json, sig: sig, image: hasImage ? image : nil, id: request.id)
    }
}

extension RelayStore {
    var tasteURL: URL { outboxURL.appending(path: "taste", directoryHint: .isDirectory) }

    /// Writes `outbox/taste/<id>/` whole: the files go into a hidden folder beside it, which is then renamed, so the
    /// Mac never sees a folder with some of its files. (iCloud may still deliver the files one by one; the Mac waits for them.)
    func writeTaste(_ drop: TasteDrop) throws {
        let fm = FileManager.default
        let final = tasteURL.appending(path: drop.id, directoryHint: .isDirectory)
        let temp = tasteURL.appending(path: ".\(drop.id).tmp", directoryHint: .isDirectory)
        try fm.createDirectory(at: tasteURL, withIntermediateDirectories: true)
        var failure: Error?
        var coordinatorError: NSError?
        NSFileCoordinator(filePresenter: nil).coordinate(writingItemAt: tasteURL, options: .forMerging,
                                                          error: &coordinatorError) { _ in
            do {
                try? fm.removeItem(at: temp)
                try fm.createDirectory(at: temp, withIntermediateDirectories: true)
                try drop.json.write(to: temp.appending(path: TasteDrop.jsonName))
                try drop.sig.data(using: .utf8)?.write(to: temp.appending(path: TasteDrop.sigName))
                if let image = drop.image { try image.write(to: temp.appending(path: TasteInput.imageName)) }
                if fm.fileExists(atPath: final.path) { try fm.removeItem(at: final) }
                try fm.moveItem(at: temp, to: final)
            } catch {
                try? fm.removeItem(at: temp)
                failure = error
            }
        }
        if let failure { throw failure }
        if let coordinatorError { throw coordinatorError }
    }
}
