import SwiftUI

/// Variant B, "morning brief": one sentence on what matters, then the questions ranked by what
/// they unblock, the tasks only you can do, and what got done. The side column holds products and running sessions.
struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        ScrollViewReader { reader in
            GeometryReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: Space.xl) {
                        header
                        if model.snapshot == nil {
                            EmptyStateView()
                        } else if proxy.size.width >= Space.wideWindow {
                            HStack(alignment: .top, spacing: Space.xxl) {
                                MainColumn().frame(maxWidth: .infinity, alignment: .leading)
                                StatusColumn().frame(width: Space.sideColumn)
                            }
                        } else {
                            VStack(alignment: .leading, spacing: Space.xl) {
                                MainColumn()
                                StatusColumn()
                            }
                        }
                    }
                    .padding(.horizontal, Space.xl + Space.xs)
                    .padding(.vertical, Space.xl)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .onChange(of: model.focusedAskID) { _, id in
                guard let id else { return }
                withAnimation(.easeOut(duration: 0.25)) { reader.scrollTo(id, anchor: .top) }
            }
        }
        .background(Palette.background)
        .toolbar {
            ToolbarItem(placement: .primaryAction) { LiveIndicator() }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    model.refresh()
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .help("Refresh now")
                .disabled(model.isRefreshing)
            }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    model.openNewTask()
                } label: {
                    Label("New task", systemImage: "square.and.pencil")
                }
                .help("New task (⌘N)")
            }
        }
        .navigationTitle("Teyla")
        .sheet(isPresented: Bindable(model.newTask).presented) {
            NewTaskSheet()
                .environment(model)
        }
        .onAppear {
            model.openMainWindow = { openWindow(id: "main") }
            Preview.runOnce(model: model, openSettings: { openSettings() })
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            model.refresh()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Space.xs + Space.xxs) {
            Text(model.briefLine)
                .font(Typo.brief)
                .lineSpacing(Space.xxs)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if let snapshot = model.snapshot {
                Text(Format.subline(questions: model.visibleAsks.count,
                                    running: snapshot.running.count,
                                    spentUSD: snapshot.totals.spentTodayUSD))
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
    }
}

private struct LiveIndicator: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            HStack(spacing: Space.xs + Space.xxs) {
                Circle()
                    .fill(model.lastError == nil ? Palette.success : Palette.warning)
                    .frame(width: Space.s - Space.xxs, height: Space.s - Space.xxs)
                Text(label(at: context.date))
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            .help(model.lastError ?? "Teyla re-reads your sessions when they change, and every minute.")
        }
    }

    private func label(at date: Date) -> String {
        guard let fetchedAt = model.fetchedAt else {
            return model.lastError == nil ? "Reading…" : "Offline"
        }
        let seconds = Int(date.timeIntervalSince(fetchedAt))
        if model.lastError != nil { return "Stale · updated \(max(0, seconds)) s ago" }
        return Format.updated(secondsAgo: seconds)
    }
}

private struct EmptyStateView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            if let error = model.lastError {
                Label("Could not read state", systemImage: "exclamationmark.triangle")
                    .font(Typo.lead)
                    .foregroundStyle(Palette.warning)
                Text(error)
                    .foregroundStyle(Palette.textSecondary)
                    .textSelection(.enabled)
                Button("Try again") { model.refresh() }
            } else {
                HStack(spacing: Space.s) {
                    ProgressView().controlSize(.small)
                    Text("Reading your sessions…").foregroundStyle(Palette.textSecondary)
                }
            }
        }
        .padding(.top, Space.s)
    }
}

/// Questions, then owner tasks, then results.
private struct MainColumn: View {
    @Environment(AppModel.self) private var model
    @State private var showAllDone = false

    private static let collapsedDone = 4

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            questions
            NotesSection()
            if !tasks.isEmpty { onlyYou }
            done
        }
    }

    private var tasks: [OwnerTask] { model.snapshot?.tasks ?? [] }

    private var questions: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionLabel("Needs you — ordered by what it unblocks")
            if model.visibleAsks.isEmpty {
                Label("Nothing is waiting for an answer.", systemImage: "checkmark.circle")
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.vertical, Space.s)
            } else {
                ForEach(model.visibleAsks) { ask in
                    AskCard(ask: ask)
                        .transition(.opacity.combined(with: .scale(scale: 0.97)))
                }
            }
        }
        .animation(.easeOut(duration: 0.25), value: model.visibleAsks.map(\.id))
    }

    private var onlyYou: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionLabel("Only you")
            ForEach(tasks) { task in
                TaskRow(task: task)
            }
        }
    }

    private var done: some View {
        let items = model.snapshot?.done ?? []
        let shown = showAllDone ? items : Array(items.prefix(Self.collapsedDone))
        return VStack(alignment: .leading, spacing: Space.m) {
            SectionLabel("Done since yesterday")
            if items.isEmpty {
                Text("Nothing finished in the last 24 hours.")
                    .foregroundStyle(Palette.textSecondary)
            } else {
                ForEach(shown) { item in
                    DoneCard(item: item)
                }
                if items.count > Self.collapsedDone {
                    Button(showAllDone ? "Show fewer" : "Show all \(items.count)") { showAllDone.toggle() }
                        .buttonStyle(.link)
                }
            }
        }
    }
}
