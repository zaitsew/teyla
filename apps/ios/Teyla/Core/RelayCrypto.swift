import CryptoKit
import Foundation

// The signing rules of the iCloud Drive relay (docs/APP.md, "The relay"). Everything here is
// pure, so the tests can reproduce tests/fixtures/relay-vector.json without a device.

enum RelayError: Error, Equatable, LocalizedError {
    case badPairing
    case invalidField(String)
    case textEmpty
    case textTooLong

    var errorDescription: String? {
        switch self {
        case .badPairing: return "That is not a Teyla pairing string."
        case .invalidField(let name): return "The field \"\(name)\" has a value the relay does not accept."
        case .textEmpty: return "Write something first."
        case .textTooLong: return "The text is longer than 8,000 characters."
        }
    }
}

enum RelayCrypto {
    static func sanitizedDevice(_ name: String, fallback: String = "iPhone") -> String {
        OutboxEntry.sanitize(name, fallback: fallback)
    }

    static let pairingPrefix = "teyla-pair:v1:"
    static let stateDomain = "teyla-state-v1\n"
    static let outboxDomain = "teyla-outbox-v1"
    static let maxTextLength = 8000

    /// Lowercase hex HMAC-SHA256.
    static func hmacHex(key: Data, message: Data) -> String {
        let mac = HMAC<SHA256>.authenticationCode(for: message, using: SymmetricKey(data: key))
        return hex(Data(mac))
    }

    static func sha256Hex(_ text: String) -> String {
        hex(Data(SHA256.hash(data: Data(text.utf8))))
    }

    static func hex(_ data: Data) -> String {
        data.map { String(format: "%02x", $0) }.joined()
    }

    /// `teyla-pair:v1:<base64url key, no padding>` becomes the 32-byte key.
    static func parsePairing(_ string: String) -> Data? {
        let text = string.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.hasPrefix(pairingPrefix) else { return nil }
        var body = String(text.dropFirst(pairingPrefix.count))
        guard !body.isEmpty,
              body.utf8.allSatisfy({ ($0 >= 0x30 && $0 <= 0x39) || ($0 >= 0x41 && $0 <= 0x5A)
                  || ($0 >= 0x61 && $0 <= 0x7A) || $0 == 0x2D || $0 == 0x5F })
        else { return nil }
        body = body.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while body.count % 4 != 0 { body += "=" }
        guard let key = Data(base64Encoded: body), key.count == 32 else { return nil }
        return key
    }

    // MARK: State file

    enum StateVerdict: Equatable {
        /// The signature matches; these are the JSON bytes exactly as signed.
        case valid(Data)
        /// No signature line, or it is not 64 hex characters.
        case malformed
        case badSignature
    }

    /// Line 1 is the signature (64 hex characters), then `\n`, then the snapshot bytes as signed.
    /// Nothing is decoded before the signature has been checked.
    static func verifyStateFile(_ file: Data, key: Data) -> StateVerdict {
        let bytes = [UInt8](file)
        guard bytes.count > 65, bytes[64] == 0x0A, let given = decodeHex(bytes[0..<64]) else { return .malformed }
        let json = Data(bytes[65...])
        let message = Data(stateDomain.utf8) + json
        let ok = HMAC<SHA256>.isValidAuthenticationCode(given, authenticating: message, using: SymmetricKey(data: key))
        return ok ? .valid(json) : .badSignature
    }

    static func decodeHex(_ bytes: some Collection<UInt8>) -> Data? {
        guard bytes.count % 2 == 0 else { return nil }
        var out = Data()
        var pending: UInt8?
        for b in bytes {
            let v: UInt8
            switch b {
            case 0x30...0x39: v = b - 0x30
            case 0x61...0x66: v = b - 0x61 + 10
            case 0x41...0x46: v = b - 0x41 + 10
            default: return nil
            }
            if let high = pending {
                out.append(high << 4 | v)
                pending = nil
            } else {
                pending = v
            }
        }
        return out
    }
}

// MARK: - Outbox entries

enum OutboxKind: String, Codable, Sendable, CaseIterable {
    case answer, say, dispatch
}

struct OutboxEntry: Codable, Equatable, Sendable {
    var v: Int
    var id: String
    var kind: OutboxKind
    var target: String
    var about: String
    var created: String
    var device: String
    var text: String
    var sig: String

    /// The signed message: the lines `teyla-outbox-v1`, `v`, `id`, `kind`, `target`, `about`,
    /// `created`, `device`, then `text`, joined with `\n`. `text` is last, so a newline in it is safe.
    var message: String {
        [RelayCrypto.outboxDomain, String(v), id, kind.rawValue, target, about, created, device, text]
            .joined(separator: "\n")
    }

    /// Checks every field but `text` against its strict pattern (so no line break can shift text
    /// into another field), then the text itself.
    func validate() throws {
        guard v == 1 else { throw RelayError.invalidField("v") }
        guard OutboxEntry.isUUID(id) else { throw RelayError.invalidField("id") }
        guard OutboxEntry.isTarget(target) else { throw RelayError.invalidField("target") }
        guard OutboxEntry.isHex64(about) else { throw RelayError.invalidField("about") }
        guard OutboxEntry.isISOTime(created) else { throw RelayError.invalidField("created") }
        guard OutboxEntry.isDevice(device) else { throw RelayError.invalidField("device") }
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { throw RelayError.textEmpty }
        if text.unicodeScalars.count > RelayCrypto.maxTextLength { throw RelayError.textTooLong }
    }

    /// Builds, validates and signs one entry. `aboutText` is the text the owner saw: the question,
    /// the session title or the product name. `text` is signed exactly as given.
    static func make(kind: OutboxKind, target: String, aboutText: String, text: String, device: String,
                     key: Data, id: String = UUID().uuidString.lowercased(),
                     created: String = Date().formatted(.iso8601)) throws -> OutboxEntry {
        var entry = OutboxEntry(v: 1, id: id, kind: kind, target: target,
                                about: RelayCrypto.sha256Hex(aboutText), created: created,
                                device: device, text: text, sig: "")
        try entry.validate()
        entry.sig = RelayCrypto.hmacHex(key: key, message: Data(entry.message.utf8))
        return entry
    }

    func jsonData() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes, .prettyPrinted]
        return try encoder.encode(self)
    }

    // MARK: Patterns
    // ASCII byte scans, not regular expressions: a regex `$` accepts a trailing newline.

    private static func matches(_ s: String, count: ClosedRange<Int>, allowed: (UInt8) -> Bool) -> Bool {
        let bytes = Array(s.utf8)
        return count.contains(bytes.count) && bytes.allSatisfy(allowed)
    }

    private static func isDigit(_ b: UInt8) -> Bool { b >= 0x30 && b <= 0x39 }
    private static func isHex(_ b: UInt8) -> Bool {
        isDigit(b) || (b >= 0x61 && b <= 0x66) || (b >= 0x41 && b <= 0x46)
    }
    private static func isLetter(_ b: UInt8) -> Bool { (b >= 0x41 && b <= 0x5A) || (b >= 0x61 && b <= 0x7A) }

    static func isUUID(_ s: String) -> Bool {
        let bytes = Array(s.utf8)
        guard bytes.count == 36 else { return false }
        for (i, b) in bytes.enumerated() {
            if i == 8 || i == 13 || i == 18 || i == 23 {
                if b != 0x2D { return false }
            } else if !isHex(b) {
                return false
            }
        }
        return true
    }

    /// `[A-Za-z0-9_.:#/-]{1,200}`
    static func isTarget(_ s: String) -> Bool {
        matches(s, count: 1...200) { isLetter($0) || isDigit($0) || "_.:#/-".utf8.contains($0) }
    }

    /// 64 hex characters.
    static func isHex64(_ s: String) -> Bool { matches(s, count: 64...64, allowed: isHex) }

    /// `[A-Za-z0-9 ._-]{1,64}`
    static func isDevice(_ s: String) -> Bool {
        matches(s, count: 1...64) { isLetter($0) || isDigit($0) || " ._-".utf8.contains($0) }
    }

    /// An ISO 8601 time such as `2026-10-17T21:45:00Z`, with an optional fraction and offset.
    static func isISOTime(_ s: String) -> Bool {
        guard s.utf8.count <= 40, s.utf8.allSatisfy({ $0 < 0x80 }) else { return false }
        return s.wholeMatch(of: /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})/) != nil
    }

    /// Makes a device name the relay accepts: other characters become "-", at most 64 of them.
    fileprivate static func sanitize(_ name: String, fallback: String = "iPhone") -> String {
        let mapped = name.unicodeScalars.map { scalar -> Character in
            if scalar.value < 0x80 {
                let b = UInt8(scalar.value)
                if isLetter(b) || isDigit(b) || " ._-".utf8.contains(b) { return Character(scalar) }
            }
            return "-"
        }
        let cleaned = String(mapped.prefix(64)).trimmingCharacters(in: .whitespaces)
        return cleaned.isEmpty ? fallback : cleaned
    }
}

/// `sent/<uuid>.json`, written by the Mac: `{id, ok, via, detail, done_at}`. Not signed, so it is
/// shown and never trusted for anything else.
struct SentResult: Decodable, Equatable, Sendable {
    var id: String
    var ok: Bool
    var via: String
    var detail: String
    var doneAt: String

    enum CodingKeys: String, CodingKey {
        case id, ok, via, detail
        case doneAt = "done_at"
    }

    init(id: String, ok: Bool, via: String = "", detail: String = "", doneAt: String = "") {
        self.id = id
        self.ok = ok
        self.via = via
        self.detail = detail
        self.doneAt = doneAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        ok = c.lenient(.ok, false)
        via = c.lenient(.via, "")
        detail = c.lenient(.detail, "")
        doneAt = c.lenient(.doneAt, "")
    }
}
