import AppKit
import SwiftUI

/// Playbook: what the owner has learned and standardized. Top to bottom: the figures, contradictions between rules and
/// corrections, the guidelines (each opens its file), the model ladder with what changed around it, what is kept, and
/// what the sessions say about the owner. Every part loads on its own: one that fails shows its reason and the rest stay.
struct PlaybookView: View {
    var body: some View {
        Page {
            ConsoleHeader(page: ConsoleText.playbook)
            ConsoleBlock(name: ConsoleText.playbook.title, pick: { $0.playbook }) { report in
                PlaybookBody(report: report)
            }
        }
        .navigationTitle(ConsoleText.playbook.title)
    }
}

private struct PlaybookBody: View {
    let report: PlaybookReport

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            figures
            ContradictionsSection(you: report.you)
            GuidelinesSection(list: report.guidelineList)
            ModelsSection(models: report.models)
            KnowledgeSection(knowledge: report.knowledge)
            YouSection(you: report.you)
        }
    }

    private var figures: some View {
        let corrections = report.knowledge.value?.corrections.value
        let missing = report.guidelines.filter { $0.exists == false }.count
        return StatStrip {
            HeadlineTile(headline: report.headline, tone: (report.headline?.number ?? 0) > 0 ? .needsYou : .neutral)
            StatTile(label: "Guidelines", value: report.guidelines.isEmpty ? nil : "\(report.guidelines.count)",
                     detail: report.guidelineList.error ?? (report.guidelines.isEmpty ? "The report lists none." : (missing == 0 ? "All files found." : "\(missing) file\(missing == 1 ? " is" : "s are") missing.")),
                     tone: missing > 0 ? .needsYou : .neutral)
            StatTile(label: "Models to look at", value: PlaybookLogic.modelsToLook(report.models.value).map { "\($0)" },
                     detail: report.models.error ?? "New in the catalogue, plus where the ladder differs.")
            StatTile(label: "Corrections, 30 days", value: PlaybookLogic.count(corrections?.last30),
                     detail: report.knowledge.error ?? corrections.map { PlaybookLogic.count($0.total).map { "\($0) in all." } ?? "" } ?? "No count in the report.")
        }
    }
}

/// A part that could not be read: the reason, small, in place of the part.
private struct PartError: View {
    let title: String
    let reason: String?

    var body: some View {
        EmptyState(symbol: "questionmark.circle", title: "\(title) could not be read.", detail: reason ?? "The report has no \(title.lowercased()).")
    }
}

// MARK: Contradictions

private struct ContradictionsSection: View {
    let you: ConsoleLoad<PlaybookYou>

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Contradictions", note: "A rule you wrote, then corrected twice or more.")
            if let part = you.value, part.available, let found = part.contradictions {
                if found.rules.isEmpty {
                    EmptyState(title: "No rule is contradicted.", detail: PlaybookLogic.plain(found.detail))
                } else {
                    RowGroup {
                        ForEach(found.rules) { hit in
                            RowCard(title: hit.rule, detail: PlaybookLogic.contradictionRow(hit)) {
                                Chip(text: "Needs a look", color: Palette.needsYou)
                            }
                        }
                    }
                    if !found.detail.isEmpty {
                        Text(PlaybookLogic.plain(found.detail)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            } else {
                PartError(title: "Contradictions", reason: you.error ?? you.value?.reason)
            }
        }
    }
}

// MARK: Guidelines

private struct GuidelinesSection: View {
    let list: ConsoleLoad<PlaybookGuidelineList>
    private var rows: [PlaybookGuideline] { list.value?.rows ?? [] }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Guidelines", note: "Pick one to open its file.", count: rows.count)
            if let why = list.error {
                PartError(title: "Guidelines", reason: why)
            } else if rows.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "The report lists no guideline.")
            } else {
                RowGroup {
                    ForEach(rows) { row in
                        if let url = PlaybookLogic.openable(row) {
                            Button { NSWorkspace.shared.open(url) } label: { line(row, opens: true) }
                                .buttonStyle(.plain)
                                .help("Open \(url.lastPathComponent)")
                        } else {
                            line(row, opens: false)
                        }
                    }
                }
            }
        }
    }

    private func line(_ row: PlaybookGuideline, opens: Bool) -> some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            HStack(spacing: Space.m) {
                Text(row.title).font(Typo.body.weight(.semibold)).lineLimit(1)
                Spacer(minLength: Space.s)
                Text(PlaybookLogic.guidelineDetail(row))
                    .font(Typo.caption)
                    .foregroundStyle(row.exists == false ? Palette.needsYou : Palette.textSecondary)
                    .lineLimit(1)
                if opens { Image(systemName: "arrow.up.right.square").imageScale(.small).foregroundStyle(Palette.textSecondary) }
            }
            if !row.summary.isEmpty {
                Text(PlaybookLogic.plain(row.summary))
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, Space.s)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }
}

// MARK: Models

private struct ModelsSection: View {
    let models: ConsoleLoad<PlaybookModels>

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Models", note: PlaybookLogic.plain(models.value?.policy ?? ""))
            if let models = models.value {
                ForEach(models.ladder) { LadderCard(row: $0) }
                if models.ladder.isEmpty {
                    EmptyState(symbol: "questionmark.circle", title: "The report has no model ladder.")
                }
                drift(models.drift)
                newModels(models)
                arena(models.arena)
            } else {
                PartError(title: "Models", reason: models.error)
            }
        }
    }

    @ViewBuilder private func drift(_ rows: [PlaybookDrift]) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Where the ladder differs").font(Typo.cardTitle)
            if rows.isEmpty {
                Text("The ladder matches the catalogue.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            } else {
                RowGroup {
                    ForEach(rows) { row in
                        Text(PlaybookLogic.driftText(row))
                            .font(Typo.body)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, Space.s)
                    }
                }
            }
        }
    }

    @ViewBuilder private func newModels(_ models: PlaybookModels) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("New in the catalogue").font(Typo.cardTitle)
            if models.new.isEmpty {
                Text(models.newNote.isEmpty ? "Nothing new that you have not seen." : PlaybookLogic.plain(models.newNote))
                    .font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                RowGroup {
                    ForEach(models.new) { model in
                        RowCard(title: model.name ?? model.modelID, detail: PlaybookLogic.newModelDetail(model)) {
                            Chip(text: "Not looked at", color: Palette.textSecondary)
                        }
                    }
                }
                if !models.newNote.isEmpty {
                    Text(PlaybookLogic.plain(models.newNote)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            }
        }
    }

    @ViewBuilder private func arena(_ board: PlaybookArena?) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Arena shortlist").font(Typo.cardTitle)
            if let board, !board.top.isEmpty {
                Text(PlaybookLogic.arenaNote(board)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                RowGroup {
                    ForEach(board.top) { row in
                        RowCard(title: row.model, detail: PlaybookLogic.arenaDetail(row)) {
                            Chip(text: PlaybookLogic.arenaStatus(row, board: board), color: Palette.textSecondary)
                        }
                    }
                }
            } else {
                Text(board.map { $0.note.isEmpty ? "No arena snapshot." : PlaybookLogic.plain($0.note) } ?? "The report has no arena snapshot.")
                    .font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// One provider: its three tiers, one line each, and its note.
private struct LadderCard: View {
    let row: PlaybookLadderRow

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text(row.label).font(Typo.cardTitle)
            tier("Plans and reviews", row.orchestrate)
            tier("Builds", row.volume)
            tier("Quick jobs", row.triage)
            if !row.note.isEmpty { ClampedText(text: PlaybookLogic.plain(row.note), lines: 2, font: Typo.caption) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    private func tier(_ label: String, _ names: [String]) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            Text(label).font(Typo.body).foregroundStyle(Palette.textSecondary).frame(width: Space.quietName, alignment: .leading)
            Text(PlaybookLogic.tier(names))
                .font(Typo.body)
                .foregroundStyle(names.isEmpty ? Palette.textTertiary : Palette.text)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: Knowledge

private struct KnowledgeSection: View {
    let knowledge: ConsoleLoad<PlaybookKnowledge>

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "What is kept", note: "Counts only. Nothing here is read aloud or sent.")
            if let part = knowledge.value {
                StatStrip {
                    StatTile(label: "Your words", value: PlaybookLogic.count(part.intent.value?.entries),
                             detail: part.intent.error ?? part.intent.value.map(PlaybookLogic.intentDetail) ?? "Not in the report.")
                    StatTile(label: "Corrections", value: PlaybookLogic.count(part.corrections.value?.total),
                             detail: part.corrections.error ?? part.corrections.value.map(PlaybookLogic.correctionsDetail) ?? "Not in the report.")
                    StatTile(label: "Wiki pages", value: PlaybookLogic.count(part.wiki.value?.pages),
                             detail: part.wiki.error ?? part.wiki.value.map(PlaybookLogic.wikiDetail) ?? "Not in the report.")
                    StatTile(label: "Design decisions", value: PlaybookLogic.count(part.taste.value?.total),
                             detail: part.taste.error ?? part.taste.value.map(PlaybookLogic.tasteDetail) ?? "Not in the report.")
                }
            } else {
                PartError(title: "Knowledge counts", reason: knowledge.error)
            }
        }
    }
}

// MARK: You

private struct YouSection: View {
    let you: ConsoleLoad<PlaybookYou>
    @State private var moreQuotes = false
    @State private var moreChores = false

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "What the sessions say about you", note: note)
            if let part = you.value, part.available {
                quote(part)
                insights(part.insights)
                postcard(part.postcard)
                chores(part.delegation)
                ForEach(part.notes, id: \.self) { note in
                    Text(PlaybookLogic.plain(note)).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
                }
            } else {
                PartError(title: "This part", reason: you.error ?? you.value?.reason)
            }
        }
    }

    private var note: String { you.value?.localOnly == true ? "Read on this Mac only." : "" }

    @ViewBuilder private func quote(_ part: PlaybookYou) -> some View {
        if let quote = part.quoteOfTheDay {
            VStack(alignment: .leading, spacing: Space.s) {
                Text("Quote of the day").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                Text("\u{201C}\(quote.text)\u{201D}")
                    .font(Typo.section)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Text(PlaybookLogic.attribution(quote)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .card()
        }
        let others = PlaybookLogic.otherQuotes(part)
        if !others.isEmpty {
            Button(moreQuotes ? "Show fewer quotes" : "Show \(others.count) more quote\(others.count == 1 ? "" : "s")") { moreQuotes.toggle() }
                .buttonStyle(.link)
            if moreQuotes {
                RowGroup {
                    ForEach(others) { other in
                        VStack(alignment: .leading, spacing: Space.xxs) {
                            Text(other.text).font(Typo.body).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                            Text(PlaybookLogic.attribution(other)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, Space.s)
                    }
                }
            }
        }
    }

    @ViewBuilder private func insights(_ rows: [PlaybookInsight]) -> some View {
        if !rows.isEmpty {
            Text("What the prompts show").font(Typo.cardTitle)
            RowGroup {
                ForEach(rows) { row in
                    VStack(alignment: .leading, spacing: Space.xxs) {
                        Text(row.label).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                        Text(row.value ?? Format.dash)
                            .font(Typo.body.weight(.semibold))
                            .fixedSize(horizontal: false, vertical: true)
                        if !row.detail.isEmpty { ClampedText(text: PlaybookLogic.plain(row.detail), lines: 2, font: Typo.caption) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, Space.s)
                }
            }
        }
    }

    @ViewBuilder private func postcard(_ card: PlaybookPostcard?) -> some View {
        if let card, let then = card.then {
            VStack(alignment: .leading, spacing: Space.s) {
                Text("Then and now").font(Typo.cardTitle)
                Text("\u{201C}\(then.text)\u{201D}").font(Typo.body).fixedSize(horizontal: false, vertical: true)
                Text(PlaybookLogic.attribution(then)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                if let commits = card.commits {
                    Text("Since then: \(PlaybookLogic.count(commits) ?? "") commits\(card.latestTag.map { ", latest tag \($0)" } ?? "").")
                        .font(Typo.body)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .card()
        }
    }

    @ViewBuilder private func chores(_ rows: [PlaybookChore]) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Chores to hand off").font(Typo.cardTitle)
            if rows.isEmpty {
                Text("No chore came up often enough to list.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            } else {
                let ordered = PlaybookLogic.choresInOrder(rows)
                RowGroup {
                    ForEach(moreChores ? ordered : Array(ordered.prefix(PlaybookLogic.choresShown))) { chore in
                        VStack(alignment: .leading, spacing: Space.xs) {
                            HStack(spacing: Space.m) {
                                Text(chore.label).font(Typo.body.weight(.semibold)).lineLimit(1)
                                Spacer(minLength: Space.s)
                                if !chore.status.isEmpty {
                                    Chip(text: PlaybookLogic.sentence(chore.status), color: PlaybookLogic.isOpen(chore) ? Palette.needsYou : Palette.textSecondary)
                                }
                            }
                            Text(PlaybookLogic.choreDetail(chore)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                            if !chore.path.isEmpty { ClampedText(text: PlaybookLogic.plain(chore.path), lines: 2, font: Typo.body, color: Palette.text) }
                            let line = PlaybookLogic.plain([chore.who, chore.verified].filter { !$0.isEmpty }.joined(separator: " · "))
                            if !line.isEmpty { Text(line).font(Typo.caption).foregroundStyle(Palette.textSecondary) }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, Space.s)
                    }
                }
                if ordered.count > PlaybookLogic.choresShown {
                    Button(moreChores ? "Show fewer" : "Show \(ordered.count - PlaybookLogic.choresShown) more") { moreChores.toggle() }
                        .buttonStyle(.link)
                }
            }
        }
    }
}
