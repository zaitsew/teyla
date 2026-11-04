import SwiftUI

/// Tools: what is wrong on this Mac's backend now (`teyla attention`), with the actions that exist for it.
/// "Nothing needs you here" appears only for a report that was read and is empty. A failed read says so.
struct ToolsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let tools = model.tools
        ScrollViewReader { reader in
            ScrollView {
                VStack(alignment: .leading, spacing: Space.xl) {
                    header(tools)
                    if let notice = tools.notice { Notice(text: notice) { tools.dismissNotice() } }
                    if let why = tools.failure { ReadFailure(message: why) }
                    if let report = tools.report {
                        let (act, info) = ToolsPage.sections(report)
                        if !act.isEmpty { section("Needs you", items: act) }
                        if !info.isEmpty { section("Worth a look", items: info) }
                        if report.items.isEmpty, tools.failure == nil { quiet(report) }
                    } else if tools.isLoading {
                        HStack(spacing: Space.s) {
                            ProgressView().controlSize(.small)
                            Text("This reads local files only and can take half a minute.")
                                .font(Typo.caption)
                                .foregroundStyle(Palette.textSecondary)
                        }
                    }
                    if model.capabilities.diagnosis { diagnosis }
                }
                .padding(.horizontal, Space.page)
                .padding(.vertical, Space.xl)
                .readingWidth()
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: tools.focusedItemID, initial: true) { _, id in
                guard let id else { return }
                withAnimation(.easeOut(duration: 0.25)) { reader.scrollTo(id, anchor: .top) }
            }
        }
        .background(Palette.background)
        .navigationTitle("Tools")
        .onAppear { tools.opened() }
    }

    private func header(_ tools: ToolsModel) -> some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Text("Tools").font(Typo.pageTitle)
            Text(ToolsPage.headline(report: tools.report, phase: tools.phase))
                .font(Typo.body)
                .foregroundStyle(tools.failure == nil ? Palette.textSecondary : Palette.danger)
            HStack(spacing: Space.s) {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    let age = ToolsPage.ageLine(readAt: tools.readAt, now: context.date)
                    if !age.isEmpty { Text(age).font(Typo.caption).foregroundStyle(Palette.textSecondary) }
                }
                Button("Check again") { tools.refresh() }
                    .buttonStyle(.borderless)
                    .font(Typo.caption)
                    .disabled(tools.isLoading)
            }
        }
    }

    private func section(_ title: String, items: [AttentionItem]) -> some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionLabel(title)
            ForEach(items) { item in
                ToolCard(item: item)
            }
        }
    }

    private func quiet(_ report: AttentionReport) -> some View {
        let line = report.quietLine
        return Group {
            if !line.isEmpty {
                Text("Checked and fine: \(line).")
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var diagnosis: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            SectionLabel("First-run diagnosis")
            Text("Read 30 days of sessions and see which changes would save money. Nothing is changed until you say so.")
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Open diagnosis") { model.go(.diagnosis) }
                .buttonStyle(.link)
        }
    }
}

/// One thing that is wrong, in a sentence, with what is known and the actions that exist.
private struct ToolCard: View {
    @Environment(AppModel.self) private var model
    let item: AttentionItem

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                Image(systemName: item.symbol)
                    .foregroundStyle(item.needsYou ? Palette.needsYou : Palette.textSecondary)
                    .accessibilityHidden(true)
                Text(item.title)
                    .font(Typo.cardTitle)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                if item.needsYou { Chip(text: "Needs you", color: Palette.needsYou) }
            }
            if !item.detail.isEmpty {
                Text(item.detail)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            ForEach(Array(item.facts.enumerated()), id: \.offset) { _, fact in
                (Text(fact.label.isEmpty ? "" : fact.label + ": ").fontWeight(.semibold) + Text(fact.text))
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            ForEach(item.actions) { action in
                ActionRow(item: item, action: action)
            }
            if item.actions.isEmpty, item.kind != "unknown" {
                Text("Nothing in the app can fix this yet.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
        .card(highlighted: model.tools.focusedItemID == item.id)
        .id(item.id)
        .accessibilityElement(children: .contain)
    }
}

/// An action's button, and below it the step it is on: preview, confirm, running, result.
private struct ActionRow: View {
    @Environment(AppModel.self) private var model
    let item: AttentionItem
    let action: ToolAction

    var body: some View {
        let tools = model.tools
        let run = tools.run(for: item, action: action)
        VStack(alignment: .leading, spacing: Space.s) {
            if ToolFlow.showsButton(run) {
                Button(action.label) { tools.begin(item: item, action: action) }
                    .disabled(!ToolFlow.canBegin(run))
            }
            if let run { step(run, tools: tools) }
        }
    }

    @ViewBuilder private func step(_ run: ToolRun, tools: ToolsModel) -> some View {
        switch run {
        case .previewing, .running:
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text(ToolsPage.runLine(run)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        case .preview(let text):
            VStack(alignment: .leading, spacing: Space.s) {
                Text(ToolsPage.runLine(run)).font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
                output(text)
                confirm(tools: tools)
            }
        case .confirming:
            VStack(alignment: .leading, spacing: Space.s) {
                Text(ToolsPage.runLine(run)).font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
                confirm(tools: tools)
            }
        case .done(let text):
            VStack(alignment: .leading, spacing: Space.xs) {
                Label(ToolsPage.runLine(run), systemImage: "checkmark.circle")
                    .font(Typo.caption.weight(.semibold))
                    .foregroundStyle(Palette.textSecondary)
                output(text)
            }
        case .failed(let why), .refused(let why):
            VStack(alignment: .leading, spacing: Space.xs) {
                Label(ToolsPage.runLine(run), systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.caption.weight(.semibold))
                    .foregroundStyle(Palette.danger)
                Text(why)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.danger)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Button("Back") { tools.cancel(item: item, action: action) }
                    .buttonStyle(.borderless)
            }
        }
    }

    /// The exact command, then the buttons. A command that cannot be undone says so in the sentence before it.
    private func confirm(tools: ToolsModel) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            if action.destructive {
                Text("This cannot be undone.")
                    .font(Typo.caption.weight(.semibold))
                    .foregroundStyle(Palette.danger)
            }
            Text(ToolCommands.display(action.command))
                .font(Typo.code)
                .textSelection(.enabled)
                .padding(Space.s)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.background, in: RoundedRectangle(cornerRadius: Radius.card))
            HStack(spacing: Space.s) {
                Button(action.destructive ? "Run it" : "Run") { tools.confirm(item: item, action: action) }
                    .buttonStyle(.borderedProminent)
                Button("Cancel") { tools.cancel(item: item, action: action) }
            }
        }
    }

    private func output(_ text: String) -> some View {
        ScrollView {
            Text(text)
                .font(Typo.code)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(Space.s)
        }
        .frame(maxHeight: Space.previewMax)
        .background(Palette.background, in: RoundedRectangle(cornerRadius: Radius.card))
    }
}

/// The last action's result, kept after its card left the list.
private struct Notice: View {
    let text: String
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            Image(systemName: "checkmark.circle").foregroundStyle(Palette.textSecondary).accessibilityHidden(true)
            Text(text)
                .font(Typo.code)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            Spacer(minLength: 0)
            Button("Dismiss", action: dismiss).buttonStyle(.borderless)
        }
        .card()
    }
}

/// The read failed: the words, and the way to try again. The list below it, if any, is the last one that was read.
private struct ReadFailure: View {
    @Environment(AppModel.self) private var model
    let message: String

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Label("Tools could not be read", systemImage: "exclamationmark.triangle.fill")
                .font(Typo.cardTitle)
                .foregroundStyle(Palette.danger)
            Text(message)
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            Button("Try again") { model.tools.refresh() }
                .disabled(model.tools.isLoading)
        }
        .card()
    }
}
