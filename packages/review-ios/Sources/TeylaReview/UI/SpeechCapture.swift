#if TEYLA_REVIEW && canImport(UIKit)
import AVFoundation
import Speech

/// Optional on-device dictation, off unless `TeylaReview.configure { $0.speech = true }`. The
/// keyboard's own microphone key is the first path and needs none of this. Audio is not kept.
/// The product's Info.plist needs NSSpeechRecognitionUsageDescription and NSMicrophoneUsageDescription.
final class SpeechCapture {
    var onText: ((String) -> Void)?

    private let recognizer: SFSpeechRecognizer?
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var running = false
    private var closed = false        // review mode closed: nothing may start any more

    init(locale: Locale = .current) {
        recognizer = SFSpeechRecognizer(locale: locale)
    }

    /// Only on-device recognition is used. A language without an on-device model is unavailable.
    var isAvailable: Bool { recognizer?.supportsOnDeviceRecognition == true }

    /// Takes the microphone. Returns false if permission is refused or the engine does not start.
    /// The guard is told, so it restores the session when review mode closes.
    /// Main actor, so nothing can suspend between the last cancellation check and the engine start.
    @MainActor
    func start(microphone: MicrophoneGuard) async -> Bool {
        guard let recognizer, isAvailable, !running, !closed else { return false }
        let speechOK = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
        guard speechOK, !closed, !Task.isCancelled else { return false }
        guard await AVAudioApplication.requestRecordPermission(), !closed, !Task.isCancelled else { return false }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        do {
            microphone.markTaken()
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: [])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let input = engine.inputNode
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in
                request.append(buffer)
            }
            engine.prepare()
            try engine.start()
        } catch {
            stop()
            return false
        }
        self.request = request
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            if let result {
                let heard = result.bestTranscription.formattedString
                DispatchQueue.main.async { self?.onText?(heard) }
            }
            if error != nil || result?.isFinal == true { DispatchQueue.main.async { self?.stop() } }
        }
        running = true
        return true
    }

    /// Review mode is closing: stop, and refuse any start that is still waiting for a permission answer.
    func shutdown() {
        closed = true
        stop()
    }

    func stop() {
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
        running = false
    }
}
#endif
