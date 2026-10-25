import Carbon.HIToolbox
import Foundation

/// A global shortcut through Carbon's `RegisterEventHotKey`. It needs no Accessibility permission
/// and sees only its own key, never other keystrokes. Each instance owns one key (its `id`); one
/// application-wide handler routes a hot-key event to the instance that registered it.
final class GlobalHotKey: @unchecked Sendable {
    /// Push-to-talk, ⌥⌘Space (fixed).
    static let shared = GlobalHotKey(id: 1)
    /// The quick-note shortcut (customizable; see `ShortcutStore`).
    static let quickNote = GlobalHotKey(id: 2)

    let id: UInt32
    /// Called on the main queue.
    var onPress: (@Sendable () -> Void)?
    var onRelease: (@Sendable () -> Void)?

    private var hotKey: EventHotKeyRef?

    init(id: UInt32) {
        self.id = id
    }

    /// Push-to-talk: ⌥⌘Space.
    static let keyCode = Shortcut.pushToTalk.keyCode
    static let modifiers = Shortcut.pushToTalk.modifiers

    /// Registers ⌥⌘Space; returns `noErr` or the Carbon error (`eventHotKeyExistsErr` when another app owns it).
    @discardableResult
    func register() -> OSStatus {
        register(.pushToTalk)
    }

    /// Registers `shortcut`, replacing this key's earlier one.
    @discardableResult
    func register(_ shortcut: Shortcut) -> OSStatus {
        unregister()
        let installed = Self.installHandler()
        guard installed == noErr else { return installed }
        var ref: EventHotKeyRef?
        let hotKeyID = EventHotKeyID(signature: OSType(0x5459_4C41), id: id)   // 'TYLA'
        let status = RegisterEventHotKey(shortcut.keyCode, shortcut.modifiers, hotKeyID, GetApplicationEventTarget(), 0, &ref)
        if status == noErr {
            hotKey = ref
            Self.live.withLock { $0[id] = self }
        }
        return status
    }

    func unregister() {
        if let hotKey { UnregisterEventHotKey(hotKey) }
        hotKey = nil
        Self.live.withLock { $0[id] = nil }
    }

    /// The line Settings shows for a push-to-talk registration result.
    static func describe(_ status: OSStatus) -> String {
        switch status {
        case noErr: return "⌥⌘Space starts voice input from any app."
        case OSStatus(eventHotKeyExistsErr): return "⌥⌘Space is taken by another app, so the shortcut is off."
        default: return "The ⌥⌘Space shortcut could not be registered (error \(status))."
        }
    }

    // MARK: Routing

    private static let live = Locked<[UInt32: GlobalHotKey]>([:])
    private static let handlerStatus = Locked<OSStatus?>(nil)

    /// Installs the one Carbon handler, once.
    private static func installHandler() -> OSStatus {
        if let done = handlerStatus.withLock({ $0 }) { return done }
        var kinds = [
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased)),
        ]
        let status = InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
            guard let event else { return OSStatus(eventNotHandledErr) }
            var hotKeyID = EventHotKeyID()
            let got = GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                                        nil, MemoryLayout<EventHotKeyID>.size, nil, &hotKeyID)
            guard got == noErr, hotKeyID.signature == OSType(0x5459_4C41) else { return OSStatus(eventNotHandledErr) }
            let kind = GetEventKind(event)
            DispatchQueue.main.async {
                guard let key = GlobalHotKey.live.withLock({ $0[hotKeyID.id] }) else { return }
                if kind == UInt32(kEventHotKeyPressed) { key.onPress?() } else { key.onRelease?() }
            }
            return noErr
        }, kinds.count, &kinds, nil, nil)
        handlerStatus.withLock { $0 = status }
        return status
    }
}

/// A value behind a lock, for the registry the Carbon callback reads from another queue.
final class Locked<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) { self.value = value }

    func withLock<T>(_ body: (inout Value) -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return body(&value)
    }
}
