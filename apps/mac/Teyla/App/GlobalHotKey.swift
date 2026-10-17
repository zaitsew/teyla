import Carbon.HIToolbox
import Foundation

/// One global shortcut through Carbon's `RegisterEventHotKey`. It needs no Accessibility
/// permission and sees only its own key, never other keystrokes.
final class GlobalHotKey: @unchecked Sendable {
    static let shared = GlobalHotKey()

    /// Called on the main queue.
    var onPress: (@Sendable () -> Void)?
    var onRelease: (@Sendable () -> Void)?

    private var hotKey: EventHotKeyRef?
    private var handler: EventHandlerRef?

    /// ⌥⌘Space.
    static let keyCode = UInt32(kVK_Space)
    static let modifiers = UInt32(optionKey | cmdKey)

    /// Registers the shortcut; returns `noErr` or the Carbon error (`eventHotKeyExistsErr` when another app owns it).
    @discardableResult
    func register() -> OSStatus {
        unregister()
        var kinds = [
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased)),
        ]
        let installed = InstallEventHandler(GetApplicationEventTarget(), { _, event, userData in
            guard let event, let userData else { return OSStatus(eventNotHandledErr) }
            let key = Unmanaged<GlobalHotKey>.fromOpaque(userData).takeUnretainedValue()
            let kind = GetEventKind(event)
            DispatchQueue.main.async {
                if kind == UInt32(kEventHotKeyPressed) { key.onPress?() } else { key.onRelease?() }
            }
            return noErr
        }, kinds.count, &kinds, Unmanaged.passUnretained(self).toOpaque(), &handler)
        guard installed == noErr else { return installed }
        let id = EventHotKeyID(signature: OSType(0x5459_4C41), id: 1)   // 'TYLA'
        let status = RegisterEventHotKey(Self.keyCode, Self.modifiers, id, GetApplicationEventTarget(), 0, &hotKey)
        if status != noErr { unregister() }
        return status
    }

    func unregister() {
        if let hotKey { UnregisterEventHotKey(hotKey) }
        if let handler { RemoveEventHandler(handler) }
        hotKey = nil
        handler = nil
    }

    /// The line Settings shows for a registration result.
    static func describe(_ status: OSStatus) -> String {
        switch status {
        case noErr: return "⌥⌘Space starts voice input from any app."
        case OSStatus(eventHotKeyExistsErr): return "⌥⌘Space is taken by another app, so the shortcut is off."
        default: return "The ⌥⌘Space shortcut could not be registered (error \(status))."
        }
    }
}
