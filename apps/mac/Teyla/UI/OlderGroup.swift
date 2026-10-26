import SwiftUI

/// A collapsed group under the fresh questions: "Older · 15". Questions that waited more than a week
/// are rarely the ones to answer now, and they pushed fresh ones down the page.
struct OlderGroup<Content: View>: View {
    let count: Int
    /// A notification pointed at a card inside the group: open it so the card can scroll into view.
    var revealsFocus = false
    @ViewBuilder var content: Content

    @State private var open = false

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Button {
                withAnimation(.easeOut(duration: 0.2)) { open.toggle() }
            } label: {
                HStack(spacing: Space.xs) {
                    Image(systemName: "chevron.right")
                        .imageScale(.small)
                        .rotationEffect(.degrees(open ? 90 : 0))
                    Text(AskFold.heading(count: count)).font(Typo.body.weight(.semibold))
                    Text("waiting more than 7 days").font(Typo.caption)
                }
                .foregroundStyle(Palette.textSecondary)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Older questions, \(count)")
            .accessibilityValue(open ? "Expanded" : "Collapsed")
            if open {
                content
            }
        }
        .onChange(of: revealsFocus) { _, reveals in
            if reveals { open = true }
        }
        .onAppear {
            if revealsFocus { open = true }
        }
    }
}
