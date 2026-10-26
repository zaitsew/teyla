import SwiftUI

/// Variant B, "morning brief", the same order as the Mac: one sentence on what matters, then the
/// questions, the tasks only you can do, what got done, and what runs now.
struct TodayView: View {
    @Environment(AppModel.self) private var model
    @Binding var showNewTask: Bool
    @Binding var showSettings: Bool

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
            ScrollView {
                // Not lazy: a few dozen cards at most, and the "Older" fold must exist to be scrolled to.
                VStack(alignment: .leading, spacing: 28) {
                    if let snapshot = model.snapshot {
                        Content(snapshot: snapshot)
                    } else {
                        WaitingView()
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 32)
                // A comfortable measure: cards stop at 640 pt however wide the screen is.
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .task {
                // Screenshots: `-TEYLA_OLDER open` also scrolls the fold into view.
                guard LaunchOptions().olderOpen else { return }
                try? await Task.sleep(for: .milliseconds(800))
                withAnimation { proxy.scrollTo("older", anchor: .top) }
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color(.systemGroupedBackground))
            .refreshable { await model.refresh() }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showSettings = true } label: { Label("Settings", systemImage: "gearshape") }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNewTask = true } label: { Text("New task").fontWeight(.semibold) }
                        .disabled(model.snapshot == nil)
                }
            }
        }
    }
}

private struct Content: View {
    @Environment(AppModel.self) private var model
    let snapshot: Snapshot
    @State private var olderOpen = LaunchOptions().olderOpen

    var body: some View {
        let now = Date()
        let split = PhoneFormat.splitAsks(snapshot.asks, snapshot: snapshot, now: now)
        VStack(alignment: .leading, spacing: 8) {
            Text(briefLine)
                .font(.title2.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
            Text(Format.subline(questions: snapshot.asks.count, running: snapshot.running.count,
                                spentUSD: snapshot.totals.spentTodayUSD))
                .font(.subheadline)
                .foregroundStyle(.secondary)
            SyncLine()
        }

        let sent = model.sentWithoutCard(in: snapshot)
        if !sent.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                SectionLabel("Sent from this iPhone")
                ForEach(sent) { action in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(heading(of: action))
                            .font(.subheadline.weight(.semibold))
                        OutcomeView(action: action) { model.dismiss(action.id) }
                    }
                    .card()
                }
            }
        }

        VStack(alignment: .leading, spacing: 12) {
            SectionLabel("Needs you")
            if snapshot.asks.isEmpty {
                Label("Nothing is waiting for an answer.", systemImage: "checkmark.circle")
                    .foregroundStyle(.secondary)
            } else if split.fresh.isEmpty {
                Label("Nothing new is waiting.", systemImage: "checkmark.circle")
                    .foregroundStyle(.secondary)
            }
            ForEach(split.fresh) { ask in
                QuestionCard(ask: ask, ageSeconds: PhoneFormat.age(ask.ageSeconds, snapshot: snapshot, now: now))
            }
        }

        if !split.older.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Color.clear.frame(height: 0).id("older")
                Button {
                    withAnimation(.easeOut(duration: 0.2)) { olderOpen.toggle() }
                } label: {
                    HStack(spacing: 8) {
                        Text("Older \u{00B7} \(split.older.count)")
                            .font(.subheadline.weight(.semibold))
                        Text("waiting more than 7 days")
                            .font(.footnote)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 8)
                        Image(systemName: olderOpen ? "chevron.up" : "chevron.down")
                            .font(.footnote.weight(.semibold))
                    }
                    .foregroundStyle(.secondary)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(.isHeader)
                .accessibilityValue(olderOpen ? "expanded" : "collapsed")
                if olderOpen {
                    ForEach(split.older) { ask in
                        QuestionCard(ask: ask, ageSeconds: PhoneFormat.age(ask.ageSeconds, snapshot: snapshot, now: now))
                    }
                }
            }
        }

        if !snapshot.tasks.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionLabel("Only you")
                ForEach(snapshot.tasks) { task in
                    TaskRow(task: task, ageSeconds: PhoneFormat.age(task.ageSeconds, snapshot: snapshot, now: now))
                }
            }
        }

        if !snapshot.done.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionLabel("Done since yesterday")
                ForEach(snapshot.done) { item in
                    DoneCard(item: item, agoSeconds: PhoneFormat.secondsSince(item.ended, now: now))
                }
            }
        }

        VStack(alignment: .leading, spacing: 12) {
            SectionLabel("Running now")
            if snapshot.running.isEmpty {
                Text("No session active in the last 10 minutes.").foregroundStyle(.secondary)
            }
            ForEach(snapshot.running) { session in
                RunningCard(session: session, runningSeconds: PhoneFormat.secondsSince(session.since, now: now))
            }
        }
    }

    private func heading(of action: PendingAction) -> String {
        switch action.kind {
        case .dispatch: return "New task \u{00B7} \(Format.product(action.label))"
        case .answer: return "Answer \u{00B7} \(action.label)"
        case .say: return "Correction \u{00B7} \(action.label)"
        }
    }

    private var briefLine: String {
        if let line = snapshot.brief?.line, !line.isEmpty { return line }
        let n = snapshot.asks.count
        return n == 0 ? "Nothing needs you right now." : "\(n) \(n == 1 ? "question needs" : "questions need") you."
    }
}

/// "Mac synced 4 min ago", orange once it is older than 10 minutes.
struct SyncLine: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TimelineView(.periodic(from: .now, by: 20)) { context in
            if model.connection == .sample {
                Label("Sample data", systemImage: "eye")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else if model.connection == .fixture {
                Label("Preview data", systemImage: "eye")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else if model.connection == .syncing {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini)
                    Text("Syncing").font(.footnote).foregroundStyle(.secondary)
                }
            } else if let date = model.syncDate {
                let seconds = max(0, context.date.timeIntervalSince(date))
                let stale = PhoneFormat.isStale(secondsAgo: seconds)
                Label(PhoneFormat.synced(secondsAgo: seconds) + (stale ? ". The Mac may be asleep." : ""),
                      systemImage: stale ? "exclamationmark.triangle.fill" : "checkmark.icloud")
                    .font(.footnote)
                    .foregroundStyle(stale ? Color.orange : Color.secondary)
            }
        }
    }
}

/// Shown instead of the data: no file, a file that failed the signature check, or a download.
struct WaitingView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 14) {
            Spacer(minLength: 80)
            if model.connection == .syncing || model.connection == .reading {
                ProgressView()
                Text(model.connection == .syncing ? "Syncing" : "Reading").font(.title3.weight(.semibold))
                Text("iCloud is bringing the Mac's latest update.")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else {
                Image(systemName: "desktopcomputer")
                    .font(.system(size: 40))
                    .foregroundStyle(.secondary)
                Text("Waiting for the Mac").font(.title3.weight(.semibold))
                Text("Pull down to check again. Wrong key? Pair again in Settings.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}
