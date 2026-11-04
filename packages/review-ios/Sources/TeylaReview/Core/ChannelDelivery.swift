import Foundation

/// What the shared review channel answered for one capture.
enum ChannelResult: Equatable, Sendable {
    /// Both files are stored, or were already.
    case delivered
    /// A busy server, a daily cap or no network: the same capture may succeed later.
    case retryLater
    /// The server will never take this capture (a bad key, the wrong product, too large, a picture
    /// that does not match its hash). Sending it again only repeats the answer.
    case refused
}

/// Where the shared channel is, from the Info.plist keys `TeylaReviewChannelURL` and
/// `TeylaReviewChannelKey`. The key is a secret of a test build: it never reaches a log, a
/// description or the JSON of a capture, and `teyla review store-check` fails a store build that holds it.
struct ChannelConfig: Equatable, CustomStringConvertible, CustomDebugStringConvertible {
    let baseURL: URL
    let key: String

    static let urlInfoKey = "TeylaReviewChannelURL"
    static let keyInfoKey = "TeylaReviewChannelKey"
    static let productInfoKey = "TeylaReviewProduct"

    /// Nil unless both values are present and non-empty and the URL is HTTPS (plain HTTP only for
    /// a loopback host, for local development). An unexpanded `$(NAME)` build setting counts as absent.
    init?(url: Any?, key: Any?) {
        guard let urlText = Self.text(url), let keyText = Self.text(key),
              let parsed = URL(string: urlText), let host = parsed.host, !host.isEmpty else { return nil }
        let loopback = ["localhost", "127.0.0.1", "::1", "[::1]"].contains(host)
        guard parsed.scheme == "https" || (parsed.scheme == "http" && loopback) else { return nil }
        self.baseURL = parsed
        self.key = keyText
    }

    init?(bundle: Bundle = .main) {
        self.init(url: bundle.object(forInfoDictionaryKey: Self.urlInfoKey),
                  key: bundle.object(forInfoDictionaryKey: Self.keyInfoKey))
    }

    /// A trimmed, non-empty string that is not an unexpanded build setting.
    static func text(_ value: Any?) -> String? {
        guard let raw = value as? String else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed.hasPrefix("$(") ? nil : trimmed
    }

    var description: String { "ChannelConfig(\(baseURL.host ?? "?"), key hidden)" }
    var debugDescription: String { description }
}

/// The built-in client for the shared channel (docs/REVIEW.md, "The shared channel"): PUT the picture,
/// then the JSON, each with the bearer key. The only network call the package makes, and only when
/// the product's Info.plist holds both channel keys and no `deliver` closure was set.
enum ChannelDelivery {
    /// Statuses that will not change by asking again. 429, 503, 507 and the rest read as "later".
    static let permanent: Set<Int> = [400, 401, 403, 413, 422]

    static func result(forStatus status: Int) -> ChannelResult {
        if status == 200 { return .delivered }
        return permanent.contains(status) ? .refused : .retryLater
    }

    static func url(_ config: ChannelConfig, id: String, file: String) -> URL {
        config.baseURL.appendingPathComponent("v1").appendingPathComponent("captures")
            .appendingPathComponent(id).appendingPathComponent(file)
    }

    /// A lowercase UUID, the only id the service accepts.
    static func isValidID(_ id: String) -> Bool {
        UUID(uuidString: id) != nil && id == id.lowercased()
    }

    static func put(
        _ body: Data, to url: URL, contentType: String, key: String, session: URLSession
    ) async -> ChannelResult {
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
        request.httpMethod = "PUT"
        request.setValue("Bearer " + key, forHTTPHeaderField: "Authorization")
        request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        do {
            let (_, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { return .retryLater }
            return result(forStatus: http.statusCode)
        } catch {
            return .retryLater          // no network, a timeout or a cancelled task: try again later
        }
    }

    /// The picture first, then the JSON. Stops at the first answer that is not 200.
    static func send(_ upload: ReviewUpload, config: ChannelConfig, session: URLSession) async -> ChannelResult {
        guard isValidID(upload.id) else { return .refused }
        let png = await put(upload.png, to: url(config, id: upload.id, file: ReviewFormat.pngName),
                            contentType: "image/png", key: config.key, session: session)
        guard png == .delivered else { return png }
        return await put(upload.json, to: url(config, id: upload.id, file: ReviewFormat.jsonName),
                         contentType: "application/json", key: config.key, session: session)
    }

    /// True when the JSON carries `app.product`. A capture saved before the field existed has none,
    /// and the service would answer 403 for it, so it is not sent (and not marked refused).
    static func hasProduct(_ json: Data) -> Bool {
        guard let object = try? JSONSerialization.jsonObject(with: json) as? [String: Any],
              let app = object["app"] as? [String: Any], let product = app["product"] as? String else { return false }
        return AppProbe.isSlug(product)
    }

    /// The closure the package uses when the product set none. True only after both files answer
    /// 200. A refusal is reported to `markRefused`, and `isRefused` stops the next attempt: the state
    /// belongs to this route, so a `deliver` closure set later is not affected by it. A capture
    /// without `app.product` waits locally, unsent and unmarked.
    static func deliver(
        config: ChannelConfig, session: URLSession = .channel,
        isRefused: @escaping @Sendable (String) -> Bool = { _ in false },
        markRefused: @escaping @Sendable (String) -> Void
    ) -> ReviewDeliver {
        { upload in
            guard !isRefused(upload.id), hasProduct(upload.json) else { return false }
            switch await send(upload, config: config, session: session) {
            case .delivered: return true
            case .retryLater: return false
            case .refused: markRefused(upload.id); return false
            }
        }
    }
}

extension URLSession {
    /// No cookies, no cache, no stored credentials: the key travels in one header and nowhere else.
    static let channel: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 30
        return URLSession(configuration: configuration)
    }()
}
