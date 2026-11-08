import SwiftUI

// The two pieces of a goal that the Mac's Today page and the iPhone's Today card share: a row of circles and the pace chip.
// The iPhone target compiles this file by path. It depends on SwiftUI, the tokens and `TodayLogic`.

/// One circle per unit of a weekly number. A circle fills only for a real outcome that came back; a draft or a send never fills
/// one. Above `TodayLogic.beadLimit` circles it draws a thin bar. VoiceOver skips the circles: the row that holds them speaks.
struct GoalBeads: View {
    let target: GtmTarget

    var body: some View {
        Group {
            switch TodayLogic.beads(target) {
            case .circles(let total, let filled):
                LazyVGrid(columns: [GridItem(.adaptive(minimum: Space.bead, maximum: Space.bead), spacing: Space.s)],
                          alignment: .leading, spacing: Space.s) {
                    ForEach(0 ..< total, id: \.self) { index in bead(filled: index < filled) }
                }
            case .bar(let fraction):
                Capsule()
                    .fill(Palette.track)
                    .frame(height: Space.beadBar)
                    .overlay(alignment: .leading) {
                        GeometryReader { box in
                            Capsule().fill(Palette.primary).frame(width: box.size.width * fraction)
                        }
                    }
            }
        }
        .accessibilityHidden(true)
    }

    @ViewBuilder private func bead(filled: Bool) -> some View {
        if filled {
            Circle().fill(Palette.primary).frame(width: Space.bead, height: Space.bead)
        } else {
            Circle().strokeBorder(Palette.beadEmpty, lineWidth: Space.beadStroke).frame(width: Space.bead, height: Space.bead)
        }
    }
}

/// "Behind this week · 14 short" in the colour of "waiting on you", "On pace this week" in the colour of "saved".
struct PaceChip: View {
    let pace: TodayLogic.Pace

    var body: some View {
        let color = pace == .onPace ? Palette.saving : Palette.needsYou
        Text(TodayLogic.paceWords(pace))
            .font(Typo.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, Space.m)
            .padding(.vertical, Space.xs)
            .background(color.opacity(0.14), in: Capsule())
            .fixedSize()
    }
}
