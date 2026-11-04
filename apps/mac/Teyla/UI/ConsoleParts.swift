import SwiftUI

/// The header every admin page shares: its title, the question it answers, when it was read, and a way to read again.
struct ConsoleHeader: View {
    @Environment(AppModel.self) private var model
    let page: ConsoleText.Page

    var body: some View {
        let console = model.console
        TimelineView(.periodic(from: .now, by: 30)) { context in
            PageHeader(title: page.title, context: page.question) {
                HStack(spacing: Space.m) {
                    if console.isLoading {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(ConsoleText.updated(generated: console.report?.generated, readAt: console.readAt, now: context.date))
                            .font(Typo.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .lineLimit(1)
                    }
                    Button("Check again") { console.refresh(rebuild: true) }
                        .disabled(console.isLoading)
                }
            }
        }
    }
}

/// One section of the report: the data when it loaded, its own error when its source failed, a dash-style note when
/// the key is missing, or the state of the read. Other sections keep working whatever this one does.
struct ConsoleBlock<Value: Equatable & Sendable, Content: View>: View {
    @Environment(AppModel.self) private var model
    let name: String
    let pick: (ConsoleReport) -> ConsoleLoad<Value>
    @ViewBuilder var content: (Value) -> Content

    var body: some View {
        let console = model.console
        if let report = console.report {
            if let why = console.failure { ClampedText(text: "\(ConsoleText.staleNote) \(why)", lines: 2, font: Typo.caption) }
            switch pick(report) {
            case .data(let value):
                content(value)
            case .failed(let why):
                ErrorRow(section: name, message: why) { console.refresh(rebuild: true) }
            case .missing:
                EmptyState(symbol: "questionmark.circle", title: ConsoleText.missing(name))
            }
        } else if let why = console.failure {
            ErrorRow(section: name, message: why) { console.refresh(rebuild: true) }
        } else {
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text("Reading \(name)…").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        }
    }
}

/// The headline of a section as one tile. A figure the source does not know is a dash, and the small line says why.
struct HeadlineTile: View {
    let headline: ConsoleHeadline?
    var tone = StatTone.neutral

    var body: some View {
        StatTile(label: headline?.label ?? "Not read", value: headline?.display,
                 detail: headline?.detail ?? "The source gave no figure.", tone: tone)
    }
}
