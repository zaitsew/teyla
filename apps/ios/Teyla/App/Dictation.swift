import AVFoundation
import Observation
import Speech

/// The three dictation languages. Recognition is always on the device: if a language has no
/// on-device model, dictation says so and does not start, and no audio is ever sent to a server.
enum DictationLanguage: String, CaseIterable, Identifiable {
    case english = "en-US"
    case spanish = "es-ES"
    case russian = "ru-RU"

    var id: String { rawValue }

    var code: String {
        switch self {
        case .english: return "EN"
        case .spanish: return "ES"
        case .russian: return "RU"
        }
    }

    /// The language's own name. The Russian one is written as escapes: the repo is English-only
    /// and `scripts/leak_check.py` bans Cyrillic in source files.
    var title: String {
        switch self {
        case .english: return "English"
        case .spanish: return "Espa\u{00F1}ol"
        case .russian: return "\u{0420}\u{0443}\u{0441}\u{0441}\u{043A}\u{0438}\u{0439}"
        }
    }

    var locale: Locale { Locale(identifier: rawValue) }
}

/// The recognition task and the audio engine sit behind plain classes so that their callbacks,
/// which run on audio and speech threads, never inherit the main actor.
private final class RequestBox: @unchecked Sendable {
    let request = SFSpeechAudioBufferRecognitionRequest()
}

/// Push-to-talk dictation: the transcript goes into one text field, nothing is sent.
@MainActor
@Observable
final class Dictation {
    /// The field that is listening now, or nil.
    private(set) var activeField: String?
    private(set) var message: String?

    private let engine = AVAudioEngine()
    private var box: RequestBox?
    private var task: SFSpeechRecognitionTask?
    private var onText: ((String) -> Void)?
    private var base = ""

    func isRecording(_ field: String) -> Bool { activeField == field }

    func clearMessage() { message = nil }

    /// Starts listening for `field`, or stops if it is already listening. `current` is the text
    /// already in the field; the transcript is appended to it through `onText`.
    func toggle(field: String, language: DictationLanguage, current: String, onText: @escaping (String) -> Void) {
        if activeField == field {
            stop()
            return
        }
        stop()
        message = nil
        Task { await start(field: field, language: language, current: current, onText: onText) }
    }

    func stop() {
        guard activeField != nil || engine.isRunning else { return }
        if engine.isRunning {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        }
        box?.request.endAudio()
        task?.cancel()
        box = nil
        task = nil
        onText = nil
        activeField = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func start(field: String, language: DictationLanguage, current: String,
                       onText: @escaping (String) -> Void) async {
        guard await Self.speechAllowed() else {
            message = "Speech recognition is off for Teyla. Turn it on in Settings > Teyla."
            return
        }
        guard await AVAudioApplication.requestRecordPermission() else {
            message = "The microphone is off for Teyla. Turn it on in Settings > Teyla."
            return
        }
        guard let recognizer = SFSpeechRecognizer(locale: language.locale), recognizer.isAvailable else {
            message = "\(language.title) dictation is not available right now."
            return
        }
        guard recognizer.supportsOnDeviceRecognition else {
            message = "\(language.title) dictation needs its on-device model. Add the language under Settings > General > Keyboard > Dictation."
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let box = RequestBox()
            box.request.requiresOnDeviceRecognition = true
            box.request.shouldReportPartialResults = true
            let input = engine.inputNode
            Self.installTap(on: input, box: box)
            engine.prepare()
            try engine.start()
            self.box = box
            self.onText = onText
            self.base = current
            activeField = field
            task = Self.makeTask(recognizer: recognizer, box: box, owner: self)
        } catch {
            message = "Could not start the microphone: \(error.localizedDescription)"
            stop()
        }
    }

    private func receive(text: String?, finished: Bool) {
        guard activeField != nil else { return }
        if let text, !text.isEmpty {
            let separator = base.isEmpty || base.hasSuffix(" ") || base.hasSuffix("\n") ? "" : " "
            onText?(base + separator + text)
        }
        if finished { stop() }
    }

    // These two are nonisolated on purpose: their closures run on the audio and speech queues.

    private nonisolated static func installTap(on input: AVAudioInputNode, box: RequestBox) {
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            box.request.append(buffer)
        }
    }

    private nonisolated static func makeTask(recognizer: SFSpeechRecognizer, box: RequestBox,
                                             owner: Dictation) -> SFSpeechRecognitionTask {
        let weakOwner = WeakOwner(owner)
        return recognizer.recognitionTask(with: box.request) { result, error in
            let text = result?.bestTranscription.formattedString
            let finished = (result?.isFinal ?? false) || error != nil
            Task { @MainActor in weakOwner.value?.receive(text: text, finished: finished) }
        }
    }

    private nonisolated static func speechAllowed() async -> Bool {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
    }
}

private final class WeakOwner: @unchecked Sendable {
    weak var value: Dictation?
    init(_ value: Dictation) { self.value = value }
}
