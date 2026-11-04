import Foundation

/// The words and the arithmetic of the Growth page, with no UI in them, so a test can hold each one.
/// A figure the report does not carry is nil (a dash with its reason on the page), never a zero.
enum GrowthLogic {
    /// "x" -> "X", "linkedin" -> "LinkedIn". A platform the app does not know reads as its own id, capitalized.
    static func platformName(_ id: String) -> String {
        switch id.lowercased() {
        case "x": return "X"
        case "linkedin": return "LinkedIn"
        case "youtube": return "YouTube"
        case "tiktok": return "TikTok"
        case "instagram": return "Instagram"
        case "threads": return "Threads"
        case "": return "Unknown channel"
        default: return id.prefix(1).uppercased() + id.dropFirst()
        }
    }

    static func languageName(_ code: String) -> String {
        switch code.lowercased() {
        case "en": return "English"
        case "es": return "Spanish"
        case "ru": return "Russian"
        case "": return ""
        default: return code.uppercased()
        }
    }

    /// "X · English"; the language is left out when the report has none.
    static func channelName(platform: String, language: String) -> String {
        let lang = languageName(language)
        return lang.isEmpty ? platformName(platform) : "\(platformName(platform)) · \(lang)"
    }

    /// "true-vibe-coding" -> "True vibe coding".
    static func formatName(_ format: String) -> String {
        let words = format.replacingOccurrences(of: "-", with: " ").replacingOccurrences(of: "_", with: " ")
        guard let first = words.first else { return "" }
        return first.uppercased() + words.dropFirst()
    }

    // MARK: Figures

    /// Slots filled today, over all channels: nil when no channel is enabled.
    static func slots(_ rows: [GrowthToday]) -> (posted: Int, target: Int)? {
        guard !rows.isEmpty else { return nil }
        return (rows.reduce(0) { $0 + min($1.posted, $1.target) }, rows.reduce(0) { $0 + $1.target })
    }

    /// Channels still waiting for today's post, in the report's order.
    static func open(_ rows: [GrowthToday]) -> [GrowthToday] { rows.filter { $0.posted < $0.target } }

    /// "Waiting for you": the drafts in review. nil when they could not be read.
    static func waitingDetail(count: Int?, skipped: Int, why: String?) -> String {
        if let why { return why }
        guard let count else { return "Not read yet." }
        let skippedNote = skipped > 0 ? " \(skipped) item file\(skipped == 1 ? "" : "s") could not be read." : ""
        if count == 0 { return "Nothing waits for you." + skippedNote }
        return "Approve, reject or edit. Nothing is posted from here." + skippedNote
    }

    /// Days of drafts ready ahead of the plan: "4.5", "2". nil when the report cannot tell.
    static func queueFigure(_ days: Double?) -> String? {
        guard let days else { return nil }
        return days == days.rounded() ? "\(Int(days))" : String(format: "%.1f", days)
    }

    static func queueDetail(_ days: Double?, gaps: Int?) -> String {
        guard let days else { return "The report cannot tell how many days of drafts are ready." }
        let gapNote = gaps.map { $0 > 0 ? " \($0) slot\($0 == 1 ? "" : "s") today still has no draft." : " Every slot today has a draft." } ?? ""
        return "Days of approved drafts ahead." + gapNote
            + (days < 1 ? " Fewer than a day: the queue runs dry." : "")
    }

    /// Days since the last public post: "Today", "1 day", "5 days". nil when nothing went public yet.
    static func sinceFigure(_ days: Int?) -> String? {
        guard let days else { return nil }
        if days <= 0 { return "Today" }
        return "\(days) day\(days == 1 ? "" : "s")"
    }

    static func sinceDetail(_ days: Int?) -> String {
        guard let days else { return "Nothing has gone public yet." }
        return days <= 0 ? "Something went public today." : "Since anything went public."
    }

    // MARK: Channels

    /// "1 of 1", "0 of 2".
    static func slotWords(_ row: GrowthToday) -> String { "\(min(row.posted, row.target)) of \(row.target)" }

    static func isDone(_ row: GrowthToday) -> Bool { row.posted >= row.target && row.target > 0 }

    /// The fraction of today's slots a channel filled, 0 to 1.
    static func fraction(_ row: GrowthToday) -> Double {
        row.target > 0 ? min(1, Double(row.posted) / Double(row.target)) : 0
    }

    /// "Last post 1 Nov" or "No post yet".
    static func lastPostWords(_ channel: GrowthChannel?) -> String {
        guard let day = channel?.lastPost, !day.isEmpty, let date = MoneyLogic.day(day) else { return "No post yet" }
        return "Last post \(MoneyLogic.shortDay(date))"
    }

    static func channel(_ row: GrowthToday, in channels: [GrowthChannel]) -> GrowthChannel? {
        channels.first { $0.platform == row.platform && $0.language == row.language }
    }

    // MARK: Pipeline

    /// The stages in order, each with its count; a stage the report does not count is nil.
    static func stages(_ pipeline: GrowthPipeline?) -> [(label: String, count: Int?, note: String)] {
        [("Ideas", pipeline?.ideas, "Not drafted yet"),
         ("Filming", pipeline?.filming, "Being filmed"),
         ("Cutting", pipeline?.cutting, "Being cut"),
         ("In review", pipeline?.review, "Waiting for you"),
         ("Ready to post", pipeline?.ready, "Approved"),
         ("Posted this week", pipeline?.live, "Last 7 days")]
    }

    static func stageWords(_ stage: String) -> String {
        switch stage {
        case "filming": return "Filming"
        case "cutting": return "Cutting"
        case "cut": return "Cut, ready for clips"
        case "": return ""
        default: return formatName(stage)
        }
    }

    /// "12 clips · 3 footage files · 25 min": what an episode has, leaving out what the report does not say.
    static func episodeDetail(_ episode: GrowthEpisode) -> String {
        var parts: [String] = []
        if let clips = episode.clips { parts.append("\(clips) clip\(clips == 1 ? "" : "s")") }
        if let footage = episode.footage { parts.append("\(footage) footage file\(footage == 1 ? "" : "s")") }
        if let minutes = episode.minutes { parts.append("\(minutes) min") }
        return parts.joined(separator: " · ")
    }

    static func rideDetail(_ ride: GrowthRide) -> String {
        guard let when = ride.when, !when.isEmpty else { return "" }
        if let date = MoneyLogic.day(when) { return MoneyLogic.shortDay(date) }
        return when
    }

    // MARK: Trends and outreach

    /// "24 of 30": what the trend scorer gave, out of its top mark.
    static func trendScore(_ score: Double?) -> String? {
        guard let score else { return nil }
        return "\(score == score.rounded() ? "\(Int(score))" : String(format: "%.1f", score)) of 30"
    }

    static func outreachLine(_ outreach: GrowthOutreach) -> String {
        var parts: [String] = []
        if let value = outreach.sentWeek { parts.append("\(value) sent") }
        if let value = outreach.repliesWeek { parts.append("\(value) repl\(value == 1 ? "y" : "ies")") }
        if let value = outreach.callsWeek { parts.append("\(value) call\(value == 1 ? "" : "s")") }
        return parts.isEmpty ? "No outreach count in the report." : parts.joined(separator: " · ") + " this week"
    }
}
