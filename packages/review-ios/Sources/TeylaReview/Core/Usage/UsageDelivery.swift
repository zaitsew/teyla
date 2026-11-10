import Foundation

/// One usage batch, as a product's own backend receives it.
public struct ReviewUsageBatch: Sendable {
    /// The batch id (a lowercase UUID). A retry of the same batch carries the same id: store by it, so a
    /// repeat is a no-op.
    public let id: String
    /// The encoded `usage.json` bytes: ids, counts and durations only, as the shared channel would get them.
    public let json: Data

    public init(id: String, json: Data) {
        self.id = id
        self.json = json
    }
}

/// Hands a usage batch to the product's backend, the twin of `ReviewDeliver`. True only once the backend holds
/// it; false (or no answer) keeps the batch for a later try under the same id. A batch sent twice must count
/// as delivered.
public typealias ReviewUsageDeliver = @Sendable (ReviewUsageBatch) async -> Bool

/// What leaves the device: one JSON file per batch, PUT to the shared review channel with the same bearer key
/// as a capture, at `/v1/captures/<batch id>/usage.json`. The server tells it from a capture by the file name.
enum UsageDelivery {
    /// A batch stays under the server's 256 KiB limit for a JSON file.
    static let batchMaxEvents = 800
    static let batchMaxBytes = 180_000

    struct AppPart: Encodable, Equatable {
        var bundleId: String
        var version: String
        var build: String
        var product: String?
        var configuration: String
        enum CodingKeys: String, CodingKey { case bundleId = "bundle_id", version, build, product, configuration }
    }

    /// The ids the app declared, so the Mac can say which allow-listed screens nobody opened. Ids only.
    struct Declared: Encodable, Equatable {
        var screens: [String]
        var actions: [String]
        var tasks: [String]
    }

    struct Payload: Encodable {
        var v = 1
        var kind = "usage"
        var id: String
        var install: String
        var sent: String
        var app: AppPart
        var declared: Declared
        var events: [UsageEvent]
    }

    /// The exact top-level and `app` keys a payload may have. A test holds the encoded bytes to them.
    static let payloadKeys: Set<String> = ["v", "kind", "id", "install", "sent", "app", "declared", "events"]
    static let appKeys: Set<String> = ["bundle_id", "version", "build", "product", "configuration"]

    static func app(_ info: AppInfo) -> AppPart {
        AppPart(bundleId: info.bundleId, version: info.version, build: info.build, product: info.product,
                configuration: info.configuration.rawValue)
    }

    static func encode(
        batch: UsageStore.Batch, install: String, app: AppInfo, declared: UsageAllowList = UsageAllowList(), now: Date
    ) throws -> Data {
        let formatter = ISO8601DateFormatter()
        let list = Declared(screens: declared.screens.sorted(), actions: declared.actions.sorted(), tasks: declared.tasks.sorted())
        let payload = Payload(id: batch.id, install: install, sent: formatter.string(from: now), app: Self.app(app),
                              declared: list, events: batch.events)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(payload)
    }

    static func url(_ config: ChannelConfig, id: String) -> URL {
        config.baseURL.appendingPathComponent("v1").appendingPathComponent("captures")
            .appendingPathComponent(id).appendingPathComponent("usage.json")
    }

    /// One PUT. The same statuses as a capture: 200 stored (or already there), 400 413 422 refused for good, the rest later.
    static func put(_ body: Data, id: String, config: ChannelConfig, session: URLSession) async -> ChannelResult {
        guard ChannelDelivery.isValidID(id) else { return .refused }
        return await ChannelDelivery.put(body, to: url(config, id: id), contentType: "application/json", key: config.key, session: session)
    }
}

extension UsageDelivery {
    /// The route a batch takes: the product's `deliverUsage` closure when it set one (it wins, as `deliver`
    /// does for captures); else the shared channel when the Info.plist holds both keys; else nil, and nothing
    /// leaves the device. A false answer is `.retryLater`: the batch stays, with its id.
    static func transport(
        deliverUsage: ReviewUsageDeliver?, channel: ChannelConfig?, session: URLSession = .channel
    ) -> UsageSender.Transport? {
        if let deliverUsage {
            return { body, id in await deliverUsage(ReviewUsageBatch(id: id, json: body)) ? .delivered : .retryLater }
        }
        guard let channel else { return nil }
        return { body, id in await put(body, id: id, config: channel, session: session) }
    }
}

/// Sends what the store holds, when the consent rule allows it. At most one send runs at a time.
final class UsageSender: @unchecked Sendable {
    typealias Transport = @Sendable (Data, String) async -> ChannelResult

    let store: UsageStore
    private let isActive: () -> Bool
    private let isOwnerDevice: () -> Bool
    private let consent: () -> UsageConsent.State
    private let appInfo: () -> AppInfo
    private let declared: () -> UsageAllowList
    private let install: () -> String
    private let transport: () -> Transport?
    private let now: () -> Date
    private let lock = NSLock()
    private var running = false

    init(store: UsageStore, isActive: @escaping () -> Bool, isOwnerDevice: @escaping () -> Bool,
         consent: @escaping () -> UsageConsent.State, appInfo: @escaping () -> AppInfo,
         declared: @escaping () -> UsageAllowList = { UsageAllowList() },
         install: @escaping () -> String, transport: @escaping () -> Transport?, now: @escaping () -> Date = Date.init) {
        self.store = store
        self.isActive = isActive
        self.isOwnerDevice = isOwnerDevice
        self.consent = consent
        self.appInfo = appInfo
        self.declared = declared
        self.install = install
        self.transport = transport
        self.now = now
    }

    /// True when the build has a channel to send to.
    var transportAvailable: Bool { transport() != nil }

    /// True when a send may go out now: an active build, a channel to send to, and consent (the owner's
    /// device, or a tester who pressed Allow).
    var mayRun: Bool {
        isActive() && transport() != nil && UsageConsent.maySend(isOwnerDevice: isOwnerDevice(), state: consent())
    }

    /// Sends batches until the store is empty, a send fails, or the rule no longer allows it. Returns the events delivered.
    @discardableResult
    func sendPending() async -> Int {
        guard mayRun, begin() else { return 0 }
        defer { end() }
        var sent = 0
        while mayRun, let send = transport(),
              let batch = store.nextBatch(maxEvents: UsageDelivery.batchMaxEvents, maxBytes: UsageDelivery.batchMaxBytes) {
            guard let body = try? UsageDelivery.encode(batch: batch, install: install(), app: appInfo(), declared: declared(), now: now()) else {
                store.confirm(batchID: batch.id)        // cannot be encoded: it can never be sent
                continue
            }
            switch await send(body, batch.id) {
            case .delivered:
                store.confirm(batchID: batch.id)
                sent += batch.events.count
            case .refused:
                // A refusal (a bad key, a wrong product, too large) repeats forever: the batch is dropped, not retried.
                store.confirm(batchID: batch.id)
            case .retryLater:
                return sent
            }
        }
        return sent
    }

    private func begin() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !running else { return false }
        running = true
        return true
    }

    private func end() {
        lock.lock(); running = false; lock.unlock()
    }
}
