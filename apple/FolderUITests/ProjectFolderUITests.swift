import XCTest

final class ProjectFolderUITests: XCTestCase {
    func testConfirmEmptyFolderReturnsToChatAndSurvivesRelaunch() {
        let app = XCUIApplication()
        app.launch()
        let web = app.webViews.firstMatch
        let folder = web.buttons.matching(NSPredicate(format:"label CONTAINS %@", "📁")).firstMatch
        XCTAssertTrue(folder.waitForExistence(timeout:30))
        folder.tap()
        let create = app.buttons["createProjectFolder"]
        XCTAssertTrue(create.waitForExistence(timeout:10))
        create.tap()
        let name = "FolderPick-" + UUID().uuidString.prefix(6)
        let alert = app.alerts.firstMatch
        alert.textFields.firstMatch.tap()
        alert.textFields.firstMatch.typeText(String(name))
        alert.buttons["إنشاء"].tap()
        XCTAssertTrue(app.staticTexts[String(name)].waitForExistence(timeout:10))
        app.buttons["confirmProjectFolder"].tap()
        let chosen = web.buttons.matching(NSPredicate(format:"label CONTAINS %@",String(name))).firstMatch
        XCTAssertTrue(chosen.waitForExistence(timeout:15))
        XCTAssertFalse(app.buttons["confirmProjectFolder"].exists)
        app.terminate()
        app.launch()
        XCTAssertTrue(chosen.waitForExistence(timeout:20))

        // Exercise the system Files "Open" callback on the same empty folder.
        chosen.tap()
        app.buttons["اختيار موقع آخر من الملفات"].tap()
        let open = app.buttons.matching(NSPredicate(format:"label IN %@", ["Open","فتح"])).firstMatch
        XCTAssertTrue(open.waitForExistence(timeout:30))
        XCTAssertTrue(open.isEnabled)
        open.tap()
        let returned = XCTNSPredicateExpectation(predicate:NSPredicate(format:"exists == false"),
                                                  object:app.buttons["confirmProjectFolder"])
        XCTAssertEqual(XCTWaiter.wait(for:[returned],timeout:20),.completed)
        XCTAssertTrue(chosen.waitForExistence(timeout:10))
    }
}
