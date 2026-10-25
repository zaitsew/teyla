import AppKit
import SwiftUI

/// Records a global shortcut: click the field, press a combination with ⌘, ⌥ or ⌃. Esc cancels, Clear turns it off.
/// While it listens, push-to-talk and the quick-note shortcut are released so pressing them reaches the field.
struct ShortcutRecorder: View {
    @Environment(AppModel.self) private var model
    @State private var recording = false
    @State private var monitor: Any?
    @State private var refusal: String?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(spacing: Space.s) {
                Button(action: toggle) {
                    Text(fieldText)
                        .frame(minWidth: Space.shortcutFieldWidth)
                        .foregroundStyle(recording ? Palette.accent : (model.quickNoteSetting == nil ? Palette.textSecondary : .primary))
                }
                .accessibilityLabel("Quick note shortcut")
                .accessibilityValue(model.quickNoteSetting?.display ?? "none")
                .accessibilityHint("Click, then press the new shortcut")
                Button("Clear") {
                    stop()
                    refusal = nil
                    model.setQuickNoteShortcut(nil)
                }
                .disabled(model.quickNoteSetting == nil && !recording)
            }
            Text(refusal ?? model.quickNoteLine)
                .font(Typo.caption)
                .foregroundStyle(refusal == nil ? Palette.textSecondary : Palette.danger)
                .fixedSize(horizontal: false, vertical: true)
        }
        .onDisappear { stop() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didResignActiveNotification)) { _ in stop() }
    }

    private var fieldText: String {
        if recording { return "Press a shortcut…" }
        return model.quickNoteSetting?.display ?? "Not set"
    }

    private func toggle() {
        recording ? stop() : start()
    }

    private func start() {
        refusal = nil
        recording = true
        model.pauseShortcuts()
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            let result = ShortcutRules.check(keyCode: UInt32(event.keyCode),
                                             modifiers: Shortcut.carbonModifiers(from: event.modifierFlags))
            switch result {
            case .cancelled:
                refusal = nil
                stop()
            case .refused(let reason):
                refusal = reason
            case .accepted(let shortcut):
                refusal = nil
                model.setQuickNoteShortcut(shortcut)
                stop()
            }
            return nil
        }
    }

    private func stop() {
        guard recording else { return }
        recording = false
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        model.resumeShortcuts()
    }
}
