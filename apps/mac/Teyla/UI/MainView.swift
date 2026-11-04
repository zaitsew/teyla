import SwiftUI

/// The window: the not-found screen, the welcome, or the sidebar and the page it points at.
struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        content
        .background(Palette.background)
        .tint(Palette.primary)
        .navigationTitle("Teyla")
        .sheet(isPresented: Bindable(model.newTask).presented) {
            NewTaskSheet()
                .environment(model)
        }
        .sheet(isPresented: Bindable(model.commandBar).presented) {
            CommandBarView()
                .environment(model)
        }
        .sheet(isPresented: Bindable(model.relay).presented) {
            ConnectPhoneSheet()
                .environment(model)
        }
        #if STORE
        .alert("Replace the pairing with this Mac?", isPresented: Binding(
            get: { model.store.hasPendingPairing },
            set: { _ in })) {   // only the two buttons decide
            Button("Keep the current pairing", role: .cancel) { model.store.declinePendingPairing() }
            Button("Replace", role: .destructive) { model.store.confirmPendingPairing() }
        } message: {
            Text("A pairing link for a different Mac arrived. Replace only if you just ran teyla relay connect yourself. "
                 + "Otherwise keep the current pairing.")
        }
        #endif
        .onAppear {
            model.openMainWindow = { openWindow(id: "main") }
            Preview.runOnce(model: model, openSettings: { openSettings() })
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            model.refresh()
        }
    }

    @ViewBuilder private var content: some View {
        #if STORE
        // Until a Mac is paired (or the sample chosen) there is nothing to read: the setup screen comes first.
        if model.store.mode == .setup {
            StoreSetupView()
        } else {
            window
        }
        #else
        if model.teylaMissing { NotFoundView() } else { window }
        #endif
    }

    @ViewBuilder private var window: some View {
        if model.showsWelcomeOnly {
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
}

private struct DetailView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        page
        #if STORE
            // Under the toolbar, above the page: the sample is never taken for the owner's own data.
            .safeAreaInset(edge: .top, spacing: 0) {
                if model.store.isSample { SampleBanner() }
            }
        #endif
    }

    @ViewBuilder private var page: some View {
        switch model.route {
        case .home: HomeView()
        case .decisions: DecisionsView()
        case .portfolio: PortfolioView()
        case .diagnosis: DiagnosisView()
        case .tools: ToolsView()
        case .product(let id): ProductPageView(id: id)
        }
    }
}

/// Home, Decisions and All products; Tools below them (the diagnosis opens from Tools). A product opens from a card or a row, not from the sidebar.
private struct SidebarView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        // The diagnosis page has no row of its own: Tools stays selected while it shows.
        List(selection: Binding(get: { model.route == .diagnosis ? .tools : model.route }, set: { model.go($0 ?? .home) })) {
            Label("Home", systemImage: "house")
                .tag(AppRoute.home)
            Label("Decisions", systemImage: "tray")
                .badge(model.ownerAsks.count)
                .tag(AppRoute.decisions)
            Label("All products", systemImage: "square.grid.2x2")
                .tag(AppRoute.portfolio)
            if model.capabilities.tools {
                Section {
                    Label("Tools", systemImage: "wrench.and.screwdriver")
                        .badge(model.tools.badge.map { Text($0) })
                        .tag(AppRoute.tools)
                }
            }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            HStack(spacing: Space.s) {
                BrandMark()
                Text("Teyla").font(Typo.cardTitle)
                Spacer()
            }
            .padding(.horizontal, Space.m)
            .padding(.vertical, Space.s)
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
            HStack(spacing: Space.xs) {
                switch indicator.state {
                case .updating:
                    ProgressView().controlSize(.mini)
                case .upToDate:
                    dot(Palette.textSecondary)
                case .stale:
                    dot(Palette.needsYou)
                case .offline:
                    dot(Palette.danger)
                }
                Text(indicator.label)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            // The toolbar draws its capsule tight around an item: the inset keeps the dot off its edge.
            .padding(.horizontal, Space.s)
            .help(indicator.tooltip)
            .accessibilityElement(children: .combine)
            .accessibilityLabel(indicator.label)
        }
    }

    private func dot(_ color: Color) -> some View {
        Circle()
            .fill(color)
            .frame(width: Space.dot, height: Space.dot)
    }
}
