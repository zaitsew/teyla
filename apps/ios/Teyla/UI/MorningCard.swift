import SwiftUI

/// The Morning post card (Lab): one question, an answer by keyboard or voice, one LinkedIn and one X draft made on this iPhone.
/// The app never posts. "Copy + open" hands the text to LinkedIn or X; the owner posts it there. The record is device only
/// (`teyla.morningCard.v1` in UserDefaults), and nothing goes to the relay. Shown only while the Lab switch is on.
struct MorningCardHost: View {
    @AppStorage(MorningCardLogic.labKey) private var on = false

    var body: some View {
        if on { MorningCard() }
    }
}

struct MorningCard: View {
    @Environment(AppModel.self) private var model
    @Environment(Dictation.self) private var dictation
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("dictationLanguage") private var languageID = DictationLanguage.english.rawValue

    @State private var state = MorningCardLogic.load()
    @State private var drafting = false
    @State private var linkText = ""
    @State private var holding = false
    @State private var holdTimer: Task<Void, Never>?
    @FocusState private var focused: Bool

    private let field = "morning-card"
    private var language: DictationLanguage { DictationLanguage(rawValue: languageID) ?? .english }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Morning post")
            if let ask = state.linkAsk { linkAsk(ask) }
            if state.posted != nil {
                Text("Posted today. Add the link tomorrow.")
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
            } else if drafting {
                HStack(spacing: Space.s) {
                    ProgressView()
                    Text("Drafting on this iPhone").font(Typo.body).foregroundStyle(Palette.textSecondary)
                }
            } else if state.hasDrafts {
                drafts
            } else {
                answer
            }
        }
        .card()
        .accessibilityElement(children: .contain)
        .onChange(of: state) { _, new in MorningCardLogic.save(new) }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { state = MorningCardLogic.load() } else { endHold() }
        }
        .onDisappear { endHold() }
    }

    // MARK: Link of yesterday's post

    private func linkAsk(_ record: PostedRecord) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Yesterday\u{2019}s post link").font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
            TextField("https://", text: $linkText)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .padding(Space.m)
                .background(Palette.track, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
            HStack(spacing: Space.m) {
                Button("Save") {
                    if state.saveLink(linkText) { linkText = "" }
                }
                .buttonStyle(.borderedProminent)
                .disabled(MorningCardLogic.validPostURL(linkText) == nil)
                Button("Skip") { state.skipLink() }
                    .buttonStyle(.bordered)
            }
            if !linkText.isEmpty, MorningCardLogic.validPostURL(linkText) == nil {
                Text("Use an https link from LinkedIn or X.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            Divider()
        }
    }

    // MARK: Answer

    private var answer: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Text(MorningCardLogic.prompt(snapshot: model.snapshot))
                .font(Typo.cardTitle)
                .fixedSize(horizontal: false, vertical: true)
            HStack(alignment: .bottom, spacing: Space.s) {
                TextField("Your words", text: $state.answer, axis: .vertical)
                    .lineLimit(3...10)
                    .focused($focused)
                    .padding(.leading, Space.m)
                    .padding(.vertical, Space.s)
                holdToTalk
            }
            .background(Palette.track, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
            if let message = dictation.message {
                Text(message).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            Button("Draft") { Task { await makeDrafts() } }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(state.answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
    }

    private var holdToTalk: some View {
        Image(systemName: holding ? "mic.circle.fill" : "mic.fill")
            .font(Glyph.mic)
            .foregroundStyle(holding ? Palette.danger : Palette.primary)
            .frame(width: Space.touchMin, height: Space.touchMin)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in if !holding { beginHold() } }
                    .onEnded { _ in endHold() }
            )
            .accessibilityLabel(holding ? "Recording. Release to stop." : "Hold to talk")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction(named: holding ? "Stop" : "Record") {
                if holding { endHold() } else { beginHold() }
            }
    }

    private func beginHold() {
        holding = true
        focused = false
        dictation.begin(field: field, language: language, current: state.answer) { state.answer = $0 }
        holdTimer?.cancel()
        holdTimer = Task {
            try? await Task.sleep(for: .seconds(MorningCardLogic.secondsLimit))
            if !Task.isCancelled { endHold() }
        }
    }

    private func endHold() {
        holdTimer?.cancel()
        holdTimer = nil
        guard holding else { return }
        holding = false
        dictation.stop()
    }

    private func makeDrafts() async {
        endHold()
        focused = false
        drafting = true
        let draft = await PostDrafter.draft(note: state.answer)
        state.linkedIn = draft.linkedIn
        state.x = draft.x
        state.source = draft.source.rawValue
        drafting = false
    }

    // MARK: Drafts

    private var drafts: some View {
        let x = state.x ?? ""
        return VStack(alignment: .leading, spacing: Space.m) {
            block("LinkedIn", text: Binding(get: { state.linkedIn ?? "" }, set: { state.linkedIn = $0 }), count: nil)
            block("X", text: Binding(get: { state.x ?? "" }, set: { state.x = $0 }), count: x.count)
            Text("Drafted on this iPhone" + (state.source == PostDraft.Source.cutter.rawValue
                 ? " \u{00B7} cut from your words, Apple Intelligence was not available" : ""))
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: Space.s) {
                Button("Copy + open LinkedIn") {
                    UIPasteboard.general.string = state.linkedIn ?? ""
                    state.markCopied(.linkedIn)
                    openURL(MorningCardLogic.linkedInURL)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                Button("Copy + open X") {
                    UIPasteboard.general.string = state.x ?? ""
                    state.markCopied(.x)
                    if let url = MorningCardLogic.xIntentURL(text: state.x ?? "") { openURL(url) }
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                Button("Posted") { state.markPosted() }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(state.copied.isEmpty)
            }
            Button("Redo") {
                state.linkedIn = nil
                state.x = nil
                state.source = nil
                state.copied = []
            }
            .font(Typo.caption)
        }
    }

    private func block(_ title: String, text: Binding<String>, count: Int?) -> some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
                Spacer(minLength: Space.s)
                if let count {
                    Text("\(count)/\(PostRules.xLimit)")
                        .font(Typo.caption.monospacedDigit())
                        .foregroundStyle(count > PostRules.xLimit ? Palette.danger : Palette.textSecondary)
                }
            }
            TextField(title, text: text, axis: .vertical)
                .lineLimit(3...14)
                .padding(Space.m)
                .background(Palette.track, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        }
    }
}
