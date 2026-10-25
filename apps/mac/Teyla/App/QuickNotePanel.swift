import AppKit
import SwiftUI

/// A borderless panel that can take typing without making Teyla the active app, so the app you were in
/// keeps its place. Esc and a click elsewhere close it; the draft stays in `QuickNoteModel`.
final class QuickNotePanel: NSPanel {
    var onCancel: (() -> Void)?

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    override func cancelOperation(_ sender: Any?) {
        onCancel?()
    }
}

@MainActor
final class QuickNotePanelController: NSObject, NSWindowDelegate {
    static let shared = QuickNotePanelController()

    private var panel: QuickNotePanel?

    var isVisible: Bool { panel?.isVisible ?? false }

    func show(model: AppModel) {
        let panel = self.panel ?? makePanel(model: model)
        self.panel = panel
        position(panel)
        model.quickNote.opened()
        panel.makeKeyAndOrderFront(nil)
    }

    func hide() {
        panel?.orderOut(nil)
    }

    private func makePanel(model: AppModel) -> QuickNotePanel {
        let size = NSSize(width: Space.capturePanelWidth, height: Space.capturePanelHeight)
        let panel = QuickNotePanel(contentRect: NSRect(origin: .zero, size: size),
                                   styleMask: [.borderless, .nonactivatingPanel, .fullSizeContentView],
                                   backing: .buffered, defer: false)
        panel.level = .floating
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.title = "Quick note"
        panel.delegate = self
        panel.onCancel = { [weak self] in self?.hide() }
        panel.contentView = NSHostingView(rootView: QuickNoteView().environment(model))
        return panel
    }

    /// Centred on the screen the pointer is on, in the upper part of it.
    private func position(_ panel: QuickNotePanel) {
        let pointer = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(pointer, $0.frame, false) } ?? NSScreen.main
        guard let area = screen?.visibleFrame else { return }
        let size = panel.frame.size
        let x = area.midX - size.width / 2
        let y = area.maxY - area.height * Space.captureTopFraction - size.height
        panel.setFrameOrigin(NSPoint(x: x.rounded(), y: y.rounded()))
    }

    nonisolated func windowDidResignKey(_ notification: Notification) {
        Task { @MainActor in self.hide() }
    }
}
