import Foundation

/// Reads and writes the relay folder (iCloud Drive/Teyla). Every call is blocking file I/O through
/// `NSFileCoordinator`, so call it off the main thread.
struct RelayStore: Sendable {
    let folder: URL

    var stateURL: URL { folder.appending(path: "state.teyla") }
    var outboxURL: URL { folder.appending(path: "outbox", directoryHint: .isDirectory) }
    var sentURL: URL { folder.appending(path: "sent", directoryHint: .isDirectory) }

    enum StateRead: Equatable, Sendable {
        /// No `state.teyla` yet: the relay is off or iCloud has not delivered it.
        case missing
        /// The file is in iCloud and not on the phone yet; the download has been requested.
        case downloading
        case data(Data)
        case failed(String)
    }

    func readState() -> StateRead {
        let url = stateURL
        let fm = FileManager.default
        if !fm.fileExists(atPath: url.path) {
            // Before iOS 17-style dataless files, an undownloaded file shows as a hidden placeholder.
            let placeholder = folder.appending(path: ".state.teyla.icloud")
            if fm.fileExists(atPath: placeholder.path) {
                try? fm.startDownloadingUbiquitousItem(at: url)
                return .downloading
            }
            return .missing
        }
        if let values = try? url.resourceValues(forKeys: [.ubiquitousItemDownloadingStatusKey]),
           let status = values.ubiquitousItemDownloadingStatus, status != .current {
            try? fm.startDownloadingUbiquitousItem(at: url)
            return .downloading
        }
        do {
            return .data(try coordinatedRead(url))
        } catch {
            return .failed(error.localizedDescription)
        }
    }

    // MARK: Outbox

    /// Writes `outbox/<id>.json` atomically: the bytes go to a hidden temporary file in the same
    /// folder, which is then renamed, so the Mac never reads half an entry.
    func writeOutbox(_ entry: OutboxEntry) throws {
        let fm = FileManager.default
        try coordinatedCreateDirectory(outboxURL)
        let final = outboxURL.appending(path: "\(entry.id).json")
        let temp = outboxURL.appending(path: ".\(entry.id).json.tmp")
        let data = try entry.jsonData()
        var failure: Error?
        var coordinatorError: NSError?
        NSFileCoordinator(filePresenter: nil).coordinate(writingItemAt: final, options: .forReplacing,
                                                          error: &coordinatorError) { destination in
            do {
                try data.write(to: temp, options: .atomic)
                if fm.fileExists(atPath: destination.path) {
                    _ = try fm.replaceItemAt(destination, withItemAt: temp)
                } else {
                    try fm.moveItem(at: temp, to: destination)
                }
            } catch {
                try? fm.removeItem(at: temp)
                failure = error
            }
        }
        if let failure { throw failure }
        if let coordinatorError { throw coordinatorError }
    }

    func outboxExists(id: String) -> Bool {
        FileManager.default.fileExists(atPath: outboxURL.appending(path: "\(id).json").path)
    }

    // MARK: Sent

    /// The `sent/` entries for the given ids. Files for other ids (another phone) are left alone.
    func readSent(ids: Set<String>) -> [SentResult] {
        var results: [SentResult] = []
        for id in ids where OutboxEntry.isUUID(id) {
            let url = sentURL.appending(path: "\(id).json")
            guard FileManager.default.fileExists(atPath: url.path),
                  let data = try? coordinatedRead(url),
                  let result = try? JSONDecoder().decode(SentResult.self, from: data), result.id == id
            else { continue }
            results.append(result)
        }
        return results
    }

    /// Removes the `sent/` entry once its result has been stored on the phone.
    func deleteSent(id: String) {
        guard OutboxEntry.isUUID(id) else { return }
        let url = sentURL.appending(path: "\(id).json")
        var error: NSError?
        NSFileCoordinator(filePresenter: nil).coordinate(writingItemAt: url, options: .forDeleting,
                                                          error: &error) { destination in
            try? FileManager.default.removeItem(at: destination)
        }
    }

    // MARK: Coordination

    private func coordinatedRead(_ url: URL) throws -> Data {
        var coordinatorError: NSError?
        var result: Result<Data, Error> = .failure(CocoaError(.fileReadUnknown))
        NSFileCoordinator(filePresenter: nil).coordinate(readingItemAt: url, options: [],
                                                          error: &coordinatorError) { readable in
            result = Result { try Data(contentsOf: readable) }
        }
        if let coordinatorError { throw coordinatorError }
        return try result.get()
    }

    private func coordinatedCreateDirectory(_ url: URL) throws {
        var coordinatorError: NSError?
        var failure: Error?
        NSFileCoordinator(filePresenter: nil).coordinate(writingItemAt: url, options: [],
                                                          error: &coordinatorError) { destination in
            do {
                try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
            } catch {
                failure = error
            }
        }
        if let failure { throw failure }
        if let coordinatorError { throw coordinatorError }
    }
}

/// The folder the owner picked, kept as a security-scoped bookmark.
enum FolderBookmark {
    static let defaultsKey = "relayFolderBookmark"

    static func save(_ url: URL, defaults: UserDefaults = .standard) throws {
        let data = try url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil)
        defaults.set(data, forKey: defaultsKey)
    }

    /// The saved folder. The caller opens its security scope. A stale bookmark is renewed.
    static func resolve(defaults: UserDefaults = .standard) -> URL? {
        guard let data = defaults.data(forKey: defaultsKey) else { return nil }
        var stale = false
        guard let url = try? URL(resolvingBookmarkData: data, options: [], relativeTo: nil,
                                 bookmarkDataIsStale: &stale) else { return nil }
        if stale { try? save(url, defaults: defaults) }
        return url
    }

    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: defaultsKey)
    }
}
