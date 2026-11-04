import AppKit
import Foundation
import SwiftUI

/// Hooks for taking screenshots of the app with sample data. They work only with
/// `TEYLA_STATE_FIXTURE` set, so a real run never reads them.
///
///     TEYLA_PREVIEW_OPEN   new-task | quick-note | settings | pair | focus:<ask id> | diagnosis | home | decisions | portfolio | tools | command-bar[:<query>] | product:<id>
///     TEYLA_START_FIXTURE / TEYLA_PRODUCT_FIXTURE / TEYLA_ATTENTION_FIXTURE  the diagnosis, product-page and Tools samples
///                         (default: start.v1.json, product.v1.json and attention.v1.json beside the state sample)
///     TEYLA_PREVIEW_START_DELAY  seconds the simulated diagnosis takes (default 1.5)
///     TEYLA_PREVIEW_NO_BINARY    pretend the teyla command is not installed (the not-found screen)
///     TEYLA_PREVIEW_SIZE   <width>x<height>, the content size of the main window
///     TEYLA_PREVIEW_DRAFT  text for the new-task sheet or the quick-note panel
///     TEYLA_PREVIEW_APPEARANCE  light | dark, for this app only
///     TEYLA_PREVIEW_SCROLL  end: scroll the main window to its bottom
///     TEYLA_PREVIEW_SNAPSHOT  <path.png>: draw the whole Home page in one image (width TEYLA_PREVIEW_WIDTH, default
///                         1100 pt, in the appearance above), save it and quit. For screenshots without a screen to click
///     TEYLA_PREVIEW_SNAPSHOT_VIEW  home (default) | decisions | portfolio | product:<id> | tools | settings | window (the window
///                         as it stands, with its toolbar; the size comes from TEYLA_PREVIEW_SIZE) | connect-phone (the "Connect iPhone"
///                         sheet) | setup (the store build's first screen; Home elsewhere)
@MainActor
enum Preview {
    private static var ran = false
    private static let env = ProcessInfo.processInfo.environment

    private static func enabled(_ model: AppModel) -> Bool { model.usesFixture }

    static func runOnce(model: AppModel, openSettings: @escaping () -> Void) {
        guard enabled(model), !ran else { return }
        ran = true
        switch env["TEYLA_PREVIEW_APPEARANCE"] {
        case "light": NSApp.appearance = NSAppearance(named: .aqua)
        case "dark": NSApp.appearance = NSAppearance(named: .darkAqua)
        default: break
        }
        if env["TEYLA_PREVIEW_SCROLL"] == "end" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                guard let view = NSApp.windows.first(where: { $0.canBecomeMain })?.contentView,
                      let scroll = firstScrollView(in: view), let doc = scroll.documentView else { return }
                let y = max(0, doc.frame.height - scroll.contentView.bounds.height)
                scroll.contentView.scroll(to: NSPoint(x: 0, y: doc.isFlipped ? y : 0))
                scroll.reflectScrolledClipView(scroll.contentView)
            }
        }
        if let size = env["TEYLA_PREVIEW_SIZE"] {
            let parts = size.split(separator: "x").compactMap { Double($0) }
            if parts.count == 2 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                    NSApp.windows.first { $0.canBecomeMain }?
                        .setContentSize(NSSize(width: parts[0], height: parts[1]))
                }
            }
        }
        if let path = env["TEYLA_PREVIEW_SNAPSHOT"] {
            let which = env["TEYLA_PREVIEW_SNAPSHOT_VIEW"] ?? "home"
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
                if which == "connect-phone" {
                    // The made-up key takes a moment to come back; the sheet is drawn once the code is there.
                    model.relay.connectPhone(turnOn: model.phoneNeedsRelayOn)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { snapshotView(which, model: model, path: path) }
                } else if which == "tools" || which.hasPrefix("product:") {
                    // These pages read their own sample file first.
                    model.go(which == "tools" ? .tools : .product(String(which.dropFirst("product:".count))))
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { snapshotView(which, model: model, path: path) }
                } else {
                    snapshotView(which, model: model, path: path)
                }
            }
            return
        }
        guard let step = env["TEYLA_PREVIEW_OPEN"] else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            switch step {
            case "new-task":
                if let draft = env["TEYLA_PREVIEW_DRAFT"] { model.newTask.draft = draft }
                model.openNewTask()
            case "quick-note":
                if let draft = env["TEYLA_PREVIEW_DRAFT"] { model.quickNote.draft = draft }
                model.openQuickNote()
            case "settings":
                openSettings()
            case "pair":
                // The "Connect iPhone" sheet with its QR code (a made-up key, so nothing is paired).
                model.showMainWindow()
                model.relay.present(turnOn: model.phoneNeedsRelayOn)
            case "diagnosis":
                model.runDiagnosis()
            case "home":
                model.go(.home)
            case "decisions":
                model.go(.decisions)
            case "portfolio":
                model.go(.portfolio)
            case "tools":
                model.go(.tools)
            case let bar where bar == "command-bar" || bar.hasPrefix("command-bar:"):
                model.go(.tools)
                model.openCommandBar()
                if bar.hasPrefix("command-bar:") { model.commandBar.query = String(bar.dropFirst("command-bar:".count)) }
            case let product where product.hasPrefix("product:"):
                model.openProduct(String(product.dropFirst("product:".count)))
            case let focus where focus.hasPrefix("focus:"):
                model.focus(askID: String(focus.dropFirst("focus:".count)))
            default:
                break
            }
        }
    }

    /// Draws one view at full height into a PNG. A scroll view would crop it to the window, so this lays the view out
    /// by itself in a hosting view of the width asked for.
    private static func snapshotView(_ which: String, model: AppModel, path: String) {
        if which == "window" {
            // The whole window with its toolbar: the frame view draws what the content view leaves out.
            if let frame = NSApp.windows.first(where: { $0.canBecomeMain })?.contentView?.superview {
                write(frame, to: path)
            }
            NSApp.terminate(nil)
            return
        }
        let width = Double(env["TEYLA_PREVIEW_WIDTH"] ?? "") ?? 1100
        let page: AnyView
        switch which {
        case "connect-phone":
            page = AnyView(ConnectPhoneSheet().environment(model))
        case "decisions":
            page = flat(DecisionsView(), model: model, width: width)
        case "portfolio":
            page = flat(PortfolioView(), model: model, width: width)
        case "tools":
            page = flat(ToolsView(), model: model, width: width)
        case "settings":
            page = flat(SettingsView(), model: model, width: width)
        case let product where product.hasPrefix("product:"):
            page = flat(ProductPageView(id: String(product.dropFirst("product:".count))), model: model, width: width)
        case "setup", "setup-hand", "setup-paired":
            #if STORE
            // A session of its own with an empty Keychain, so the screen shows the first run whatever this Mac holds.
            let session = StoreSession(backend: StoreBackend(), defaults: UserDefaults(suiteName: "teyla-preview-\(UUID().uuidString)")!,
                                       keyStore: PreviewKeys(key: which == "setup-paired" ? Data(repeating: 7, count: 32) : nil),
                                       bookmark: BookmarkStore(save: { _, _ in }, resolve: { _ in nil }, clear: { _ in }))
            page = AnyView(StoreSetupView(store: session, expanded: which == "setup-hand")
                .frame(width: min(width, 760), height: which == "setup-hand" ? 1250 : 760).environment(model))
            #else
            page = flat(HomeView(), model: model, width: width)
            #endif
        default:
            page = flat(HomeView(), model: model, width: width)
        }
        let host = NSHostingView(rootView: page)
        host.appearance = NSApp.appearance
        host.frame = NSRect(origin: .zero, size: host.fittingSize)
        host.layoutSubtreeIfNeeded()
        // A view that measures itself (`ClampedText`, the product page's width) updates on the next pass: fit again.
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(600))
            host.frame = NSRect(origin: .zero, size: host.fittingSize)
            host.layoutSubtreeIfNeeded()
            write(host, to: path)
            NSApp.terminate(nil)
        }
    }

    private static func write(_ view: NSView, to path: String) {
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: rep)
        if let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: path))
        }
    }

    /// A page at the width asked for, without its scroll view, so the image holds all of it.
    private static func flat(_ view: some View, model: AppModel, width: Double) -> AnyView {
        AnyView(view
            .environment(\.pageFlat, true)
            .frame(width: width, alignment: .topLeading)
            .background(Palette.background)
            .environment(model))
    }

    private static func firstScrollView(in view: NSView) -> NSScrollView? {
        if let scroll = view as? NSScrollView { return scroll }
        for sub in view.subviews { if let found = firstScrollView(in: sub) { return found } }
        return nil
    }
}

#if STORE
/// A key store that lives in memory, for the first-run previews.
private final class PreviewKeys: KeyStore, @unchecked Sendable {
    var key: Data?
    init(key: Data?) { self.key = key }
    func load() -> Data? { key }
    func save(_ key: Data) throws { self.key = key }
    func delete() { key = nil }
}
#endif
