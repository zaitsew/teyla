import Foundation

enum ReviewError: Error, Equatable {
    case notSaved
    case unsigned          // no relay key: the capture stays on the phone
    case noRelayFolder
    case io(String)
}

/// The phone-local record of one capture, `status.json` in its folder.
struct LocalStatus: Codable, Equatable {
    var v: Int
    var id: String
    var status: ReviewStatus
    var updated: String
    var relayCopied: String?     // when the folder was copied to the relay outbox

    enum CodingKeys: String, CodingKey { case v, id, status, updated, relayCopied = "relay_copied" }
}

/// What the Mac writes to `review-status/<id>.json`. Signed with the relay key.
struct RemoteStatus: Codable, Equatable {
    var v: Int
    var id: String
    var status: ReviewStatus
    var updated: String
    var pr: String?
    var sig: String
}

struct SavedCapture: Equatable {
    var id: String
    var folder: URL
    var signed: Bool
}

enum CopyResult: Equatable { case copied, alreadyThere }

/// Writes a capture to the app's Documents first, then copies the folder to the relay outbox.
/// The Documents copy is the one that cannot fail halfway: the owner's words are never lost to a
/// full disk in iCloud or a folder that went offline.
struct CaptureStore {
    let root: URL                       // .../Documents/TeylaReview/captures
    var now: () -> Date = Date.init

    init(root: URL, now: @escaping () -> Date = Date.init) {
        self.root = root
        self.now = now
    }

    static func defaultRoot() -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        return docs.appendingPathComponent("TeylaReview", isDirectory: true).appendingPathComponent("captures", isDirectory: true)
    }

    func folder(for id: String) -> URL { root.appendingPathComponent(id, isDirectory: true) }

    /// Writes capture.png, capture.json, then capture.sig (only when there is a key), then status.json.
    /// The signature is written last: a folder with a signature is complete.
    @discardableResult
    func save(record: CaptureRecord, png: Data, key: RelayKey?) throws -> SavedCapture {
        var record = record
        record.screenshot.sha256 = ReviewSigner.sha256Hex(png)
        let dir = folder(for: record.id)
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let json = try CaptureCoding.encoder().encode(record)
            try png.write(to: dir.appendingPathComponent(ReviewFormat.pngName), options: .atomic)
            try json.write(to: dir.appendingPathComponent(ReviewFormat.jsonName), options: .atomic)
            if let key {
                let message = ReviewSigner.captureMessage(
                    id: record.id, created: record.created, jsonSHA256: ReviewSigner.sha256Hex(json), pngSHA256: ReviewSigner.sha256Hex(png))
                let sig = ReviewSigner.sign(message, key: key) + "\n"
                try Data(sig.utf8).write(to: dir.appendingPathComponent(ReviewFormat.sigName), options: .atomic)
            }
            try writeStatus(LocalStatus(v: 1, id: record.id, status: .savedOnPhone, updated: CaptureCoding.iso(now()), relayCopied: nil), in: dir)
        } catch {
            throw ReviewError.io(String(describing: error))
        }
        return SavedCapture(id: record.id, folder: dir, signed: key != nil)
    }

    /// Copies `<id>/` to `<relay>/outbox/review/<id>/`. It copies into a hidden temp folder in the
    /// same directory and renames it, so the Mac never lists a folder that is half written.
    /// iCloud still delivers files one by one: the Mac reads a capture only when all three files
    /// are there and the signature verifies (docs/REVIEW.md).
    @discardableResult
    func copyToRelay(id: String, relayRoot: URL) throws -> CopyResult {
        let fm = FileManager.default
        let src = folder(for: id)
        guard fm.fileExists(atPath: src.appendingPathComponent(ReviewFormat.jsonName).path) else { throw ReviewError.notSaved }
        guard fm.fileExists(atPath: src.appendingPathComponent(ReviewFormat.sigName).path) else { throw ReviewError.unsigned }
        let outbox = relayRoot.appendingPathComponent("outbox", isDirectory: true).appendingPathComponent("review", isDirectory: true)
        let dest = outbox.appendingPathComponent(id, isDirectory: true)
        let temp = outbox.appendingPathComponent(".tmp-" + id, isDirectory: true)

        var failure: Error?
        var result = CopyResult.copied
        var coordinationError: NSError?
        NSFileCoordinator(filePresenter: nil).coordinate(writingItemAt: outbox, options: [], error: &coordinationError) { _ in
            do {
                try fm.createDirectory(at: outbox, withIntermediateDirectories: true)
                if fm.fileExists(atPath: dest.path) { result = .alreadyThere; return }
                if fm.fileExists(atPath: temp.path) { try fm.removeItem(at: temp) }
                try fm.createDirectory(at: temp, withIntermediateDirectories: true)
                for name in [ReviewFormat.pngName, ReviewFormat.jsonName, ReviewFormat.sigName] {
                    try fm.copyItem(at: src.appendingPathComponent(name), to: temp.appendingPathComponent(name))
                }
                try fm.moveItem(at: temp, to: dest)
            } catch {
                failure = error
                try? fm.removeItem(at: temp)
            }
        }
        if let coordinationError { throw ReviewError.io(coordinationError.localizedDescription) }
        if let failure { throw ReviewError.io(String(describing: failure)) }

        var status = readLocalStatus(id: id) ?? LocalStatus(v: 1, id: id, status: .savedOnPhone, updated: CaptureCoding.iso(now()), relayCopied: nil)
        status.relayCopied = CaptureCoding.iso(now())
        try? writeStatus(status, in: src)
        return result
    }

    // MARK: status

    func readLocalStatus(id: String) -> LocalStatus? {
        guard let data = try? Data(contentsOf: folder(for: id).appendingPathComponent(ReviewFormat.statusName)) else { return nil }
        return try? CaptureCoding.decoder().decode(LocalStatus.self, from: data)
    }

    private func writeStatus(_ status: LocalStatus, in dir: URL) throws {
        let data = try CaptureCoding.encoder().encode(status)
        try data.write(to: dir.appendingPathComponent(ReviewFormat.statusName), options: .atomic)
    }

    /// The status the owner sees: the Mac's, when `review-status/<id>.json` has a valid signature
    /// and is further along the chain, else the phone's own.
    func status(id: String, relayRoot: URL?, key: RelayKey?) -> ReviewStatus {
        let local = readLocalStatus(id: id)?.status ?? .savedOnPhone
        guard let relayRoot, let key else { return local }
        let file = relayRoot.appendingPathComponent("review-status", isDirectory: true).appendingPathComponent(id + ".json")
        guard let data = try? Data(contentsOf: file),
              let remote = try? CaptureCoding.decoder().decode(RemoteStatus.self, from: data), remote.id == id else { return local }
        let message = ReviewSigner.statusMessage(id: remote.id, status: remote.status.rawValue, updated: remote.updated, pr: remote.pr)
        guard ReviewSigner.verify(message, signature: remote.sig, key: key) else { return local }
        return max(local, remote.status)
    }

    /// Saved captures, newest first.
    func list() -> [String] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []
        return names.filter { readLocalStatus(id: $0) != nil }.sorted {
            (readLocalStatus(id: $0)?.updated ?? "") > (readLocalStatus(id: $1)?.updated ?? "")
        }
    }
}
