import XCTest

final class TeylaConfigTests: XCTestCase {
    private func fixture() throws -> TeylaConfig {
        ConfigFile.parse(String(decoding: try SampleFiles.data("config.v1.toml"), as: UTF8.self))
    }

    private func row(_ key: String, _ config: TeylaConfig) -> ConfigRow? {
        ConfigLogic.groups(config).flatMap(\.rows).first { $0.key == key }
    }

    func testTablesScalarsAndListsAreRead() throws {
        let config = try fixture()
        XCTAssertEqual(config.values["code_root"], .text("~/repos"))
        XCTAssertEqual(config.values["update.channel"], .text("release"))
        XCTAssertEqual(config.values["storage.idle_days"], .number(3))
        XCTAssertEqual(config.values["guard.enabled"], .flag(true))
        XCTAssertEqual(config.values["products.repos"], .list(["alpha", "beta", "~/work/gamma"]))
        XCTAssertEqual(config.values["spend.a20_models"], .list(["model-a", "model-b"]), "a list over several lines")
        XCTAssertEqual(config.values["state.merge_approved"], .list([]))
    }

    func testACommentAfterAValueIsDroppedButAHashInQuotesStays() {
        let config = ConfigFile.parse("a = \"x # y\"  # note\nb = 2 # note\n")
        XCTAssertEqual(config.values["a"], .text("x # y"))
        XCTAssertEqual(config.values["b"], .number(2))
        XCTAssertEqual(config.unread, 0)
    }

    func testALineThatIsNotTomlIsCountedNotGuessed() throws {
        XCTAssertEqual(try fixture().unread, 1)
    }

    func testSecretsAndEnvironmentValuesAreNeverKept() throws {
        let config = try fixture()
        XCTAssertEqual(config.values["update.token"], .hidden)
        XCTAssertEqual(config.values["state.api_key"], .hidden)
        XCTAssertEqual(config.values["env.HTTPS_PROXY"], .hidden)
        XCTAssertEqual(config.environmentNames, ["HTTPS_PROXY", "SSL_CERT_FILE"])
        // Nothing the file holds as a secret appears in any row the page builds.
        let shown = ConfigLogic.groups(config).flatMap { $0.rows.map { $0.value + $0.label + $0.hint } }.joined(separator: "\n")
            + ConfigLogic.environmentLine(config)
        for secret in ["ghp_not_a_real_token", "sk-not-a-real-key", "user:pass", "proxy.example", "ca.pem"] {
            XCTAssertFalse(shown.contains(secret), secret)
        }
    }

    func testWhatMakesAKeySecretIsItsLastPart() {
        XCTAssertTrue(ConfigFile.isSecret("update.token"))
        XCTAssertTrue(ConfigFile.isSecret("api_key"))
        XCTAssertTrue(ConfigFile.isSecret("db.PASSWORD"))
        XCTAssertFalse(ConfigFile.isSecret("storage.idle_days"))
        XCTAssertFalse(ConfigFile.isSecret("token.owner_name"))
    }

    func testRowsReadInPlainWords() throws {
        let config = try fixture()
        XCTAssertEqual(row("update.channel", config)?.value, "Published releases")
        XCTAssertEqual(row("storage.auto_clean", config)?.value, "On", "a string \"true\" reads as On")
        XCTAssertEqual(row("storage.idle_days", config)?.value, "3 days")
        XCTAssertEqual(row("guard.max_builds", config)?.value, "No limit", "0 means no limit")
        XCTAssertEqual(row("guard.max_sims", config)?.value, "2")
        XCTAssertEqual(row("spend.daily_budget_usd", config)?.value, Format.spent(25))
        XCTAssertEqual(row("products.repos", config)?.value, "alpha, beta, ~/work/gamma")
        XCTAssertEqual(row("harness.disabled", config)?.value, "hermes")
    }

    func testAKeyTheFileDoesNotSetShowsItsDefaultAndSaysSo() throws {
        let config = try fixture()
        let channel = try XCTUnwrap(row("update.pin", config))
        XCTAssertEqual(channel.value, "Not pinned")
        XCTAssertTrue(channel.isDefault)
        XCTAssertFalse(try XCTUnwrap(row("update.channel", config)).isDefault)
        XCTAssertEqual(row("runs_root", config)?.value, "Inside the ops folder", "an empty value is the default")
        XCTAssertEqual(row("harness.disabled", ConfigFile.parse(""))?.value, "None turned off")
    }

    func testKeysNoRowListsAreCounted() throws {
        let config = try fixture()
        // storage.sim_prune_pattern, storage.docker_superseded_repos, spend.a20_models, update.repo is listed; the token is
        // hidden but still a key the file sets.
        XCTAssertGreaterThanOrEqual(ConfigLogic.otherKeys(config), 3)
        XCTAssertEqual(ConfigLogic.otherKeys(ConfigFile.parse("code_root = \"~/repos\"\n")), 0)
    }

    func testAMissingFileIsTheDefaultsNotAnError() throws {
        let config = try ConfigFile.read(file: URL(fileURLWithPath: "/nonexistent/teyla/config.toml"), home: "/home/x")
        XCTAssertFalse(config.exists)
        XCTAssertTrue(config.values.isEmpty)
        XCTAssertEqual(row("code_root", config)?.value, "~/repos")
    }

    func testAFileThatCannotBeReadIsAnErrorNotTheDefaults() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("config-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        XCTAssertThrowsError(try ConfigFile.read(file: dir, home: "/home/x"))
    }

    func testThePathIsShownWithTildeAndFollowsTeylaHome() {
        XCTAssertEqual(ConfigFile.file(home: "/h", env: [:]).path, "/h/.teyla/config.toml")
        XCTAssertEqual(ConfigFile.file(home: "/h", env: ["TEYLA_HOME": "/t"]).path, "/t/config.toml")
        XCTAssertEqual(ConfigFile.shown("/h/.teyla/config.toml", home: "/h"), "~/.teyla/config.toml")
        XCTAssertEqual(ConfigFile.shown("/t/config.toml", home: "/h"), "/t/config.toml")
    }

    func testEveryRowAndHintFitsOnOneLine() {
        for group in ConfigLogic.groups(ConfigFile.parse("")) {
            for row in group.rows {
                XCTAssertLessThanOrEqual(row.hint.count, 60, row.key)
                XCTAssertFalse(row.label.contains("_"), "a key name is not a label: \(row.key)")
            }
        }
    }

    func testEnvironmentLineNamesAtMostSix() {
        let many = (1...9).map { "V\($0) = \"x\"" }.joined(separator: "\n")
        let line = ConfigLogic.environmentLine(ConfigFile.parse("[env]\n" + many))
        XCTAssertTrue(line.hasSuffix("and 3 more."), line)
        XCTAssertEqual(ConfigLogic.environmentLine(ConfigFile.parse("")), "None set.")
    }

    func testAMultiLineStringIsOneValueNotSettings() {
        let quotes = String(repeating: "'", count: 3)
        let text = "[env]\nSECRET = \(quotes)\n[update]\nrepo = \"private-value\"\n\(quotes)\n[guard]\nenabled = true\n"
        let config = ConfigFile.parse(text)
        XCTAssertEqual(config.values["env.SECRET"], .hidden)
        XCTAssertNil(config.values["update.repo"], "a line inside a string is not a key")
        XCTAssertEqual(config.values["guard.enabled"], .flag(true))
        let doubles = String(repeating: "\"", count: 3)
        let other = ConfigFile.parse("[intent]\nnote = \(doubles)one\ntwo\(doubles)\nenabled = false\n")
        XCTAssertEqual(other.values["intent.note"], .text("one\ntwo"))
        XCTAssertEqual(other.values["intent.enabled"], .flag(false))
        // An escaped quote inside a basic multi-line string does not close it.
        let escaped = "[env]\nSECRET = \(doubles)\n\\\(doubles)\n[update]\nrepo = \"private-value\"\n\(doubles)\n"
        let hidden = ConfigFile.parse(escaped)
        XCTAssertEqual(hidden.values["env.SECRET"], .hidden)
        XCTAssertNil(hidden.values["update.repo"])
    }

    func testAHugeOrInfiniteNumberDoesNotCrashThePage() {
        for text in ["1e30", "-1e30", "inf", "nan", "1e308", "9007199254740993"] {
            let config = ConfigFile.parse("[guard]\nmax_builds = \(text)\nmax_sims = \(text)\n[spend]\ndaily_budget_usd = \(text)\n[storage]\nidle_days = \(text)\n")
            XCTAssertFalse(ConfigLogic.groups(config).isEmpty, text)
        }
        XCTAssertEqual(ConfigFile.parse("a = inf").unread, 1, "a number that is not finite is not read")
    }

    func testTheSettingsPageIsReachableAndKnown() {
        XCTAssertFalse(AppRoute.settings.isConsole)
        XCTAssertTrue(CommandBar.entries(products: [], report: nil, capabilities: .full).contains { $0.id == "go:settings" })
        XCTAssertFalse(CommandBar.entries(products: [], report: nil, capabilities: .store).contains { $0.id == "go:settings" })
    }
}
