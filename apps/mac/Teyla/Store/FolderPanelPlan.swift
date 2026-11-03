import Foundation

/// What the folder panel shows. The owner should not have to think about which folder to give: when the
/// `Teyla` folder already exists in iCloud Drive, the panel opens on it and one click finishes the step;
/// when it does not, the panel opens one level up and says to make it or pick it. Pure, so tests reach it.
struct FolderPanelPlan: Equatable, Sendable {
    /// The folder the panel opens on.
    var directory: URL
    var prompt: String
    var message: String
    var canCreateDirectories: Bool
    /// True when `directory` is the Teyla folder itself.
    var opensOnTeyla: Bool

    static let folderName = "Teyla"

    static func iCloudDrive(home: URL) -> URL {
        home.appendingPathComponent("Library/Mobile Documents/com~apple~CloudDocs", isDirectory: true)
    }

    static func teylaFolder(home: URL) -> URL {
        iCloudDrive(home: home).appendingPathComponent(folderName, isDirectory: true)
    }

    /// `exists` answers whether a directory is there; the sandbox may hide it, which counts as absent.
    static func make(home: URL, exists: (URL) -> Bool) -> FolderPanelPlan {
        let teyla = teylaFolder(home: home)
        if exists(teyla) {
            return FolderPanelPlan(
                directory: teyla, prompt: "Use this folder",
                message: "This is the Teyla folder in iCloud Drive. Click \"Use this folder\": it is the only click you need.",
                canCreateDirectories: false, opensOnTeyla: true)
        }
        return FolderPanelPlan(
            directory: iCloudDrive(home: home), prompt: "Use this folder",
            message: "Create a folder named Teyla in iCloud Drive (New Folder), or pick one if you have it already. Then click \"Use this folder\".",
            canCreateDirectories: true, opensOnTeyla: false)
    }

    /// The home folder of the real user. A sandboxed app's own `NSHomeDirectory()` is its container.
    static func realHome() -> URL? {
        getpwuid(getuid()).flatMap { $0.pointee.pw_dir }.map { URL(fileURLWithPath: String(cString: $0), isDirectory: true) }
    }

    static func directoryExists(_ url: URL) -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) && isDirectory.boolValue
    }

    /// The notice for a chosen folder where the Mac has not written yet. The folder is kept: it is not refused.
    static let emptyFolderNotice = "The Mac has not written to this folder yet. Run teyla relay connect on the Mac, and Teyla fills in by itself."

    /// True when the folder holds the Mac's snapshot (or iCloud's placeholder for it).
    static func hasSnapshot(in folder: URL) -> Bool {
        let fm = FileManager.default
        return fm.fileExists(atPath: folder.appendingPathComponent("state.teyla").path)
            || fm.fileExists(atPath: folder.appendingPathComponent(".state.teyla.icloud").path)
    }
}
