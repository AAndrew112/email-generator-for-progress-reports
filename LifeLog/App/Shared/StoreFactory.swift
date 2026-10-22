import Foundation
import LifeLogKit

/// Opens the single on-device database. On iPhone it lives in the App Group
/// container so the widget extension can log too; on Watch (or if the App
/// Group isn't provisioned) it falls back to Application Support.
enum StoreFactory {
    static let appGroupID: String? = {
        guard let id = Bundle.main.object(forInfoDictionaryKey: "LifeLogAppGroup") as? String,
              !id.isEmpty, !id.contains("$(") else { return nil }
        return id
    }()

    static let containerURL: URL = {
        if let id = appGroupID,
           let url = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: id) {
            return url.appendingPathComponent("LifeLog", isDirectory: true)
        }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return support.appendingPathComponent("LifeLog", isDirectory: true)
    }()

    static var databaseURL: URL { containerURL.appendingPathComponent("lifelog.sqlite") }
    static var photosURL: URL { containerURL.appendingPathComponent("Photos", isDirectory: true) }

    static let defaults: UserDefaults = appGroupID.flatMap { UserDefaults(suiteName: $0) } ?? .standard

    /// Stable per-install identifier recorded on every entry ("iphone-…", "watch-…").
    static let deviceID: String = {
        let key = "LifeLogDeviceID"
        if let id = defaults.string(forKey: key) { return id }
        #if os(watchOS)
        let prefix = "watch"
        #else
        let prefix = "iphone"
        #endif
        let id = "\(prefix)-\(UUID().uuidString.prefix(8).lowercased())"
        defaults.set(id, forKey: key)
        return id
    }()

    static var defaultSource: EntrySource {
        #if os(watchOS)
        return .watch
        #elseif WIDGET_EXTENSION
        return .widget
        #else
        return .iPhone
        #endif
    }

    /// Set when the database could not be opened and an in-memory store is used instead.
    private(set) static var openError: String?

    static let shared: Store = {
        do {
            try FileManager.default.createDirectory(at: containerURL, withIntermediateDirectories: true)
            let store = try Store(url: databaseURL, deviceID: deviceID, defaultSource: defaultSource)
            try store.seedIfNeeded()
            return store
        } catch {
            openError = "Could not open the database (\(error)). Changes made now will not be saved."
            let store = try! Store.inMemory(deviceID: deviceID, source: defaultSource)
            try? store.seedIfNeeded()
            return store
        }
    }()

    static let photos = PhotoStore(directory: photosURL)
}
