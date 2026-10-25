import Foundation

/// Where the `teyla` binary lives. The order is part of the contract (see README):
/// the file the owner chose, `$TEYLA_BIN`, what a login shell finds on its PATH, then the fixed paths.
enum TeylaBinary {
    /// UserDefaults key of the file picked with "Choose…".
    static let defaultsKey = "teylaBinaryPath"
    /// What the not-found screen shows and copies.
    static let installCommand = "uv tool install --python 3.12 git+https://github.com/zaitsew/teyla"

    static func fixedPaths(home: String) -> [String] {
        ["\(home)/.local/bin/teyla", "/opt/homebrew/bin/teyla", "/usr/local/bin/teyla"]
    }

    /// Every place the binary is looked for, in order. `shellPath` is the login shell's answer, when it is known.
    static func candidates(env: [String: String], home: String, chosen: String? = nil, shellPath: String? = nil) -> [String] {
        explicit(env: env, chosen: chosen) + [shellPath].compactMap { $0 }.filter { !$0.isEmpty } + fixedPaths(home: home)
    }

    /// What the owner named: the file picked in the app, then `$TEYLA_BIN`.
    private static func explicit(env: [String: String], chosen: String?) -> [String] {
        [chosen, env["TEYLA_BIN"]].compactMap { $0 }.filter { !$0.isEmpty }
    }

    /// The first candidate that can be run. The login shell is asked only when the chosen file and
    /// `$TEYLA_BIN` did not answer, because starting it costs tens of milliseconds and sometimes much more.
    static func locate(env: [String: String], home: String, chosen: String? = nil,
                       shellPath: () -> String? = { nil },
                       isExecutable: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) }) -> String? {
        if let hit = explicit(env: env, chosen: chosen).first(where: isExecutable) { return hit }
        if let shell = shellPath(), isExecutable(shell) { return shell }
        return fixedPaths(home: home).first(where: isExecutable)
    }

    // MARK: The chosen file

    static func chosenPath(defaults: UserDefaults = .standard) -> String? {
        let path = defaults.string(forKey: defaultsKey) ?? ""
        return path.isEmpty ? nil : path
    }

    /// Stores the file the owner picked; nil forgets it.
    static func choose(_ path: String?, defaults: UserDefaults = .standard) {
        if let path, !path.isEmpty { defaults.set(path, forKey: defaultsKey) } else { defaults.removeObject(forKey: defaultsKey) }
    }

    // MARK: The login shell's PATH

    /// `command -v teyla` prints a path for a program, but the text of an alias or a function for those;
    /// only an absolute path is a binary.
    static func parseShellOutput(_ output: String) -> String? {
        let line = output.split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespaces) }.last { !$0.isEmpty }
        guard let line, line.hasPrefix("/") else { return nil }
        return line
    }

    private static let cache = ShellCache()

    /// Asks a login shell where `teyla` is, once; the answer is kept until `forgetShellAnswer()`.
    static func loginShellPath() -> String? {
        cache.value { runLoginShell() }
    }

    /// "Check again" asks the shell afresh: the owner may have installed Teyla or changed the PATH since.
    static func forgetShellAnswer() { cache.reset() }

    private static func runLoginShell(timeout: TimeInterval = 5) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-lc", "command -v teyla"]
        let out = Pipe()
        process.standardOutput = out
        process.standardError = FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        let killer = DispatchWorkItem { process.terminate() }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: killer)
        let data = out.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        killer.cancel()
        guard process.terminationStatus == 0 else { return nil }
        return parseShellOutput(String(decoding: data, as: UTF8.self))
    }
}

/// Holds the login shell's answer, which may itself be "not found".
private final class ShellCache: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: String??

    func value(_ compute: () -> String?) -> String? {
        lock.lock()
        defer { lock.unlock() }
        if let stored { return stored }
        let found = compute()
        stored = .some(found)
        return found
    }

    func reset() {
        lock.lock()
        stored = nil
        lock.unlock()
    }
}
