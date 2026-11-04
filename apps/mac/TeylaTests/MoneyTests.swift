import XCTest

private func money(_ json: String) throws -> MoneyReport {
    try JSONDecoder().decode(MoneyReport.self, from: Data(json.utf8))
}

private func sample() throws -> MoneyReport {
    guard let report = try ConsoleReport.decode(SampleFiles.data("console.v1.json")).money.value else {
        throw TeylaError.badOutput("no money in the sample")
    }
    return report
}

final class MoneyParsingTests: XCTestCase {
    func testTheSampleHoldsEverySection() throws {
        let report = try sample()
        XCTAssertEqual(report.forecast?.monthlyUSD, 335)
        XCTAssertEqual(report.forecast?.unpriced, ["Hosting"])
        XCTAssertEqual(report.forecast?.renewals.count, 2)
        XCTAssertEqual(report.subscriptions.count, 4)
        XCTAssertNil(report.subscriptions.last?.monthlyUSD, "no price stays nil, never zero")
        XCTAssertEqual(report.spend?.days7?.listUSD, 1480.5)
        XCTAssertNil(report.spend?.days30?.billedUSD)
        XCTAssertEqual(report.byProduct.count, 4)
        XCTAssertEqual(report.byModel.first?.name, "claude-opus-5-5", "a model row is keyed model")
        XCTAssertEqual(report.byDay.count, 30)
        XCTAssertEqual(report.creditsTotalUSD, 300)
        XCTAssertEqual(report.providers.map(\.name), ["anthropic", "openai"])
        XCTAssertNil(report.providers.first?.billedUSD30)
        XCTAssertEqual(report.providers.first?.reason, "no admin key in the Keychain")
        XCTAssertEqual(report.cloud.count, 2)
        XCTAssertEqual(report.actions?.accounts.count, 2)
        XCTAssertEqual(report.actions?.accounts.first?.topRepos, ["sample-web", "sample-app"])
    }

    func testAnEmptyObjectIsAnEmptyReport() throws {
        let report = try money("{}")
        XCTAssertNil(report.headline)
        XCTAssertNil(report.forecast)
        XCTAssertTrue(report.subscriptions.isEmpty)
        XCTAssertTrue(report.providers.isEmpty)
        XCTAssertNil(report.actions)
    }

    func testNullsAndWrongTypesLeaveNilNotZero() throws {
        let report = try money("""
        {"forecast": {"monthly_usd": null, "priced": "x", "unpriced": null, "renewals": null},
         "spend": {"days7": {"list_usd": "lots", "sessions": null}, "days30": null},
         "credits_total_usd": null, "actions": {"minutes_used": null, "accounts": null},
         "providers": {"openai": {"billed_usd_30d": null}}}
        """)
        XCTAssertNil(report.forecast?.monthlyUSD)
        XCTAssertNil(report.forecast?.priced)
        XCTAssertTrue(report.forecast?.unpriced.isEmpty ?? false)
        XCTAssertNil(report.spend?.days7?.listUSD)
        XCTAssertNil(report.spend?.days30)
        XCTAssertNil(report.creditsTotalUSD)
        XCTAssertNil(report.actions?.minutesUsed)
        XCTAssertEqual(report.providers.count, 1)
        XCTAssertNil(report.providers[0].billedUSD30)
    }

    func testOneUnreadableRowIsSkippedNotTheList() throws {
        let report = try money("""
        {"subscriptions": [{"name": "A", "monthly_usd": 5}, {"monthly_usd": 9}, 7, {"name": "B"}],
         "by_day": [{"day": "2026-11-02", "list_usd": 2}, {"day": "soon"}, {"day": "2026-11-01", "list_usd": 1}],
         "by_product": [{"name": "x", "days7_usd": 1}, {"days7_usd": 4}],
         "providers": {"good": {"billed_usd_30d": 1}, "bad": 4}}
        """)
        XCTAssertEqual(report.subscriptions.map(\.name), ["A", "B"])
        XCTAssertEqual(report.byDay.count, 2)
        XCTAssertEqual(report.byDay.first?.listUSD, 1, "days come oldest first")
        XCTAssertEqual(report.byProduct.map(\.name), ["x"])
        XCTAssertEqual(report.providers.map(\.name), ["good"])
    }

    func testASectionErrorStaysItsOwn() throws {
        let all = try ConsoleReport.decode(Data(#"{"version": 1, "money": {"error": "no subscriptions file"}}"#.utf8))
        XCTAssertEqual(all.money, .failed("no subscriptions file"))
    }
}

final class MoneyLogicTests: XCTestCase {
    func testDollarWords() {
        XCTAssertEqual(MoneyLogic.usd(335), "$335")
        XCTAssertEqual(MoneyLogic.usd(6120.8), "$6,121")
        XCTAssertEqual(MoneyLogic.usd(23.18), "$23.18")
        XCTAssertEqual(MoneyLogic.usd(0), "$0")
        XCTAssertEqual(MoneyLogic.usd(35), "$35")
        XCTAssertEqual(MoneyLogic.usd(35.5), "$35.50")
        XCTAssertEqual(MoneyLogic.usd(0.001), "less than $0.01", "a cost is never rounded to nothing")
        XCTAssertEqual(MoneyLogic.usd(-5), "-$5")
        XCTAssertNil(MoneyLogic.usd(nil))
        XCTAssertEqual(MoneyLogic.perMonth(200), "$200 a month")
        XCTAssertNil(MoneyLogic.perMonth(nil))
    }

    func testCashComesFromTheForecastOnly() throws {
        let report = try sample()
        XCTAssertEqual(MoneyLogic.cash(report).value, "$335")
        let none = MoneyLogic.cash(try money(#"{"spend": {"days30": {"list_usd": 9000}}}"#))
        XCTAssertNil(none.value, "list price is never shown as cash")
        XCTAssertFalse(none.detail.isEmpty)
    }

    func testSubscriptionsPricedFirstThenTheUnpriced() throws {
        let rows = MoneyLogic.subscriptionsInOrder(try sample().subscriptions)
        XCTAssertEqual(rows.map(\.name), ["Assistant plan", "Second assistant plan", "Domain", "Hosting"])
        let hosting = MoneyLogic.priceText(rows[3])
        XCTAssertFalse(hosting.known)
        XCTAssertEqual(hosting.text, "no price listed")
        XCTAssertEqual(MoneyLogic.priceText(MoneySubscription(name: "X")).text, "no price listed")
    }

    func testSubscriptionDetail() {
        let row = MoneySubscription(name: "A", monthlyUSD: 5, category: "ai", renews: MoneyLogic.day("2026-11-21"), note: "billed yearly")
        XCTAssertEqual(MoneyLogic.subscriptionDetail(row), "AI · renews 21 Nov · billed yearly")
        XCTAssertEqual(MoneyLogic.subscriptionDetail(MoneySubscription(name: "B")), "")
    }

    func testNextRenewalIsTheSoonestNotPast() throws {
        let forecast = try sample().forecast
        XCTAssertEqual(MoneyLogic.nextRenewal(forecast)?.name, "Domain")
        let past = MoneyForecast(renewals: [MoneyRenewal(name: "Old", days: -2), MoneyRenewal(name: "Later", days: 9),
                                            MoneyRenewal(name: "NoDate")])
        XCTAssertEqual(MoneyLogic.nextRenewal(past)?.name, "Later")
        XCTAssertNil(MoneyLogic.nextRenewal(MoneyForecast()))
        XCTAssertNil(MoneyLogic.nextRenewal(nil))
        XCTAssertEqual(MoneyLogic.inDays(0), "today")
        XCTAssertEqual(MoneyLogic.inDays(1), "tomorrow")
        XCTAssertEqual(MoneyLogic.inDays(8), "in 8 days")
    }

    func testSharesComeLargestFirstWithBars() throws {
        let rows = try sample().byProduct
        let month = MoneyLogic.shares(rows, window: .month)
        XCTAssertEqual(month.first?.name, "sample-app")
        XCTAssertEqual(MoneyLogic.fraction(month[0], of: month, window: .month), 1)
        let half = MoneyLogic.fraction(MoneyShare(name: "h", days30USD: 1400), of: month, window: .month)
        XCTAssertEqual(half ?? 0, 0.5, accuracy: 0.001)
        let unknown = MoneyShare(name: "u")
        XCTAssertNil(MoneyLogic.fraction(unknown, of: month, window: .month), "no amount, no bar")
        XCTAssertEqual(MoneyLogic.shares(month + [unknown], window: .week).last?.name, "u")
        XCTAssertNil(MoneyLogic.fraction(month[0], of: [], window: .month))
    }

    func testDayBars() throws {
        let days = try sample().byDay
        let heights = MoneyLogic.dayHeights(days, last: 30)
        XCTAssertEqual(heights.count, 30)
        XCTAssertEqual(heights.max() ?? 0, 1, accuracy: 0.0001)
        XCTAssertTrue(heights.allSatisfy { $0 >= 0 && $0 <= 1 })
        XCTAssertTrue(MoneyLogic.dayHeights([MoneyDay(day: Date(), listUSD: 4)], last: 30).isEmpty, "one day is no chart")
        XCTAssertTrue(MoneyLogic.dayHeights(days.map { MoneyDay(day: $0.day, listUSD: 0) }, last: 30).isEmpty)
        XCTAssertTrue(MoneyLogic.dayCaption(days, last: 30).contains("on 30 Oct"))
        XCTAssertEqual(MoneyLogic.dayCaption([], last: 30), "Not enough days for a chart yet.")
    }

    func testProvidersSayWhyOrHowMuch() throws {
        let providers = try sample().providers
        let anthropic = MoneyLogic.providerLine(providers[0])
        XCTAssertNil(anthropic.value)
        XCTAssertEqual(anthropic.why, "no admin key in the Keychain")
        XCTAssertEqual(MoneyLogic.providerLine(providers[1]).value, "$23.18")
        XCTAssertFalse(MoneyLogic.providerLine(MoneyProvider(name: "x")).why.isEmpty)
        XCTAssertEqual(MoneyLogic.providerName("openai"), "OpenAI")
        XCTAssertEqual(MoneyLogic.providerName("anthropic"), "Anthropic")
        XCTAssertEqual(MoneyLogic.providerName("google"), "Google")
    }

    func testCloudAndActionsWords() throws {
        let report = try sample()
        XCTAssertEqual(MoneyLogic.cloudPrice(report.cloud[0]).text, "$35 a month")
        let metered = MoneyLogic.cloudPrice(report.cloud[1])
        XCTAssertEqual(metered.text, "$0 so far")
        XCTAssertTrue(metered.known)
        XCTAssertFalse(MoneyLogic.cloudPrice(MoneyCloud(name: "x")).known)
        XCTAssertTrue(MoneyLogic.cloudRows(report.cloud, subscriptions: report.subscriptions, actions: report.actions).isEmpty,
                      "the domain is a subscription above, the Actions rows are the accounts")
        XCTAssertEqual(MoneyLogic.cloudRows(report.cloud, subscriptions: [], actions: nil).count, 2)
        XCTAssertEqual(MoneyLogic.cloudRows(report.cloud, subscriptions: [], actions: report.actions).map(\.name), ["Domain"])
        let account = report.actions!.accounts[0]
        XCTAssertEqual(MoneyLogic.minutesLine(account), "25 of 2,000 minutes")
        XCTAssertEqual(MoneyLogic.accountDetail(account), "25 of 2,000 minutes · free plan · most use: sample-web, sample-app")
        XCTAssertEqual(MoneyLogic.paidText(0), "$0 paid")
        XCTAssertEqual(MoneyLogic.paidText(nil), Format.dash)
        XCTAssertEqual(MoneyLogic.actionsDetail(report.actions), "of 5,000 included · $0 paid")
        XCTAssertEqual(MoneyLogic.minutes(47), "47")
        XCTAssertNil(MoneyLogic.minutes(nil))
        XCTAssertEqual(MoneyLogic.minutesLine(MoneyActionsAccount(account: "a")), "no minutes figure")
    }

    func testTheFilePathShowsTheHomeAsTilde() {
        let home = NSHomeDirectory()
        XCTAssertEqual(MoneyLogic.fileLine(home + "/.teyla/subscriptions.toml"), "~/.teyla/subscriptions.toml")
        XCTAssertNil(MoneyLogic.fileLine(nil))
        XCTAssertNil(MoneyLogic.fileLine(""))
    }

    func testTheSpendNote() throws {
        XCTAssertTrue(MoneyLogic.spendNote(try sample().spend).contains("subscription bills differently"))
        XCTAssertTrue(MoneyLogic.spendNote(try sample().spend).hasSuffix("Not cash."))
        XCTAssertTrue(MoneyLogic.spendNote(nil).hasPrefix("Not cash"))
        XCTAssertEqual(MoneyLogic.categoryName("ai"), "AI")
        XCTAssertEqual(MoneyLogic.categoryName("cloud"), "Cloud")
    }
}
