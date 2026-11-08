import SwiftUI

/// The Today card at the top of the Growth tab, read-only: the goal furthest behind with one row of circles per outcome target,
/// how it stands this week, one line on what is next, and the quiet line (Sent, Came back, Prepared). The Mac sends counts and the
/// owner's goal titles in the snapshot's `gtm`; there are no names, links or messages in it, and no commit counts. A circle fills
/// only for a real outcome that came back; a draft or a send never fills one. An older Mac sends no `gtm`, and the card is hidden.
/// VoiceOver reads each row of circles as one sentence, and the quiet line as one sentence.
struct TodayCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let gtm = model.snapshot?.gtm {
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: "Today", note: TodayLogic.dayWords(gtm.day) ?? gtm.day)
                if let lead = gtm.lead {
                    LeadGoal(goal: lead, gtm: gtm)
                } else {
                    Text(gtm.hasGoals ? "No goal has a weekly number yet." : "Set a goal on your Mac: open Today there.")
                        .font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
                QuietLine(gtm: gtm)
                if let untagged = gtm.untaggedLine {
                    Text(untagged).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            }
            .card()
        }
    }
}

private struct LeadGoal: View {
    let goal: GtmGoal
    let gtm: GtmGlimpse

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            VStack(alignment: .leading, spacing: Space.xs) {
                Text(goal.title).font(Typo.cardTitle).fixedSize(horizontal: false, vertical: true)
                Text(TodayLogic.goalMeta(goal)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                if let pace = TodayLogic.pace(goal) { PaceChip(pace: pace) }
            }
            ForEach(goal.outcomeTargets, id: \.stage) { target in
                VStack(alignment: .leading, spacing: Space.xs) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(TodayLogic.stageLabel(target.stage)).font(Typo.caption)
                        Spacer(minLength: Space.s)
                        Text(TodayLogic.targetWords(target)).font(Typo.caption.weight(.semibold).monospacedDigit())
                    }
                    GoalBeads(target: target)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(TodayLogic.beadsSpoken(target))
            }
            if let next = gtm.nextTitle {
                Divider()
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text("Next").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    Text(next).font(Typo.body.weight(.semibold))
                    if let detail = gtm.nextDetail { Text(detail).font(Typo.caption).foregroundStyle(Palette.textSecondary) }
                }
                .accessibilityElement(children: .combine)
            }
        }
    }
}

/// Sent today, what came back and waits, what agents prepared: one quiet line. Prepared is agent work, so it is never accented.
private struct QuietLine: View {
    let gtm: GtmGlimpse

    var body: some View {
        let sent = gtm.distribution.target.map { "\(gtm.distribution.today) of \($0)" } ?? "\(gtm.distribution.today)"
        let back = gtm.cameBack == 0 ? "none waiting" : "\(gtm.cameBack) waiting"
        Text("Sent \(sent)  ·  Came back \(back)  ·  Prepared \(gtm.approve)")
            .font(Typo.caption.monospacedDigit())
            .foregroundStyle(Palette.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(gtm.stripSpoken)
    }
}
