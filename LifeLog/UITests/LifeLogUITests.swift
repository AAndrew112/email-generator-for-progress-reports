import XCTest

/// End-to-end checks of the main flows on a fresh database (`-uiTesting`).
/// Screenshots are attached to the result bundle.
final class LifeLogUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-uiTesting"]
        app.launch()
    }

    private func snapshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func toast(_ title: String) -> XCUIElement {
        app.staticTexts[title].firstMatch
    }

    func testOneTapLogUndo() {
        XCTAssertTrue(app.buttons["tile-Automatic pickup"].waitForExistence(timeout: 10))
        snapshot("01-today")
        app.buttons["tile-Automatic pickup"].tap()
        XCTAssertTrue(app.buttons["Undo"].waitForExistence(timeout: 3), "toast with Undo appears after one tap")
        snapshot("02-logged-toast")
        app.buttons["Undo"].tap()
        XCTAssertTrue(app.staticTexts["Nothing logged yet today."].waitForExistence(timeout: 3), "undo removes the entry")
    }

    func testPresetIsOneTap() {
        XCTAssertTrue(app.buttons["tile-Urge resisted"].waitForExistence(timeout: 10))
        app.buttons["tile-Urge resisted"].tap()
        XCTAssertTrue(app.buttons["Undo"].waitForExistence(timeout: 3))
    }

    func testScrollingEpisodeInTwoTaps() {
        XCTAssertTrue(app.buttons["tile-Scrolling episode"].waitForExistence(timeout: 10))
        app.buttons["tile-Scrolling episode"].tap()
        let chip = app.buttons["15m"]
        XCTAssertTrue(chip.waitForExistence(timeout: 3))
        snapshot("03-episode-sheet")
        chip.tap()
        XCTAssertTrue(app.buttons["Undo"].waitForExistence(timeout: 3), "answering the required duration saves")
        snapshot("04-episode-logged")
    }

    func testMorningCheckIn() {
        let card = app.buttons["checkin-morning"]
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        card.tap()
        // Sleep times: set each time, then confirm.
        for _ in 0..<3 {
            let set = app.buttons["Set time"].firstMatch
            XCTAssertTrue(set.waitForExistence(timeout: 3))
            set.tap()
        }
        snapshot("05-checkin-sleep")
        app.buttons["Confirm"].tap()
        let good = app.buttons["3, Good"]
        XCTAssertTrue(good.waitForExistence(timeout: 3))
        snapshot("06-checkin-rating")
        good.tap()
        let rested = app.buttons["2, Moderately"]
        XCTAssertTrue(rested.waitForExistence(timeout: 3))
        rested.tap()
        let done = app.buttons["Done"]
        XCTAssertTrue(done.waitForExistence(timeout: 3))
        snapshot("07-checkin-summary")
        done.tap()
        XCTAssertTrue(app.buttons["checkin-morning"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.buttons["checkin-morning"].label, "Morning check-in, done")
        snapshot("08-today-after-checkin")
    }

    func testCreateCustomMeasure() {
        app.tabBars.buttons["Measures"].tap()
        snapshot("09-measures")
        app.buttons["New measure"].tap()
        app.buttons["Yes / No"].tap()
        let name = app.textFields["Name"]
        XCTAssertTrue(name.waitForExistence(timeout: 3))
        name.tap()
        name.typeText("Took a walk")
        snapshot("10-new-measure")
        app.buttons["Save"].tap()
        XCTAssertTrue(app.staticTexts["Took a walk"].waitForExistence(timeout: 3))
    }

    func testExportProducesShareSheet() {
        app.tabBars.buttons["Settings"].tap()
        let export = app.buttons["Export CSV + JSON"]
        XCTAssertTrue(export.waitForExistence(timeout: 5))
        snapshot("11-settings")
        export.tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'entries ·'")).firstMatch.waitForExistence(timeout: 15),
                      "export summary appears")
        snapshot("12-export")
    }
}
