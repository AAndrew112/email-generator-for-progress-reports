import SwiftUI
import LifeLogKit

@main
struct LifeLogWatchApp: App {
    @State private var model = AppModel(store: StoreFactory.shared)
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            WatchRootView()
                .environment(model)
                .environment(WatchSync.shared)
                .task {
                    model.onLocalChange = { WatchSync.shared.schedulePush() }
                    WatchSync.shared.activate()
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
