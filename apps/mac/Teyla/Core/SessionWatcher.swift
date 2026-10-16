import CoreServices
import Foundation

/// Watches the session stores with one FSEventStream. FSEvents coalesces bursts for `latency`
/// seconds, which is the debounce; directories that do not exist are skipped.
final class SessionWatcher: @unchecked Sendable {
    /// The three session stores named in docs/APP.md, relative to the home directory.
    static let storeSubpaths = [
        "Library/Application Support/Claude/claude-code-sessions",
        ".claude/projects",
        ".codex/sessions",
    ]

    static func existingPaths(home: String = NSHomeDirectory(),
                              exists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }) -> [String] {
        storeSubpaths.map { "\(home)/\($0)" }.filter(exists)
    }

    private let handler: @Sendable () -> Void
    private var stream: FSEventStreamRef?
    private let queue = DispatchQueue(label: "com.zaitsew.teyla.fsevents")

    init(handler: @escaping @Sendable () -> Void) {
        self.handler = handler
    }

    deinit { stop() }

    /// Returns false when none of the stores exist (the 60 s timer still covers that case).
    @discardableResult
    func start(paths: [String] = SessionWatcher.existingPaths(), latency: TimeInterval = 2.0) -> Bool {
        stop()
        guard !paths.isEmpty else { return false }
        var context = FSEventStreamContext(
            version: 0,
            info: Unmanaged.passUnretained(self).toOpaque(),
            retain: nil, release: nil, copyDescription: nil
        )
        let callback: FSEventStreamCallback = { _, info, _, _, _, _ in
            guard let info else { return }
            let watcher = Unmanaged<SessionWatcher>.fromOpaque(info).takeUnretainedValue()
            watcher.handler()
        }
        guard let created = FSEventStreamCreate(
            kCFAllocatorDefault, callback, &context, paths as CFArray,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow), latency,
            FSEventStreamCreateFlags(kFSEventStreamCreateFlagIgnoreSelf)
        ) else { return false }
        FSEventStreamSetDispatchQueue(created, queue)
        guard FSEventStreamStart(created) else {
            FSEventStreamInvalidate(created)
            FSEventStreamRelease(created)
            return false
        }
        stream = created
        return true
    }

    func stop() {
        guard let stream else { return }
        FSEventStreamStop(stream)
        FSEventStreamInvalidate(stream)
        FSEventStreamRelease(stream)
        self.stream = nil
    }
}
