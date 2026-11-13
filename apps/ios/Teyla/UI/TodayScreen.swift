import SwiftUI

/// Today (Lab): the Home tab with exactly three things, decisions, the content card and builds to try.
/// Variant A "stack" lists the three groups. Variant B "one next thing" puts one large card first and the rest below it, small.
/// `teyla.lab.today` is "off", "a" or "b"; off keeps the current Home.
struct TodayScreen: View {
    @Environment(AppModel.self) private var model
    let variant: TodayVariant
    @Binding var tab: AppTab
    @Binding var showNewTask: Bool
    @AppStorage(MorningCardLogic.labKey) private var morningCardOn = false
    @State private var posted = MorningCardLogic.load().posted != nil

    private var owner: [Ask] { model.ownerAsks }
    private var builds: [TodayBuild] { PhoneToday.builds(model.snapshot?.today) }
    private var contentDue: Bool { morningCardOn && !posted }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Space.xl) {
                    if model.snapshot != nil {
                        switch variant {
                        case .b:
                            TodayStackB(owner: owner, builds: builds, contentOn: morningCardOn, contentDue: contentDue, tab: $tab)
                        default:
                            TodayStackA(owner: owner, builds: builds, contentOn: morningCardOn, tab: $tab)
                        }
                    } else {
                        WaitingView()
                    }
                }
                .padding(.horizontal, Space.l)
                .padding(.top, Space.s)
                .padding(.bottom, Space.xxl)
                .frame(maxWidth: Space.readingCard)
                .frame(maxWidth: .infinity)
            }
            .background(Palette.background)
            .refreshable { await model.refresh() }
            .navigationTitle("Today")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNewTask = true } label: { Text("New task").fontWeight(.semibold) }
                        .disabled(model.snapshot == nil)
                }
            }
            .onAppear { posted = MorningCardLogic.load().posted != nil }
        }
    }
}

// MARK: Shared rows

/// One decision as a row: where it comes from and how long it waits, the question, a chevron. One tap opens Decisions.
private struct DecisionRow: View {
    @Environment(AppModel.self) private var model
    let ask: Ask
    @Binding var tab: AppTab

    var body: some View {
        let age = PhoneFormat.age(ask.ageSeconds, snapshot: model.snapshot ?? Snapshot(), now: Date())
        let meta = "\(Format.product(ask.product)) \u{00B7} \(Format.age(seconds: age))"
        Button { tab = .decisions } label: {
            HStack(spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(meta).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    Text(ask.question).font(Typo.body.weight(.semibold)).foregroundStyle(Palette.text)
                        .lineLimit(3).multilineTextAlignment(.leading)
                }
                Spacer(minLength: Space.s)
                Image(systemName: "chevron.right").font(Typo.caption).foregroundStyle(Palette.textTertiary)
            }
            .padding(.vertical, Space.s)
            .frame(minHeight: Space.touchMin)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(Format.product(ask.product)), waiting \(Format.age(seconds: age)). \(ask.question)")
        .accessibilityHint("Opens Decisions")
        .accessibilityAddTraits(.isButton)
    }
}

/// One build as a row. No tap: Teyla has no link that opens TestFlight on a given build.
private struct BuildRow: View {
    let build: TodayBuild

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(PhoneToday.buildTitle(build)).font(Typo.body.weight(.semibold))
                Text(PhoneToday.buildDetail(build)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            Spacer(minLength: Space.s)
            Text(PhoneToday.uploadedWords(build)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.trailing)
        }
        .padding(.vertical, Space.s)
        .frame(minHeight: Space.touchMin)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(PhoneToday.buildSpoken(build))
    }
}

// MARK: Variant A: stack

private struct TodayStackA: View {
    @Environment(AppModel.self) private var model
    let owner: [Ask]
    let builds: [TodayBuild]
    let contentOn: Bool
    @Binding var tab: AppTab

    var body: some View {
        decisions
        content
        buildsToTry
    }

    private var decisions: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Decisions", count: owner.isEmpty ? nil : owner.count)
            if owner.isEmpty {
                RowGroup { EmptyState(title: "Nothing waits on you.", detail: "Questions only you can answer land here.") }
            } else {
                RowGroup { ForEach(PhoneToday.decisions(owner)) { DecisionRow(ask: $0, tab: $tab) } }
                if owner.count > PhoneToday.decisionLimit {
                    Button("See all \(owner.count)") { tab = .decisions }
                        .font(Typo.body.weight(.medium))
                        .frame(minHeight: Space.touchMin)
                }
            }
        }
    }

    @ViewBuilder private var content: some View {
        if contentOn {
            MorningCard()
        } else {
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: "Content")
                RowGroup {
                    EmptyState(symbol: "square.and.pencil", title: "No post card.",
                               detail: "Turn on Morning post card in More, under Settings, Lab.",
                               actionTitle: "Open More", action: { tab = .more })
                }
            }
        }
    }

    private var buildsToTry: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Builds to try", count: builds.isEmpty ? nil : builds.count)
            if let caption = PhoneToday.buildsCaption(model.snapshot?.today) {
                Text(caption).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if builds.isEmpty {
                RowGroup { EmptyState(title: "No build to try.", detail: "A new TestFlight upload shows here for 7 days.") }
            } else {
                RowGroup { ForEach(builds) { BuildRow(build: $0) } }
            }
        }
    }
}

// MARK: Variant B: one next thing

private struct TodayStackB: View {
    @Environment(AppModel.self) private var model
    let owner: [Ask]
    let builds: [TodayBuild]
    let contentOn: Bool
    let contentDue: Bool
    @Binding var tab: AppTab

    private var next: TodayNext { PhoneToday.next(owner: owner, contentDue: contentDue, builds: builds) }
    private var heroAsk: Ask? { if case .decision(let ask) = next { return ask } else { return nil } }
    private var heroBuild: TodayBuild? { if case .build(let build) = next { return build } else { return nil } }
    private var heroContent: Bool { if case .content = next { return true } else { return false } }

    var body: some View {
        hero
        rest
    }

    /// The large card.
    @ViewBuilder private var hero: some View {
        switch next {
        case .decision(let ask): HeroDecision(ask: ask, tab: $tab)
        case .content: MorningCard()
        case .build(let build): HeroBuild(build: build)
        case .nothing:
            RowGroup { EmptyState(title: "All clear.", detail: "Decisions, a post card and new builds show here.") }
        }
    }

    /// The rest of the three groups, compact.
    private var rest: some View {
        let more = owner.filter { $0.id != heroAsk?.id }
        let room = PhoneToday.decisionLimit - (heroAsk == nil ? 0 : 1)
        let list = PhoneToday.newestFirst(builds).filter { $0.id != heroBuild?.id }
        return VStack(alignment: .leading, spacing: Space.l) {
            group("Decisions") {
                if more.isEmpty {
                    Text("Nothing else waits on you.").font(Typo.body).foregroundStyle(Palette.textSecondary)
                } else {
                    RowGroup { ForEach(Array(more.prefix(room))) { DecisionRow(ask: $0, tab: $tab) } }
                    if more.count > room {
                        Button("See all \(owner.count)") { tab = .decisions }
                            .font(Typo.body.weight(.medium)).frame(minHeight: Space.touchMin)
                    }
                }
            }
            if !heroContent {
                group("Content") {
                    Text(contentOn ? "Posted today. Add the link tomorrow."
                                   : "No post card. Turn on Morning post card in More, under Settings, Lab.")
                        .font(Typo.body).foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            group("Builds to try") {
                if let caption = PhoneToday.buildsCaption(model.snapshot?.today) {
                    Text(caption).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else if list.isEmpty {
                    Text(heroBuild == nil ? "No build to try." : "No other build to try.")
                        .font(Typo.body).foregroundStyle(Palette.textSecondary)
                } else {
                    RowGroup { ForEach(Array(list.prefix(PhoneToday.compactBuildLimit))) { BuildRow(build: $0) } }
                }
            }
        }
    }

    private func group<Body: View>(_ title: String, @ViewBuilder _ body: () -> Body) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text(title).font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
                .accessibilityAddTraits(.isHeader)
            body()
        }
    }
}

private struct HeroDecision: View {
    @Environment(AppModel.self) private var model
    let ask: Ask
    @Binding var tab: AppTab

    var body: some View {
        let age = PhoneFormat.age(ask.ageSeconds, snapshot: model.snapshot ?? Snapshot(), now: Date())
        VStack(alignment: .leading, spacing: Space.m) {
            Text("Next").font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.primary)
            Text(ask.question).font(Typo.section).fixedSize(horizontal: false, vertical: true)
            Text("\(Format.product(ask.product)) \u{00B7} \(Format.age(seconds: age))"
                 + (ask.unblocks.isEmpty ? "" : " \u{00B7} Unblocks \(ask.unblocks)"))
                .font(Typo.body).foregroundStyle(Palette.textSecondary)
            Button("Open decision") { tab = .decisions }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
        }
        .card()
        .accessibilityElement(children: .contain)
    }
}

private struct HeroBuild: View {
    let build: TodayBuild

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Text("Next").font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.primary)
            Text("Try \(PhoneToday.buildTitle(build)) \(PhoneToday.buildDetail(build))")
                .font(Typo.section).fixedSize(horizontal: false, vertical: true)
            Text("\(PhoneToday.uploadedWords(build)). Open TestFlight to install it.")
                .font(Typo.body).foregroundStyle(Palette.textSecondary)
        }
        .card()
        .accessibilityElement(children: .combine)
    }
}
