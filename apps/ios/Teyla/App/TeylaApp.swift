import SwiftUI

@main
struct TeylaApp: App {
    @State private var model = AppModel()
    @State private var dictation = Dictation()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(dictation)
                // A pairing code scanned with the system Camera arrives here as `teyla-pair:v1:<key>`.
                .onOpenURL { url in model.handlePairingLink(url) }
        }
    }
}

/// The tabs; `TEYLA_TAB` (home, decisions, products) opens one on launch, for screenshots.
enum AppTab: String, Hashable {
    case home, decisions, products
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @State private var showNewTask = false
    @State private var showSettings = false
    @State private var tab: AppTab
    private let options: LaunchOptions

    init() {
        let options = LaunchOptions()
        self.options = options
        _tab = State(initialValue: AppTab(rawValue: options.tab ?? "") ?? (options.openProduct == nil ? .home : .products))
    }

    var body: some View {
        Group {
            if model.setupStep < 3 {
                OnboardingView()
            } else {
                tabs
            }
        }
        // Read on launch and every 15 s while the app is in the foreground.
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await model.refresh()
                try? await Task.sleep(for: .seconds(15))
            }
        }
        .alert("Could not send", isPresented: Binding(
            get: { model.sendError != nil && !showNewTask },
            set: { if !$0 { model.sendError = nil } }
        )) {
            Button("OK") { model.sendError = nil }
        } message: {
            Text(model.sendError ?? "")
        }
        .alert("Could not pair", isPresented: Binding(
            get: { model.pairingError != nil },
            set: { if !$0 { model.pairingError = nil } }
        )) {
            Button("OK") { model.pairingError = nil }
        } message: {
            Text(model.pairingError ?? "")
        }
        // Any web page can open a pairing link, so a different key never replaces the stored one unasked.
        .alert("Pair with a different Mac?", isPresented: Binding(
            get: { model.pendingPairing != nil },
            set: { _ in }   // only the two buttons decide
        )) {
            Button("Keep current Mac", role: .cancel) { model.cancelPendingPairing() }
            Button("Pair with the new Mac", role: .destructive) { model.confirmPendingPairing() }
        } message: {
            Text("A pairing code asked this iPhone to switch to another Mac. If you did not just scan a code on your Mac, keep the current one.")
        }
    }

    private var tabs: some View {
        TabView(selection: $tab) {
            Tab("Home", systemImage: "house", value: AppTab.home) {
                HomeView(tab: $tab, showNewTask: $showNewTask, showSettings: $showSettings)
            }
            Tab("Decisions", systemImage: "checkmark.bubble", value: AppTab.decisions) {
                DecisionsView()
            }
            .badge(model.ownerAsks.count)
            Tab("Products", systemImage: "square.stack.3d.up", value: AppTab.products) {
                PortfolioView(showNewTask: $showNewTask, options: options)
            }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            if model.isSample { SampleBanner() }
        }
        .sheet(isPresented: $showNewTask) { NewTaskView() }
        .sheet(isPresented: $showSettings) { SettingsView() }
    }
}

/// Always visible in sample mode, so nobody mistakes made-up data for their own.
struct SampleBanner: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: Space.s) {
            Image(systemName: "eye").accessibilityHidden(true).foregroundStyle(Palette.textSecondary)
            Text(SampleData.bannerText)
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: Space.xs)
            Button("Pair") { model.leaveSample() }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
        }
        .padding(.horizontal, Space.l)
        .padding(.vertical, Space.s)
        .frame(maxWidth: .infinity)
        .background(.bar)
        .accessibilityElement(children: .contain)
    }
}
