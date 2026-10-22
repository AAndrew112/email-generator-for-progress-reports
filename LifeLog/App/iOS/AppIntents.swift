import AppIntents
import LifeLogKit

/// A favourite, measure or preset exposed to Shortcuts, Siri and the Action button.
struct QuickActionEntity: AppEntity {
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "LifeLog Item"
    static let defaultQuery = QuickActionQuery()

    let id: String
    let title: String
    let subtitle: String?

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(title)", subtitle: subtitle.map { "\($0)" })
    }

    init(_ action: QuickAction) {
        id = action.id
        title = action.title
        subtitle = action.subtitle
    }
}

struct QuickActionQuery: EntityQuery {
    func entities(for identifiers: [String]) async throws -> [QuickActionEntity] {
        let measures = StoreFactory.shared.measures()
        return identifiers.compactMap { QuickAction.find($0, in: measures).map(QuickActionEntity.init) }
    }

    func suggestedEntities() async throws -> [QuickActionEntity] {
        let measures = StoreFactory.shared.measures()
        var actions = QuickLogger.favorites(from: measures)
        for a in QuickLogger.allActions(from: measures) where !actions.contains(where: { $0.id == a.id }) {
            actions.append(a)
        }
        return actions.map(QuickActionEntity.init)
    }
}

/// "Log Urge resisted in LifeLog". Logs immediately when no input is needed,
/// otherwise opens the app at the entry form.
struct LogQuickActionIntent: AppIntent, ForegroundContinuableIntent {
    static let title: LocalizedStringResource = "Quick Log"
    static let description = IntentDescription("Records an entry in LifeLog with the current time.")

    @Parameter(title: "Item")
    var action: QuickActionEntity

    static var parameterSummary: some ParameterSummary {
        Summary("Log \(\.$action)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let store = StoreFactory.shared
        guard let quick = QuickAction.find(action.id, in: store.measures()) else {
            return .result(dialog: "That item no longer exists in LifeLog.")
        }
        if try QuickLogger.logIfComplete(quick, store: store, context: .shortcut) != nil {
            await MainActor.run { WatchSync.shared.schedulePush() }
            return .result(dialog: "Logged \(quick.title).")
        }
        let id = quick.id
        throw needsToContinueInForegroundError("\(quick.title) needs a few details.") {
            Router.shared.sheet = .newEntry(actionID: id)
        }
    }
}

enum CheckInKindEnum: String, AppEnum {
    case morning
    case evening

    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Check-in"
    static let caseDisplayRepresentations: [CheckInKindEnum: DisplayRepresentation] = [
        .morning: "Morning",
        .evening: "Evening",
    ]
}

struct StartCheckInIntent: AppIntent {
    static let title: LocalizedStringResource = "Start Check-in"
    static let description = IntentDescription("Opens LifeLog's morning or evening check-in.")
    static let openAppWhenRun = true

    @Parameter(title: "Check-in", default: .morning)
    var kind: CheckInKindEnum

    @MainActor
    func perform() async throws -> some IntentResult {
        Router.shared.sheet = .checkIn(kind == .morning ? .morning : .evening)
        return .result()
    }
}

struct LifeLogShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: LogQuickActionIntent(),
                    phrases: ["Log \(\.$action) in \(.applicationName)",
                              "\(.applicationName) log \(\.$action)",
                              "Quick log in \(.applicationName)"],
                    shortTitle: "Quick Log",
                    systemImageName: "plus.circle.fill")
        AppShortcut(intent: StartCheckInIntent(),
                    phrases: ["Start my \(\.$kind) check-in in \(.applicationName)",
                              "\(.applicationName) \(\.$kind) check-in",
                              "Check in with \(.applicationName)"],
                    shortTitle: "Check-in",
                    systemImageName: "checklist")
    }

    static let shortcutTileColor: ShortcutTileColor = .teal
}
