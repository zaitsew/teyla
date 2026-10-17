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

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @State private var showNewTask = false
    @State private var showSettings = false

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
        TabView {
            Tab("Today", systemImage: "sun.max") {
                TodayView(showNewTask: $showNewTask, showSettings: $showSettings)
            }
            Tab("Products", systemImage: "square.stack.3d.up") {
                ProductsView(showNewTask: $showNewTask)
            }
        }
        .sheet(isPresented: $showNewTask) { NewTaskView() }
        .sheet(isPresented: $showSettings) { SettingsView() }
    }
}
