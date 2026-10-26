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
        }
    }
}

/// The tabs; `TEYLA_TAB` (today, portfolio, products) opens one on launch, for screenshots.
enum AppTab: String, Hashable {
    case today, portfolio, products
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
        _tab = State(initialValue: AppTab(rawValue: options.tab ?? "") ?? (options.openProduct == nil ? .today : .portfolio))
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
    }

    private var tabs: some View {
        TabView(selection: $tab) {
            Tab("Today", systemImage: "sun.max", value: AppTab.today) {
                TodayView(showNewTask: $showNewTask, showSettings: $showSettings)
            }
            Tab("Portfolio", systemImage: "chart.bar.doc.horizontal", value: AppTab.portfolio) {
                PortfolioView(showNewTask: $showNewTask, options: options)
            }
            Tab("Products", systemImage: "square.stack.3d.up", value: AppTab.products) {
                ProductsView(showNewTask: $showNewTask)
            }
        }
        .sheet(isPresented: $showNewTask) { NewTaskView() }
        .sheet(isPresented: $showSettings) { SettingsView() }
    }
}
