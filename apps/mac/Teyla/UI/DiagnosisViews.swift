import SwiftUI

/// What the first run shows: the promise and one button, then the diagnosis, then the offers.

// MARK: Run control

/// The promise, the Run button, and the progress and failure states. Shared by the welcome and the Diagnosis page.
struct DiagnosisRunPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let run = model.firstRun
        VStack(spacing: Space.l) {
            switch run.phase {
            case .running:
                progress(since: run.startedAt ?? Date())
            case .failed(let message):
                Label("The diagnosis stopped", systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.lead)
                    .foregroundStyle(Palette.danger)
                Text(message)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                runButton("Try again")
            case .idle, .ready:
                runButton("Run diagnosis")
                Text(FirstRun.runNote)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: Space.readingWidth)
    }

    private func runButton(_ title: String) -> some View {
        Button(title) { model.runDiagnosis() }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .keyboardShortcut(.defaultAction)
    }

    private func progress(since start: Date) -> some View {
        VStack(spacing: Space.s) {
            ProgressView()
                .controlSize(.regular)
            TimelineView(.periodic(from: start, by: 1)) { context in
                Text("Reading your sessions… \(max(0, Int(context.date.timeIntervalSince(start)))) s")
                    .font(Typo.lead)
                    .monospacedDigit()
            }
            Text("This takes up to a minute on a large machine. Nothing is changed.")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: Welcome

/// A machine Teyla has not seen at work: the lockup, the one-line promise, one button.
struct WelcomeView: View {
    var body: some View {
        VStack(spacing: Space.xl) {
            BrandLockup()
            Text(FirstRun.promise)
                .font(Typo.lead)
                .lineSpacing(Space.xxs)
                .multilineTextAlignment(.center)
                .frame(maxWidth: Space.readingWidth)
                .fixedSize(horizontal: false, vertical: true)
            DiagnosisRunPanel()
        }
        .padding(Space.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.background)
    }
}

// MARK: The Diagnosis page

struct DiagnosisView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let run = model.firstRun
        ScrollView {
            VStack(alignment: .leading, spacing: Space.xl) {
                if let report = run.report {
                    DiagnosisReport(report: report)
                } else {
                    VStack(spacing: Space.xl) {
                        Text("Diagnosis")
                            .font(Typo.brief)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Text(FirstRun.promise)
                            .foregroundStyle(Palette.textSecondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .fixedSize(horizontal: false, vertical: true)
                        DiagnosisRunPanel()
                            .frame(maxWidth: .infinity)
                            .padding(.top, Space.l)
                    }
                }
            }
            .padding(.horizontal, Space.xl + Space.xs)
            .padding(.vertical, Space.xl)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Palette.background)
        .navigationTitle("Diagnosis")
        .sheet(item: Bindable(run).pending) { offer in
            ConfirmApplySheet(offer: offer)
                .environment(model)
        }
    }
}

private struct DiagnosisReport: View {
    @Environment(AppModel.self) private var model
    let report: StartReport

    var body: some View {
        let d = report.diagnosis
        VStack(alignment: .leading, spacing: Space.xl) {
            VStack(alignment: .leading, spacing: Space.s) {
                SectionLabel("Diagnosis · last \(d.days) days")
                if d.empty {
                    Text("Teyla found no sessions in the last \(d.days) days.")
                        .font(Typo.brief)
                    Text("Use Claude Code or Codex for a while, then run the diagnosis again. Nothing was changed.")
                        .foregroundStyle(Palette.textSecondary)
                } else {
                    Text(Format.spent(d.totalUSD))
                        .font(Typo.display)
                        .monospacedDigit()
                    Text("at API list price · \(d.scope)")
                        .foregroundStyle(Palette.textSecondary)
                    VStack(alignment: .leading, spacing: Space.xs) {
                        ForEach(d.lines, id: \.self) { line in
                            Label(line, systemImage: "circle.fill")
                                .labelStyle(BulletLabelStyle())
                        }
                    }
                    .padding(.top, Space.xs)
                    if !d.note.isEmpty {
                        Text(d.note)
                            .font(Typo.caption)
                            .foregroundStyle(Palette.textSecondary)
                    }
                }
            }
            offers
            HStack {
                Button("Run again") { model.firstRun.run() }
                    .disabled(model.firstRun.isRunning)
                Text("Reads the session files again and changes nothing.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
    }

    @ViewBuilder
    private var offers: some View {
        let applicable = report.applicable
        VStack(alignment: .leading, spacing: Space.m) {
            SectionLabel(applicable.isEmpty ? "What Teyla can change" : "What Teyla can change · \(applicable.count)")
            if applicable.isEmpty {
                Label("Nothing to change right now.", systemImage: "checkmark.circle")
                    .foregroundStyle(Palette.textSecondary)
            }
            ForEach(applicable) { offer in
                OfferCard(offer: offer)
            }
            if !report.skipped.isEmpty {
                DisclosureGroup("Left out (\(report.skipped.count))") {
                    VStack(alignment: .leading, spacing: Space.s) {
                        ForEach(report.skipped) { offer in
                            VStack(alignment: .leading, spacing: Space.xxs) {
                                Text(offer.title).font(Typo.body.weight(.medium))
                                Text(offer.reason)
                                    .font(Typo.caption)
                                    .foregroundStyle(Palette.textSecondary)
                            }
                        }
                    }
                    .padding(.top, Space.s)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .foregroundStyle(Palette.textSecondary)
            }
        }
    }
}

private struct BulletLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            configuration.icon
                .font(.system(size: 5))
                .foregroundStyle(Palette.textSecondary)
                .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
            configuration.title
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: Offers

private struct OfferCard: View {
    @Environment(AppModel.self) private var model
    let offer: StartOffer

    var body: some View {
        let status = model.firstRun.status(of: offer)
        VStack(alignment: .leading, spacing: Space.m) {
            VStack(alignment: .leading, spacing: Space.xs) {
                Text(offer.title).font(Typo.lead)
                if !offer.gain.isEmpty {
                    Text(offer.gain)
                        .font(Typo.body.weight(.medium))
                        .foregroundStyle(offer.hasSaving ? Palette.saving : Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            fact("Trade-off", offer.tradeoff)
            fact("Undo", offer.undo, emphasised: offer.undoIsUninstall)
            if !offer.basis.isEmpty {
                DisclosureGroup("How this is worked out") {
                    Text(offer.basis)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                        .padding(.top, Space.xs)
                }
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
            }
            footer(status)
        }
        .card()
        .accessibilityElement(children: .contain)
    }

    private func fact(_ label: String, _ text: String, emphasised: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(label)
                .font(Typo.caption.weight(.semibold))
                .foregroundStyle(Palette.textSecondary)
            Text(text)
                .foregroundStyle(emphasised ? Palette.warning : Palette.text)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
    }

    @ViewBuilder
    private func footer(_ status: OfferStatus?) -> some View {
        switch status {
        case .applying:
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text("Applying…").foregroundStyle(Palette.textSecondary)
            }
        case .applied(let lines):
            VStack(alignment: .leading, spacing: Space.xs) {
                Label("Applied", systemImage: "checkmark.circle.fill")
                    .font(Typo.body.weight(.semibold))
                    .foregroundStyle(Palette.success)
                if !lines.isEmpty {
                    Text(lines)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
            }
        case .failed(let message):
            VStack(alignment: .leading, spacing: Space.s) {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(Palette.danger)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                HStack {
                    Button("Try again") { model.firstRun.ask(offer) }
                    Button("Back") { model.firstRun.dismissError(offer) }
                }
            }
        case nil:
            Button("Apply…") { model.firstRun.ask(offer) }
                .buttonStyle(.borderedProminent)
                .help("Shows what changes and asks once before anything is written")
        }
    }
}

/// One confirmation, naming the file and the key (or the command), and how to take it back.
struct ConfirmApplySheet: View {
    @Environment(AppModel.self) private var model
    let offer: StartOffer

    var body: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            Text("Apply “\(offer.title)”?")
                .font(Typo.lead)
                .fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: Space.s) {
                Text(offer.willChange)
                    .font(Typo.body.weight(.medium))
                    .textSelection(.enabled)
                if !offer.change.summary.isEmpty {
                    Text(offer.change.summary)
                        .font(.system(.callout, design: .monospaced))
                        .foregroundStyle(Palette.textSecondary)
                        .textSelection(.enabled)
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            Label {
                Text(offer.safety)
                    .fixedSize(horizontal: false, vertical: true)
            } icon: {
                Image(systemName: offer.undoIsUninstall ? "exclamationmark.triangle.fill" : "arrow.uturn.backward.circle")
            }
            .foregroundStyle(offer.undoIsUninstall ? Palette.warning : Palette.textSecondary)
            HStack {
                Spacer()
                Button("Cancel") { model.firstRun.cancel() }
                    .keyboardShortcut(.cancelAction)
                Button("Apply") { model.firstRun.confirm() }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(Space.xl)
        .frame(width: Space.readingWidth - Space.xxl)
        .accessibilityElement(children: .contain)
    }
}
