import SwiftUI
import UserNotifications
import LifeLogKit

@main
struct LifeLogApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var model = AppModel(store: StoreFactory.shared)
    @State private var router = Router.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(router)
                .environment(WatchSync.shared)
                .onOpenURL { router.handle(url: $0) }
                .task {
                    model.onLocalChange = { WatchSync.shared.schedulePush() }
                    WatchSync.shared.activate()
                    LifeLogShortcuts.updateAppShortcutParameters()
                }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                model.reload()
                WatchSync.shared.schedulePush()
            }
        }
    }
}

/// Handles taps on check-in reminder notifications.
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let kind = response.notification.request.content.userInfo["checkin"] as? String
        Task { @MainActor in
            if let kind, let k = CheckInKind(rawValue: kind) { Router.shared.sheet = .checkIn(k) }
            completionHandler()
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}

/// App-wide navigation requests (deep links, intents, notifications, quick log).
@MainActor
@Observable
final class Router {
    static let shared = Router()

    enum Sheet: Identifiable, Equatable {
        case checkIn(CheckInKind)
        case newEntry(actionID: String)
        case editEntry(UUID)
        case pickMeasure

        var id: String {
            switch self {
            case .checkIn(let k): return "checkin-\(k.rawValue)"
            case .newEntry(let a): return "new-\(a)"
            case .editEntry(let id): return "edit-\(id)"
            case .pickMeasure: return "pick"
            }
        }
    }

    var sheet: Sheet?
    var tab: AppTab = .today

    enum AppTab: Hashable { case today, history, measures, settings }

    /// lifelog://checkin/morning, lifelog://log/<action id>, lifelog://quicklog, lifelog://entry/<uuid>
    func handle(url: URL) {
        guard url.scheme == "lifelog" else { return }
        let parts = url.pathComponents.filter { $0 != "/" }
        switch url.host {
        case "checkin":
            sheet = .checkIn(parts.first.flatMap(CheckInKind.init(rawValue:)) ?? .morning)
        case "log":
            if let id = parts.first { sheet = .newEntry(actionID: id) } else { sheet = .pickMeasure }
        case "quicklog":
            tab = .today
            sheet = .pickMeasure
        case "entry":
            if let id = parts.first.flatMap(UUID.init(uuidString:)) { sheet = .editEntry(id) }
        default:
            tab = .today
        }
    }
}
