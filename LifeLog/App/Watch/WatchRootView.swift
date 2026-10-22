import SwiftUI
import LifeLogKit

struct WatchRootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        NavigationStack {
            List(model.favorites) { action in
                Button(action.title) { _ = model.quickLog(action) }
            }
            .navigationTitle("LifeLog")
        }
    }
}
