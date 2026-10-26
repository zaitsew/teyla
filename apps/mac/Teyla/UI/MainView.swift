import SwiftUI

/// The window: the not-found screen, the welcome, or the sidebar and the page it points at.
struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        Group {
            if model.teylaMissing {
                NotFoundView()
            } else if model.showsWelcomeOnly {
                WelcomeView()
            } else {
                NavigationSplitView {
                    SidebarView()
                        .navigationSplitViewColumnWidth(min: Space.sidebarMin, ideal: Space.sidebarIdeal, max: Space.sidebarMax)
                } detail: {
                    DetailView()
                }
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
            }
        }
        .background(Palette.background)
        .tint(Palette.primary)
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
}

private struct DetailView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        switch model.route {
        case .today: TodayView()
        case .portfolio: PortfolioView()
        case .diagnosis: DiagnosisView()
        case .product(let id): ProductPageView(id: id)
        }
    }
}

/// Today, Diagnosis, and a page per registered product.
private struct SidebarView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let products = (model.snapshot?.products ?? []).filter(\.hasPage)
        List(selection: Binding(get: { model.route }, set: { model.go($0 ?? .today) })) {
            Label {
                Text("Today")
            } icon: {
                Image(systemName: "sun.max")
            }
            .badge(model.visibleAsks.count)
            .tag(AppRoute.today)
            Label("Portfolio", systemImage: "square.grid.2x2")
                .badge(model.snapshot?.portfolio.map { $0.counts.offTrack + $0.counts.atRisk } ?? 0)
                .tag(AppRoute.portfolio)
            Label("Diagnosis", systemImage: "stethoscope")
                .tag(AppRoute.diagnosis)
            if !products.isEmpty {
                Section("Products") {
                    ForEach(products) { product in
                        HStack(spacing: Space.xs) {
                            Text(product.title).lineLimit(1)
                            if product.focus {
                                Image(systemName: "star.fill")
                                    .font(Typo.caption)
                                    .foregroundStyle(Palette.warning)
                                    .accessibilityLabel("In focus")
                            }
                        }
                        .badge(product.waiting)
                        .tag(AppRoute.product(product.name))
                    }
                }
            }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            HStack(spacing: Space.s) {
                BrandMark()
                Text("Teyla").font(Typo.lead)
                Spacer()
            }
            .padding(.horizontal, Space.m)
            .padding(.vertical, Space.s)
        }
    }
}

/// Variant B, "morning brief": one sentence on what matters, then the questions ranked by what
/// they unblock, the tasks only you can do, and what got done. The side column holds products and running sessions.
private struct TodayView: View {
    @Environment(AppModel.self) private var model

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
                                // The cards stop at the reading width; extra room goes to the side column.
                                MainColumn().readingWidth()
                                StatusColumn().frame(minWidth: Space.sideColumn, maxWidth: Space.sideColumnMax, alignment: .leading)
                            }
                        } else {
                            VStack(alignment: .leading, spacing: Space.xl) {
                                MainColumn().readingWidth()
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
        .navigationTitle("Today")
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

/// The toolbar status. It says what the data on screen is doing, not whether the command once answered:
/// updating (a refresh or the open page is reading), up to date, stale (older than two minutes) or offline.
/// Green is reserved for money saved, so "up to date" is a neutral dot.
private struct LiveIndicator: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let indicator = model.syncIndicator(at: context.date)
            HStack(spacing: Space.xs + Space.xxs) {
                switch indicator.state {
                case .updating:
                    ProgressView().controlSize(.mini)
                case .upToDate:
                    dot(Palette.textSecondary)
                case .stale:
                    dot(Palette.warning)
                case .offline:
                    dot(Palette.danger)
                }
                Text(indicator.label)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            .help(indicator.tooltip)
            .accessibilityElement(children: .combine)
            .accessibilityLabel(indicator.label)
        }
    }

    private func dot(_ color: Color) -> some View {
        Circle()
            .fill(color)
            .frame(width: Space.s - Space.xxs, height: Space.s - Space.xxs)
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
        let asks = AskFold.partition(model.visibleAsks) { model.age(of: $0) }
        return VStack(alignment: .leading, spacing: Space.m) {
            SectionLabel("Needs you — ordered by what it unblocks")
            if model.visibleAsks.isEmpty {
                Label("Nothing is waiting for an answer.", systemImage: "checkmark.circle")
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.vertical, Space.s)
            } else {
                ForEach(asks.fresh) { ask in
                    AskCard(ask: ask)
                        .transition(.opacity.combined(with: .scale(scale: 0.97)))
                }
                if !asks.older.isEmpty {
                    OlderGroup(count: asks.older.count, revealsFocus: asks.older.contains { $0.id == model.focusedAskID }) {
                        ForEach(asks.older) { ask in
                            AskCard(ask: ask, older: true)
                                .transition(.opacity.combined(with: .scale(scale: 0.97)))
                        }
                    }
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
