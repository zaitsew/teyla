/// The keys that open review mode on the Mac, as plain data. `ReviewCommands` turns it into a menu
/// shortcut. Control-Option-Command-F is the Mac's choice because no system or common app command
/// uses all three modifiers with F: Command-F is Find, Option-Command-F is Find and Replace in
/// several apps, and Control-Command-F is Enter Full Screen.
public struct ReviewShortcut: Equatable, Sendable {
    public var key: Character
    public var control: Bool
    public var option: Bool
    public var command: Bool
    public var shift: Bool

    public init(key: Character, control: Bool = false, option: Bool = false, command: Bool = false, shift: Bool = false) {
        self.key = key; self.control = control; self.option = option; self.command = command; self.shift = shift
    }

    public static let mac = ReviewShortcut(key: "f", control: true, option: true, command: true)

    /// The shortcut as the menu draws it, for example "⌃⌥⌘F".
    public var display: String {
        (control ? "⌃" : "") + (option ? "⌥" : "") + (shift ? "⇧" : "") + (command ? "⌘" : "") + String(key).uppercased()
    }

    /// Shortcuts the system or a common command already owns for the same key. The test keeps the Mac
    /// shortcut away from all of them.
    static let knownClashes: [ReviewShortcut] = [
        ReviewShortcut(key: "f", command: true),                                  // Find
        ReviewShortcut(key: "f", option: true, command: true),                    // Find and Replace
        ReviewShortcut(key: "f", control: true, command: true),                   // Enter Full Screen
        ReviewShortcut(key: "f", command: true, shift: true),                     // Find in project
        ReviewShortcut(key: "f", option: true, command: true, shift: true),       // Replace in project
    ]
}
