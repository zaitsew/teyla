import AppKit
import Foundation

/// Hooks for taking screenshots of the app with sample data. They work only with
/// `TEYLA_STATE_FIXTURE` set, so a real run never reads them.
///
///     TEYLA_PREVIEW_OPEN   new-task | quick-note | settings | pair | focus:<ask id> | diagnosis | product:<id>
///     TEYLA_START_FIXTURE / TEYLA_PRODUCT_FIXTURE  the diagnosis and product-page samples (default: start.v1.json and
///                         product.v1.json beside the state sample)
///     TEYLA_PREVIEW_START_DELAY  seconds the simulated diagnosis takes (default 1.5)
///     TEYLA_PREVIEW_NO_BINARY    pretend the teyla command is not installed (the not-found screen)
///     TEYLA_PREVIEW_SIZE   <width>x<height>, the content size of the main window
///     TEYLA_PREVIEW_DRAFT  text for the new-task sheet or the quick-note panel
///     TEYLA_PREVIEW_APPEARANCE  light | dark, for this app only
///     TEYLA_PREVIEW_SCROLL  end: scroll the main window to its bottom
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
            case let product where product.hasPrefix("product:"):
                model.openProduct(String(product.dropFirst("product:".count)))
            case let focus where focus.hasPrefix("focus:"):
                model.focus(askID: String(focus.dropFirst("focus:".count)))
            default:
                break
            }
        }
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
