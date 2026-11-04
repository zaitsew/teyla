import XCTest

final class SaleAttemptsTests: XCTestCase {
    private func sample() throws -> SaleLedger.Read {
        SaleLedger.parse(String(decoding: try SampleFiles.data("ledger.v1.jsonl"), as: UTF8.self))
    }

    func testTheLedgerCountsPostsMarketingAndMeetingsPerProduct() throws {
        let read = try sample()
        let app = read.attempts(for: "sample-app")
        XCTAssertEqual(app.posts, 2)
        XCTAssertEqual(app.marketing, 1)
        XCTAssertEqual(app.icpMeetings, 1)
        XCTAssertEqual(app.total, 4)
        XCTAssertEqual(app.last, "2026-11-03")
        XCTAssertTrue(app.tried)
    }

    func testIdeasAndRejectsAreNotAttempts() throws {
        let tool = try sample().attempts(for: "sample-tool")
        XCTAssertEqual(tool.total, 0)
        XCTAssertFalse(tool.tried)
    }

    func testALineThatIsNotJSONIsCountedAsSkipped() throws {
        XCTAssertEqual(try sample().skipped, 1)
    }

    func testAnAttemptOfKindPostCountsAsAPost() {
        let read = SaleLedger.parse(#"{"day": "2026-11-01", "ev": "attempt", "kind": "post", "product": "x"}"#)
        XCTAssertEqual(read.attempts(for: "x").posts, 1)
    }

    func testAnAttemptOfAnotherKindOrWithoutAProductIsIgnored() {
        let text = """
        {"day": "2026-11-01", "ev": "attempt", "kind": "tweet", "product": "x"}
        {"day": "2026-11-01", "ev": "published"}
        {"day": "2026-11-01", "ev": "published", "product": ""}
        """
        let read = SaleLedger.parse(text)
        XCTAssertTrue(read.byProduct.isEmpty)
        XCTAssertEqual(read.skipped, 0)
    }

    func testAMissingLedgerIsNoAttemptsNotAnError() throws {
        let read = try SaleLedger.read(file: URL(fileURLWithPath: "/nonexistent/teyla/ledger.jsonl"))
        XCTAssertTrue(read.byProduct.isEmpty)
        XCTAssertFalse(read.attempts(for: "anything").tried)
    }

    func testALedgerThatCannotBeReadIsAnErrorNotZero() {
        // A directory where the file should be: it exists, so it is not "missing", and reading it fails.
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("sale-ledger-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        XCTAssertThrowsError(try SaleLedger.read(file: dir))
    }

    func testTheLedgerLivesUnderTeylaHomeWhenSet() {
        XCTAssertEqual(SaleLedger.file(home: "/h", env: [:]).path, "/h/.teyla/growth/ledger.jsonl")
        XCTAssertEqual(SaleLedger.file(home: "/h", env: ["TEYLA_HOME": "/t"]).path, "/t/growth/ledger.jsonl")
    }

    func testZeroReadsNotTriedYetAndNeverSuggestsClosing() {
        let none = SaleAttempts()
        XCTAssertEqual(SaleLogic.figure(none), "0")
        XCTAssertEqual(SaleLogic.detail(none, parked: false), "Not tried yet. Next in line.")
        XCTAssertEqual(SaleLogic.detail(none, parked: true), "Not tried yet. Parked.")
        XCTAssertFalse(SaleLogic.detail(none, parked: false).lowercased().contains("clos"))
        XCTAssertEqual(SaleLogic.lastWords(none), "No attempt yet")
    }

    func testAttemptsReadAsPostsMarketingAndMeetings() {
        let tried = SaleAttempts(posts: 2, marketing: 0, icpMeetings: 1, last: "2026-11-03")
        XCTAssertEqual(SaleLogic.detail(tried, parked: false), "Posts, marketing and ICP meetings.")
        XCTAssertEqual(SaleLogic.rows(tried).map(\.count), [2, 0, 1])
        XCTAssertEqual(SaleLogic.lastWords(tried), "3 Nov")
    }

    // The Mac screen must count what `teyla growth sale-attempts` counts (`growth.attempt_rows`): a row an agent logged is a claim.

    func testAnAttemptAnAgentLoggedIsClaimedNotCounted() {
        let text = """
        {"day": "2026-11-01", "ev": "attempt", "kind": "outreach", "product": "x", "by": "agent"}
        {"day": "2026-11-02", "ev": "attempt", "kind": "icp-meeting", "product": "x", "by": "agent"}
        {"day": "2026-11-03", "ev": "attempt", "kind": "post", "product": "x", "by": "agent"}
        """
        let attempts = SaleLedger.parse(text).attempts(for: "x")
        XCTAssertEqual(attempts.total, 0)
        XCTAssertFalse(attempts.tried, "claims alone are still not tried yet")
        XCTAssertEqual(attempts.claimed, 3)
        XCTAssertEqual(attempts.last, "", "a claim does not set the last day")
    }

    func testAClaimDoesNotHideWhatTheOwnerLogged() {
        let text = """
        {"day": "2026-11-01", "ev": "attempt", "kind": "icp-meeting", "product": "x", "by": "owner"}
        {"day": "2026-11-02", "ev": "attempt", "kind": "outreach", "product": "x"}
        {"day": "2026-11-04", "ev": "attempt", "kind": "outreach", "product": "x", "by": "agent"}
        """
        let attempts = SaleLedger.parse(text).attempts(for: "x")
        XCTAssertEqual(attempts.icpMeetings, 1)
        XCTAssertEqual(attempts.marketing, 1, "a row logged before `by` existed counts as before")
        XCTAssertEqual(attempts.claimed, 1)
        XCTAssertEqual(attempts.last, "2026-11-02")
    }

    func testAPublishedRowAlwaysCountsEvenFromAnAgent() {
        let text = #"{"day": "2026-11-02", "ev": "published", "product": "x", "by": "agent"}"#
        let attempts = SaleLedger.parse(text).attempts(for: "x")
        XCTAssertEqual(attempts.posts, 1)
        XCTAssertEqual(attempts.claimed, 0)
    }

    func testAnAgentRowThatIsNotAnAttemptIsNotAClaim() {
        let text = #"{"day": "2026-11-02", "ev": "idea", "product": "x", "by": "agent"}"#
        XCTAssertEqual(SaleLedger.parse(text).attempts(for: "x").claimed, 0)
    }

    func testTheWordsNameClaimsAndStillSayNotTriedYet() {
        let claimed = SaleAttempts(claimed: 2)
        XCTAssertEqual(SaleLogic.detail(claimed, parked: false), "Not tried yet. Next in line. 2 logged by an agent, not counted.")
        XCTAssertEqual(SaleLogic.detail(SaleAttempts(posts: 1, last: "2026-11-01", claimed: 1), parked: false),
                       "Posts, marketing and ICP meetings. 1 logged by an agent, not counted.")
    }
}
