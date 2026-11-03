#if TEYLA_REVIEW && canImport(UIKit)
import SwiftUI
import UIKit

/// Review mode. The frozen app shrinks into a framed picture so the mode cannot be mistaken for a
/// hang, and the owner goes through three steps: point at something, say what is wrong, see what
/// became of it. The picture is scaled, but every point kept here is a window point, so the anchors'
/// bounds and the capture stay in the coordinates the format promises.
struct ReviewOverlay: View {
    let image: UIImage
    let size: CGSize
    let anchors: [Anchor]
    let probe: (CGPoint) -> (identifier: String?, label: String?)
    let speechEnabled: Bool
    let microphone: MicrophoneGuard
    let speech: SpeechCapture
    let strings: ReviewStrings
    let onClose: () -> Void
    /// Saves the draft and reports the outcome. While it runs the overlay accepts no edits. A
    /// failed save leaves the overlay editable with the text kept.
    let onSend: (ReviewDraft, @escaping (ReviewSaveOutcome) -> Void) -> Void

    private enum Step: Equatable { case point, comment, done(ReviewSaveOutcome) }

    @State private var step = Step.point
    @State private var entered = false
    @State private var tap: CGPoint?
    @State private var region: CGRect?
    @State private var drawing: CGRect?
    @State private var stroke: (start: CGPoint, bounds: CGRect)?
    @State private var hit: Anchor?
    @State private var identifier: String?
    @State private var label: String?
    @State private var text = ""
    @State private var input: CommentInfo.Input = .text
    @State private var listening = false
    @State private var microphoneFailed = false
    @State private var speechTask: Task<Void, Never>?
    @State private var sending = false
    @State private var failure: String?
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            if entered {
                banner.transition(.move(edge: .top).combined(with: .opacity))
            }
            stage
            if entered {
                panel.transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        // The first frame fills the window, the picture exactly over the app it froze. Then the
        // safe area and the keyboard apply, so the panel never sits under either.
        .ignoresSafeArea(.container, edges: entered ? [] : .all)
        .background(Color(uiColor: .secondarySystemBackground).ignoresSafeArea())
        .onAppear { withAnimation(.spring(duration: 0.35)) { entered = true } }
        .onDisappear { stopListening() }
    }

    // MARK: the banner

    private var banner: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(strings.modeTitle)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(Color.accentColor, in: Capsule())
                .accessibilityIdentifier("teyla.review.banner")
            Text(bannerHint)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }

    private var bannerHint: String {
        step == .point ? strings.modeHint : ""
    }

    // MARK: the picture

    private var stage: some View {
        GeometryReader { geo in
            let inset: CGFloat = entered ? 12 : 0
            let available = CGSize(width: geo.size.width - 2 * inset, height: geo.size.height - 2 * inset)
            let scale = ReviewGeometry.fit(size, in: available)
            picture(scale: scale)
                .position(x: geo.size.width / 2, y: geo.size.height / 2)
        }
    }

    private func picture(scale: CGFloat) -> some View {
        let shape = RoundedRectangle(cornerRadius: entered ? 16 : 0, style: .continuous)
        return ZStack(alignment: .topLeading) {
            Image(uiImage: image)
                .resizable()
                .frame(width: size.width * scale, height: size.height * scale)
                .gesture(touch(scale: scale))
                .accessibilityHidden(true)
            marks(scale: scale)
        }
        .frame(width: size.width * scale, height: size.height * scale, alignment: .topLeading)
        .clipShape(shape)
        .overlay {
            if entered {
                shape.strokeBorder(Color.accentColor, lineWidth: 3).allowsHitTesting(false)
            }
        }
    }

    /// The bounds of the stroke so far. A new start point begins a new stroke, so a stroke the system
    /// cancelled, which never reaches `onEnded`, does not grow into the next one.
    private func strokeBounds(_ value: DragGesture.Value) -> CGRect {
        let earlier = stroke?.start == value.startLocation ? stroke?.bounds : nil
        return ReviewGeometry.grow(earlier ?? CGRect(origin: value.startLocation, size: .zero), with: value.location)
    }

    private func touch(scale: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                guard step == .point else { return }
                let bounds = strokeBounds(value)
                stroke = (value.startLocation, bounds)
                drawing = ReviewGeometry.region(stroke: bounds, scale: scale, window: size)
            }
            .onEnded { value in
                switch step {
                case .point:
                    let bounds = strokeBounds(value)
                    stroke = nil
                    drawing = nil
                    if let area = ReviewGeometry.region(stroke: bounds, scale: scale, window: size) {
                        select(area: area)
                    } else {
                        select(point: ReviewGeometry.toWindow(value.location, scale: scale, window: size), area: nil)
                    }
                case .comment:
                    focused = false
                case .done:
                    break
                }
            }
    }

    @ViewBuilder
    private func marks(scale: CGFloat) -> some View {
        if let area = drawing ?? region {
            areaMark(area, scale: scale)
        } else {
            if let r = hit?.bounds {
                areaMark(r, scale: scale)
            }
            if let p = tap {
                Circle()
                    .fill(Color.accentColor)
                    .overlay(Circle().stroke(.white, lineWidth: 2))
                    .frame(width: 18, height: 18)
                    .position(x: p.x * scale, y: p.y * scale)
                    .allowsHitTesting(false)
            }
        }
    }

    private func areaMark(_ r: CGRect, scale: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: 6, style: .continuous)
            .strokeBorder(Color.accentColor, lineWidth: 2.5)
            .background(Color.accentColor.opacity(0.15), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            .frame(width: max(r.width * scale, 1), height: max(r.height * scale, 1))
            .position(x: r.midX * scale, y: r.midY * scale)
            .allowsHitTesting(false)
    }

    // MARK: the panel

    @ViewBuilder
    private var panel: some View {
        VStack(alignment: .leading, spacing: 10) {
            switch step {
            case .point: pointPanel
            case .comment: commentPanel
            case .done(let outcome): donePanel(outcome)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(.regularMaterial, ignoresSafeAreaEdges: .bottom)
    }

    private var selection: String? {
        if region != nil { return strings.areaChosen }
        if tap != nil { return strings.spotChosen }
        return nil
    }

    private var pointPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            // The line is always there: if it appeared on the first touch, the picture would
            // shrink under the finger and the mark would land away from where the owner pointed.
            Text(selection ?? " ")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            HStack {
                Button(strings.exit, action: onClose)
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("teyla.review.exit")
                Spacer()
                Button(selection == nil ? strings.wholeScreen : strings.next) {
                    withAnimation(.easeInOut(duration: 0.2)) { step = .comment }
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("teyla.review.next")
            }
        }
    }

    private var canDictate: Bool { speechEnabled && speech.isAvailable }

    private var commentPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(strings.commentTitle)
                .font(.subheadline.weight(.semibold))
            HStack(alignment: .bottom, spacing: 8) {
                TextField(strings.placeholder, text: $text, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(Color(uiColor: .systemBackground), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .focused($focused)
                    .disabled(sending)
                    .accessibilityIdentifier("teyla.review.comment")
                    .onAppear { focused = true }
                if canDictate {
                    Button(action: toggleListening) {
                        Image(systemName: listening ? "stop.fill" : "mic.fill")
                            .frame(width: 24, height: 24)
                    }
                    .buttonStyle(.bordered)
                    .tint(listening ? .red : .accentColor)
                    .disabled(sending)
                    .accessibilityLabel(strings.dictate)
                    .accessibilityIdentifier("teyla.review.dictate")
                }
            }
            if listening {
                Text(strings.listening)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else if microphoneFailed {
                Text(strings.microphoneUnavailable)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if let failure {
                Text(failure)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .accessibilityIdentifier("teyla.review.error")
            }
            HStack {
                Button(strings.back) {
                    stopListening()
                    focused = false
                    withAnimation(.easeInOut(duration: 0.2)) { step = .point }
                }
                .buttonStyle(.bordered)
                .disabled(sending)
                .accessibilityIdentifier("teyla.review.back")
                Spacer()
                if sending {
                    ProgressView()
                        .accessibilityIdentifier("teyla.review.saving")
                }
                Button(sending ? strings.saving : (failure == nil ? strings.send : strings.retry)) { send() }
                    .buttonStyle(.borderedProminent)
                    .disabled(sending || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityIdentifier("teyla.review.send")
            }
        }
    }

    private func donePanel(_ outcome: ReviewSaveOutcome) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(outcome == .sent ? strings.sentTitle : strings.savedTitle,
                  systemImage: outcome == .sent ? "checkmark.circle.fill" : "iphone")
                .font(.subheadline.weight(.semibold))
                .accessibilityIdentifier("teyla.review.outcome")
            Text(outcome == .sent ? strings.sentDetail : strings.savedDetail)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button(strings.done, action: onClose)
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("teyla.review.done")
            }
        }
    }

    // MARK: what the owner does

    private func select(area: CGRect) {
        select(point: CGPoint(x: area.midX, y: area.midY), area: area)
    }

    private func select(point: CGPoint, area: CGRect?) {
        focused = false
        tap = point
        region = area
        hit = HitTester.hit(x: Double(point.x), y: Double(point.y), in: anchors)
        let found = probe(point)
        identifier = found.identifier
        label = found.label
    }

    private func toggleListening() {
        if listening { stopListening(); return }
        focused = false
        microphoneFailed = false
        // Dictation adds to what is already typed, and never replaces it.
        let typed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        speech.onText = { heard in
            guard !sending else { return }      // a late result must not change the text being saved
            text = typed.isEmpty ? heard : typed + " " + heard
            input = .speech
        }
        speech.onEnd = { listening = false }
        speechTask?.cancel()
        speechTask = Task {
            let started = await speech.start(microphone: microphone)
            if Task.isCancelled { speech.stop(); return }
            listening = started
            microphoneFailed = !started
        }
    }

    /// Also cancels a start that is still waiting for a permission answer, so recording cannot
    /// begin after the owner left the overlay.
    private func stopListening() {
        speechTask?.cancel()
        speechTask = nil
        guard listening else { return }
        speech.stop()
        listening = false
    }

    private func send() {
        stopListening()
        let comment = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !comment.isEmpty, !sending else { return }
        sending = true
        focused = false
        failure = nil
        let draft = ReviewDraft(tap: tap, region: region, hit: hit, accessibilityIdentifier: identifier,
                                accessibilityLabel: label, text: comment, input: input)
        onSend(draft) { outcome in
            sending = false
            if outcome == .failed {
                failure = strings.saveFailed
            } else {
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                withAnimation(.easeInOut(duration: 0.2)) { step = .done(outcome) }
            }
        }
    }
}
#endif
