import Foundation

// The Growth section of `teyla console --json` (docs/CONSOLE.md): posts today against the target per channel, the
// pipeline, the episodes in the works, the next ride, trend ideas, outreach counts and the channels. Decoding is
// lenient: a key that is missing, null or of another type leaves a nil or an empty list, and the page shows a dash
// with the reason. The drafts waiting for review are not in this report: they come from `GrowthDrafts`.
// The iPhone app compiles this file by path, so keep it free of UI.

/// One channel's slots today.
struct GrowthToday: Decodable, Equatable, Sendable, Identifiable {
    var platform: String
    var language: String
    var posted: Int
    var target: Int

    var id: String { "\(platform)-\(language)" }

    enum CodingKeys: String, CodingKey { case platform, language, posted, target }

    init(platform: String, language: String = "", posted: Int = 0, target: Int = 1) {
        self.platform = platform
        self.language = language
        self.posted = posted
        self.target = target
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        platform = try c.decode(String.self, forKey: .platform)
        language = c.lenient(.language, "")
        posted = c.lenient(.posted, 0)
        target = c.lenient(.target, 1)
    }
}

/// How many items sit in each stage. A stage the report does not count is nil, never zero.
struct GrowthPipeline: Decodable, Equatable, Sendable {
    var ideas: Int?
    var filming: Int?
    var cutting: Int?
    var review: Int?
    var ready: Int?
    var live: Int?

    enum CodingKeys: String, CodingKey { case ideas, filming, cutting, review, ready, live }

    init(ideas: Int? = nil, filming: Int? = nil, cutting: Int? = nil, review: Int? = nil, ready: Int? = nil, live: Int? = nil) {
        self.ideas = ideas
        self.filming = filming
        self.cutting = cutting
        self.review = review
        self.ready = ready
        self.live = live
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ideas = c.optional(.ideas)
        filming = c.optional(.filming)
        cutting = c.optional(.cutting)
        review = c.optional(.review)
        ready = c.optional(.ready)
        live = c.optional(.live)
    }
}

/// An episode in the works: filming, cutting or cut.
struct GrowthEpisode: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var idea: String
    var stage: String
    var question: String
    var job: String
    var minutes: Int?
    var footage: Int?
    var clips: Int?

    enum CodingKeys: String, CodingKey { case id, idea, title, stage, question, job, minutes, footage, clips }

    init(id: String, idea: String, stage: String = "", question: String = "", job: String = "", minutes: Int? = nil,
         footage: Int? = nil, clips: Int? = nil) {
        self.id = id
        self.idea = idea
        self.stage = stage
        self.question = question
        self.job = job
        self.minutes = minutes
        self.footage = footage
        self.clips = clips
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        let idea: String? = c.optional(.idea)
        let title: String? = c.optional(.title)
        self.idea = idea ?? title ?? ""
        stage = c.lenient(.stage, "")
        question = c.lenient(.question, "")
        job = c.lenient(.job, "")
        minutes = c.optional(.minutes)
        footage = c.optional(.footage)
        clips = c.optional(.clips)
    }
}

/// The next ride to film. The report may carry nothing (null), a sentence or an object with a title and a day.
struct GrowthRide: Decodable, Equatable, Sendable {
    var title: String
    var when: String?

    enum CodingKeys: String, CodingKey { case title, when, question, job }

    init(title: String, when: String? = nil) {
        self.title = title
        self.when = when
    }

    init(from decoder: Decoder) throws {
        if let single = try? decoder.singleValueContainer(), let text = try? single.decode(String.self) {
            title = text
            when = nil
            return
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let title: String? = c.optional(.title)
        let job: String? = c.optional(.job)
        let question: String? = c.optional(.question)
        self.title = title ?? job ?? question ?? ""
        when = c.optional(.when)
    }
}

struct GrowthTrend: Decodable, Equatable, Sendable, Identifiable {
    var title: String
    var score: Double?
    var hook: String
    var source: String
    var url: String

    var id: String { url.isEmpty ? title : url }

    enum CodingKeys: String, CodingKey { case title, score, hook, source, url }

    init(title: String, score: Double? = nil, hook: String = "", source: String = "", url: String = "") {
        self.title = title
        self.score = score
        self.hook = hook
        self.source = source
        self.url = url
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = try c.decode(String.self, forKey: .title)
        score = c.optional(.score)
        hook = c.lenient(.hook, "")
        source = c.lenient(.source, "")
        url = c.lenient(.url, "")
    }
}

struct GrowthOutreachSource: Decodable, Equatable, Sendable, Identifiable {
    var source: String
    var connected: Bool

    var id: String { source }

    enum CodingKeys: String, CodingKey { case source, connected }

    init(source: String, connected: Bool) {
        self.source = source
        self.connected = connected
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        source = try c.decode(String.self, forKey: .source)
        connected = c.lenient(.connected, false)
    }
}

/// Counts only. Teyla drafts outreach and never sends it; nothing here can.
struct GrowthOutreach: Decodable, Equatable, Sendable {
    var drafts: Int?
    var sentWeek: Int?
    var repliesWeek: Int?
    var callsWeek: Int?
    var sources: [GrowthOutreachSource]

    enum CodingKeys: String, CodingKey { case drafts, sentWeek = "sent_week", repliesWeek = "replies_week", callsWeek = "calls_week", sources }

    init(drafts: Int? = nil, sentWeek: Int? = nil, repliesWeek: Int? = nil, callsWeek: Int? = nil, sources: [GrowthOutreachSource] = []) {
        self.drafts = drafts
        self.sentWeek = sentWeek
        self.repliesWeek = repliesWeek
        self.callsWeek = callsWeek
        self.sources = sources
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        drafts = c.optional(.drafts)
        sentWeek = c.optional(.sentWeek)
        repliesWeek = c.optional(.repliesWeek)
        callsWeek = c.optional(.callsWeek)
        let rows: [LossyBox<GrowthOutreachSource>] = c.lenient(.sources, [])
        sources = rows.compactMap(\.value)
    }
}

struct GrowthAd: Decodable, Equatable, Sendable, Identifiable {
    var product: String
    var day: String

    var id: String { "\(product)|\(day)" }

    enum CodingKeys: String, CodingKey { case product, day }

    init(product: String, day: String) {
        self.product = product
        self.day = day
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        product = c.lenient(.product, "")
        day = c.lenient(.day, "")
    }
}

struct GrowthChannel: Decodable, Equatable, Sendable, Identifiable {
    var platform: String
    var language: String
    var connected: Bool?
    var lastPost: String?

    var id: String { "\(platform)-\(language)" }

    enum CodingKeys: String, CodingKey { case platform, language, connected, lastPost = "last_post" }

    init(platform: String, language: String = "", connected: Bool? = nil, lastPost: String? = nil) {
        self.platform = platform
        self.language = language
        self.connected = connected
        self.lastPost = lastPost
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        platform = try c.decode(String.self, forKey: .platform)
        language = c.lenient(.language, "")
        connected = c.optional(.connected)
        lastPost = c.optional(.lastPost)
    }
}

struct GrowthReport: Decodable, ConsoleSectionData {
    var headline: ConsoleHeadline?
    /// Posts a day per channel, from the config.
    var targetPerChannel: Int?
    var today: [GrowthToday]
    /// Days since anything went public; nil when nothing has.
    var lastPublicDays: Int?
    /// Days of approved drafts ahead of the plan; nil when the report cannot tell.
    var queueDays: Double?
    /// Slots today that no draft fills.
    var gaps: Int?
    var pipeline: GrowthPipeline?
    var episodes: [GrowthEpisode]
    var nextRide: GrowthRide?
    var trends: [GrowthTrend]
    var outreach: GrowthOutreach?
    var ads: [GrowthAd]
    var channels: [GrowthChannel]
    /// Conversations with a person who fits, this week.
    var qualifiedWeek: Int?
    /// The ids of the products with no sale attempt (posts, marketing, ICP meetings); nil when the report cannot tell.
    var notTried: [String]?

    enum CodingKeys: String, CodingKey {
        case headline, target, today, lastPublicDays = "last_public_days", queueDays = "queue_days", gaps, pipeline, episodes,
             nextRide = "next_ride", trends, outreach, ads, channels, qualifiedWeek = "qualified_week", notTried = "not_tried"
    }

    /// `target` is `{"posts_per_day_per_channel": n}`.
    private struct Target: Decodable {
        var perChannel: Int?

        enum CodingKeys: String, CodingKey { case perChannel = "posts_per_day_per_channel" }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            perChannel = c.optional(.perChannel)
        }
    }

    init(headline: ConsoleHeadline? = nil, targetPerChannel: Int? = nil, today: [GrowthToday] = [], lastPublicDays: Int? = nil,
         queueDays: Double? = nil, gaps: Int? = nil, pipeline: GrowthPipeline? = nil, episodes: [GrowthEpisode] = [],
         nextRide: GrowthRide? = nil, trends: [GrowthTrend] = [], outreach: GrowthOutreach? = nil, ads: [GrowthAd] = [],
         channels: [GrowthChannel] = [], qualifiedWeek: Int? = nil, notTried: [String]? = nil) {
        self.headline = headline
        self.targetPerChannel = targetPerChannel
        self.today = today
        self.lastPublicDays = lastPublicDays
        self.queueDays = queueDays
        self.gaps = gaps
        self.pipeline = pipeline
        self.episodes = episodes
        self.nextRide = nextRide
        self.trends = trends
        self.outreach = outreach
        self.ads = ads
        self.channels = channels
        self.qualifiedWeek = qualifiedWeek
        self.notTried = notTried
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
        let target: Target? = c.optional(.target)
        targetPerChannel = target?.perChannel
        let today: [LossyBox<GrowthToday>] = c.lenient(.today, [])
        self.today = today.compactMap(\.value)
        lastPublicDays = c.optional(.lastPublicDays)
        queueDays = c.optional(.queueDays)
        gaps = c.optional(.gaps)
        pipeline = c.optional(.pipeline)
        let episodes: [LossyBox<GrowthEpisode>] = c.lenient(.episodes, [])
        self.episodes = episodes.compactMap(\.value)
        nextRide = c.optional(.nextRide)
        let trends: [LossyBox<GrowthTrend>] = c.lenient(.trends, [])
        self.trends = trends.compactMap(\.value)
        outreach = c.optional(.outreach)
        let ads: [LossyBox<GrowthAd>] = c.lenient(.ads, [])
        self.ads = ads.compactMap(\.value)
        let channels: [LossyBox<GrowthChannel>] = c.lenient(.channels, [])
        self.channels = channels.compactMap(\.value)
        qualifiedWeek = c.optional(.qualifiedWeek)
        notTried = c.optional(.notTried)
    }
}
