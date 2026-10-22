import XCTest

/// Smoke tests for the Watch app on a fresh database (`-uiTesting`).
final class LifeLogWatchUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-uiTesting"]
        app.launch()
        snapshot("w00-launch-\(name)")
    }

    private func snapshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func button(containing text: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    @discardableResult
    private func scrollTo(_ element: XCUIElement) -> Bool {
        var n = 0
        while !element.exists && n < 8 {
            app.swipeUp()
            n += 1
        }
        let found = element.waitForExistence(timeout: 2)
        if !found {
            let tree = XCTAttachment(string: app.debugDescription)
            tree.name = "hierarchy-\(name)"
            tree.lifetime = .keepAlways
            add(tree)
        }
        return found
    }

    func testOneTapFavorite() {
        let pickup = button(containing: "Automatic pickup")
        XCTAssertTrue(app.buttons.firstMatch.waitForExistence(timeout: 20))
        XCTAssertTrue(scrollTo(pickup))
        pickup.tap()
        XCTAssertTrue(app.buttons["Undo"].waitForExistence(timeout: 4), "toast with Undo after one tap")
        snapshot("w01-logged")
    }

    func testAnswerToSave() {
        let episode = button(containing: "Scrolling episode")
        XCTAssertTrue(episode.waitForExistence(timeout: 20))
        episode.tap()
        let fifteen = button(containing: "15 min")
        XCTAssertTrue(app.buttons.firstMatch.waitForExistence(timeout: 4))
        XCTAssertTrue(scrollTo(fifteen))
        snapshot("w02-duration")
        fifteen.tap()
        XCTAssertTrue(app.buttons["Undo"].waitForExistence(timeout: 4), "answering the required field saves")
    }

    func testCheckIn() {
        let checkIn = button(containing: "check-in")
        XCTAssertTrue(checkIn.waitForExistence(timeout: 20))
        checkIn.tap()
        snapshot("w03-checkin")
        XCTAssertTrue(app.navigationBars.firstMatch.waitForExistence(timeout: 5) || app.buttons.firstMatch.exists)
    }
}
