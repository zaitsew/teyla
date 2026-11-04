import AppKit
import SwiftUI
import UserNotifications

@main
struct TeylaApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    private let model: AppModel

    init() {
        // Before the model reads its settings: the full app keeps what it stored under its old bundle id.
        #if !STORE
        DefaultsMigration.run()
        #endif
        model = AppModel.shared
    }

    var body: some Scene {
        // A single window with a fixed id. Closing it never strands the user: the Window menu
        // lists it as "Teyla" with ⌘0, and the menu-bar item opens it too.
        Window("Teyla", id: "main") {
            MainView()
                .environment(model)
                .frame(minWidth: Space.windowMinWidth, minHeight: Space.windowMinHeight)
        }
        .defaultSize(width: Space.windowDefaultWidth, height: Space.windowDefaultHeight)
        .keyboardShortcut("0")
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Task…") { model.openNewTask() }
                    .keyboardShortcut("n")
                Button("Connect iPhone…") { model.openConnectPhone() }
                    .disabled(!model.canConnectPhone)
            }
            CommandGroup(before: .toolbar) {
                Button("Command Bar…") { model.openCommandBar() }
                    .keyboardShortcut("k")
                Divider()
            }
        }

        MenuBarExtra {
            MenuBarContent()
                .environment(model)
        } label: {
            MenuBarLabel(model: model)
        }
        .menuBarExtraStyle(.window)

        Settings {
            SettingsView()
                .environment(model)
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        if Bundle.main.bundleURL.pathExtension == "app" {
            UNUserNotificationCenter.current().delegate = self
        }
        AppModel.shared.start()
        AppModel.shared.registerHotKey()
    }

    #if STORE
    /// `teyla relay connect` hands the pairing key to this build as a `teyla-pair:` link (only this target registers it).
    func application(_ application: NSApplication, open urls: [URL]) {
        let session = AppModel.shared.store
        for url in urls { session.receive(url: url) }
        AppModel.shared.showMainWindow()
    }
    #endif

    /// Clicking the Dock icon with no window open brings the window back.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { AppModel.shared.showMainWindow() }
        return true
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    /// A clicked notification brings the window forward and marks the card it was about.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            didReceive response: UNNotificationResponse) async {
        let askID = response.notification.request.content.userInfo["ask"] as? String
        await MainActor.run {
            if let askID { AppModel.shared.focus(askID: askID) } else { AppModel.shared.showMainWindow() }
        }
    }
}
