import Foundation

/// A language the voice input can recognise. Recognition is always on the device.
struct VoiceLocale: Identifiable, Equatable, Sendable {
    /// The locale identifier handed to Apple Speech, such as "en-US".
    let id: String
    /// The name shown in the picker.
    let name: String
}

enum Voice {
    static let locales: [VoiceLocale] = [
        VoiceLocale(id: "en-US", name: "English"),
        VoiceLocale(id: "es-ES", name: "Spanish"),
        VoiceLocale(id: "ru-RU", name: "Russian"),
    ]

    static let defaultsKey = "voiceLocale"

    /// The remembered language; an unknown or missing value falls back to English.
    static func stored(in defaults: UserDefaults = .standard) -> VoiceLocale {
        let id = defaults.string(forKey: defaultsKey) ?? ""
        return locales.first { $0.id == id } ?? locales[0]
    }

    static func remember(_ locale: VoiceLocale, in defaults: UserDefaults = .standard) {
        defaults.set(locale.id, forKey: defaultsKey)
    }

    /// Why dictation cannot start, with the fix; nil when it can. The caller reads the three
    /// facts from `SFSpeechRecognizer`. Server recognition is never a fallback: audio stays on the device.
    static func problem(for locale: VoiceLocale, hasRecognizer: Bool, supportsOnDevice: Bool,
                        isAvailable: Bool) -> String? {
        guard hasRecognizer else { return "\(locale.name) is not supported for dictation on this Mac." }
        guard supportsOnDevice else {
            return "\(locale.name) dictation is not installed on this Mac. Fix: System Settings → Keyboard → "
                + "Dictation: add the language. Teyla never sends audio to a server."
        }
        guard isAvailable else { return "\(locale.name) dictation is not available right now. Try again in a moment." }
        return nil
    }

    static let speechDeniedMessage =
        "Speech recognition is off for Teyla. Fix: System Settings → Privacy & Security → Speech Recognition: turn on Teyla."
    static let microphoneDeniedMessage =
        "The microphone is off for Teyla. Fix: System Settings → Privacy & Security → Microphone: turn on Teyla."

    /// The text field value while dictating: what was typed before, then what was heard.
    static func merged(base: String, heard: String) -> String {
        let spoken = heard.trimmingCharacters(in: .whitespacesAndNewlines)
        if spoken.isEmpty { return base }
        let typed = base.trimmingCharacters(in: .whitespaces)
        return typed.isEmpty ? spoken : typed + " " + spoken
    }
}

/// The text of a field while it is dictated into. Recognition results are cumulative, so each one is
/// written over the field; words typed since the last write are kept by taking the field as the new base
/// and writing only the words heard after that point. Words are counted, not compared: the recognizer
/// may revise the ones it already gave (case, punctuation, a better guess), and a revision must not
/// bring them back after the owner edited the field.
struct DictationText: Equatable {
    private var base: String
    private var wordsBefore = 0
    private var lastHeard = ""
    private var lastWritten: String

    init(base: String) {
        self.base = base
        lastWritten = base
    }

    /// The full text for the field, given everything heard so far and what the field holds now.
    mutating func text(heard: String, field: String) -> String {
        if field != lastWritten {
            base = field
            wordsBefore = Self.words(lastHeard).count
        }
        lastHeard = heard
        let spoken = Self.words(heard).dropFirst(wordsBefore).joined(separator: " ")
        let merged = Voice.merged(base: base, heard: spoken)
        lastWritten = merged
        return merged
    }

    private static func words(_ text: String) -> [String] {
        text.split(whereSeparator: \.isWhitespace).map(String.init)
    }
}

/// Push-to-talk on a button or a key: hold to talk, or tap to start and tap again to stop.
/// A press that is held for `holdThreshold` or longer stops on release; a shorter press keeps listening.
struct PushToTalk: Equatable {
    enum Action: Equatable { case none, start, stop }

    static let holdThreshold: TimeInterval = 0.5

    private var pressedAt: Date?
    private var startedByThisPress = false

    mutating func press(at now: Date, listening: Bool) -> Action {
        guard pressedAt == nil else { return .none }   // key repeat or a second mouse-down
        pressedAt = now
        if listening {
            startedByThisPress = false
            return .stop
        }
        startedByThisPress = true
        return .start
    }

    mutating func release(at now: Date) -> Action {
        defer { pressedAt = nil; startedByThisPress = false }
        guard let pressedAt, startedByThisPress else { return .none }
        return now.timeIntervalSince(pressedAt) >= Self.holdThreshold ? .stop : .none
    }
}
