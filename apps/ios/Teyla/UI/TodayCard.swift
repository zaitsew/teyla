import SwiftUI

/// The Today card at the top of the Growth tab, read-only: what waits for you, today's sends against the target, and one row per goal
/// with its weekly targets and the days left. The Mac sends counts and the owner's goal titles in the snapshot's `gtm`; there are no
/// names, links or messages in it, and no commit counts. An older Mac sends no `gtm`, and the card is hidden.
/// VoiceOver reads the top of the card as one sentence, and each goal as one sentence.
struct TodayCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let gtm = model.snapshot?.gtm {
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: "Today", note: gtm.day.isEmpty ? "What waits for you and what you sent." : gtm.day)
                VStack(alignment: .leading, spacing: Space.m) {
                    HStack(alignment: .firstTextBaseline, spacing: Space.l) {
                        figure("\(gtm.approve)", "to approve")
                        figure("\(gtm.send)", "to send")
                        figure("\(gtm.reply)", "replies")
                    }
                    HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                        Text(gtm.distributionFigure).font(Typo.cardTitle.monospacedDigit())
                        Text("sent today").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                        Spacer(minLength: Space.s)
                        Text("\(gtm.outcomesWeek) outcomes this week").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    }
                    if let fraction = gtm.distributionFraction {
                        ProgressView(value: fraction).tint(Palette.primaryMuted)
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(gtm.spoken)
                if gtm.goals.isEmpty {
                    Text(gtm.hasGoals ? "No goal has a weekly target." : "Add goals on your Mac with `teyla gtm init`.")
                        .font(Typo.caption).foregroundStyle(Palette.textSecondary)
                } else {
                    ForEach(gtm.goals) { goal in GoalRow(goal: goal) }
                }
            }
            .card()
        }
    }

    private func figure(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(value).font(Typo.number)
            Text(label).font(Typo.caption).foregroundStyle(Palette.textSecondary)
        }
    }
}

private struct GoalRow: View {
    let goal: GtmGlimpse.Goal

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Divider()
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                Text(goal.title).font(Typo.body.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: Space.s)
                if let left = TodayLogic.daysLeftWords(goal.daysLeft) {
                    Text(left).font(Typo.caption).foregroundStyle(Palette.textSecondary).multilineTextAlignment(.trailing)
                }
            }
            ForEach(goal.targets, id: \.stage) { target in
                HStack {
                    Text(TodayLogic.stageName(target.stage).capitalized).font(Typo.caption)
                    Spacer(minLength: Space.s)
                    Text(TodayLogic.targetWords(GtmTarget(stage: target.stage, count: target.count, target: target.target)))
                        .font(Typo.caption.weight(.semibold).monospacedDigit())
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(TodayLogic.goalSpoken(GtmGoal(id: goal.id, title: goal.title, daysLeft: goal.daysLeft,
                                                          targets: goal.targets.map { GtmTarget(stage: $0.stage, count: $0.count, target: $0.target) })))
    }
}
