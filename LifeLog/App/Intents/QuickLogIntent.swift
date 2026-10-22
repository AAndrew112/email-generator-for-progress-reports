import AppIntents
import LifeLogKit
#if canImport(WidgetKit)
import WidgetKit
#endif

/// Logs a favourite in the background. Used by interactive widget buttons,
/// so it is compiled into both the app and the widget extension.
struct QuickLogIntent: AppIntent {
    static let title: LocalizedStringResource = "Log Favorite"
    static let isDiscoverable = false

    @Parameter(title: "Favorite ID")
    var actionID: String

    init() {}

    init(actionID: String) {
        self.actionID = actionID
    }

    func perform() async throws -> some IntentResult {
        let store = StoreFactory.shared
        if let action = QuickAction.find(actionID, in: store.measures()) {
            _ = try QuickLogger.logIfComplete(action, store: store, context: .widget)
        }
        #if canImport(WidgetKit)
        WidgetCenter.shared.reloadAllTimelines()
        #endif
        return .result()
    }
}
