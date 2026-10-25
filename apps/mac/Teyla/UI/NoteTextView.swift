import AppKit
import Carbon.HIToolbox
import SwiftUI

/// A multi-line text field for a note. Return saves, Shift-Return adds a line, Esc closes, and ⌘0–⌘9 pick a
/// product. The text is kept as typed: no smart quotes, no dash or text replacement.
struct NoteTextView: NSViewRepresentable {
    @Binding var text: String
    var placeholder: String
    var focusToken: Int
    var isEditable: Bool
    var onEdit: () -> Void
    var onSubmit: () -> Void
    var onCancel: () -> Void
    var onDigit: (Int) -> Bool

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder
        let view = KeyTextView()
        view.delegate = context.coordinator
        view.drawsBackground = false
        view.isRichText = false
        view.allowsUndo = true
        view.isAutomaticQuoteSubstitutionEnabled = false
        view.isAutomaticDashSubstitutionEnabled = false
        view.isAutomaticTextReplacementEnabled = false
        view.isAutomaticSpellingCorrectionEnabled = false
        view.font = NSFont.preferredFont(forTextStyle: .title3)
        view.textColor = .labelColor
        view.textContainerInset = NSSize(width: 0, height: Space.xs)
        view.isVerticallyResizable = true
        view.isHorizontallyResizable = false
        view.autoresizingMask = [.width]
        view.textContainer?.widthTracksTextView = true
        view.placeholder = placeholder
        scroll.documentView = view
        context.coordinator.view = view
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        context.coordinator.parent = self
        guard let view = context.coordinator.view else { return }
        if view.string != text { view.string = text }
        view.isEditable = isEditable
        view.placeholder = placeholder
        view.onSubmit = onSubmit
        view.onCancel = onCancel
        view.onDigit = onDigit
        if context.coordinator.focusToken != focusToken {
            context.coordinator.focusToken = focusToken
            DispatchQueue.main.async {
                view.window?.makeFirstResponder(view)
                view.setSelectedRange(NSRange(location: (view.string as NSString).length, length: 0))
            }
        }
    }

    @MainActor
    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: NoteTextView
        weak var view: KeyTextView?
        var focusToken = -1

        init(_ parent: NoteTextView) { self.parent = parent }

        func textDidChange(_ notification: Notification) {
            guard let view else { return }
            parent.text = view.string
            parent.onEdit()
        }
    }
}

final class KeyTextView: NSTextView {
    var placeholder = "" {
        didSet { needsDisplay = true }
    }
    var onSubmit: (() -> Void)?
    var onCancel: (() -> Void)?
    var onDigit: ((Int) -> Bool)?

    override func keyDown(with event: NSEvent) {
        let isReturn = event.keyCode == UInt16(kVK_Return) || event.keyCode == UInt16(kVK_ANSI_KeypadEnter)
        // A Return that confirms an input-method composition is not ours.
        if isReturn, !hasMarkedText() {
            if event.modifierFlags.contains(.shift) { insertNewline(nil) } else { onSubmit?() }
            return
        }
        super.keyDown(with: event)
    }

    override func cancelOperation(_ sender: Any?) {
        onCancel?()
    }

    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        if flags == .command, let digit = event.charactersIgnoringModifiers.flatMap({ Int($0) }), onDigit?(digit) == true {
            return true
        }
        return super.performKeyEquivalent(with: event)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard string.isEmpty, !placeholder.isEmpty else { return }
        let origin = NSPoint(x: textContainerOrigin.x + (textContainer?.lineFragmentPadding ?? 0), y: textContainerOrigin.y)
        let attributes: [NSAttributedString.Key: Any] = [
            .font: font ?? NSFont.preferredFont(forTextStyle: .title3),
            .foregroundColor: NSColor.placeholderTextColor,
        ]
        placeholder.draw(at: origin, withAttributes: attributes)
    }
}
