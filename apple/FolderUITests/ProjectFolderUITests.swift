import XCTest

final class ProjectFolderUITests: XCTestCase {
    func testConfirmEmptyFolderReturnsToChatAndSurvivesRelaunch() {
        continueAfterFailure = false
        let app = XCUIApplication()
        addUIInterruptionMonitor(withDescription:"Simulator permission") { alert in
            for title in ["Allow","OK","السماح","موافق"] where alert.buttons[title].exists {
                alert.buttons[title].tap()
                return true
            }
            return false
        }
        app.launch()
        func project(_ name: String) -> XCUIElement {
            app.webViews.buttons.matching(NSPredicate(format:"label CONTAINS %@",name)).firstMatch
        }
        let initial = project("Workspace")
        XCTAssertTrue(initial.waitForExistence(timeout:40),app.debugDescription)
        initial.tap()
        let empty = app.buttons["Empty Project"]
        XCTAssertTrue(empty.waitForExistence(timeout:12),app.debugDescription)
        empty.tap()
        app.buttons["confirmProjectFolder"].tap()
        let chosen = project("Empty Project")
        XCTAssertTrue(chosen.waitForExistence(timeout:20),app.debugDescription)
        XCTAssertFalse(app.buttons["confirmProjectFolder"].exists)
        app.terminate()
        app.launch()
        XCTAssertTrue(chosen.waitForExistence(timeout:30),app.debugDescription)

        chosen.tap()
        app.buttons["اختيار موقع آخر من الملفات"].tap()
        let open = app.buttons.matching(NSPredicate(format:"label IN %@", ["Open","فتح"])).firstMatch
        XCTAssertTrue(open.waitForExistence(timeout:30),app.debugDescription)
        XCTAssertTrue(open.isEnabled,app.debugDescription)
        open.tap()
        XCTAssertTrue(chosen.waitForExistence(timeout:20),app.debugDescription)
        XCTAssertFalse(app.buttons["confirmProjectFolder"].exists)
        XCTAssertFalse(open.exists)
    }
}
