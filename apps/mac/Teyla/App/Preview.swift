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
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { snapshotHome(model: model, path: path) }
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
            case "settings", "pair":
                openSettings()
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

    /// Draws `HomeContent` at full height into a PNG. A scroll view would crop it to the window, so this lays the page out
    /// by itself in a hosting view of the width asked for.
    private static func snapshotHome(model: AppModel, path: String) {
        let width = Double(env["TEYLA_PREVIEW_WIDTH"] ?? "") ?? 1100
        let page = HomeContent(eager: true)
            .padding(.horizontal, Space.xl + Space.xs)
            .padding(.vertical, Space.xl)
            .frame(width: width, alignment: .topLeading)
            .background(Palette.background)
            .environment(model)
        let host = NSHostingView(rootView: page)
        host.appearance = NSApp.appearance
        let height = host.fittingSize.height
        host.frame = NSRect(x: 0, y: 0, width: width, height: height)
        host.layoutSubtreeIfNeeded()
        if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
            host.cacheDisplay(in: host.bounds, to: rep)
            if let png = rep.representation(using: .png, properties: [:]) {
                try? png.write(to: URL(fileURLWithPath: path))
            }
        }
        NSApp.terminate(nil)
    }

    private static func firstScrollView(in view: NSView) -> NSScrollView? {
        if let scroll = view as? NSScrollView { return scroll }
        for sub in view.subviews { if let found = firstScrollView(in: sub) { return found } }
        return nil
    }

    static func settingsShown(model: AppModel) {
        guard enabled(model), env["TEYLA_PREVIEW_OPEN"] == "pair" else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            model.relay.setOn(true)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { model.relay.pair() }
        }
    }
}
