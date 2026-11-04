import AppKit
import SwiftUI

/// Operations: what failed or needs capacity. One section of `teyla console --json`, top to bottom:
/// the figures (failures, the lid, disk, swap), the machine with its 24-hour lines, the failures with the actions that
/// exist for them, the scheduled tasks worst first, the harnesses and the AGENTS.md copies, and what security last found.
/// A figure the report does not carry is a dash with the reason.
struct OperationsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let tools = model.tools
        ScrollViewReader { reader in
            Page {
                ConsoleHeader(page: ConsoleText.operations)
                if let notice = tools.notice { Notice(text: notice) { tools.dismissNotice() } }
                ConsoleBlock(name: ConsoleText.operations.title, pick: { $0.operations }) { report in
                    OperationsBody(report: report)
                }
                if model.capabilities.diagnosis { diagnosis }
            }
            .onChange(of: tools.focusedItemID, initial: true) { _, id in
                guard let id else { return }
                withAnimation(.easeOut(duration: 0.25)) { reader.scrollTo(id, anchor: .top) }
            }
        }
        .navigationTitle(ConsoleText.operations.title)
        .onAppear { tools.opened() }
    }

    private var diagnosis: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            SectionHeader(title: "First-run diagnosis")
            Text("Read 30 days of sessions and see which changes would save money. Nothing is changed until you say so.")
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Open diagnosis") { model.go(.diagnosis) }
                .buttonStyle(.link)
        }
    }
}

private struct OperationsBody: View {
    let report: OperationsReport

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            figures
            if report.leave?.ok == false, let blockers = report.leave?.blockers, !blockers.isEmpty {
                stillRunning(blockers)
            }
            MachineSection(machine: report.machine)
            FailuresSection(failures: report.failures)
            SchedulesSection(schedules: report.schedules)
            HarnessSection(harnesses: report.harnesses, sync: report.policySync)
            SecuritySection(security: report.security)
        }
    }

    private var figures: some View {
        let lid = OperationsLogic.lidFigure(report.leave)
        let machine = report.machine
        let failures = report.headline?.number
        return StatStrip {
            HeadlineTile(headline: report.headline, tone: (failures ?? 0) > 0 ? .needsYou : .neutral)
            StatTile(label: "Safe to leave", value: lid.value, detail: lid.detail, tone: lid.needsYou ? .needsYou : .neutral)
            StatTile(label: "Disk free", value: OperationsLogic.gb(machine?.diskFreeGB), detail: OperationsLogic.diskDetail(machine))
            StatTile(label: "Swap used", value: OperationsLogic.gb(machine?.swapUsedGB), detail: OperationsLogic.swapDetail(machine))
        }
    }

    private func stillRunning(_ blockers: [String]) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            SectionHeader(title: "Still running", note: "These stop the Mac from being left alone.", count: blockers.count)
            RowGroup {
                ForEach(blockers, id: \.self) { line in
                    Text(line)
                        .font(Typo.body)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, Space.s)
                }
            }
        }
    }
}

// MARK: Machine

private struct MachineSection: View {
    let machine: OpsMachine?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Machine", note: note)
            if let machine {
                HStack(alignment: .top, spacing: Space.m) {
                    SeriesCard(title: "Disk free", value: OperationsLogic.gb(machine.diskFreeGB), points: machine.diskSeries, unit: "GB")
                    SeriesCard(title: "Swap used", value: OperationsLogic.gb(machine.swapUsedGB), points: machine.swapSeries, unit: "GB")
                }
                .fixedSize(horizontal: false, vertical: true)
                RowGroup {
                    FactRow(label: "Memory", value: memory(machine))
                    FactRow(label: "Processor", value: processor(machine))
                    FactRow(label: "Agents", value: OperationsLogic.agentsLine(machine.agents))
                    FactRow(label: "Work in flight", value: flight(machine))
                    FactRow(label: "Biggest apps", value: apps(machine))
                }
            } else {
                EmptyState(symbol: "questionmark.circle", title: "The report has no machine figures.")
            }
        }
    }

    private var note: String {
        guard let word = OperationsLogic.verdictWord(machine?.verdict) else { return "" }
        let reason = machine?.reason ?? ""
        return reason.isEmpty ? word : "\(word): \(reason)"
    }

    private func memory(_ m: OpsMachine) -> String {
        var parts: [String] = []
        if let ram = m.ramGB { parts.append("\(Int(ram.rounded())) GB RAM") }
        if let compressor = OperationsLogic.gb(m.compressorGB) { parts.append("\(compressor) compressed") }
        if let total = OperationsLogic.gb(m.swapTotalGB) { parts.append("swap file \(total)") }
        return parts.isEmpty ? Format.dash : parts.joined(separator: " · ")
    }

    private func processor(_ m: OpsMachine) -> String {
        guard let load = m.cpuLoad else { return Format.dash }
        let cores = m.cores.map { " on \($0) cores" } ?? ""
        return "load \(String(format: "%.1f", load))\(cores)"
    }

    private func flight(_ m: OpsMachine) -> String {
        let counts: [(String, String, Int?)] = [("build", "builds", m.builds), ("simulator", "simulators", m.sims),
                                                ("agent lane", "agent lanes", m.lanes)]
        let known = counts.compactMap { one, many, value in value.map { "\($0) \($0 == 1 ? one : many)" } }
        return known.isEmpty ? Format.dash : known.joined(separator: " · ")
    }

    private func apps(_ m: OpsMachine) -> String {
        let rows = m.top.prefix(5).compactMap { app in OperationsLogic.gb(app.gb).map { "\(app.name) \($0)" } }
        return rows.isEmpty ? Format.dash : rows.joined(separator: " · ")
    }
}

/// A figure with its 24-hour line under it, and the range the line covers.
private struct SeriesCard: View {
    let title: String
    let value: String?
    let points: [OpsPoint]
    let unit: String

    var body: some View {
        let scaled = OperationsLogic.scaled(points)
        VStack(alignment: .leading, spacing: Space.xs) {
            Text(title).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            Text(value ?? Format.dash)
                .font(Typo.number)
                .foregroundStyle(value == nil ? Palette.textTertiary : Palette.text)
            if scaled.isEmpty {
                Spacer(minLength: 0)
            } else {
                SeriesLine(values: scaled)
                    .frame(height: Space.seriesHeight)
            }
            Text(OperationsLogic.seriesRange(points, unit: unit))
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2, reservesSpace: true)
        }
        .surface(padding: Space.m)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(title): \(value ?? "unknown"). \(OperationsLogic.seriesRange(points, unit: unit))")
    }
}

/// Values between 0 and 1 as a line with a pale area under it. The newest reading is on the right.
private struct SeriesLine: View {
    let values: [Double]

    var body: some View {
        GeometryReader { box in
            let width = box.size.width, height = box.size.height
            let step = values.count > 1 ? width / Double(values.count - 1) : 0
            let points = values.enumerated().map { CGPoint(x: Double($0.offset) * step, y: height * (1 - $0.element)) }
            ZStack {
                Path { path in
                    guard let first = points.first, let last = points.last else { return }
                    path.move(to: CGPoint(x: first.x, y: height))
                    points.forEach { path.addLine(to: $0) }
                    path.addLine(to: CGPoint(x: last.x, y: height))
                    path.closeSubpath()
                }
                .fill(Palette.primaryTint)
                Path { path in
                    guard let first = points.first else { return }
                    path.move(to: first)
                    points.dropFirst().forEach { path.addLine(to: $0) }
                }
                .stroke(Palette.primary, style: StrokeStyle(lineWidth: Space.xxs, lineCap: .round, lineJoin: .round))
            }
        }
    }
}

// MARK: Failures

private struct FailuresSection: View {
    @Environment(AppModel.self) private var model
    let failures: [OpsFailure]
    @State private var showInfo = false

    var body: some View {
        let groups = OperationsLogic.failuresInOrder(failures)
        let focused = model.tools.focusedItemID
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Failures", note: note(failures), count: failures.count)
            if failures.isEmpty {
                EmptyState(title: "Nothing is failing.", detail: "The last read found no unresolved failure.")
            }
            ForEach(groups.act) { card($0) }
            if !groups.info.isEmpty {
                // What is only worth a look stays folded, so a long list of small notes never hides what needs you.
                Button(showInfo ? "Show fewer" : "Show \(groups.info.count) more") { showInfo.toggle() }
                    .buttonStyle(.link)
                if showInfo { ForEach(groups.info) { card($0) } }
            }
        }
        .onChange(of: focused) { _, id in
            // A card the command bar points at must be on the page to scroll to.
            if let id, groups.info.contains(where: { failure in model.tools.report?.items.first { $0.title == failure.title }?.id == id }) {
                showInfo = true
            }
        }
    }

    private func note(_ failures: [OpsFailure]) -> String {
        let info = failures.filter { !$0.needsYou }.count
        return info == 0 ? "" : "\(failures.count - info) need you, \(info) are worth a look"
    }

    @ViewBuilder private func card(_ failure: OpsFailure) -> some View {
        if let item = model.tools.report?.items.first(where: { $0.title == failure.title }) {
            ToolCard(item: item)
        } else {
            FailureCard(failure: failure)
        }
    }
}

/// A failure the app has no allow-listed action for: the sentence, what is known, and the command to copy.
private struct FailureCard: View {
    let failure: OpsFailure

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                Image(systemName: failure.needsYou ? "exclamationmark.circle" : "info.circle")
                    .foregroundStyle(failure.needsYou ? Palette.needsYou : Palette.textSecondary)
                    .accessibilityHidden(true)
                ClampedText(text: failure.title, lines: 2, font: Typo.cardTitle, color: Palette.text)
                if failure.needsYou { Chip(text: "Needs you", color: Palette.needsYou) }
            }
            if !failure.detail.isEmpty {
                ClampedText(text: failure.detail, lines: 3, font: Typo.body)
            }
            if !failure.product.isEmpty {
                Text(failure.product).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            if let command = failure.action {
                CopyCommand(command: command)
            }
        }
        .card()
        .id(failure.id)
        .accessibilityElement(children: .contain)
    }
}

/// A command shown as it is, with a button that copies it. The app does not run it.
private struct CopyCommand: View {
    let command: String
    @State private var copied = false

    var body: some View {
        HStack(spacing: Space.s) {
            Text(command)
                .font(Typo.code)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .padding(Space.s)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.background, in: RoundedRectangle(cornerRadius: Radius.control))
            Button(copied ? "Copied" : "Copy command") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(command, forType: .string)
                copied = true
            }
        }
    }
}

// MARK: Schedules

private struct SchedulesSection: View {
    let schedules: OpsSchedules?
    @State private var showAll = false

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Scheduled tasks", note: note, count: schedules?.rows.count)
            if let schedules, !schedules.rows.isEmpty {
                let split = OperationsLogic.scheduleSplit(schedules.rows)
                let shown = showAll ? split.look + split.rest : split.look
                if !shown.isEmpty {
                    RowGroup {
                        ForEach(shown) { ScheduleRow(row: $0) }
                    }
                } else {
                    EmptyState(title: "Every task ran on time.")
                }
                if !split.rest.isEmpty {
                    Button(showAll ? "Show fewer" : "Show all \(schedules.rows.count)") { showAll.toggle() }
                        .buttonStyle(.link)
                }
            } else {
                EmptyState(symbol: "questionmark.circle", title: "The report lists no scheduled task.")
            }
        }
    }

    private var note: String { OperationsLogic.scheduleNote(schedules?.rows ?? []) }
}

private struct ScheduleRow: View {
    let row: OpsScheduleRow

    var body: some View {
        RowCard(title: row.name, detail: OperationsLogic.scheduleDetail(row, now: .now)) {
            Chip(text: OperationsLogic.stateWord(row.state), color: color)
        }
    }

    private var color: Color {
        OperationsLogic.needsAction(row.state) ? Palette.needsYou : Palette.textSecondary
    }
}

// MARK: Harnesses

private struct HarnessSection: View {
    let harnesses: [OpsHarness]
    let sync: OpsPolicySync?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Harnesses", note: OperationsLogic.syncLine(sync, now: .now))
            if harnesses.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "The report lists no harness.")
            } else {
                RowGroup {
                    ForEach(harnesses) { harness in
                        RowCard(title: harness.name, detail: detail(harness)) {
                            Chip(text: OperationsLogic.policyWord(harness),
                                 color: OperationsLogic.policyOK(harness) || !harness.installed ? Palette.textSecondary : Palette.needsYou)
                        }
                    }
                }
            }
            if let sync {
                ForEach(sync.drift) { drift in
                    VStack(alignment: .leading, spacing: Space.s) {
                        Text("\(drift.harness.isEmpty ? "A harness" : drift.harness) differs")
                            .font(Typo.cardTitle)
                        ClampedText(text: drift.why, lines: 2, font: Typo.body)
                        if let fix = drift.fix { CopyCommand(command: fix) }
                    }
                    .card()
                }
                if let line = OperationsLogic.repoLine(sync.repos) {
                    Text(line)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func detail(_ harness: OpsHarness) -> String {
        guard harness.installed else { return "" }
        let parts = [harness.version.map { "version \($0)" }, harness.note].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.joined(separator: " · ")
    }
}

// MARK: Security

private struct SecuritySection: View {
    let security: OpsSecurity?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Security", note: "Counts from the last scan of each kind.")
            if let security {
                let now = Date.now
                StatStrip {
                    StatTile(label: "Leak findings", value: OperationsLogic.count(security.leakFindings),
                             detail: OperationsLogic.asOf(security.leakAsOf, now: now),
                             tone: (security.leakFindings ?? 0) > 0 ? .needsYou : .neutral)
                    StatTile(label: "Vulnerable packages", value: OperationsLogic.count(security.depsVulns),
                             detail: OperationsLogic.asOf(security.depsAsOf, now: now),
                             tone: (security.depsVulns ?? 0) > 0 ? .needsYou : .neutral)
                    StatTile(label: "Unreviewed PRs", value: OperationsLogic.count(security.unreviewedPRs),
                             detail: OperationsLogic.asOf(security.reviewsAsOf, now: now))
                    StatTile(label: "Shield issues", value: OperationsLogic.count(security.shieldIssues),
                             detail: security.shieldIssues == nil ? OperationsLogic.shieldWhy : "")
                }
            } else {
                EmptyState(symbol: "questionmark.circle", title: "The report has no security counts.")
            }
        }
    }
}

// MARK: Rows

/// A label and its value on one line; a long value wraps under the label's column.
private struct FactRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            Text(label)
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .frame(width: Space.quietName, alignment: .leading)
            Text(value)
                .font(Typo.body)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
        }
        .padding(.vertical, Space.s)
    }
}
