import CryptoKit
import Foundation

/// The relay key: 32 bytes shared with the Mac (docs/APP.md, "Signing"). The pairing string is
/// `teyla-pair:v1:<base64url key, no padding>`.
struct RelayKey: Equatable {
    static let prefix = "teyla-pair:v1:"
    let bytes: Data

    init?(bytes: Data) {
        guard bytes.count == 32 else { return nil }
        self.bytes = bytes
    }

    init?(pairing: String) {
        let text = pairing.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.hasPrefix(Self.prefix) else { return nil }
        var body = String(text.dropFirst(Self.prefix.count))
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        while body.count % 4 != 0 { body += "=" }
        guard let data = Data(base64Encoded: body) else { return nil }
        self.init(bytes: data)
    }

    init?(hex: String) {
        guard let data = Hex.decode(hex) else { return nil }
        self.init(bytes: data)
    }
}

enum Hex {
    static func encode(_ data: some Sequence<UInt8>) -> String {
        data.map { String(format: "%02x", $0) }.joined()
    }

    static func decode(_ text: String) -> Data? {
        let chars = Array(text.utf8)
        guard chars.count % 2 == 0 else { return nil }
        var out = Data(capacity: chars.count / 2)
        var i = 0
        while i < chars.count {
            guard let hi = nibble(chars[i]), let lo = nibble(chars[i + 1]) else { return nil }
            out.append(hi << 4 | lo)
            i += 2
        }
        return out
    }

    private static func nibble(_ c: UInt8) -> UInt8? {
        switch c {
        case 48...57: return c - 48
        case 97...102: return c - 87
        case 65...70: return c - 55
        default: return nil
        }
    }
}

/// Signatures for a capture and for the status the Mac writes back. Same scheme as the relay's
/// outbox: lowercase hex HMAC-SHA256 of a message of lines joined with "\n".
enum ReviewSigner {
    static func sha256Hex(_ data: Data) -> String { Hex.encode(SHA256.hash(data: data)) }

    /// `teyla-review-v1`, id, created, SHA-256 of capture.json, SHA-256 of capture.png.
    static func captureMessage(id: String, created: String, jsonSHA256: String, pngSHA256: String) -> String {
        ["teyla-review-v1", id, created, jsonSHA256, pngSHA256].joined(separator: "\n")
    }

    /// `teyla-review-status-v1`, id, status, updated, pr (an empty line when there is none).
    static func statusMessage(id: String, status: String, updated: String, pr: String?) -> String {
        ["teyla-review-status-v1", id, status, updated, pr ?? ""].joined(separator: "\n")
    }

    static func sign(_ message: String, key: RelayKey) -> String {
        let mac = HMAC<SHA256>.authenticationCode(for: Data(message.utf8), using: SymmetricKey(data: key.bytes))
        return Hex.encode(mac)
    }

    static func verify(_ message: String, signature: String, key: RelayKey) -> Bool {
        guard let given = Hex.decode(signature.trimmingCharacters(in: .whitespacesAndNewlines)), given.count == 32 else { return false }
        let mac = HMAC<SHA256>.authenticationCode(for: Data(message.utf8), using: SymmetricKey(data: key.bytes))
        var diff: UInt8 = 0                       // compare every byte, so the time does not leak the first mismatch
        for (a, b) in zip(Array(mac), Array(given)) { diff |= a ^ b }
        return diff == 0
    }
}

/// Where the phone keeps the key. The real store is the Keychain; tests use the in-memory one.
protocol RelayKeyStoring: AnyObject {
    func load() -> RelayKey?
    func save(_ key: RelayKey) -> Bool
    func delete()
}

final class MemoryKeyStore: RelayKeyStoring {
    private var key: RelayKey?
    init(_ key: RelayKey? = nil) { self.key = key }
    func load() -> RelayKey? { key }
    func save(_ key: RelayKey) -> Bool { self.key = key; return true }
    func delete() { key = nil }
}
