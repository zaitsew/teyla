import AVFoundation
import Observation
import Speech

/// Voice input. Speech is recognised on this Mac only (`requiresOnDeviceRecognition`); when the
/// language is not installed for on-device use, dictation says how to add it and does not start.
/// There is no server fallback. The recognised text goes into the field that asked for it, and
/// nothing is sent until the owner presses Send.
@MainActor
@Observable
final class Dictation {
    static let shared = Dictation()

    struct Problem: Equatable {
        let target: String
        let text: String
    }

    /// The field that is receiving text now, or nil when nothing is listening.
    private(set) var activeTarget: String?
    private(set) var problem: Problem?
    /// The language of the current or last session, shown while listening.
    private(set) var localeName = Voice.stored().name

    @ObservationIgnored private var engine: AVAudioEngine?
    @ObservationIgnored private var request: SFSpeechAudioBufferRecognitionRequest?
    @ObservationIgnored private var task: SFSpeechRecognitionTask?
    @ObservationIgnored private var recognizer: SFSpeechRecognizer?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var write: (@MainActor (String) -> Void)?
    @ObservationIgnored private var read: (@MainActor () -> String)?
    @ObservationIgnored private var text = DictationText(base: "")
    @ObservationIgnored private var heardAnything = false

    func isListening(_ target: String) -> Bool { activeTarget == target }

    func problem(for target: String) -> String? {
        problem?.target == target ? problem?.text : nil
    }

    /// Starts listening for `target`. `current` is the text already in the field, `read` returns what the field
    /// holds now (so words typed while listening are kept), and `write` receives the full new text.
    func start(target: String, current: String, read: @escaping @MainActor () -> String,
               write: @escaping @MainActor (String) -> Void) {
        endSession()
        generation += 1
        let mine = generation
        problem = nil
        text = DictationText(base: current)
        self.read = read
        self.write = write
        heardAnything = false
        let locale = Voice.stored()
        localeName = locale.name
        activeTarget = target
        Task { await begin(target: target, locale: locale, generation: mine) }
    }

    /// Stops listening. The words still in flight arrive and are written.
    func stop() {
        guard activeTarget != nil else { return }
        engine?.stop()
        engine?.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        engine = nil
        request = nil
        activeTarget = nil
    }

    // MARK: Session

    private func begin(target: String, locale: VoiceLocale, generation mine: Int) async {
        guard await Self.speechAuthorized() else { return fail(target, Voice.speechDeniedMessage, mine) }
        guard await Self.microphoneAllowed() else { return fail(target, Voice.microphoneDeniedMessage, mine) }
        // The owner may have released the key or the button while permissions were being checked.
        guard mine == generation, activeTarget == target else { return }

        let recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale.id))
        if let why = Voice.problem(for: locale, hasRecognizer: recognizer != nil,
                                   supportsOnDevice: recognizer?.supportsOnDeviceRecognition ?? false,
                                   isAvailable: recognizer?.isAvailable ?? false) {
            return fail(target, why, mine)
        }
        guard let recognizer else { return }

        let engine = AVAudioEngine()
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else { return fail(target, "No microphone input was found.", mine) }
        input.installTap(onBus: 0, bufferSize: 1024, format: format, block: Self.tap(request))
        engine.prepare()
        do { try engine.start() } catch {
            input.removeTap(onBus: 0)
            return fail(target, "Could not start the microphone: \(error.localizedDescription)", mine)
        }
        self.recognizer = recognizer
        self.engine = engine
        self.request = request
        task = recognizer.recognitionTask(with: request, resultHandler: Self.results { [weak self] heard, final, failure in
            Task { @MainActor in self?.received(heard, final: final, failure: failure, generation: mine) }
        })
    }

    private func received(_ heard: String?, final: Bool, failure: String?, generation mine: Int) {
        guard mine == generation else { return }
        if let heard, !heard.isEmpty {
            heardAnything = true
            if let write, let read { write(text.text(heard: heard, field: read())) }
        }
        if final || failure != nil {
            if let failure, !heardAnything, activeTarget != nil, let target = activeTarget {
                problem = Problem(target: target, text: "Dictation stopped: \(failure)")
            }
            stop()
            task = nil
            write = nil
            read = nil
        }
    }

    private func fail(_ target: String, _ text: String, _ mine: Int) {
        guard mine == generation else { return }
        problem = Problem(target: target, text: text)
        activeTarget = nil
        write = nil
        read = nil
    }

    private func endSession() {
        stop()
        task?.cancel()
        task = nil
        write = nil
        read = nil
    }

    // MARK: Callbacks that run off the main actor

    nonisolated private static func tap(_ request: SFSpeechAudioBufferRecognitionRequest) -> AVAudioNodeTapBlock {
        nonisolated(unsafe) let request = request
        return { buffer, _ in request.append(buffer) }
    }

    nonisolated private static func results(
        _ deliver: @escaping @Sendable (String?, Bool, String?) -> Void
    ) -> @Sendable (SFSpeechRecognitionResult?, Error?) -> Void {
        { result, error in
            deliver(result?.bestTranscription.formattedString, result?.isFinal ?? false, error?.localizedDescription)
        }
    }

    nonisolated private static func speechAuthorized() async -> Bool {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0 == .authorized) }
        }
    }

    nonisolated private static func microphoneAllowed() async -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return true
        case .notDetermined: return await AVCaptureDevice.requestAccess(for: .audio)
        default: return false
        }
    }
}
