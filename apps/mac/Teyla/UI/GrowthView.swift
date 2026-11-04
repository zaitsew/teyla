import AppKit
import SwiftUI

/// Which of the two layouts the page uses. Both show the same parts; the choice is only what comes first. The owner picks
/// one on the device, and the other is removed (docs/APP.md).
enum GrowthLayout: String, CaseIterable {
    /// The drafts waiting for you first, the channel rows after.
    case review
    /// The channel board first, the drafts after.
    case channels

    static let key = "growthLayout"
}

/// Growth: did every channel get its post today, and what waits for the owner. Top to bottom: four figures, then
/// either the review queue or the channel board first, the pipeline, what is in the works, trend ideas and outreach.
/// Approving only marks a draft: nothing on this page posts, sends or publishes.
struct GrowthView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let growth = model.console.report?.growth
        Page {
            ConsoleHeader(page: ConsoleText.growth)
            ConsoleBlock(name: ConsoleText.growth.title, pick: { $0.growth }) { report in
                GrowthBody(report: report)
            }
            // The queue is files, not the report: it stays when the report failed.
            if model.console.report != nil, growth?.value == nil {
                ReviewQueue(compact: false)
            }
        }
        .navigationTitle(ConsoleText.growth.title)
        .onAppear { model.growth.opened() }
        .onChange(of: model.console.readAt) { model.growth.refresh() }
    }
}

private struct GrowthBody: View {
    @Environment(AppModel.self) private var model
    @AppStorage(GrowthLayout.key) private var layoutName = GrowthLayout.review.rawValue
    let report: GrowthReport

    private var layout: GrowthLayout { GrowthLayout(rawValue: layoutName) ?? .review }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            figures
            layoutSwitch
            switch layout {
            case .review:
                ReviewQueue(compact: false)
                ChannelRows(report: report)
            case .channels:
                ChannelCards(report: report)
                ReviewQueue(compact: true)
            }
            PipelineSection(pipeline: report.pipeline)
            InTheWorks(report: report)
            TrendsSection(trends: report.trends)
            OutreachSection(report: report)
        }
    }

    private var figures: some View {
        let queue = model.growth
        let waiting = queue.isRead ? queue.drafts.count : nil
        return StatStrip {
            HeadlineTile(headline: report.headline, tone: (report.gaps ?? 0) > 0 ? .needsYou : .neutral)
            StatTile(label: "Waiting for you", value: waiting.map { "\($0)" },
                     detail: GrowthLogic.waitingDetail(count: waiting, skipped: queue.skipped, why: queue.isRead ? nil : queue.failure),
                     tone: (waiting ?? 0) > 0 ? .needsYou : .neutral)
            StatTile(label: "Drafts ahead", value: GrowthLogic.queueFigure(report.queueDays),
                     detail: GrowthLogic.queueDetail(report.queueDays, gaps: report.gaps),
                     tone: (report.queueDays ?? 1) < 1 ? .needsYou : .neutral)
            StatTile(label: "Since a public post", value: GrowthLogic.sinceFigure(report.lastPublicDays),
                     detail: GrowthLogic.sinceDetail(report.lastPublicDays),
                     tone: (report.lastPublicDays ?? 0) > 1 ? .needsYou : .neutral)
        }
    }

    /// Two layouts to compare on the device. The one the owner keeps stays; this switch goes with the other.
    private var layoutSwitch: some View {
        HStack(spacing: Space.m) {
            Text("Layout").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            SegmentSwitch(options: [(GrowthLayout.review.rawValue, "Review first"), (GrowthLayout.channels.rawValue, "Channels first")],
                          selection: $layoutName, spokenLabel: "Layout")
            Spacer(minLength: Space.s)
        }
    }
}

// MARK: Review queue

/// The drafts waiting for the owner, the best editor score first. `compact` shows every draft closed.
private struct ReviewQueue: View {
    @Environment(AppModel.self) private var model
    let compact: Bool
    @State private var showAll = false

    private static let firstShown = 5

    var body: some View {
        let queue = model.growth
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Waiting for you", note: "Best editor score first. Approving only marks a draft; you post it yourself.",
                          count: queue.isRead ? queue.drafts.count : nil)
            if let notice = queue.notice {
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    Image(systemName: "checkmark.circle").foregroundStyle(Palette.saving)
                    Text(notice).font(Typo.caption).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: Space.s)
                    Button("Dismiss") { queue.dismissNotice() }.buttonStyle(.plain).font(Typo.caption).foregroundStyle(Palette.primary)
                }
            }
            if let why = queue.failure {
                ErrorRow(section: "the drafts", message: why) { queue.refresh() }
            }
            if queue.isRead || queue.failure == nil {
                content(queue)
            }
        }
    }

    @ViewBuilder
    private func content(_ queue: GrowthModel) -> some View {
        if !queue.isRead {
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text("Reading the drafts…").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        } else if queue.drafts.isEmpty {
            EmptyState(title: "Nothing waits for you.", detail: "New drafts appear here once the factory writes them.")
        } else {
            let shown = showAll ? queue.drafts : Array(queue.drafts.prefix(Self.firstShown))
            VStack(alignment: .leading, spacing: Space.m) {
                ForEach(Array(shown.enumerated()), id: \.element.id) { index, draft in
                    DraftCard(draft: draft, startOpen: !compact && index == 0)
                }
                if queue.drafts.count > Self.firstShown {
                    Button(showAll ? "Show fewer" : "Show \(queue.drafts.count - Self.firstShown) more") { showAll.toggle() }
                        .buttonStyle(.plain)
                        .font(Typo.caption.weight(.medium))
                        .foregroundStyle(Palette.primary)
                }
            }
        }
    }
}

/// One draft: its text, what the editor said, the checks, and approve, reject and edit.
private struct DraftCard: View {
    @Environment(AppModel.self) private var model
    let draft: GrowthDraft
    let startOpen: Bool
    @State private var open: Bool?
    @State private var mode = Mode.reading
    @State private var reason = ""
    @State private var text = ""
    @State private var hook = ""

    private enum Mode { case reading, rejecting, editing }

    private var isOpen: Bool { open ?? startOpen }

    var body: some View {
        let act = model.growth.act(for: draft.id)
        VStack(alignment: .leading, spacing: Space.m) {
            header
            if isOpen {
                openBody(act: act)
            } else if !draft.body.isEmpty {
                Text(draft.body)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .surface()
        .accessibilityElement(children: .contain)
    }

    private var header: some View {
        Button { open = !isOpen } label: {
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(GrowthLogic.draftTitle(draft))
                        .font(Typo.cardTitle)
                        .foregroundStyle(Palette.text)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    Text(GrowthLogic.draftDetail(draft))
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)
                }
                Spacer(minLength: Space.s)
                if let editor = GrowthLogic.editorWords(draft) { Chip(text: editor, color: Palette.primary) }
                if !draft.canApprove { Chip(text: "Check failed", color: Palette.danger, symbol: "exclamationmark.triangle") }
                Image(systemName: isOpen ? "chevron.up" : "chevron.down").imageScale(.small).foregroundStyle(Palette.textSecondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(GrowthLogic.draftTitle(draft)). \(isOpen ? "Close" : "Open")")
    }

    @ViewBuilder
    private func openBody(act: GrowthAct?) -> some View {
        switch mode {
        case .reading:
            reading
        case .rejecting:
            rejecting
        case .editing:
            editing
        }
        if let act {
            switch act {
            case .running(let word):
                HStack(spacing: Space.s) {
                    ProgressView().controlSize(.small)
                    Text(word).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            case .failed(let why):
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Palette.danger)
                    VStack(alignment: .leading, spacing: Space.xxs) {
                        Text("That did not work. Nothing changed.").font(Typo.body.weight(.semibold))
                        ClampedText(text: why, lines: 3, font: Typo.caption)
                    }
                }
            }
        }
    }

    private var busy: Bool { model.growth.act(for: draft.id)?.isBusy ?? false }

    // MARK: Reading

    private var reading: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Text(draft.body.isEmpty ? "This draft has no text yet." : draft.body)
                .font(Typo.body)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
            if !draft.hook.isEmpty { labelled("Hook", draft.hook) }
            if !draft.firstComment.isEmpty { labelled("First comment", draft.firstComment) }
            if !draft.critique.isEmpty { labelled("The editor said", draft.critique) }
            if !draft.facts.isEmpty { labelled("Facts it rests on", draft.facts.map { "· \($0)" }.joined(separator: "\n")) }
            if !draft.sources.isEmpty { sources }
            checks
            actions
        }
    }

    private func labelled(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(label).font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
            ClampedText(text: value, lines: 3, font: Typo.caption, color: Palette.text)
        }
    }

    private var sources: some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text("Sources").font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
            ForEach(draft.sources) { source in
                if let url = Self.web(source.link) {
                    Button { NSWorkspace.shared.open(url) } label: {
                        Text(source.link).font(Typo.caption).lineLimit(1).truncationMode(.middle)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Palette.primary)
                    .help(source.link)
                } else {
                    Text("\(source.kind) \(source.link)").font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                }
            }
        }
    }

    /// Only a web address opens; any other text stays text.
    private static func web(_ link: String) -> URL? {
        guard let url = URL(string: link), ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil else { return nil }
        return url
    }

    private var checks: some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            HStack(spacing: Space.s) {
                Chip(text: draft.voiceOK == true ? "Voice ok" : (draft.voiceOK == false ? "Voice failed" : "Voice not checked"),
                     color: draft.voiceOK == true ? Palette.saving : Palette.danger,
                     symbol: draft.voiceOK == true ? "checkmark" : "exclamationmark.triangle")
                Chip(text: draft.leakOK == true ? "Nothing private" : (draft.leakOK == false ? "Leak check failed" : "Leak not checked"),
                     color: draft.leakOK == true ? Palette.saving : Palette.danger,
                     symbol: draft.leakOK == true ? "checkmark" : "exclamationmark.triangle")
            }
            ForEach(draft.checkNotes, id: \.self) { note in
                Text(note).font(Typo.caption).foregroundStyle(Palette.danger).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var actions: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(spacing: Space.s) {
                Button("Approve") { model.growth.approve(draft) }
                    .buttonStyle(.borderedProminent)
                    .disabled(!draft.canApprove || busy)
                Button("Edit") {
                    text = draft.body
                    hook = draft.hook
                    mode = .editing
                }
                .disabled(busy)
                Button("Reject") { mode = .rejecting }
                    .disabled(busy)
            }
            if let why = GrowthLogic.approveBlock(draft) {
                Text(why).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // MARK: Rejecting and editing

    private var rejecting: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Why? The next draft learns from your answer.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            TextField("For example: too salesy, wrong fact, not our voice", text: $reason, axis: .vertical)
                .lineLimit(2...4)
                .textFieldStyle(.roundedBorder)
                .font(Typo.body)
            HStack(spacing: Space.s) {
                Button("Reject draft", role: .destructive) {
                    model.growth.reject(draft, reason: reason)
                    mode = .reading
                    reason = ""
                }
                .disabled(!GrowthLogic.canReject(reason: reason) || busy)
                Button("Cancel") { mode = .reading; reason = "" }
            }
        }
    }

    private var editing: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Edit the text. The voice and leak checks run again when you save.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            TextEditor(text: $text)
                .font(Typo.body)
                .scrollContentBackground(.hidden)
                .padding(Space.s)
                .frame(minHeight: Space.editorMin)
                .background(Palette.background, in: RoundedRectangle(cornerRadius: Radius.control))
                .overlay(RoundedRectangle(cornerRadius: Radius.control).stroke(Palette.border))
            if !draft.hook.isEmpty {
                TextField("Hook", text: $hook, axis: .vertical)
                    .lineLimit(1...3)
                    .textFieldStyle(.roundedBorder)
                    .font(Typo.body)
            }
            HStack(spacing: Space.s) {
                Button("Save") {
                    model.growth.edit(draft, body: text, hook: draft.hook.isEmpty ? "" : hook)
                    mode = .reading
                }
                .buttonStyle(.borderedProminent)
                .disabled(!GrowthLogic.canSave(body: text, original: draft.body, hook: hook, originalHook: draft.hook) || busy)
                Button("Cancel") { mode = .reading }
            }
        }
    }
}

// MARK: Channels

/// Variant one: one row per channel, with a bar for today's slots.
private struct ChannelRows: View {
    let report: GrowthReport

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Today by channel", note: targetNote, count: report.today.count)
            if report.today.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "No channel is enabled.",
                           detail: "Run `teyla growth init` in a terminal to write the channel list.")
            } else {
                RowGroup {
                    ForEach(report.today) { row in
                        VStack(alignment: .leading, spacing: Space.xs) {
                            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                                Text(GrowthLogic.channelName(platform: row.platform, language: row.language))
                                    .font(Typo.body.weight(.semibold))
                                    .lineLimit(1)
                                Spacer(minLength: Space.s)
                                Text(GrowthLogic.lastPostWords(GrowthLogic.channel(row, in: report.channels)))
                                    .font(Typo.caption)
                                    .foregroundStyle(Palette.textSecondary)
                                    .lineLimit(1)
                                Text(GrowthLogic.slotWords(row))
                                    .font(Typo.body.weight(.semibold).monospacedDigit())
                                    .foregroundStyle(GrowthLogic.isDone(row) ? Palette.saving : Palette.needsYou)
                                    .lineLimit(1)
                            }
                            ProgressView(value: GrowthLogic.fraction(row))
                                .progressViewStyle(.linear)
                                .tint(GrowthLogic.isDone(row) ? Palette.saving : Palette.primaryMuted)
                                .accessibilityHidden(true)
                        }
                        .padding(.vertical, Space.s)
                        .accessibilityElement(children: .combine)
                    }
                }
            }
        }
    }

    private var targetNote: String {
        report.targetPerChannel.map { "The target is \($0) post\($0 == 1 ? "" : "s") a day on each channel." } ?? "The report gives no target."
    }
}

/// Variant two: one card per channel, a grid.
private struct ChannelCards: View {
    let report: GrowthReport

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Today by channel",
                          note: report.targetPerChannel.map { "The target is \($0) post\($0 == 1 ? "" : "s") a day on each channel." } ?? "The report gives no target.",
                          count: report.today.count)
            if report.today.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "No channel is enabled.",
                           detail: "Run `teyla growth init` in a terminal to write the channel list.")
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: Space.builtCardMin), spacing: Space.m, alignment: .top)], alignment: .leading, spacing: Space.m) {
                    ForEach(report.today) { row in
                        VStack(alignment: .leading, spacing: Space.xs) {
                            Text(GrowthLogic.channelName(platform: row.platform, language: row.language))
                                .font(Typo.cardTitle)
                                .lineLimit(1)
                            Text(GrowthLogic.slotWords(row))
                                .font(Typo.number)
                                .foregroundStyle(GrowthLogic.isDone(row) ? Palette.saving : Palette.needsYou)
                                .lineLimit(1)
                            Text(GrowthLogic.lastPostWords(GrowthLogic.channel(row, in: report.channels)))
                                .font(Typo.caption)
                                .foregroundStyle(Palette.textSecondary)
                                .lineLimit(1)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .surface(padding: Space.m)
                        .accessibilityElement(children: .combine)
                    }
                }
            }
        }
    }
}

// MARK: Pipeline

private struct PipelineSection: View {
    let pipeline: GrowthPipeline?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Pipeline", note: "From an idea to a post that is live.")
            StatStrip {
                ForEach(GrowthLogic.stages(pipeline), id: \.label) { stage in
                    StatTile(label: stage.label, value: stage.count.map { "\($0)" },
                             detail: stage.count == nil ? "The report does not count this stage." : stage.note)
                }
            }
        }
    }
}

// MARK: Episodes and the next ride

private struct InTheWorks: View {
    let report: GrowthReport

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "In the works", note: "Episodes being filmed or cut, and the next ride to film.", count: report.episodes.count)
            if report.episodes.isEmpty, report.nextRide == nil {
                EmptyState(symbol: "questionmark.circle", title: "No episode is in the works.", detail: "The report names no next ride either.")
            } else {
                RowGroup {
                    ForEach(report.episodes) { episode in
                        RowCard(title: episode.idea.isEmpty ? episode.id : episode.idea,
                                detail: [GrowthLogic.episodeDetail(episode), episode.question].filter { !$0.isEmpty }.joined(separator: " · ")) {
                            Text(GrowthLogic.stageWords(episode.stage)).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                        }
                    }
                    if let ride = report.nextRide, !ride.title.isEmpty {
                        RowCard(title: ride.title, detail: "Next ride") {
                            Text(GrowthLogic.rideDetail(ride)).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                        }
                    }
                }
            }
        }
    }
}

// MARK: Trends

private struct TrendsSection: View {
    let trends: [GrowthTrend]

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Trend ideas", note: "Scored out of 30 for your customers. Each one only starts a draft.", count: trends.count)
            if trends.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "No trend scored well enough.")
            } else {
                RowGroup {
                    ForEach(trends) { trend in TrendRow(trend: trend) }
                }
            }
        }
    }
}

private struct TrendRow: View {
    let trend: GrowthTrend

    private var url: URL? {
        guard let url = URL(string: trend.url), ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil else { return nil }
        return url
    }

    var body: some View {
        RowCard(title: trend.title, detail: [trend.hook, trend.source].filter { !$0.isEmpty }.joined(separator: " · ")) {
            HStack(spacing: Space.s) {
                Text(GrowthLogic.trendScore(trend.score) ?? Format.dash)
                    .font(Typo.caption.monospacedDigit())
                    .foregroundStyle(Palette.textSecondary)
                if url != nil { Image(systemName: "arrow.up.right.square").imageScale(.small).foregroundStyle(Palette.textSecondary) }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { if let url { NSWorkspace.shared.open(url) } }
        .accessibilityAddTraits(url == nil ? [] : .isButton)
    }
}

// MARK: Outreach

private struct OutreachSection: View {
    let report: GrowthReport

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Outreach", note: "Counts only. Teyla drafts outreach and never sends it.")
            if let outreach = report.outreach {
                RowGroup {
                    RowCard(title: "Drafts waiting", detail: GrowthLogic.outreachLine(outreach)) {
                        Text(outreach.drafts.map { "\($0)" } ?? Format.dash)
                            .font(Typo.body.weight(.semibold).monospacedDigit())
                            .foregroundStyle(outreach.drafts == nil ? Palette.textTertiary : Palette.text)
                    }
                    RowCard(title: "Conversations that fit", detail: "Qualified, in the last 7 days") {
                        Text(report.qualifiedWeek.map { "\($0)" } ?? Format.dash)
                            .font(Typo.body.weight(.semibold).monospacedDigit())
                            .foregroundStyle(report.qualifiedWeek == nil ? Palette.textTertiary : Palette.text)
                    }
                    ForEach(outreach.sources) { source in
                        RowCard(title: source.source, detail: source.connected ? "Its counts are read" : "Not connected: no count to read") {
                            Chip(text: source.connected ? "Connected" : "Not connected",
                                 color: source.connected ? Palette.saving : Palette.textSecondary)
                        }
                    }
                }
            } else {
                EmptyState(symbol: "questionmark.circle", title: "The report has no outreach count.")
            }
        }
    }
}
