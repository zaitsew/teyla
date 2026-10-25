import AppKit
import Carbon.HIToolbox

/// A global shortcut: a key code and Carbon modifier bits (`cmdKey`, `optionKey`, `controlKey`, `shiftKey`).
struct Shortcut: Equatable, Hashable, Sendable {
    var keyCode: UInt32
    var modifiers: UInt32

    static let command = UInt32(cmdKey)
    static let option = UInt32(optionKey)
    static let control = UInt32(controlKey)
    static let shift = UInt32(shiftKey)

    /// Push-to-talk, ⌥⌘Space. Fixed: the recorder refuses it for anything else.
    static let pushToTalk = Shortcut(keyCode: UInt32(kVK_Space), modifiers: option | command)
    /// The quick-note shortcut until the owner records another, ⌥Space.
    static let quickNoteDefault = Shortcut(keyCode: UInt32(kVK_Space), modifiers: option)

    /// Modifier bits for the Carbon API from what an AppKit key event reports. Caps Lock, Fn and the
    /// numeric-pad flag are not part of a shortcut.
    static func carbonModifiers(from flags: NSEvent.ModifierFlags) -> UInt32 {
        var bits: UInt32 = 0
        if flags.contains(.command) { bits |= command }
        if flags.contains(.option) { bits |= option }
        if flags.contains(.control) { bits |= control }
        if flags.contains(.shift) { bits |= shift }
        return bits
    }

    /// "⌥Space", "⌃⌥Space", "⇧⌘K": modifiers in the order macOS menus use (⌃⌥⇧⌘), then the key.
    var display: String {
        var text = ""
        if modifiers & Self.control != 0 { text += "⌃" }
        if modifiers & Self.option != 0 { text += "⌥" }
        if modifiers & Self.shift != 0 { text += "⇧" }
        if modifiers & Self.command != 0 { text += "⌘" }
        return text + Self.keyName(keyCode)
    }

    /// The label of a key on a US layout; an unknown code is shown as "Key 99".
    static func keyName(_ code: UInt32) -> String {
        names[code] ?? "Key \(code)"
    }

    private static let names: [UInt32: String] = [
        0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C", 9: "V", 11: "B", 12: "Q",
        13: "W", 14: "E", 15: "R", 16: "Y", 17: "T", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5",
        24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0", 30: "]", 31: "O", 32: "U", 33: "[", 34: "I",
        35: "P", 36: "Return", 37: "L", 38: "J", 39: "'", 40: "K", 41: ";", 42: "\\", 43: ",", 44: "/",
        45: "N", 46: "M", 47: ".", 48: "Tab", 49: "Space", 50: "`", 51: "Delete", 53: "Esc",
        96: "F5", 97: "F6", 98: "F7", 99: "F3", 100: "F8", 101: "F9", 103: "F11", 105: "F13", 107: "F14",
        109: "F10", 111: "F12", 113: "F15", 114: "Help", 115: "Home", 116: "Page Up", 117: "Forward Delete",
        118: "F4", 119: "End", 120: "F2", 121: "Page Down", 122: "F1", 123: "←", 124: "→", 125: "↓", 126: "↑",
    ]
}

/// What the recorder makes of a key press.
enum ShortcutCheck: Equatable {
    case accepted(Shortcut)
    /// Esc: stop recording, change nothing.
    case cancelled
    /// A reason to show next to the field; nothing changes.
    case refused(String)
}

enum ShortcutRules {
    /// A recorded combination is kept when it has ⌘, ⌥ or ⌃ (⇧ alone would fire while typing), and is not push-to-talk.
    /// Esc without modifiers cancels the recording.
    static func check(keyCode: UInt32, modifiers: UInt32) -> ShortcutCheck {
        let chord = Shortcut.command | Shortcut.option | Shortcut.control
        if keyCode == UInt32(kVK_Escape), modifiers & chord == 0 { return .cancelled }
        guard modifiers & chord != 0 else {
            return .refused("Hold ⌘, ⌥ or ⌃ with the key, so the shortcut does not fire while you type.")
        }
        let candidate = Shortcut(keyCode: keyCode, modifiers: modifiers)
        if candidate == .pushToTalk {
            return .refused("\(Shortcut.pushToTalk.display) is push-to-talk. Pick another combination.")
        }
        return .accepted(candidate)
    }
}

/// Where the quick-note shortcut is remembered. Never recorded means the default; "off" means the owner
/// cleared it; anything unreadable falls back to the default rather than leaving the owner with no way in.
struct ShortcutStore {
    static let key = "quickNoteShortcut"
    static let offValue = "off"

    var defaults: UserDefaults = .standard

    func load() -> Shortcut? {
        guard let raw = defaults.string(forKey: Self.key) else { return .quickNoteDefault }
        if raw == Self.offValue { return nil }
        let parts = raw.split(separator: ":").compactMap { UInt32($0) }
        guard parts.count == 2, raw.split(separator: ":").count == 2 else { return .quickNoteDefault }
        return Shortcut(keyCode: parts[0], modifiers: parts[1])
    }

    func save(_ shortcut: Shortcut?) {
        guard let shortcut else {
            defaults.set(Self.offValue, forKey: Self.key)
            return
        }
        defaults.set("\(shortcut.keyCode):\(shortcut.modifiers)", forKey: Self.key)
    }
}

enum QuickNoteShortcut {
    /// The line in Settings for a registration result. `status` is nil when nothing was registered.
    static func describe(_ shortcut: Shortcut?, status: OSStatus?) -> String {
        guard let shortcut else {
            return "No shortcut. The menu-bar item still opens the quick note."
        }
        switch status ?? noErr {
        case noErr:
            return "\(shortcut.display) opens a quick note from any app."
        case OSStatus(eventHotKeyExistsErr):
            return "\(shortcut.display) is taken by another app, so the shortcut is off. Record another one."
        case let code:
            return "\(shortcut.display) could not be registered (error \(code)), so the shortcut is off. Record another one."
        }
    }

    /// The menu-bar item: "Quick note ⌥Space", or just "Quick note" when the shortcut is off.
    static func menuTitle(_ shortcut: Shortcut?) -> String {
        shortcut.map { "Quick note \($0.display)" } ?? "Quick note"
    }
}
